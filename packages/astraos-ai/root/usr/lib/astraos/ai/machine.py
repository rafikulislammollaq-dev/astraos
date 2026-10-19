"""The machine's own capability profile: what this computer is, measured.

Stage 2 of the roadmap asks for a capability profile - CPU flags and instruction
sets, RAM, graphics, an accelerator where one exists, audio, free storage -
written at first run and shown in plain words, with an "AI readiness" statement
derived from measurements rather than from branding. This module is that
measurement.

Everything is read from files under one root (default ``/``): ``/proc/cpuinfo``,
``/proc/meminfo``, ``/proc/asound/cards``, ``/sys/class/drm`` and
``/sys/class/accel``. That is a deliberate choice with two consequences:

  * it is an unprivileged reading. An ordinary process can read all of it, so
    the profile is produced the way the assistant itself runs - as the user,
    never as root; and
  * it is testable and auditable. ``collect(root=...)`` points at a fixture
    tree in tests, and anyone can compare the output against the files it
    claims to have read.

The readiness statement is conservative and its thresholds come from the model
ladder in ``tiers.py``, not from taste: a 1.5B Q4 model is about 1 GB resident
and a 4B about 2.4 GB, the KV cache adds a slice on top, and the downloaded
files themselves take disk. The engine builds this release ships are compiled
with AVX on and AVX2, F16C, FMA, BMI2 and AVX512 off (``setup.py``), for the
Sandy Bridge target machine, so AVX is the hard floor and AVX2 is genuinely
optional. The readiness line says what was measured; it is not a benchmark and
does not pretend to be one.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

# The floors the small models in tiers.py stay comfortable above on the
# reference machine (Sandy Bridge desktop, 4 GB). Below either number the
# rung drops to "tight" with the reason named, rather than silently promising
# a model will fit.
MIN_RAM_GIB = 3.5
MIN_FREE_GIB = 4.0

# The flag the shipped engine builds actually require. See the module docstring.
REQUIRED_FLAG = "avx"

# The flags worth reporting: what llama.cpp-style CPU inference uses or is
# commonly asked about. The list is fixed so the profile has the same shape on
# every machine.
WATCHED_FLAGS = ("avx", "avx2", "f16c", "fma", "bmi2", "avx512f", "sse4_2")

# The flags the avx2 build is compiled for (setup.py). "avx2" alone is not the
# question: the build also uses F16C, FMA and BMI2, and a CPU that lists AVX2 but
# lacks one of those would SIGILL on the first question - the exact failure this
# profile exists to prevent.
AVX2_BUILD_FLAGS = ("avx2", "f16c", "fma", "bmi2")

# Headroom kept free after the models are downloaded, so that installing the
# ladder cannot be the thing that fills the user's disk.
DISK_HEADROOM_GIB = 1.0

# The ladder rungs, highest first. Each entry is the rung's name, the RAM it needs,
# the tiers it fills with their model and resident size, and the sentence a person
# reads. The sizes and floors are docs/AI.md's table, not taste: the 1.7B executor
# is ~1.0 GB resident and runs on the 4 GB reference machine, the 4B middle brain
# is ~2.4 GB and wants 6 GB, and the 360M router is ~0.4 GB.
LADDER_RUNGS: tuple[tuple[str, float, tuple[tuple[str, str, float], ...], str], ...] = (
    (
        "full",
        6.0,
        (
            ("worker", "spark-x2.5-1.7b-q4_k_m", 1.0),
            ("brain", "spark-x2.5-4b-q4_k_m", 2.4),
            ("router", "smollm2-360m-instruct-q8_0", 0.4),
        ),
        "the whole ladder: the executor, the middle brain and the router",
    ),
    (
        "worker",
        3.5,
        (
            ("worker", "spark-x2.5-1.7b-q4_k_m", 1.0),
            ("router", "smollm2-360m-instruct-q8_0", 0.4),
        ),
        "the executor and the router; a request that needs the middle brain is "
        "handed back to the user instead of being guessed at",
    ),
    (
        "router",
        2.0,
        (("router", "smollm2-360m-instruct-q8_0", 0.4),),
        "the router alone: the assistant can sort a request but cannot act on it",
    ),
)


def _read(path: Path) -> str:
    """Read a file that may legitimately not exist on this machine."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _gib(kib: int) -> float:
    return kib / (1024 * 1024)


def _cpu(root: Path) -> dict:
    text = _read(root / "proc" / "cpuinfo")
    name = ""
    flags: set[str] = set()
    cores = 0
    for line in text.splitlines():
        if line.startswith("processor"):
            cores += 1
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if key == "model name" and not name:
            name = value
        elif key == "flags" and not flags:
            # split() on the whole line, so "avx" never matches "avx2".
            flags = set(value.split())
    return {
        "name": name or "unknown",
        "cores": cores,
        "instructions": [flag for flag in WATCHED_FLAGS if flag in flags],
        "missing_instructions": [flag for flag in WATCHED_FLAGS if flag not in flags],
    }


def _memory(root: Path) -> dict:
    text = _read(root / "proc" / "meminfo")
    values: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, rest = line.partition(":")
        if sep:
            values[key.strip()] = rest.strip()

    def kib(name: str) -> int:
        digits = values.get(name, "").split()
        try:
            return int(digits[0]) if digits else 0
        except ValueError:
            return 0

    return {"ram_kib": kib("MemTotal"), "swap_kib": kib("SwapTotal")}


def _graphics(root: Path) -> dict:
    base = root / "sys" / "class" / "drm"
    cards: list[str] = []
    if base.is_dir():
        cards = sorted(p.name for p in base.glob("card[0-9]*") if p.is_dir())
    first = ""
    if cards:
        device = base / cards[0] / "device"
        vendor = _read(device / "vendor").strip()
        product = _read(device / "device").strip()
        if vendor and product:
            first = f"{vendor}:{product}"
    return {"cards": cards, "first": first}


def _accelerators(root: Path) -> list[str]:
    base = root / "sys" / "class" / "accel"
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir())


def _audio(root: Path) -> list[str]:
    text = _read(root / "proc" / "asound" / "cards")
    return [line.strip() for line in text.splitlines() if line.strip()]


def _storage(root: Path) -> dict:
    try:
        stats = os.statvfs(root)
    except OSError:
        return {"free_bytes": 0}
    return {"free_bytes": stats.f_bavail * stats.f_frsize}


def assess(profile: dict) -> dict:
    """Derive the AI-readiness rung from the measurements. See the docstring."""
    cpu = profile["cpu"]
    ram = _gib(profile["memory"]["ram_kib"])
    free = profile["storage"]["free_bytes"] / (1024 ** 3)

    if REQUIRED_FLAG not in cpu["instructions"]:
        return {
            "rung": "unsupported",
            "why": [
                f"the CPU does not report {REQUIRED_FLAG}",
                "the engine builds this release ships require it",
            ],
        }

    rung = "ready"
    why = [f"{REQUIRED_FLAG} present"]
    if ram < MIN_RAM_GIB:
        rung = "tight"
        why.append(f"{ram:.1f} GiB of RAM, below the {MIN_RAM_GIB} GiB the small models want")
    else:
        why.append(f"{ram:.1f} GiB of RAM")
    if free < MIN_FREE_GIB:
        rung = "tight"
        why.append(
            f"{free:.1f} GiB free on /, below the {MIN_FREE_GIB} GiB a downloaded model needs"
        )
    else:
        why.append(f"{free:.1f} GiB free on /")
    if not profile["graphics"]["cards"]:
        why.append("no card under /sys/class/drm (headless machine or virtual machine)")
    if profile["accelerators"]:
        why.append("accelerator present: " + ", ".join(profile["accelerators"]))
    return {"rung": rung, "why": why}


def recommend(profile: dict) -> dict:
    """Choose the engine build and the model rung from the measurements.

    Stage 2's promise is that the assistant picks the build and the models itself.
    This is that choice, and it is a function of the numbers in the profile and
    nothing else: the flags the CPU reports decide the engine variant, the RAM
    decides how far up the ladder the machine can go, and the free space decides
    whether the models fit. It is not a benchmark and does not guess at quality -
    it says what will run here, not how well it will think.
    """
    cpu = profile["cpu"]
    flags = set(cpu["instructions"])
    ram = _gib(profile["memory"]["ram_kib"])
    free = profile["storage"]["free_bytes"] / (1024 ** 3)

    if all(flag in flags for flag in AVX2_BUILD_FLAGS):
        variant = "avx2"
        variant_why = (
            "the CPU lists " + ", ".join(AVX2_BUILD_FLAGS) + ", so the avx2 build runs"
        )
    elif REQUIRED_FLAG in flags:
        variant = "avx"
        missing = [flag for flag in AVX2_BUILD_FLAGS if flag not in flags]
        variant_why = (
            f"the CPU lists {REQUIRED_FLAG} but not {', '.join(missing)}, so the avx "
            "build is the newest one that cannot SIGILL here"
        )
    else:
        variant = None
        variant_why = f"the CPU does not report {REQUIRED_FLAG}; no shipped build can run"

    why = [variant_why]
    if variant is None:
        return {
            "rung": "none",
            "engine_variant": None,
            "models": [],
            "summary": "no model: the engine builds this release ships cannot run on this CPU",
            "quantization": "Q4_K_M",
            "why": why,
        }

    for rung, floor_ram, models, summary in LADDER_RUNGS:
        need = sum(model[2] for model in models) + DISK_HEADROOM_GIB
        if ram < floor_ram:
            why.append(
                f"the {rung} rung wants {floor_ram:.1f} GiB of RAM; this machine has "
                f"{ram:.1f} GiB"
            )
            continue
        if free < need:
            why.append(
                f"the {rung} rung wants {need:.1f} GiB free on / for its models and "
                f"headroom; this machine has {free:.1f} GiB"
            )
            continue
        why.append(f"{summary} ({need:.1f} GiB of models and headroom)")
        return {
            "rung": rung,
            "engine_variant": variant,
            "models": [
                {"tier": tier, "model": model, "resident_gib": resident}
                for tier, model, resident in models
            ],
            "summary": summary,
            "quantization": "Q4_K_M",
            "why": why,
        }

    last = LADDER_RUNGS[-1]
    last_need = sum(model[2] for model in last[2]) + DISK_HEADROOM_GIB
    why.append(
        f"no rung fits: even the {last[0]} rung wants {last[1]:.1f} GiB of RAM and "
        f"{last_need:.1f} GiB free on /"
    )
    return {
        "rung": "none",
        "engine_variant": variant,
        "models": [],
        "summary": "no model fits this machine",
        "quantization": "Q4_K_M",
        "why": why,
    }


def collect(root: Path | str = "/") -> dict:
    """Measure the machine. ``root`` exists so tests can point at a fixture tree."""
    root = Path(root)
    profile = {
        "cpu": _cpu(root),
        "memory": _memory(root),
        "graphics": _graphics(root),
        "accelerators": _accelerators(root),
        "audio": _audio(root),
        "storage": _storage(root),
    }
    profile["readiness"] = assess(profile)
    profile["recommendation"] = recommend(profile)
    return profile


def plain_words(profile: dict) -> list[str]:
    """The profile as lines a person reads, including the readiness sentence."""
    cpu = profile["cpu"]
    memory = profile["memory"]
    storage = profile["storage"]
    presented = ", ".join(cpu["instructions"]) or "none of the ones watched"
    absent = ", ".join(cpu["missing_instructions"]) or "none"
    graphics = profile["graphics"]
    if graphics["cards"]:
        graphics_line = "yes" + (f" ({graphics['first']})" if graphics["first"] else "")
    else:
        graphics_line = "no card under /sys/class/drm"
    audio_line = profile["audio"][0] if profile["audio"] else "no cards in /proc/asound"
    accelerator_line = ", ".join(profile["accelerators"]) if profile["accelerators"] else "none found"
    readiness = profile["readiness"]
    recommendation = profile.get("recommendation") or recommend(profile)
    variant = recommendation["engine_variant"] or "none"
    models = ", ".join(
        f"{entry['tier']} {entry['model']}" for entry in recommendation["models"]
    ) or "none fit this machine"
    return [
        f"CPU           {cpu['name']} ({cpu['cores']} cores)",
        f"Instructions  {presented}",
        f"Not reported  {absent}",
        f"Memory        {_gib(memory['ram_kib']):.1f} GiB RAM, "
        f"{_gib(memory['swap_kib']):.1f} GiB swap",
        f"Graphics      {graphics_line}",
        f"Accelerator   {accelerator_line}",
        f"Audio         {audio_line}",
        f"Free on /     {storage['free_bytes'] / (1024 ** 3):.1f} GiB",
        "",
        f"AI readiness  {readiness['rung']} "
        f"(derived from the measurements above: {'; '.join(readiness['why'])})",
        f"AI rung       {recommendation['rung']} - {recommendation['summary']}",
        f"Engine build  {variant} (chosen from the flags above)",
        f"Models        {models}",
    ]


def write(profile: dict, path: Path | str, now: str | None = None) -> Path:
    """Write the profile as JSON beside the assistant's settings."""
    path = Path(path)
    data = dict(profile)
    data["generated_at"] = now or time.strftime("%Y-%m-%dT%H:%M:%S%z")
    data["generated_by"] = "astra-ai profile"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load(path: Path | str) -> dict | None:
    """Read back a written profile, or None when there is none to read."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
