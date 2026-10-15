"""Live system sampling for the AstraOS HUD.

Why this module has no GTK import
---------------------------------
The HUD is the desktop's "show desktop" surface, so it is the one AstraOS
application that a user is guaranteed to see. Anything that makes it crash takes
the session's overview mode with it. Keeping every sampler in a module that
imports nothing but the standard library means the data layer can be exercised
(and reasoned about) on a build host that has no gi at all, and means a missing
or broken GTK binding cannot take the sampling code down with it: `main()` can
report a precise error instead of dying inside a collector.

The rule that shapes everything below: a HUD that shows "N/A" is useful, a HUD
that invents a number is not. Every collector returns a structurally valid
sample with honest defaults when the kernel does not answer - no battery, no
thermal zone, no `/proc` entry, a filesystem unmounted mid-scan. Values that
have not been measured yet (CPU percentages need two samples) are `None`, which
the widgets render as a dash. They are never zero-filled, because a fabricated
0% CPU is indistinguishable from an idle machine and hides a real fault.

Percentage arithmetic
---------------------
CPU load and network throughput are *rates*, and `/proc` only exposes them as
monotonic counters. Every rate in this module is therefore computed as a delta
between two samples spaced by a measured wall-clock interval. The first sample
after start-up has no predecessor and returns `None`; the second one produces a
real number. This is also why the collector keeps state objects (`CpuMeter`,
`ProcessMeter`, `TrafficMeter`) instead of being a bag of free functions.

Sources (Linux, no third-party packages - `psutil` is not in the image):
    /proc/stat                  CPU totals, per-core totals
    /proc/meminfo               memory and swap
    /proc/loadavg, /proc/uptime load averages, uptime, task counts
    /proc/net/dev               per-interface byte counters
    /proc/net/route             default gateway and outbound interface
    /proc/diskstats             sector counters for mounted volumes
    /proc/self/mounts           mounted filesystems
    /proc/<pid>/stat, statm     per-process CPU time and RSS
    /sys/class/thermal/...      CPU/package temperatures
    /sys/class/hwmon/...        board, GPU and drive temperatures
    /sys/class/power_supply/... battery state
    /etc/astraos/hud-endpoints.conf   operator-supplied endpoint coordinates
"""

from __future__ import annotations

import os
import re
import select
import socket
import struct
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional, Sequence, Tuple

__all__ = [
    "PALETTE",
    "FONT_UI",
    "FONT_MONO",
    "FONT_DISPLAY",
    "HUD_COLUMNS",
    "HUD_SAMPLE_INTERVAL_MS",
    "HUD_TRAFFIC_SAMPLES",
    "HUD_LABEL_HOT",
    "HUD_LABEL_COLD",
    "NA",
    "PENDING",
    "Collector",
    "SystemSnapshot",
    "CpuSample",
    "CpuTimes",
    "CpuMeter",
    "MemorySample",
    "LoadSample",
    "Temperature",
    "BatterySample",
    "ProcessRow",
    "ProcessMeter",
    "NetworkSample",
    "InterfaceTraffic",
    "TrafficMeter",
    "PingProbe",
    "MountInfo",
    "FilesystemSample",
    "Endpoint",
    "SystemIdentity",
    "load_endpoint_map",
    "read_cpu_times",
    "read_meminfo",
    "read_loadavg",
    "read_temperatures",
    "read_battery",
    "read_cpu_model",
    "filesystem_sample",
    "default_gateway",
    "local_ipv4",
    "format_bytes",
    "format_rate",
    "format_uptime",
    "format_duration",
    "hex_to_rgb",
    "clamp",
    "group_cores",
]


# ---------------------------------------------------------------------------
# Palette - a mirror of config/branding.env
# ---------------------------------------------------------------------------
#
# branding.env is the single source of truth for AstraOS colours (docs/DESIGN.md
# §1, and the comment above the HUD block of that file explains why: the CSS,
# the window-decoration renderer, the cursor renderer and this application must
# all read one palette instead of three hand-copied ones).
#
# It cannot be *imported* at run time: scripts/lib/astraos_env.py resolves the
# file relative to the repository checkout, and by the time the HUD runs it is
# installed under /usr/lib/astraos-hud with no repository nearby. So the token
# values are duplicated here as data, and the values below are byte-identical to
# the HUD section of config/branding.env:
#
#     COLOR_VOID, COLOR_VOID_2, COLOR_SURFACE, COLOR_SURFACE_RAISED,
#     COLOR_HAIRLINE_BASE, COLOR_HAIRLINE_HOT, COLOR_TEXT, COLOR_TEXT_DIM,
#     COLOR_TEXT_FAINT, COLOR_HUD_TEAL, COLOR_HUD_RED, HUD_COLUMNS,
#     HUD_LABEL_HOT, HUD_LABEL_COLD, HUD_SAMPLE_INTERVAL_MS, HUD_TRAFFIC_SAMPLES.
#
# TEST VISIBILITY: tests/static/test_branding.py parses branding.env and this
# dict. If a HUD token is renamed or recoloured there, it must be renamed or
# recoloured here in the same commit, or the HUD silently drifts from the
# theme. Do not add a colour to this dict that is not a branding.env token.
PALETTE: Dict[str, str] = {
    "COLOR_VOID": "#05030A",
    "COLOR_VOID_2": "#0B0716",
    "COLOR_SURFACE": "#120C20",
    "COLOR_SURFACE_RAISED": "#1C1430",
    "COLOR_HAIRLINE_BASE": "#1F1830",
    "COLOR_HAIRLINE_HOT": "#FF2FB9",
    "COLOR_TEXT": "#F2EEFF",
    "COLOR_TEXT_DIM": "#9A93B8",
    "COLOR_TEXT_FAINT": "#6B6386",
    "COLOR_HUD_TEAL": "#2EE6C9",
    "COLOR_HUD_RED": "#FF4D4D",
}

# Typography: branding.env BRAND_FONT_UI / BRAND_FONT_MONO. DejaVu is present on
# every Debian system by default, so the HUD never falls back to an unbranded
# default (docs/DESIGN.md §2).
FONT_UI = "DejaVu Sans"
FONT_MONO = "DejaVu Sans Mono"
FONT_DISPLAY = "DejaVu Sans"

# Layout and cadence tokens, also from branding.env.
HUD_COLUMNS: Tuple[int, ...] = (1, 1, 4, 1, 1, 2)
HUD_SAMPLE_INTERVAL_MS = 1000
HUD_TRAFFIC_SAMPLES = 120
HUD_LABEL_HOT = "#F2EEFF"
HUD_LABEL_COLD = "#6B6386"

PROC = "/proc"
SYS = "/sys"

#: Shown when the kernel does not answer. Deliberately not an empty string and
#: not a zero: "N/A" is visibly a missing measurement.
NA = "N/A"

#: Shown when a rate has not been measured *yet* because it needs two samples.
PENDING = "—"

ENDPOINTS_FILE = "/etc/astraos/hud-endpoints.conf"


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------

def hex_to_rgb(value: str) -> Tuple[float, float, float]:
    """'#FF2FB9' -> (1.0, 0.184, 0.725).

    Values are 0..1 because Cairo wants them that way; there is no second
    conversion anywhere in the drawing code, which keeps the widget layer free of
    colour arithmetic.
    """
    text = (value or "").strip().lstrip("#")
    if len(text) != 6:
        raise ValueError(f"expected a 6-digit hex colour, got {value!r}")
    return (
        int(text[0:2], 16) / 255.0,
        int(text[2:4], 16) / 255.0,
        int(text[4:6], 16) / 255.0,
    )


def clamp(value: float, low: float, high: float) -> float:
    """Constrain `value` to [low, high]; NaN maps to `low` rather than propagating."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return low
    if value != value:  # NaN
        return low
    return low if value < low else (high if value > high else value)


def format_bytes(value: Optional[float], unit: str = "B") -> str:
    """Human byte count. `None` (not measured) renders as N/A, not as 0 B."""
    if value is None:
        return NA
    negative = value < 0
    value = abs(float(value))
    for suffix, scale in ((unit, 1.0), ("KB", 1024.0), ("MB", 1024.0 ** 2), ("GB", 1024.0 ** 3)):
        if value < scale * 999.5 or suffix == "GB":
            text = f"{value / scale:.1f} {suffix}" if suffix != unit else f"{value:.0f} {suffix}"
            return f"-{text}" if negative else text
    return f"{value:.1f} TB"


def format_rate(bytes_per_second: Optional[float]) -> str:
    """Throughput in MB/s, which is the unit the HUD's traffic column uses."""
    if bytes_per_second is None:
        return NA
    value = abs(float(bytes_per_second))
    if value < 1024.0:
        return f"{value:.0f} B/s"
    return f"{value / (1024.0 * 1024.0):.1f} MB/s"


def format_uptime(seconds: Optional[float]) -> str:
    """Uptime as H:MM:SS - the short form the left column shows."""
    if seconds is None:
        return NA
    seconds = int(max(0.0, seconds))
    return f"{seconds // 3600}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def format_duration(seconds: Optional[float]) -> str:
    """Uptime as '4d 02:11:03' - the form the bottom status line shows."""
    if seconds is None:
        return NA
    seconds = int(max(0.0, seconds))
    days, rest = divmod(seconds, 86400)
    clock = format_uptime(rest)
    return f"{days}d {clock}" if days else clock


def group_cores(cores: Sequence[Optional[float]], size: int = 2) -> List[Optional[float]]:
    """Average logical cores into the per-physical-core rows the HUD draws.

    The reference design shows one waveform per physical core ('#1-2', '#3-4'),
    which on an SMT machine is two logical CPUs. Averaging - rather than showing
    each sibling separately - keeps the left column the same height on a 2-core
    laptop and a 16-thread desktop. A group containing an unmeasured core is
    reported as unmeasured instead of being averaged from the one sibling that
    does have a value.
    """
    size = max(1, int(size))
    rows: List[Optional[float]] = []
    for start in range(0, len(cores), size):
        window = list(cores[start:start + size])
        if any(value is None for value in window):
            rows.append(None)
        else:
            rows.append(sum(window) / len(window))  # type: ignore[arg-type]
    return rows


def read_text(path: str, limit: Optional[int] = None) -> Optional[str]:
    """Read a small kernel file, or return None if it is missing or unreadable.

    Every /proc and /sys access in this module goes through here (or
    read_lines). The point is not tidiness: a /proc entry can vanish between the
    directory listing and the read when a process exits, and a HUD that raises
    IOError from a timer callback takes the whole main loop down with it.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read() if limit is None else handle.read(limit)
    except (OSError, ValueError):
        return None


def read_lines(path: str) -> List[str]:
    """Read a kernel file as a list of lines; unreadable files give an empty list."""
    text = read_text(path)
    if not text:
        return []
    return [line for line in text.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# CPU
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CpuTimes:
    """Raw jiffy counters from /proc/stat, kept so the next sample can delta them."""

    total: int
    idle: int
    per_core: Tuple[Tuple[int, int], ...]


@dataclass(frozen=True)
class CpuSample:
    """A CPU load measurement. `None` means "not measured yet", never 0."""

    total_percent: Optional[float]
    cores: Tuple[Optional[float], ...]
    raw: CpuTimes


def read_cpu_times() -> Optional[CpuTimes]:
    """Parse the aggregate and per-core rows of /proc/stat.

    `/proc/stat` counts in USER_HZ since boot; it has no percentage field at all,
    which is the mistake this function exists to avoid. The first eight fields
    are used, and `idle + iowait` is treated as not-busy: a CPU blocked on disk
    is not computing, and counting it as load makes the HUD panic on every
    package update.
    """
    total_counter: Optional[int] = None
    total_idle = 0
    per_core: List[Tuple[int, int]] = []
    for line in read_lines(f"{PROC}/stat"):
        if not line.startswith("cpu"):
            break  # the cpu block is first; everything after it is other counters
        fields = line.split()
        label = fields[0]
        try:
            values = [int(value) for value in fields[1:9]]
        except (ValueError, IndexError):
            continue
        if len(values) < 5:
            continue
        idle = values[3] + values[4]  # idle + iowait: blocked time is not load
        ticks = sum(values)
        if label == "cpu":
            total_counter, total_idle = ticks, idle
        elif label[3:].isdigit():
            per_core.append((ticks, idle))

    if total_counter is None:
        return None
    return CpuTimes(total=total_counter, idle=total_idle, per_core=tuple(per_core))


class CpuMeter:
    """Turns /proc/stat counters into percentages by differencing two samples.

    The previous counters are kept here rather than in the widgets so that a
    repaint can never change what the next sample reports, and so the collection
    pass stays a pure function of one shared state object.
    """

    def __init__(self) -> None:
        self._previous: Optional[CpuTimes] = None

    def sample(self) -> Optional[CpuSample]:
        """Return load for this instant, or None if /proc/stat was unreadable."""
        current = read_cpu_times()
        if current is None:
            return None
        previous, self._previous = self._previous, current
        if previous is None:
            # First sample: no delta exists yet. Reporting 0% here would be a
            # fabricated number, so the HUD shows a dash until the next tick.
            return CpuSample(total_percent=None, cores=tuple(None for _ in current.per_core), raw=current)

        total_delta = current.total - previous.total
        if total_delta <= 0:
            # Suspend/resume or a counter reset: the counters went backwards, so
            # a rate over a negative interval is meaningless.
            return CpuSample(total_percent=None, cores=tuple(None for _ in current.per_core), raw=current)

        def percent(delta_busy: int, delta_total: int) -> Optional[float]:
            if delta_total <= 0:
                return None
            return clamp(100.0 * delta_busy / delta_total, 0.0, 100.0)

        cores: List[Optional[float]] = []
        for index, (total, idle) in enumerate(current.per_core):
            if index >= len(previous.per_core):
                cores.append(None)
                continue
            prev_total, prev_idle = previous.per_core[index]
            cores.append(percent((total - idle) - (prev_total - prev_idle), total - prev_total))

        return CpuSample(
            total_percent=percent((current.total - current.idle) - (previous.total - previous.idle), total_delta),
            cores=tuple(cores),
            raw=current,
        )

    @property
    def core_count(self) -> int:
        previous = self._previous
        return len(previous.per_core) if previous else 0

    @property
    def total_ticks(self) -> int:
        """Jiffies burned by every logical CPU since boot.

        Process CPU percentages are divided by *this* counter's delta, which is
        what makes 'top' show 100% for one saturated thread on any core count.
        """
        return self._previous.total if self._previous else 0


def read_cpu_model() -> str:
    """The marketing name of the first CPU, e.g. 'Intel(R) Core(TM) i5-6203U'.

    This is the string /proc/cpuinfo carries verbatim. Nothing is reformatted
    into a prettier shape: a CPU name is not ours to re-letter, and truncating it
    would hide the difference between an i5 and an i7 at a glance.
    """
    for line in read_lines(f"{PROC}/cpuinfo"):
        if line.lower().startswith(("model name", "hardware", "cpu model")):
            _, _, value = line.partition(":")
            value = value.strip()
            if value:
                return value
    return NA


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MemorySample:
    total_bytes: Optional[float]
    used_bytes: Optional[float]
    available_bytes: Optional[float]
    percent: Optional[float]
    swap_total_bytes: Optional[float]
    swap_used_bytes: Optional[float]
    swap_percent: Optional[float]


_MEMINFO_KEYS = {
    "used_bytes": ("MemTotal", "MemAvailable"),
    "swap_total_bytes": ("SwapTotal",),
    "swap_used_bytes": ("SwapTotal", "SwapFree"),
}


def read_meminfo() -> MemorySample:
    """Parse /proc/meminfo.

    'Used' is MemTotal - MemAvailable rather than MemTotal - MemFree: MemFree
    excludes reclaimable page cache, so the MemFree definition reports a full
    memory bank as nearly empty after five minutes of normal desktop use, which
    is exactly the kind of wrong-but-plausible number this HUD must not show.
    MemAvailable is absent on pre-3.14 kernels; those fall back to MemFree.
    """
    values: Dict[str, int] = {}
    for line in read_lines(f"{PROC}/meminfo"):
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts:
            try:
                values[key.strip()] = int(parts[0])
            except ValueError:
                continue

    def kb(name: str) -> Optional[float]:
        raw = values.get(name)
        return None if raw is None else float(raw) * 1024.0

    total = kb("MemTotal")
    available = kb("MemAvailable")
    if available is None:
        available = kb("MemFree")
    used = None if (total is None or available is None) else max(0.0, total - available)
    percent = None if (total is None or used is None or total <= 0) else clamp(100.0 * used / total, 0.0, 100.0)

    swap_total = kb("SwapTotal")
    swap_free = kb("SwapFree")
    swap_used = None
    if swap_total is not None and swap_free is not None:
        swap_used = max(0.0, swap_total - swap_free)
    swap_percent = None
    if swap_total and swap_used is not None:
        swap_percent = 0.0 if swap_total <= 0 else clamp(100.0 * swap_used / swap_total, 0.0, 100.0)

    return MemorySample(
        total_bytes=total,
        used_bytes=used,
        available_bytes=available,
        percent=percent,
        swap_total_bytes=swap_total,
        swap_used_bytes=swap_used,
        swap_percent=swap_percent,
    )


# ---------------------------------------------------------------------------
# Load, uptime, task counts
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LoadSample:
    one: Optional[float]
    five: Optional[float]
    fifteen: Optional[float]
    uptime_seconds: Optional[float]
    tasks: Optional[int]
    running: Optional[int]


def read_loadavg() -> LoadSample:
    """1/5/15-minute load averages, uptime and task counts.

    /proc/loadavg is preferred over os.getloadavg() because it also carries the
    runnable/total process counts in one read; os.getloadavg() is the fallback
    for the (hypothetical) system where /proc is not mounted.
    """
    one = five = fifteen = None
    tasks = running = None
    for line in read_lines(f"{PROC}/loadavg"):
        fields = line.split()
        if len(fields) >= 3:
            try:
                one, five, fifteen = (float(fields[0]), float(fields[1]), float(fields[2]))
            except ValueError:
                pass
        if len(fields) >= 4 and "/" in fields[3]:
            runnable, _, total = fields[3].partition("/")
            try:
                running, tasks = int(runnable), int(total)
            except ValueError:
                pass
        break

    if one is None:
        try:
            one, five, fifteen = os.getloadavg()
        except (OSError, AttributeError):
            pass

    uptime_seconds = None
    text = read_text(f"{PROC}/uptime", 64)
    if text:
        try:
            uptime_seconds = float(text.split()[0])
        except (ValueError, IndexError):
            uptime_seconds = None

    if tasks is None:
        tasks = count_processes()

    return LoadSample(one=one, five=five, fifteen=fifteen,
                      uptime_seconds=uptime_seconds, tasks=tasks, running=running)


def count_processes() -> Optional[int]:
    """Number of live tasks, counted from /proc's numeric directories."""
    try:
        entries = os.listdir(PROC)
    except OSError:
        return None
    return sum(1 for entry in entries if entry.isdigit())


# ---------------------------------------------------------------------------
# Temperatures and battery
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Temperature:
    label: str
    celsius: Optional[float]
    source: str


def read_temperatures(limit: int = 4) -> List[Temperature]:
    """CPU, board, drive and GPU temperatures from thermal zones and hwmon.

    hwmon is scanned first and thermal_zone second so that a machine exposing
    the same sensor through both interfaces reports the more specific hwmon
    label. Duplicates (same label, same rounded value) are collapsed, because
    'pkg_temp' and 'coretemp Package id 0' are the same die and printing both
    twice looks like a bug even though it is not.
    """
    readings: List[Temperature] = []

    for hwmon in _sorted_glob(f"{SYS}/class/hwmon/hwmon*"):
        for path in _sorted_glob(f"{hwmon}/temp*_input"):
            millidegrees = _read_int(path)
            if millidegrees is None:
                continue
            base = path[: -len("_input")]
            label = _read_text(f"{base}_label") or _path_tail(base)
            readings.append(Temperature(label=label, celsius=millidegrees / 1000.0, source="hwmon"))

    for zone in _sorted_glob(f"{SYS}/class/thermal/thermal_zone*"):
        millidegrees = _read_int(f"{zone}/temp")
        if millidegrees is None:
            continue
        kind = _read_text(f"{zone}/type") or _path_tail(zone)
        readings.append(Temperature(label=_abbreviate(kind), celsius=millidegrees / 1000.0, source="thermal"))

    unique: List[Temperature] = []
    seen = set()
    for reading in readings:
        key = (reading.label.upper(), None if reading.celsius is None else round(reading.celsius))
        if key in seen:
            continue
        seen.add(key)
        unique.append(reading)
    return unique[:max(0, limit)]


@dataclass(frozen=True)
class BatterySample:
    present: bool
    percent: Optional[float]
    status: str
    watts: Optional[float]


def read_battery() -> BatterySample:
    """First battery in /sys/class/power_supply, or present=False.

    A desktop has no battery and a VM may not expose power_supply at all; both
    are normal, so the caller gets a sample that says so instead of an error.
    """
    for path in _sorted_glob(f"{SYS}/class/power_supply/*"):
        scope = _read_text(f"{path}/scope")
        if scope and scope.lower() not in ("battery", "device"):
            continue
        percent = _read_float(f"{path}/capacity")
        if percent is None:
            continue  # a mains adapter has no capacity file
        status = (_read_text(f"{path}/status") or NA).lower()
        watts = _read_float(f"{path}/power_now")
        if watts is not None:
            # power_now is microwatts for USB devices and milliwatts for
            # everything else; both spellings appear in the wild.
            watts = watts / 1_000_000.0 if watts > 100_000 else watts / 1000.0
        return BatterySample(present=True, percent=clamp(percent, 0.0, 100.0), status=status, watts=watts)
    return BatterySample(present=False, percent=None, status=NA, watts=None)


# ---------------------------------------------------------------------------
# Processes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProcessRow:
    pid: int
    name: str
    cpu_percent: Optional[float]
    mem_percent: Optional[float]
    rss_bytes: int


class ProcessMeter:
    """Top processes by CPU, computed from /proc/<pid>/stat jiffy deltas.

    `psutil` is not in the image and must not be added: the HUD's whole point is
    that it works on a stock AstraOS install with nothing but what the desktop
    package list already pulls in. Two reads per process per tick is the
    affordable price of that - the full task list on a desktop session is a few
    hundred entries, which is a sub-millisecond scan.

    CPU percentage uses the same convention as `top`: the delta of a process's
    utime+stime divided by the delta of *all* CPUs, so 100% means one fully
    saturated logical CPU regardless of core count.
    """

    def __init__(self, limit: int = 6, page_size: Optional[int] = None) -> None:
        self.limit = max(1, int(limit))
        self.page_size = page_size or _page_size()
        self._previous: Dict[int, int] = {}

    def sample(self, cpu_ticks_delta: int, memory_total: Optional[float]) -> List[ProcessRow]:
        """Return the busiest processes, or an empty list if /proc is unreadable.

        A process that exits between the directory scan and its own /proc read
        simply drops out of the table. That is the common case, not an error, and
        it must never raise out of a timer callback.
        """
        try:
            entries = os.listdir(PROC)
        except OSError:
            return []

        current: Dict[int, int] = {}
        rows: List[ProcessRow] = []
        for entry in entries:
            if not entry.isdigit():
                continue
            pid = int(entry)
            record = _read_process(pid, self.page_size)
            if record is None:
                continue
            ticks, rss_bytes = record
            current[pid] = ticks

            previous_ticks = self._previous.get(pid)
            percent: Optional[float] = None
            if previous_ticks is not None and cpu_ticks_delta > 0:
                delta = ticks - previous_ticks
                if delta >= 0:
                    percent = clamp(100.0 * delta / cpu_ticks_delta, 0.0, 999.0)
            mem_percent = None
            if memory_total:
                mem_percent = clamp(100.0 * rss_bytes / memory_total, 0.0, 100.0)
            rows.append(ProcessRow(
                pid=pid,
                name=_PROCESS_NAME.get(pid, "?"),
                cpu_percent=percent,
                mem_percent=mem_percent,
                rss_bytes=rss_bytes,
            ))

        # Drop the names of processes that no longer exist, so the cache cannot
        # grow for the lifetime of a session that has run thousands of them.
        self._previous = current
        for dead in [pid for pid in _PROCESS_NAME if pid not in current]:
            del _PROCESS_NAME[dead]

        measurable = [row for row in rows if row.cpu_percent is not None]
        if not measurable:
            # Nothing has two samples yet. Sort by memory instead of showing an
            # empty table - it is real data, and CPU values appear from the next
            # tick onwards.
            measurable = rows
        measurable.sort(key=lambda row: (row.cpu_percent if row.cpu_percent is not None else 0.0,
                                         row.mem_percent or 0.0, row.rss_bytes), reverse=True)
        return measurable[: self.limit]


# /proc/<pid>/stat is re-read on the next tick, so names are cached in a module
# level dict keyed by pid. A private cache beats re-parsing comm for every
# process on every tick, and is cleared of dead pids by sample() itself.
_PROCESS_NAME: Dict[int, str] = {}


def _read_process(pid: int, page_size: int) -> Optional[Tuple[int, int]]:
    """Return (utime + stime in jiffies, resident bytes) for one pid."""
    stat = read_text(f"{PROC}/{pid}/stat", 4096)
    if not stat:
        return None
    # comm may contain spaces and parentheses ('(a b) worker'), so the fixed
    # fields are located after the *last* ')' rather than by splitting blindly.
    close = stat.rfind(")")
    if close < 0:
        return None
    fields = stat[close + 2:].split()
    if len(fields) < 13:
        return None
    comm = stat[stat.find("(") + 1:close]
    try:
        ticks = int(fields[11]) + int(fields[12])  # utime, stime
    except ValueError:
        return None
    _PROCESS_NAME[pid] = comm

    statm = read_text(f"{PROC}/{pid}/statm", 128)
    resident_pages = 0
    if statm:
        parts = statm.split()
        if len(parts) >= 2:
            try:
                resident_pages = int(parts[1])
            except ValueError:
                resident_pages = 0
    return ticks, resident_pages * page_size


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class InterfaceTraffic:
    name: str
    rx_bytes: int
    tx_bytes: int
    rx_bytes_per_second: Optional[float]
    tx_bytes_per_second: Optional[float]


@dataclass(frozen=True)
class NetworkSample:
    state: str
    interface: Optional[str]
    ipv4: Optional[str]
    gateway: Optional[str]
    ping_ms: Optional[float]
    ping_supported: bool
    interfaces: Tuple[InterfaceTraffic, ...]
    rx_bytes_per_second: Optional[float]
    tx_bytes_per_second: Optional[float]
    total_rx_bytes: int
    total_tx_bytes: int
    uptime_seconds: Optional[float]


class TrafficMeter:
    """Per-interface byte rates plus the rolling history the traffic graph draws.

    /proc/net/dev is monotonic, so rates come from differencing two readings
    against the wall clock, exactly as the CPU meter does. The history deque is
    bounded by HUD_TRAFFIC_SAMPLES (120 samples, two minutes at the default
    1 s cadence) because an unbounded list on a long-running desktop session is a
    slow memory leak that nobody notices until the machine feels wrong.
    """

    def __init__(self, history: int = HUD_TRAFFIC_SAMPLES) -> None:
        self.history: Deque[Tuple[float, float]] = deque(maxlen=max(2, history))
        self._previous: Dict[str, Tuple[int, int]] = {}
        self._previous_time: Optional[float] = None
        self._lock = threading.Lock()

    def sample(self, uptime_seconds: Optional[float] = None) -> Tuple[
        Tuple[InterfaceTraffic, ...], Optional[float], Optional[float], int, int
    ]:
        """Return (interfaces, rx/s, tx/s, total_rx, total_tx) for non-loopback links."""
        counters = _read_net_dev()
        now = time.monotonic()
        with self._lock:
            previous, previous_time = self._previous, self._previous_time
            elapsed = None if (previous_time is None or not counters) else max(1e-6, now - previous_time)
            self._previous = counters
            self._previous_time = now if counters else previous_time

        interfaces: List[InterfaceTraffic] = []
        total_rx = total_tx = 0
        rx_rate = tx_rate = None
        for name, (rx_bytes, tx_bytes) in sorted(counters.items()):
            if name == "lo":
                # Loopback traffic on a desktop is normally constant background
                # chatter; counting it would peg the graph and hide real WAN use.
                continue
            total_rx += rx_bytes
            total_tx += tx_bytes
            rx_per_second = tx_per_second = None
            if elapsed and name in previous:
                delta_rx = max(0, rx_bytes - previous[name][0])
                delta_tx = max(0, tx_bytes - previous[name][1])
                rx_per_second = delta_rx / elapsed
                tx_per_second = delta_tx / elapsed
                rx_rate = (rx_rate or 0.0) + rx_per_second
                tx_rate = (tx_rate or 0.0) + tx_per_second
            interfaces.append(
                InterfaceTraffic(
                    name=name,
                    rx_bytes=rx_bytes,
                    tx_bytes=tx_bytes,
                    rx_bytes_per_second=rx_per_second,
                    tx_bytes_per_second=tx_per_second,
                )
            )

        if rx_rate is None or tx_rate is None:
            # No previous sample yet, so the graph gets no point at all rather
            # than a zero that would read as "this link is idle".
            pass
        else:
            self.history.append((rx_rate, tx_rate))
        return tuple(interfaces), rx_rate, tx_rate, total_rx, total_tx


def _read_net_dev() -> Dict[str, Tuple[int, int]]:
    """Parse /proc/net/dev into {interface: (rx_bytes, tx_bytes)}."""
    counters: Dict[str, Tuple[int, int]] = {}
    for line in read_lines(f"{PROC}/net/dev"):
        name, _, rest = line.partition(":")
        fields = rest.split()
        if len(fields) < 9:
            continue
        try:
            counters[name.strip()] = (int(fields[0]), int(fields[8]))
        except ValueError:
            continue
    return counters


def default_gateway() -> Tuple[Optional[str], Optional[str]]:
    """Return (gateway address, outbound interface) from /proc/net/route.

    Addresses in the routing table are little-endian hex (0202A8C0 is
    192.168.2.2), a detail that is easy to get backwards; the value is byte
    swapped before being formatted.
    """
    try:
        with open(f"{PROC}/net/route", "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return None, None
    for line in lines[1:]:
        fields = line.split()
        if len(fields) < 4 or fields[1] != "00000000":
            continue
        try:
            gateway = socket.inet_ntoa(struct.pack("<L", int(fields[2], 16)))
        except (ValueError, OSError, struct.error):
            gateway = None
        return gateway, fields[0]
    return None, None


def local_ipv4(gateway: Optional[str] = None) -> Optional[str]:
    """The address this host uses to reach the outside world, or None.

    A datagram socket is connected to the gateway with port 1 and never sends a
    byte: connect() on UDP only asks the kernel which source address and route
    it would use, so this costs no packets and no privileges. That is a far more
    reliable answer than enumerating interfaces for one that is not loopback,
    which is what naive implementations do.
    """
    if gateway is None:
        gateway, _ = default_gateway()
    target = gateway or "192.0.2.1"  # RFC 5737 TEST-NET-1: routed nowhere by the kernel.
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.settimeout(0.2)
        probe.connect((target, 1))
        address = probe.getsockname()[0]
    except OSError:
        address = None
    finally:
        probe.close()

    if not address or address.startswith("127."):
        try:
            fallback = socket.gethostbyname(socket.gethostname())
        except OSError:
            fallback = None
        if fallback and not fallback.startswith("127."):
            address = fallback
    if address == "0.0.0.0":
        return None
    return address


_ICMP_ECHO_REQUEST = 8
_ICMP_ECHO_REPLY = 0


class PingProbe:
    """Round-trip latency to the default gateway, measured with an ICMP echo.

    Why not `ping`: forking a subprocess every second from a GTK timeout handler
    is a main-loop stall and an ugly dependency on a coreutils binary being
    installed. Instead the probe speaks ICMP itself over a raw (or, when the
    kernel's ping_group_range allows it, datagram) socket, which needs no root.

    The measurement happens on a daemon thread and is read back through a lock,
    so a missing gateway or a filtered packet can never stall the tick: the
    worker reports failure once and stops rather than retrying forever. When the
    socket cannot be opened at all (no CAP_NET_RAW and no ping_group_range
    entry - both plausible in a locked-down session) `supported` is False and the
    HUD prints N/A instead of a latency figure nobody measured.
    """

    def __init__(self, timeout: float = 0.8, interval: float = 5.0, enabled: bool = True) -> None:
        self.timeout = max(0.1, float(timeout))
        self.interval = max(1.0, float(interval))
        self._enabled = bool(enabled)
        self._target: Optional[str] = None
        self._result: Optional[float] = None
        self._supported: Optional[bool] = None
        self._last_attempt: float = 0.0
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    # -- public API used by the collector ----------------------------------

    def set_target(self, address: Optional[str]) -> None:
        """Point the probe at a new address (the gateway, when there is one)."""
        with self._lock:
            if address != self._target:
                self._target = address
                self._result = None

    def result(self) -> Tuple[Optional[float], bool]:
        """Return (latency_ms, supported). Never blocks."""
        with self._lock:
            return self._result, bool(self._supported)

    def close(self) -> None:
        self._stop.set()

    def ensure_started(self) -> None:
        """Start the worker thread. No-op when the probe is disabled.

        Called from the collection pass rather than __init__ so that a disabled
        probe never creates a thread at all, which keeps `--no-network` free of
        any socket, any DNS lookup and any background work.
        """
        self._ensure_thread()

    # -- worker ------------------------------------------------------------

    def _ensure_thread(self) -> None:
        if not self._enabled or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="astraos-hud-ping", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        sock = None
        try:
            sock = self._open_socket()
            with self._lock:
                self._supported = sock is not None
            if sock is None:
                return  # permissions or a kernel without ICMP: report N/A forever
            while not self._stop.is_set():
                with self._lock:
                    target = self._target
                    due = (time.monotonic() - self._last_attempt) >= self.interval
                    self._last_attempt = time.monotonic()
                if target and due:
                    latency = self._echo_once(sock, target)
                    with self._lock:
                        self._result = latency
                self._stop.wait(0.5)
        except Exception:  # noqa: BLE001 - a probe thread must never take the app down
            with self._lock:
                self._supported = False
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass

    def _open_socket(self) -> Optional[socket.socket]:
        """Prefer an unprivileged ICMP datagram socket, fall back to a raw one."""
        for kind in (socket.SOCK_DGRAM, socket.SOCK_RAW):
            try:
                return socket.socket(socket.AF_INET, kind, socket.IPPROTO_ICMP)
            except (PermissionError, OSError):
                continue
        return None

    def _echo_once(self, sock: socket.socket, host: str) -> Optional[float]:
        try:
            address = socket.gethostbyname(host)
        except OSError:
            return None
        identifier = os.getpid() & 0xFFFF
        sequence = int(time.monotonic() * 1000) & 0xFFFF
        payload = b"astraos-hud"
        header = struct.pack("!BBHHH", _ICMP_ECHO_REQUEST, 0, 0, identifier, sequence)
        checksum = _icmp_checksum(header + payload)
        packet = struct.pack("!BBHHH", _ICMP_ECHO_REQUEST, 0, checksum, identifier, sequence) + payload

        started = time.perf_counter()
        try:
            sock.sendto(packet, (address, 0))
            readable, _, _ = select.select([sock], [], [], self.timeout)
            if not readable:
                return None
            reply, _peer = sock.recvfrom(2048)
        except OSError:
            return None
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if not reply or reply[0] != _ICMP_ECHO_REPLY or len(reply) < 8:
            return None
        reply_id, reply_seq = struct.unpack("!HH", reply[4:8])
        if reply_id != identifier or reply_seq != sequence:
            return None  # a stale reply from an earlier probe: ignore it
        return max(0.0, elapsed_ms)


def _icmp_checksum(data: bytes) -> int:
    """The Internet checksum (RFC 1071) used by ICMP echo."""
    if len(data) % 2:
        data += b"\x00"
    total = 0
    for index in range(0, len(data), 2):
        total += (data[index] << 8) + data[index + 1]
    total = (total >> 16) + (total & 0xFFFF)
    total += total >> 16
    return (~total) & 0xFFFF


# ---------------------------------------------------------------------------
# Endpoints for the world view
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Endpoint:
    """A network endpoint with coordinates supplied by the operator.

    AstraOS does not ship a geolocation database and the HUD makes no outbound
    HTTP request to a third party to find one - a desktop that phones home
    every second to draw a dot on a globe is not a desktop anybody asked for.
    Coordinates therefore come from a local, operator-edited file:

        # /etc/astraos/hud-endpoints.conf
        192.168.2.1     37.7749  -122.4194   gateway
        198.51.100.24   51.5072  -0.1276     mirror

    With no file the world view says so instead of inventing a location.
    """

    label: str
    address: str
    latitude: float
    longitude: float


def load_endpoint_map(path: str = ENDPOINTS_FILE) -> Dict[str, Endpoint]:
    """Parse the endpoint file into {address: Endpoint}. Missing file -> empty map."""
    endpoints: Dict[str, Endpoint] = {}
    for lineno, raw in enumerate(read_lines(path), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        fields = line.split()
        if len(fields) < 3:
            continue  # tolerate a malformed line rather than refusing to start
        address, latitude, longitude = fields[0], fields[1], fields[2]
        label = " ".join(fields[3:]) if len(fields) > 3 else address
        try:
            lat, lon = float(latitude), float(longitude)
        except ValueError:
            continue
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue
        endpoints[address] = Endpoint(label=label, address=address, latitude=lat, longitude=lon)
    return endpoints


# ---------------------------------------------------------------------------
# Filesystems
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MountInfo:
    device: str
    mountpoint: str
    fstype: str
    total_bytes: Optional[float]
    used_bytes: Optional[float]
    percent: Optional[float]
    readable: bool


#: Pseudo and container filesystems never shown to a user: they are not storage
#: anyone can fill up, and listing them would bury the volumes that matter.
_PSEUDO_FILESYSTEMS = frozenset({
    "autofs", "bpf", "cgroup", "cgroup2", "configfs", "debugfs", "devpts", "devtmpfs",
    "efivarfs", "fuse.gvfsd-fuse", "fuse.portal", "fusectl", "hugetlbfs", "mqueue",
    "overlay", "proc", "pstore", "ramfs", "rpc_pipefs", "securityfs", "squashfs",
    "sysfs", "tmpfs", "tracefs", "nsfs",
})


@dataclass(frozen=True)
class FilesystemSample:
    mounts: Tuple[MountInfo, ...]
    unreadable: int


def filesystem_sample(limit: int = 10) -> FilesystemSample:
    """Mounted volumes with used/total from statvfs.

    A volume can be unmounted, or its filesystem can return EIO, between reading
    /proc/self/mounts and calling statvfs. Those mounts are reported with
    readable=False and counted separately, so the bottom strip can say
    '1 volume unreadable' rather than quietly shrinking the list and pretending
    the disk is fine.
    """
    mounts: List[MountInfo] = []
    unreadable = 0
    seen = set()
    for line in read_lines(f"{PROC}/self/mounts"):
        fields = line.split()
        if len(fields) < 3:
            continue
        device, mountpoint, fstype = fields[0], _unescape_octal(fields[1]), fields[2]
        if fstype in _PSEUDO_FILESYSTEMS:
            continue
        if not (mountpoint == "/" or device.startswith("/dev/") or fstype in ("btrfs", "zfs")):
            continue
        key = (device, mountpoint)
        if key in seen:
            continue
        seen.add(key)

        try:
            stat = os.statvfs(mountpoint)
        except OSError:
            mounts.append(MountInfo(device=device, mountpoint=mountpoint, fstype=fstype,
                                    total_bytes=None, used_bytes=None, percent=None, readable=False))
            unreadable += 1
            continue
        fragment = stat.f_frsize or stat.f_bsize
        total = float(stat.f_blocks) * fragment
        used = float(stat.f_blocks - stat.f_bfree) * fragment
        mounts.append(MountInfo(
            device=device,
            mountpoint=mountpoint,
            fstype=fstype,
            total_bytes=total,
            used_bytes=used,
            percent=None if total <= 0 else clamp(100.0 * used / total, 0.0, 100.0),
            readable=True,
        ))

    mounts.sort(key=lambda mount: (
        mount.mountpoint != "/",
        -(mount.total_bytes or 0.0),
        mount.mountpoint,
    ))
    return FilesystemSample(mounts=tuple(mounts[: max(0, limit)]), unreadable=unreadable)


def disk_io_rates() -> Tuple[Optional[float], Optional[float]]:
    """Sector read/write rates from /proc/diskstats, in bytes per second.

    Returns (read_bytes_per_second, write_bytes_per_second) over the same class
    of mounted block devices the FILESYSTEM strip lists. Fields 3 and 5 of a
    /proc/diskstats row are the sectors read and written; the kernel's sector
    size is 512 bytes regardless of the device's logical block size.
    """
    counts: Dict[str, Tuple[int, int]] = {}
    for line in read_lines(f"{PROC}/diskstats"):
        fields = line.split()
        if len(fields) < 10:
            continue
        name = fields[2]
        try:
            counts[name] = (int(fields[5]), int(fields[9]))
        except ValueError:
            continue
    if not counts:
        return None, None

    try:
        stat = os.statvfs("/")
    except OSError:
        return None, None
    now = time.monotonic()
    previous = _DISK_IO.get("counts")
    elapsed = None if previous is None else max(1e-6, now - _DISK_IO.get("time", now))
    _DISK_IO["counts"], _DISK_IO["time"] = counts, now
    if previous is None or elapsed <= 0:
        return None, None
    read_delta = sum(max(0, current[0] - previous.get(name, current)[0]) for name, current in counts.items())
    write_delta = sum(max(0, current[1] - previous.get(name, current)[1]) for name, current in counts.items())
    return read_delta * 512.0 / elapsed, write_delta * 512.0 / elapsed


#: Previous /proc/diskstats reading and the monotonic time it was taken at, so
#: the next call can difference it. Module level rather than per-call because
#: disk_io_rates() is a free function and the HUD has exactly one instance.
_DISK_IO: Dict[str, object] = {"counts": None, "time": 0.0}


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SystemIdentity:
    hostname: str
    user: str
    os_name: str
    kernel: str
    cpu_model: str
    shell: str


def read_identity() -> SystemIdentity:
    """Static facts about this machine and this session.

    Read once per snapshot rather than cached forever: the hostname can be
    changed from the settings daemon while the HUD is open, and a status line
    that lies about the machine it is reporting on is worse than one that is
    half a second stale in the right direction.
    """
    pretty = NA
    for line in read_lines("/etc/os-release"):
        if line.startswith("PRETTY_NAME="):
            pretty = line.partition("=")[2].strip().strip('"') or NA
            break
    try:
        uname = os.uname()
    except (AttributeError, OSError):
        uname = None
    return SystemIdentity(
        hostname=socket.gethostname() or NA,
        user=os.environ.get("USER") or os.environ.get("LOGNAME") or NA,
        os_name=pretty,
        kernel=(f"{uname.sysname} {uname.release}".strip() if uname else NA),
        cpu_model=read_cpu_model(),
        shell=os.environ.get("SHELL") or "/bin/bash",
    )


# ---------------------------------------------------------------------------
# The snapshot
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SystemSnapshot:
    """Everything one tick of the HUD measures, in one immutable object.

    Widgets receive this and nothing else. That is what keeps a panel repaint
    from reading /proc: there is exactly one collection pass per tick, so the
    whole HUD costs the same whether one region or six are visible.
    """

    timestamp: float
    monotonic: float
    tick: int
    first_sample: bool
    identity: SystemIdentity
    cpu: Optional[CpuSample]
    cpu_core_rows: Tuple[Optional[float], ...]
    memory: MemorySample
    load: LoadSample
    temperatures: Tuple[Temperature, ...]
    battery: BatterySample
    processes: Tuple[ProcessRow, ...]
    network: NetworkSample
    filesystems: FilesystemSample
    endpoints: Dict[str, Endpoint]
    disk_read_rate: Optional[float]
    disk_write_rate: Optional[float]


class Collector:
    """Owns the sampling state and produces one immutable snapshot per tick.

    The HUD drives this from a single GLib timeout. It is not a singleton on
    purpose: tests and the `--interval` flag construct their own, and two
    collectors in one process cannot contaminate each other's deltas.
    """

    def __init__(
        self,
        *,
        network_enabled: bool = True,
        endpoints_path: str = ENDPOINTS_FILE,
        top_processes: int = 6,
        core_group: int = 2,
    ) -> None:
        self.cpu = CpuMeter()
        self.processes = ProcessMeter(limit=top_processes)
        self.traffic = TrafficMeter()
        self.ping = PingProbe(enabled=network_enabled)
        self.endpoints_path = endpoints_path
        self.core_group = max(1, int(core_group))
        self.tick = 0
        self._previous_cpu_total = 0

    def collect(self) -> SystemSnapshot:
        """Run one full sampling pass. Never raises; never blocks on I/O."""
        self.tick += 1
        cpu_sample = self.cpu.sample()
        cpu_total = self.cpu.total_ticks
        cpu_delta = max(0, cpu_total - self._previous_cpu_total)
        self._previous_cpu_total = cpu_total

        memory = read_meminfo()
        load = read_loadavg()
        temperatures = tuple(read_temperatures())
        battery = read_battery()
        identity = read_identity()
        processes = tuple(self.processes.sample(cpu_delta, memory.total_bytes))

        gateway, interface = default_gateway()
        interfaces, rx_rate, tx_rate, total_rx, total_tx = self.traffic.sample(load.uptime_seconds)
        ipv4 = local_ipv4(gateway)
        self.ping.set_target(gateway)
        self.ping.ensure_started()
        ping_ms, ping_supported = self.ping.result()

        network = NetworkSample(
            state="ONLINE" if ipv4 else ("LOCAL" if interface else "OFFLINE"),
            interface=interface,
            ipv4=ipv4,
            gateway=gateway,
            ping_ms=ping_ms,
            ping_supported=ping_supported,
            interfaces=interfaces,
            rx_bytes_per_second=rx_rate,
            tx_bytes_per_second=tx_rate,
            total_rx_bytes=total_rx,
            total_tx_bytes=total_tx,
            uptime_seconds=load.uptime_seconds,
        )

        read_rate, write_rate = disk_io_rates()

        return SystemSnapshot(
            timestamp=time.time(),
            monotonic=time.monotonic(),
            tick=self.tick,
            first_sample=self.tick <= 1,
            identity=identity,
            cpu=cpu_sample,
            cpu_core_rows=tuple(group_cores(cpu_sample.cores, self.core_group)) if cpu_sample else tuple(),
            memory=memory,
            load=load,
            temperatures=temperatures,
            battery=battery,
            processes=processes,
            network=network,
            filesystems=filesystem_sample(),
            endpoints=load_endpoint_map(self.endpoints_path),
            disk_read_rate=read_rate,
            disk_write_rate=write_rate,
        )

    def close(self) -> None:
        """Stop the background probe thread. Called once, on application exit."""
        self.ping.close()


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------

_OCTAL_ESCAPE = re.compile(r"\\([0-7]{3})")


def _unescape_octal(value: str) -> str:
    """/proc/self/mounts writes spaces and other specials as \\040 style octal."""
    return _OCTAL_ESCAPE.sub(lambda match: chr(int(match.group(1), 8)), value)


def _sorted_glob(pattern: str) -> List[str]:
    """Sorted glob that returns an empty list instead of raising on a bad pattern."""
    from glob import glob

    try:
        return sorted(glob(pattern))
    except OSError:
        return []


def _path_tail(path: str) -> str:
    return path.rstrip("/").rsplit("/", 1)[-1] or path


def _abbreviate(label: str) -> str:
    """Shorten a sensor type to something that fits a HUD column ('x86_pkg_temp' -> 'PKG')."""
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", label).strip("_").upper()
    for prefix, short in (("X86_PKG_TEMP", "PKG"), ("CPU", "CPU"), ("SOC", "SOC"), ("GPU", "GPU")):
        if cleaned.startswith(prefix):
            return short
    return cleaned[:8] if len(cleaned) > 8 else (cleaned or "TEMP")


def _read_text(path: str) -> Optional[str]:
    text = read_text(path, 512)
    return text.strip() if text else None


def _read_int(path: str) -> Optional[float]:
    value = _read_text(path)
    try:
        return float(value) if value else None
    except ValueError:
        return None


def _read_float(path: str) -> Optional[float]:
    return _read_int(path)


def _page_size() -> int:
    try:
        return int(os.sysconf("SC_PAGE_SIZE"))
    except (AttributeError, ValueError, OSError):
        return 4096
