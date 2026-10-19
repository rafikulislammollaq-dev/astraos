"""Everything the assistant can do, and the rules that bound it.

The catalog in this file is the assistant's entire repertoire. The model may
ask for nothing else: parse_plan() rejects any action name that is not a key of
ACTIONS, and execute() never guesses what an unknown name might have meant.

Why the destructive actions are separated out:

    Some actions cannot be undone, or cannot be undone cheaply: closing a
    window that has unsaved work in it, suspending, restarting, powering off,
    running an arbitrary command, and - since Astra Guard classified it - typing
    text into the focused window and pressing a key, because a terminal makes
    both of those a way to run a command. They carry dangerous=True *and*
    needs_confirm=True, and execute() refuses them unless the caller passes
    confirmed=True. The refusal names the action it refused, so the message
    can be shown to the user as-is.

    Astra Guard's four levels (observe / prepare / modify / privileged) are the
    general form of the same rule, and guard.evaluate() is the enforcement;
    these flags are how the worker knows to ask before it gets that far. A test
    holds the two together, so an action that joins one without the other fails
    the suite instead of shipping.

    "Passes confirmed=True" is not something the model can do. The plan comes
    from the model, the confirmation comes from a human in front of the
    screen; the web interface and the CLI both ask before setting the flag.

Why run_command gets three extra guards:

    1. It refuses shell syntax outright (pipes, semicolons, redirection,
       substitution) instead of running it, because this code executes one
       program with subprocess and *does not run a shell*. A command that
       still contains "| sh" would therefore not do what it looks like it
       does, and a command that looks like it deletes something must not be
       silently reinterpreted.
    2. It refuses anything that names /etc, /boot, /usr or /var, sudo, doas,
       pkexec or su, and anything that would start a shell - not only a shell
       as the first word: `env sh -c "..."`, `nice sh -c "..."` and
       `xargs -0 sh -c "..."` reach a shell through a wrapper that looks
       harmless where argv[0] is tested. The rule is that the assistant never
       runs anything as root and never edits the system's own files; the guard
       is what makes that true even when the model suggests otherwise.
    3. It echoes the exact command line it is about to run, and the result
       keeps that string, so the user sees what happened rather than a
       summary of it.

What this catalog deliberately cannot do:

    Install, remove or update packages; edit files outside the home
    directory; change system settings; start or stop services; mount or
    format anything; use the network for anything but opening a page in the
    browser the user already has. If a request needs one of those, the
    assistant has to say in words that it cannot do it. The prompt says so
    too - but the prompt is a request, and this file is the enforcement.

Every subprocess call goes through _which(), _run() or _spawn(). Those three
functions are the single seam between this package and the machine, which is
why the test suite can run the whole catalog without touching a display, a
sound card or a power button: it replaces the three of them and records what
would have been executed.
"""

from __future__ import annotations

import datetime
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import config as _config
from . import guard as _guard

# The maximum output an action hands back to the model or the web interface.
# A window listing or a command that prints a directory tree can be megabytes;
# no user has ever wanted the whole thing pasted into a chat window.
MAX_OUTPUT_CHARS = 4000

# Where screenshots and typed text are capped. A "screenshot" action that
# fills the disk, or a "type_text" that types for an hour into whatever window
# has focus, is a failure mode that is cheap to close.
MAX_TYPED_CHARS = 1000

# Paths under these prefixes are refused by run_command. The assistant never
# edits the system's own files; /usr is included because a command that writes
# there is a command that has left the account it is allowed to touch.
FORBIDDEN_PREFIXES = ("/etc", "/boot", "/usr", "/var")

# Names that mean "become another user". Refused anywhere in a run_command
# line, not only as the first word: "sh -c 'sudo ...'" is the same thing.
PRIVILEGE_TOOLS = {"sudo", "doas", "pkexec", "su", "sudoedit"}

# Shell syntax that this code does not execute. See the module docstring: the
# refusal is the honest answer, because the command would otherwise be run as
# literal arguments and do something other than what it looks like.
SHELL_SYNTAX = (";", "&&", "||", "|", "`", "$(", ">", "<", "&", "\n", "\r")

# Shells, refused anywhere in a run_command line. `bash -c "..."` is a script,
# not a command, and running one would make every guard above optional - and
# argv[0] is not the only way to start one: `env sh -c ...`, `nice sh -c ...`,
# `nohup sh -c ...`, `busybox sh -c ...` and `xargs -0 sh -c ...` all reach a
# shell through a wrapper that looks harmless where the command itself is read.
# Refusing any word that names a shell is the same choice PRIVILEGE_TOOLS above
# already makes for the same reason; a word that merely mentions one (a search
# for the string "sh") is refused too, and the refusal says so and can be run
# by the user instead.
SHELLS = {"sh", "bash", "dash", "zsh", "ksh", "csh", "tcsh", "fish", "ash"}

# Keys press_key() may send. A whitelist rather than a passthrough: xdotool
# takes keysym sequences, and "any string" would let a plan send a combination
# the catalog never offered. Letters and digits are included because the
# useful combinations are ctrl+c, ctrl+v, alt+F4; everything else a model might
# invent ("ctrl+shift+Esc+F13") is refused with the list.
ALLOWED_KEYS = {
    "return", "enter", "escape", "esc", "tab", "space", "backspace", "delete",
    "insert", "home", "end", "page_up", "page_down", "prior", "next",
    "up", "down", "left", "right", "print", "menu", "super", "hyper",
    "ctrl", "control", "alt", "shift",
    "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
} | set("abcdefghijklmnopqrstuvwxyz") | set("0123456789")

# Where a bare wallpaper name is looked for, in order.
WALLPAPER_DIRS = (
    _config.PATHS.share_dir / "wallpapers",
    Path("/usr/share/astraos/wallpapers"),
    Path.home() / "Pictures",
)


class ActionError(Exception):
    """An action failed in a way the user can act on.

    The message is the whole report: one line, no traceback, phrased so it can
    be pasted into a terminal (it names the package to install, or the reason
    the argument is wrong). execute() turns it into {"ok": False, ...}.
    """


# ---------------------------------------------------------------------------
# The single seam between this package and the machine
# ---------------------------------------------------------------------------


def _which(tool: str) -> str | None:
    """shutil.which, behind a name the tests can replace."""
    return shutil.which(tool)


def _need(tool: str, package: str | None = None) -> str:
    """The path to a tool, or ActionError naming how to install it.

    `package` is the Debian package when it differs from the command name
    (bluetoothctl lives in bluez, nmcli in network-manager).
    """
    found = _which(tool)
    if found:
        return found
    install = package or tool
    raise ActionError(
        f"not installed: {tool} - install it with: astra install {install}"
    )


def _run(argv: list[str], timeout: int = 30) -> tuple[int, str]:
    """Run a program, wait for it, return (exit code, output).

    stdout and stderr are merged: for a one-shot desktop command, the useful
    diagnostic is usually on stderr ("Cannot autolaunch D-Bus without X11
    $DISPLAY") and the two interleave in the order they happened. Never raises
    for a non-zero exit - a failing command is a result, not a crash - but
    raises ActionError for the two cases the caller cannot see: the program is
    not installed, or it did not finish in time.
    """
    try:
        completed = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            text=True,
            errors="replace",
        )
    except FileNotFoundError as exc:
        raise ActionError(f"not installed: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise ActionError(f"timed out after {timeout}s: {argv[0]}") from exc
    return completed.returncode, (completed.stdout or "").strip()


def _spawn(argv: list[str]) -> None:
    """Start a program and return without waiting for it.

    Used for anything that is a window: an editor, a browser, a file manager.
    start_new_session detaches it from this process group, so Ctrl+C in the
    terminal that launched the assistant does not close the application the
    assistant just opened for the user.
    """
    try:
        subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        raise ActionError(f"not installed: {argv[0]}") from exc
    except OSError as exc:
        raise ActionError(f"could not start {argv[0]}: {exc}") from exc


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------


def _clip(text: str) -> str:
    """Cap an action's output, saying so rather than silently dropping it."""
    text = (text or "").strip()
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + "\n(output shortened)"


def _audit(decision: dict, outcome: str, detail: str = "") -> bool:
    """Append one decision to Astra Guard's audit chain; False if it could not.

    The failure is not raised for the levels that may run without a record: a
    full disk must not stop the assistant from telling the time. execute()
    refuses privileged work without a record, which is the part that matters.
    """
    try:
        _guard.record(decision, outcome=outcome, detail=detail)
    except _guard.GuardError:
        return False
    return True


def _run_or_reason(argv: list[str], timeout: int = 30) -> str:
    """Run a one-shot command and return its output, or raise with the reason."""
    code, output = _run(argv, timeout=timeout)
    if code != 0:
        first = (output.splitlines() or ["no output"])[0]
        raise ActionError(f"{Path(argv[0]).name} failed: {first}")
    return output


def _percent(value: Any, action: str) -> int:
    """An integer 0-100, or ActionError naming the action that asked for it."""
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ActionError(f"{action} needs a whole number, not {value!r}") from None
    if not 0 <= number <= 100:
        raise ActionError(f"{action} needs 0-100, not {number}")
    return number


def _windows() -> list[tuple[str, str]]:
    """(window id, title) for every managed window, via wmctrl or xdotool."""
    wmctrl = _which("wmctrl")
    if wmctrl:
        code, output = _run([wmctrl, "-l"])
        if code != 0:
            raise ActionError("wmctrl could not list the windows (is this an X session?)")
        found = []
        for line in output.splitlines():
            parts = line.split(None, 3)
            if len(parts) == 4:
                found.append((parts[0], parts[3]))
        return found

    xdotool = _which("xdotool")
    if xdotool:
        code, output = _run([xdotool, "search", "--name", ""])
        if code != 0:
            raise ActionError("xdotool could not list the windows (is this an X session?)")
        found = []
        for window in output.split():
            code, title = _run([xdotool, "getwindowname", window])
            if code == 0 and title:
                found.append((window, title))
        return found

    raise ActionError("not installed: wmctrl or xdotool - install one with: astra install wmctrl")


def _match_window(title: str) -> tuple[str, str]:
    """The single window whose title contains `title` (case-insensitive)."""
    wanted = (title or "").strip().lower()
    if not wanted:
        raise ActionError("this action needs part of a window title")
    matches = [(wid, name) for wid, name in _windows() if wanted in name.lower()]
    if not matches:
        raise ActionError(f"no window title contains '{title}'")
    return matches[0]


def _desktop_exec(entry: Path) -> list[str]:
    """The Exec= line of a .desktop file, as an argument list.

    Parsed by hand rather than with configparser: .desktop files are INI-like
    but configparser rejects the first file that has a stray line, and the
    failure would be reported as "could not parse" for a launcher that works
    perfectly well when clicked. Only the first Exec= of [Desktop Entry] is
    read, which is what the menu does too.
    """
    try:
        text = entry.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ActionError(f"cannot read {entry.name}: {exc}") from exc

    in_entry = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            in_entry = line == "[Desktop Entry]"
            continue
        if not in_entry or not line.startswith("Exec="):
            continue

        argv = shlex.split(line[len("Exec="):])
        # Field codes (%f, %U, %i ...) are placeholders the launcher fills in;
        # leaving them would pass a literal "%U" to the program.
        cleaned = [arg for arg in argv if not re.fullmatch(r"%[a-zA-Z]", arg)]
        cleaned = [re.sub(r"%[a-zA-Z]", "", arg) for arg in cleaned]
        cleaned = [arg for arg in cleaned if arg]
        if cleaned:
            return cleaned
    raise ActionError(f"{entry.name} has no Exec line")


def _find_desktop_entry(name: str) -> Path | None:
    """The menu entry that best matches `name`, or None.

    Ranked rather than "first hit": an exact file name beats an exact menu
    name, which beats a name that starts with what was asked for, which beats
    one that merely contains it. "open the browser" has to reach Firefox even
    when a dozen entries contain the word.
    """
    wanted = (name or "").strip().lower()
    if not wanted:
        return None

    directories = [
        Path.home() / ".local" / "share" / "applications",
        Path("/usr/local/share/applications"),
        Path("/usr/share/applications"),
    ]

    best: tuple[int, Path] | None = None
    for directory in directories:
        try:
            entries = sorted(directory.glob("*.desktop"))
        except OSError:
            continue
        for entry in entries:
            stem = entry.stem.lower()
            if stem == wanted or stem == wanted + ".desktop":
                rank = 0
            else:
                menu_name = _desktop_name(entry)
                if menu_name == wanted:
                    rank = 1
                elif menu_name.startswith(wanted):
                    rank = 2
                elif wanted in menu_name or wanted in stem:
                    rank = 3
                else:
                    continue
            if _hidden_entry(entry):
                continue
            if best is None or rank < best[0]:
                best = (rank, entry)
    return best[1] if best else None


def _desktop_name(entry: Path) -> str:
    try:
        text = entry.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    in_entry = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            in_entry = line == "[Desktop Entry]"
            continue
        if in_entry and line.startswith("Name=") and "[" not in line[:6]:
            return line[len("Name="):].strip().lower()
    return ""


def _hidden_entry(entry: Path) -> bool:
    """True for entries the menu itself would not show."""
    try:
        text = entry.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return True
    for raw in text.splitlines():
        line = raw.strip()
        if line in ("NoDisplay=true", "Hidden=true"):
            return True
    return False


def _power(action: str) -> str:
    """Log out machinery: suspend, restart and power off.

    xfce4-session-logout is tried first because it is the session's own way of
    asking, it works for the logged-in user without any privilege, and it
    brings up the same confirmation the panel's menu does. systemctl is the
    fallback for a session without Xfce's logout dialog; both are run as the
    user, never with sudo.
    """
    logout = _which("xfce4-session-logout")
    if logout:
        flag = {"suspend": "--suspend", "reboot": "--reboot", "halt": "--halt"}[action]
        code, output = _run([logout, flag], timeout=60)
        if code == 0:
            return {"suspend": "suspending now", "reboot": "restarting now",
                    "halt": "powering off now"}[action]
        first = (output.splitlines() or ["no output"])[0]
        raise ActionError(f"xfce4-session-logout failed: {first}")

    command = {"suspend": "suspend", "reboot": "reboot", "halt": "poweroff"}[action]
    systemctl = _which("systemctl")
    if systemctl:
        code, output = _run([systemctl, command], timeout=60)
        if code == 0:
            return {"suspend": "suspending now", "reboot": "restarting now",
                    "halt": "powering off now"}[action]
        first = (output.splitlines() or ["no output"])[0]
        raise ActionError(f"systemctl {command} failed: {first}")
    raise ActionError("not installed: xfce4-session-logout or systemctl")


# ---------------------------------------------------------------------------
# Applications and files
# ---------------------------------------------------------------------------


def open_app(name: str = "") -> str:
    """Open a menu application by name, or a command from PATH."""
    wanted = (name or "").strip()
    if not wanted:
        raise ActionError("open_app needs an application name")

    entry = _find_desktop_entry(wanted)
    if entry is not None:
        argv = _desktop_exec(entry)
        _spawn(argv)
        return f"opened {entry.stem}"

    exe = _which(wanted)
    if exe:
        _spawn([exe])
        return f"opened {wanted}"

    raise ActionError(
        f"no application matches '{wanted}' - it is neither in the menu nor on PATH"
    )


def open_url(url: str = "") -> str:
    """Open a web page in the user's browser.

    Only http and https are accepted. The assistant is not a way to launch
    arbitrary handlers: open_path() exists for local files, and refusing
    everything else means a model-invented "url" cannot start a mail client,
    a torrent client or whatever else the desktop has registered.
    """
    target = (url or "").strip()
    if not target:
        raise ActionError("open_url needs a URL")
    if "://" not in target:
        target = "https://" + target

    parsed = urllib.parse.urlparse(target)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ActionError(f"open_url only opens http and https pages, not '{url}'")

    xdg_open = _need("xdg-open", "xdg-utils")
    _spawn([xdg_open, target])
    return f"opened {target} in the browser"


def open_path(path: str = "") -> str:
    """Open a file or folder in whatever application the user has for it."""
    target = (path or "").strip()
    if not target:
        raise ActionError("open_path needs a path")
    resolved = Path(target).expanduser()

    # Opening a device node or a kernel file in a GUI application ranges from
    # pointless to harmful, and none of them is a file the user asked to see.
    for prefix in ("/proc", "/sys", "/dev"):
        if str(resolved) == prefix or str(resolved).startswith(prefix + "/"):
            raise ActionError(f"open_path does not open {prefix} paths")

    if not resolved.exists():
        raise ActionError(f"no such file or folder: {resolved}")

    xdg_open = _need("xdg-open", "xdg-utils")
    _spawn([xdg_open, str(resolved)])
    return f"opened {resolved}"


# ---------------------------------------------------------------------------
# Volume and brightness
# ---------------------------------------------------------------------------


def _pactl() -> str | None:
    return _which("pactl")


def _amixer() -> str | None:
    return _which("amixer")


def volume_up() -> str:
    """Raise the output volume by 5%."""
    pactl = _pactl()
    if pactl:
        code, output = _run([pactl, "set-sink-volume", "@DEFAULT_SINK@", "+5%"])
        if code == 0:
            return "volume up by 5%"
        raise ActionError(f"pactl failed: {(output.splitlines() or ['no output'])[0]}")
    amixer = _amixer()
    if amixer:
        code, output = _run([amixer, "-q", "sset", "Master", "5%+"])
        if code == 0:
            return "volume up by 5%"
        raise ActionError(f"amixer failed: {(output.splitlines() or ['no output'])[0]}")
    raise ActionError("not installed: pactl or amixer - install one with: astra install pulseaudio-utils")


def volume_down() -> str:
    """Lower the output volume by 5%."""
    pactl = _pactl()
    if pactl:
        code, output = _run([pactl, "set-sink-volume", "@DEFAULT_SINK@", "-5%"])
        if code == 0:
            return "volume down by 5%"
        raise ActionError(f"pactl failed: {(output.splitlines() or ['no output'])[0]}")
    amixer = _amixer()
    if amixer:
        code, output = _run([amixer, "-q", "sset", "Master", "5%-"])
        if code == 0:
            return "volume down by 5%"
        raise ActionError(f"amixer failed: {(output.splitlines() or ['no output'])[0]}")
    raise ActionError("not installed: pactl or amixer - install one with: astra install pulseaudio-utils")


def set_volume(percent: Any = 50) -> str:
    """Set the output volume to an exact percentage."""
    level = _percent(percent, "set_volume")
    pactl = _pactl()
    if pactl:
        code, output = _run([pactl, "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"])
        if code == 0:
            return f"volume set to {level}%"
        raise ActionError(f"pactl failed: {(output.splitlines() or ['no output'])[0]}")
    amixer = _amixer()
    if amixer:
        code, output = _run([amixer, "-q", "sset", "Master", f"{level}%"])
        if code == 0:
            return f"volume set to {level}%"
        raise ActionError(f"amixer failed: {(output.splitlines() or ['no output'])[0]}")
    raise ActionError("not installed: pactl or amixer - install one with: astra install pulseaudio-utils")


def mute_toggle() -> str:
    """Mute or unmute the output, whichever it is not."""
    pactl = _pactl()
    if pactl:
        code, output = _run([pactl, "set-sink-mute", "@DEFAULT_SINK@", "toggle"])
        if code == 0:
            code, state = _run([pactl, "get-sink-mute", "@DEFAULT_SINK@"])
            if code == 0 and "no" not in state:
                return "sound muted"
            return "sound unmuted"
        raise ActionError(f"pactl failed: {(output.splitlines() or ['no output'])[0]}")
    amixer = _amixer()
    if amixer:
        code, output = _run([amixer, "-q", "sset", "Master", "toggle"])
        if code == 0:
            return "sound muted or unmuted"
        raise ActionError(f"amixer failed: {(output.splitlines() or ['no output'])[0]}")
    raise ActionError("not installed: pactl or amixer - install one with: astra install pulseaudio-utils")


def set_brightness(percent: Any = 50) -> str:
    """Set the screen backlight to an exact percentage.

    brightnessctl and light are both optional packages and both talk to
    /sys/class/backlight through udev/logind rules. On a machine where neither
    is installed, or where the user is not allowed to change the backlight,
    the honest answer is one line saying so - the assistant does not escalate
    to root to change a screen setting.
    """
    level = _percent(percent, "set_brightness")

    brightnessctl = _which("brightnessctl")
    if brightnessctl:
        code, output = _run([brightnessctl, "set", f"{level}%"])
        if code == 0:
            return f"brightness set to {level}%"
        raise ActionError(f"brightnessctl failed: {(output.splitlines() or ['no output'])[0]}")

    light = _which("light")
    if light:
        code, output = _run([light, "-S", str(level)])
        if code == 0:
            return f"brightness set to {level}%"
        raise ActionError(f"light failed: {(output.splitlines() or ['no output'])[0]}")

    raise ActionError(
        "not installed: brightnessctl or light - install one with: "
        "astra install brightnessctl"
    )


# ---------------------------------------------------------------------------
# Session: lock, screenshot
# ---------------------------------------------------------------------------


def lock_screen() -> str:
    """Lock the session with whichever locker this desktop has."""
    for tool, argv in (
        ("xflock4", ["xflock4"]),
        ("light-locker-command", ["light-locker-command", "-l"]),
        ("xfce4-screensaver-command", ["xfce4-screensaver-command", "-l"]),
        ("xdg-screensaver", ["xdg-screensaver", "lock"]),
    ):
        found = _which(tool)
        if not found:
            continue
        code, output = _run([found] + argv[1:])
        if code == 0:
            return "screen locked"
        raise ActionError(f"{tool} failed: {(output.splitlines() or ['no output'])[0]}")
    raise ActionError(
        "no screen locker is installed - install one with: astra install light-locker"
    )


def screenshot() -> str:
    """Take a full-screen screenshot into ~/Pictures/Screenshots.

    The file name is whatever the tool chooses; the action reports the path it
    actually produced by looking for the newest file, rather than predicting a
    name and being wrong about it.
    """
    directory = Path.home() / "Pictures" / "Screenshots"
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ActionError(f"cannot create {directory}: {exc}") from exc

    before = {p.name for p in directory.glob("*.png")}

    shooter = _which("xfce4-screenshooter")
    if shooter:
        code, output = _run([shooter, "--fullscreen", "--save", str(directory)])
        if code != 0:
            raise ActionError(
                f"xfce4-screenshooter failed: {(output.splitlines() or ['no output'])[0]}"
            )
    else:
        scrot = _which("scrot")
        if scrot:
            code, output = _run([scrot, str(directory / "screenshot-%Y%m%d-%H%M%S.png")])
            if code != 0:
                raise ActionError(f"scrot failed: {(output.splitlines() or ['no output'])[0]}")
        else:
            imagemagick = _which("import")
            if not imagemagick:
                raise ActionError(
                    "not installed: xfce4-screenshooter - install it with: "
                    "astra install xfce4-screenshooter"
                )
            code, output = _run([imagemagick, "-window", "root", str(directory / "screenshot.png")])
            if code != 0:
                raise ActionError(f"import failed: {(output.splitlines() or ['no output'])[0]}")

    produced = sorted(
        (p for p in directory.glob("*.png") if p.name not in before),
        key=lambda p: p.stat().st_mtime,
    )
    if produced:
        return f"screenshot saved to {produced[-1]}"
    return f"screenshot saved in {directory}"


# ---------------------------------------------------------------------------
# Network radios
# ---------------------------------------------------------------------------


def wifi_on() -> str:
    """Turn the Wi-Fi radio on."""
    nmcli = _need("nmcli", "network-manager")
    code, output = _run([nmcli, "radio", "wifi", "on"])
    if code != 0:
        raise ActionError(f"nmcli failed: {(output.splitlines() or ['no output'])[0]}")
    return "Wi-Fi on"


def wifi_off() -> str:
    """Turn the Wi-Fi radio off."""
    nmcli = _need("nmcli", "network-manager")
    code, output = _run([nmcli, "radio", "wifi", "off"])
    if code != 0:
        raise ActionError(f"nmcli failed: {(output.splitlines() or ['no output'])[0]}")
    return "Wi-Fi off"


def bluetooth_on() -> str:
    """Turn the Bluetooth radio on."""
    bluetoothctl = _which("bluetoothctl")
    if bluetoothctl:
        code, output = _run([bluetoothctl, "power", "on"])
        if code == 0:
            return "Bluetooth on"
        first = (output.splitlines() or ["no output"])[0]
        raise ActionError(f"bluetoothctl failed: {first}")
    rfkill = _which("rfkill")
    if rfkill:
        code, output = _run([rfkill, "unblock", "bluetooth"])
        if code == 0:
            return "Bluetooth on (with rfkill)"
        raise ActionError(f"rfkill failed: {(output.splitlines() or ['no output'])[0]}")
    raise ActionError("not installed: bluetoothctl - install it with: astra install bluez")


def bluetooth_off() -> str:
    """Turn the Bluetooth radio off."""
    bluetoothctl = _which("bluetoothctl")
    if bluetoothctl:
        code, output = _run([bluetoothctl, "power", "off"])
        if code == 0:
            return "Bluetooth off"
        first = (output.splitlines() or ["no output"])[0]
        raise ActionError(f"bluetoothctl failed: {first}")
    rfkill = _which("rfkill")
    if rfkill:
        code, output = _run([rfkill, "block", "bluetooth"])
        if code == 0:
            return "Bluetooth off (with rfkill)"
        raise ActionError(f"rfkill failed: {(output.splitlines() or ['no output'])[0]}")
    raise ActionError("not installed: bluetoothctl - install it with: astra install bluez")


# ---------------------------------------------------------------------------
# Media keys and windows
# ---------------------------------------------------------------------------


def _media_key(keysym: str) -> str:
    """Send one XF86 media keysym through xdotool.

    This is deliberately the *keysym* and not a player API: Xfce binds these
    keys to whatever the user chose (by default its own mixer or Parole via
    the multimedia keys plugin), so pressing the same key the keyboard would
    press is the only way to honour that choice. On a session with no Xfce
    multimedia plugin, or without xdotool, the answer is one line, not a
    silently ignored key.
    """
    xdotool = _need("xdotool")
    code, output = _run([xdotool, "key", keysym])
    if code != 0:
        raise ActionError(f"xdotool failed: {(output.splitlines() or ['no output'])[0]}")
    return keysym


def media_play_pause() -> str:
    _media_key("XF86AudioPlay")
    return "sent play/pause"


def media_next() -> str:
    _media_key("XF86AudioNext")
    return "sent next track"


def media_prev() -> str:
    _media_key("XF86AudioPrev")
    return "sent previous track"


def focus_window(title: str = "") -> str:
    """Bring the window whose title contains `title` to the front."""
    window, name = _match_window(title)
    wmctrl = _which("wmctrl")
    if wmctrl:
        code, output = _run([wmctrl, "-i", "-a", window])
        if code == 0:
            return f"focused '{name}'"
        raise ActionError(f"wmctrl failed: {(output.splitlines() or ['no output'])[0]}")
    xdotool = _which("xdotool")
    if xdotool:
        code, output = _run([xdotool, "windowactivate", "--sync", window])
        if code == 0:
            return f"focused '{name}'"
        raise ActionError(f"xdotool failed: {(output.splitlines() or ['no output'])[0]}")
    raise ActionError("not installed: wmctrl or xdotool - install one with: astra install wmctrl")


def close_window(title: str = "") -> str:
    """Close the window whose title contains `title`. Confirmed by the user."""
    window, name = _match_window(title)
    wmctrl = _which("wmctrl")
    if wmctrl:
        code, output = _run([wmctrl, "-i", "-c", window])
        if code == 0:
            return f"closed '{name}'"
        raise ActionError(f"wmctrl failed: {(output.splitlines() or ['no output'])[0]}")
    xdotool = _which("xdotool")
    if xdotool:
        code, output = _run([xdotool, "windowkill", window])
        if code == 0:
            return f"closed '{name}'"
        raise ActionError(f"xdotool failed: {(output.splitlines() or ['no output'])[0]}")
    raise ActionError("not installed: wmctrl or xdotool - install one with: astra install wmctrl")


def list_windows() -> str:
    """Every open window, one per line, as `id title`."""
    windows = _windows()
    if not windows:
        return "no windows are open"
    return _clip("\n".join(f"{wid}  {name}" for wid, name in windows))


# ---------------------------------------------------------------------------
# Typing and keys
# ---------------------------------------------------------------------------


def type_text(text: str = "") -> str:
    """Type text into whatever window has focus.

    Note for whoever reads the log: this is the action with the sharpest edge
    in the whole catalog. Typing into a focused terminal is running a command.

    This function used to run without a confirmation, on the argument that a
    person who asked "type this for me" should not be asked "are you sure?" for
    every phrase. Astra Guard changed that decision: typing is classified
    `modify` - it can change or lose the user's work - and everything above
    `prepare` needs a yes that names the exact text. The person is asked once
    per request, not once per phrase, because the text is fixed when the plan is
    made. The length cap and the "no shell" rule stay as well: they limit what
    can be typed, not who approved it.
    """
    wanted = text or ""
    if not wanted.strip():
        raise ActionError("type_text needs some text")
    if len(wanted) > MAX_TYPED_CHARS:
        raise ActionError(
            f"type_text is limited to {MAX_TYPED_CHARS} characters, got {len(wanted)}"
        )
    xdotool = _need("xdotool")
    # --delay 12 keeps the keystrokes from outrunning the application on a
    # machine of this generation; --clearmodifiers stops a held modifier from
    # turning the text into shortcuts.
    code, output = _run([xdotool, "type", "--clearmodifiers", "--delay", "12", "--", wanted])
    if code != 0:
        raise ActionError(f"xdotool failed: {(output.splitlines() or ['no output'])[0]}")
    return f"typed {len(wanted)} characters"


def press_key(key: str = "") -> str:
    """Press one key or one modifier combination, from a fixed list."""
    wanted = (key or "").strip()
    if not wanted:
        raise ActionError("press_key needs a key name")
    parts = [part.strip().lower() for part in wanted.split("+")]
    unknown = [part for part in parts if part not in ALLOWED_KEYS]
    if unknown:
        raise ActionError(
            f"press_key does not know {', '.join(repr(u) for u in unknown)}; it sends "
            "letters, digits, F1-F12, arrows and the keys Return, Escape, Tab, space, "
            "BackSpace, Delete, Home, End, Page_Up, Page_Down, Print, Menu, optionally "
            "combined with ctrl, alt, shift or super"
        )
    xdotool = _need("xdotool")
    code, output = _run([xdotool, "key", "+".join(parts)])
    if code != 0:
        raise ActionError(f"xdotool failed: {(output.splitlines() or ['no output'])[0]}")
    return f"pressed {wanted}"


# ---------------------------------------------------------------------------
# Telling
# ---------------------------------------------------------------------------


def tell_time() -> str:
    """The current local time. No subprocess, no network, no timezone server."""
    now = datetime.datetime.now()
    return now.strftime("It is %H:%M on %A %d %B %Y.")


def tell_battery() -> str:
    """The battery charge, read from /sys/class/power_supply."""
    batteries = sorted(Path("/sys/class/power_supply").glob("BAT*"))
    if not batteries:
        return "no battery detected (this looks like a desktop machine)"

    lines = []
    for battery in batteries:
        try:
            capacity = (battery / "capacity").read_text(encoding="ascii").strip()
        except OSError:
            continue
        try:
            status = (battery / "status").read_text(encoding="ascii").strip()
        except OSError:
            status = "unknown"
        lines.append(f"{battery.name}: {capacity}% ({status.lower()})")
    if not lines:
        return "the battery is present but its charge cannot be read"
    return "battery: " + ", ".join(lines)


def _first_line(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def tell_system_info() -> str:
    """A short summary of the machine, read from /proc and /sys.

    Everything here is a file read. `uname -a`-style output would be one long
    line that a small model then has to repeat; four labelled lines are what
    fits on the screen and in a 1.5B model's attention.
    """
    lines = []

    pretty = ""
    release_text = _first_line(Path("/etc/astraos-release"))
    for raw in release_text.splitlines():
        if raw.startswith("PRETTY_NAME="):
            pretty = raw.split("=", 1)[1].strip().strip('"')
    if not pretty:
        for raw in _first_line(Path("/etc/os-release")).splitlines():
            if raw.startswith("PRETTY_NAME="):
                pretty = raw.split("=", 1)[1].strip().strip('"')
    if pretty:
        lines.append(f"OS: {pretty}")
    lines.append(f"Kernel: {platform.release()}")

    model = _first_line(Path("/sys/devices/virtual/dmi/id/product_name"))
    if model:
        lines.append(f"Machine: {model}")

    cpu = ""
    for raw in _first_line(Path("/proc/cpuinfo")).splitlines():
        if raw.startswith("model name"):
            cpu = raw.split(":", 1)[1].strip()
            break
    if cpu:
        cores = os.cpu_count() or 0
        lines.append(f"CPU: {cpu} ({cores} threads)")

    memory = ""
    for raw in _first_line(Path("/proc/meminfo")).splitlines():
        if raw.startswith("MemTotal:"):
            memory = raw.split(":", 1)[1].strip()
            break
    if memory:
        lines.append(f"Memory: {memory} total")

    try:
        usage = shutil.disk_usage("/")
        free_gb = usage.free / (1024 ** 3)
        total_gb = usage.total / (1024 ** 3)
        lines.append(f"Disk: {free_gb:.1f} GB free of {total_gb:.1f} GB on /")
    except OSError:
        pass

    return _clip("\n".join(lines))


# ---------------------------------------------------------------------------
# Web, wallpaper, theme
# ---------------------------------------------------------------------------


def search_web(query: str = "") -> str:
    """Open a web search for `query` in the user's browser.

    DuckDuckGo rather than a search API: no key, no account, and the request
    comes from the browser the user already uses, so the assistant itself
    never talks to the network.
    """
    wanted = (query or "").strip()
    if not wanted:
        raise ActionError("search_web needs something to search for")
    url = "https://duckduckgo.com/?q=" + urllib.parse.quote_plus(wanted)
    xdg_open = _need("xdg-open", "xdg-utils")
    _spawn([xdg_open, url])
    return f"searching the web for '{wanted}'"


def _resolve_wallpaper(path_or_name: str) -> Path:
    """Turn a name or a path into an existing image file."""
    wanted = (path_or_name or "").strip()
    if not wanted:
        raise ActionError("set_wallpaper needs a file name or a path")

    candidate = Path(wanted).expanduser()
    if candidate.is_file():
        return candidate

    suffixes = ("", ".png", ".jpg", ".jpeg", ".webp")
    searched = []
    for directory in WALLPAPER_DIRS:
        searched.append(str(directory))
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            if not entry.is_file():
                continue
            stem = entry.name
            for suffix in suffixes:
                if suffix and stem == wanted + suffix:
                    return entry
            if stem == wanted:
                return entry
    raise ActionError(
        f"no wallpaper named '{wanted}' in: " + ", ".join(searched)
    )


def set_wallpaper(path_or_name: str = "") -> str:
    """Set the desktop background.

    xfdesktop keeps the image in one xfconf property per monitor and per
    workspace, so every property that ends in /last-image is set rather than a
    guessed screen0/monitor0 path: a two-monitor machine has properties this
    code would otherwise never find, and on a fresh account xfdesktop may not
    have created any yet - which is reported as one line instead of a silent
    no-op.
    """
    image = _resolve_wallpaper(path_or_name)
    xfconf = _need("xfconf-query", "xfconf")

    code, listing = _run([xfconf, "-c", "xfce4-desktop", "-l"])
    if code != 0:
        raise ActionError("no Xfce desktop session to set a wallpaper in")
    properties = [line.strip() for line in listing.splitlines() if line.strip().endswith("/last-image")]
    if not properties:
        raise ActionError(
            "xfdesktop has no wallpaper property yet - open Desktop Settings once, then retry"
        )

    for prop in properties:
        code, output = _run([xfconf, "-c", "xfce4-desktop", "-p", prop, "-s", str(image)])
        if code != 0:
            first = (output.splitlines() or ["no output"])[0]
            raise ActionError(f"could not set {prop}: {first}")

    xfdesktop = _which("xfdesktop")
    if xfdesktop:
        _run([xfdesktop, "--reload"])
    return f"wallpaper set to {image.name}"


def set_theme(dark_or_light: str = "") -> str:
    """Switch between the two AstraOS themes, AstraOS-Dark and AstraOS-Light.

    The theme name is set in both xsettings (what GTK applications read) and
    xfwm4 (what the window decorations are drawn from). Setting only one of
    them produces the half-themed desktop this action exists to avoid: a dark
    titlebar on light applications.
    """
    wanted = (dark_or_light or "").strip().lower()
    if wanted in ("dark", "night", "black"):
        theme = "AstraOS-Dark"
    elif wanted in ("light", "day", "bright"):
        theme = "AstraOS-Light"
    else:
        raise ActionError("set_theme takes 'dark' or 'light'")

    if not (Path("/usr/share/themes") / theme).is_dir():
        raise ActionError(
            f"the theme {theme} is not installed (it ships with astraos-desktop)"
        )

    xfconf = _need("xfconf-query", "xfconf")
    settings = [
        ("xsettings", "/Net/ThemeName", theme),
        ("xfwm4", "/general/theme", theme),
    ]
    for channel, prop, value in settings:
        code, output = _run([xfconf, "-c", channel, "-p", prop, "-s", value])
        if code != 0:
            first = (output.splitlines() or ["no output"])[0]
            raise ActionError(f"could not set {channel}{prop}: {first}")
    return f"theme set to {theme}"


# ---------------------------------------------------------------------------
# The irreversible five
# ---------------------------------------------------------------------------


def suspend() -> str:
    """Suspend the machine. The user is asked first; see execute()."""
    return _power("suspend")


def reboot() -> str:
    """Restart the machine. The user is asked first; see execute()."""
    return _power("reboot")


def shutdown() -> str:
    """Power the machine off. The user is asked first; see execute()."""
    return _power("halt")


def run_command(command: str = "") -> str:
    """Run one program, with the three guards from the module docstring.

    The command is echoed before it is run and the echo is what the caller
    gets back, so "what did you do?" has an exact answer. Nothing here runs a
    shell: the line is split into arguments with shlex and executed directly,
    which is also why shell syntax is refused instead of being passed along.
    """
    raw = (command or "").strip()
    if not raw:
        raise ActionError("run_command needs a command")

    found = [syntax for syntax in SHELL_SYNTAX if syntax in raw]
    if found:
        raise ActionError(
            "refused: this assistant runs one command and no shell, so "
            f"{found[0]!r} would not do what it looks like - run it yourself if you meant it"
        )

    try:
        argv = shlex.split(raw)
    except ValueError as exc:
        raise ActionError(f"refused: cannot read that command line: {exc}") from exc
    if not argv:
        raise ActionError("run_command needs a command")

    lowered = [Path(word).name.lower() for word in argv]
    for tool in PRIVILEGE_TOOLS:
        if tool in lowered:
            raise ActionError(
                f"refused: '{raw}' asks for {tool}, and the assistant never runs "
                "anything as root"
            )
    if any(word in SHELLS for word in lowered):
        raise ActionError(
            f"refused: '{raw}' would start a shell, and this assistant runs one "
            "command and no shell - run it yourself if you meant it"
        )

    for word in argv:
        candidate = Path(word.strip("'\"")).expanduser()
        if not str(candidate).startswith("/"):
            continue
        normalised = os.path.normpath(str(candidate))
        for prefix in FORBIDDEN_PREFIXES:
            if normalised == prefix or normalised.startswith(prefix + "/"):
                raise ActionError(
                    f"refused: '{raw}' touches {prefix}, which the assistant does not "
                    "change (system files are managed by dpkg and by the user)"
                )

    code, output = _run(argv, timeout=60)
    report = [f"ran: {raw}"]
    if output:
        report.append(output)
    if code != 0:
        report.append(f"(exit code {code})")
        return _clip("\n".join(report))
    return _clip("\n".join(report))


# ---------------------------------------------------------------------------
# The catalog
# ---------------------------------------------------------------------------


@dataclass
class Action:
    """One thing the assistant may do.

    name          what the model writes in its JSON plan
    summary       one line, shown in the prompt and in `astra-ai actions`
    args          {argument: {"type", "description", "required", "default"}}
    dangerous     true when running it can lose work or power the machine down
    needs_confirm true for the actions that require a human's yes; execute()
                  refuses these unless it is told confirmed=True
    func          called as func(**args); returns a string, or raises ActionError
    """

    name: str
    summary: str
    args: dict
    dangerous: bool
    needs_confirm: bool
    func: Callable[..., str]


def _string(description: str, required: bool = True) -> dict:
    return {"type": "string", "description": description, "required": required}


def _integer(description: str, required: bool = True, default: int = 50) -> dict:
    return {
        "type": "integer",
        "description": description,
        "required": required,
        "default": default,
    }


# Keys are the action names, in the order the prompt should show them: grouped
# by what they are for, so a small model reads the catalog the way a person
# reads a menu. Do not reorder for cosmetics; the model's behaviour is tuned
# against this list.
ACTIONS: dict[str, Action] = {
    # Applications and files
    "open_app": Action(
        "open_app", "open an application from the menu",
        {"name": _string("the application's name, e.g. firefox")},
        False, False, open_app,
    ),
    "open_url": Action(
        "open_url", "open an http or https page in the browser",
        {"url": _string("the address, e.g. https://example.com")},
        False, False, open_url,
    ),
    "open_path": Action(
        "open_path", "open a file or folder in its usual application",
        {"path": _string("a path, e.g. ~/Documents or /home/you/report.pdf")},
        False, False, open_path,
    ),
    # Sound
    "volume_up": Action(
        "volume_up", "raise the volume by 5%", {}, False, False, volume_up,
    ),
    "volume_down": Action(
        "volume_down", "lower the volume by 5%", {}, False, False, volume_down,
    ),
    "set_volume": Action(
        "set_volume", "set the volume to an exact percentage",
        {"percent": _integer("0-100", default=50)},
        False, False, set_volume,
    ),
    "mute_toggle": Action(
        "mute_toggle", "mute or unmute the sound", {}, False, False, mute_toggle,
    ),
    # Screen
    "set_brightness": Action(
        "set_brightness", "set the screen backlight to an exact percentage",
        {"percent": _integer("0-100", default=50)},
        False, False, set_brightness,
    ),
    "lock_screen": Action(
        "lock_screen", "lock the session", {}, False, False, lock_screen,
    ),
    "screenshot": Action(
        "screenshot", "take a full-screen screenshot",
        {}, False, False, screenshot,
    ),
    # Radios
    "wifi_on": Action("wifi_on", "turn the Wi-Fi radio on", {}, False, False, wifi_on),
    "wifi_off": Action("wifi_off", "turn the Wi-Fi radio off", {}, False, False, wifi_off),
    "bluetooth_on": Action(
        "bluetooth_on", "turn the Bluetooth radio on", {}, False, False, bluetooth_on,
    ),
    "bluetooth_off": Action(
        "bluetooth_off", "turn the Bluetooth radio off", {}, False, False, bluetooth_off,
    ),
    # Media and windows
    "media_play_pause": Action(
        "media_play_pause", "press the play/pause media key", {}, False, False, media_play_pause,
    ),
    "media_next": Action(
        "media_next", "press the next-track media key", {}, False, False, media_next,
    ),
    "media_prev": Action(
        "media_prev", "press the previous-track media key", {}, False, False, media_prev,
    ),
    "focus_window": Action(
        "focus_window", "bring a window to the front by part of its title",
        {"title": _string("part of the window title")},
        False, False, focus_window,
    ),
    "close_window": Action(
        "close_window",
        "close a window by part of its title (the window may have unsaved work in it)",
        {"title": _string("part of the window title")},
        True, True, close_window,
    ),
    "list_windows": Action(
        "list_windows", "list the open windows", {}, False, False, list_windows,
    ),
    # Typing
    "type_text": Action(
        "type_text", "type text into the focused window",
        {"text": _string("the text to type")},
        True, True, type_text,
    ),
    "press_key": Action(
        "press_key", "press one key, e.g. Return or ctrl+c",
        {"key": _string("a key name from the fixed list in the catalog")},
        True, True, press_key,
    ),
    # Telling
    "tell_time": Action(
        "tell_time", "say the current time and date", {}, False, False, tell_time,
    ),
    "tell_battery": Action(
        "tell_battery", "say the battery charge", {}, False, False, tell_battery,
    ),
    "tell_system_info": Action(
        "tell_system_info", "say what machine this is", {}, False, False, tell_system_info,
    ),
    # The web, the wallpaper, the theme
    "search_web": Action(
        "search_web", "search the web in the browser",
        {"query": _string("what to search for")},
        False, False, search_web,
    ),
    "set_wallpaper": Action(
        "set_wallpaper", "set the desktop background",
        {"path_or_name": _string("a file name from the wallpaper folder, or a full path")},
        False, False, set_wallpaper,
    ),
    "set_theme": Action(
        "set_theme", "switch between the dark and the light theme",
        {"dark_or_light": _string("either 'dark' or 'light'")},
        False, False, set_theme,
    ),
    # Irreversible
    "suspend": Action(
        "suspend", "suspend the machine", {}, True, True, suspend,
    ),
    "reboot": Action(
        "reboot", "restart the machine", {}, True, True, reboot,
    ),
    "shutdown": Action(
        "shutdown", "power the machine off", {}, True, True, shutdown,
    ),
    "run_command": Action(
        "run_command", "run one command line, echoed first (see the guard list)",
        {"command": _string("one command with no shell syntax")},
        True, True, run_command,
    ),
}


def catalog_for_prompt() -> str:
    """The catalog as the prompt shows it: `name(args) - summary`."""
    lines = []
    for action in ACTIONS.values():
        arguments = ", ".join(action.args.keys())
        suffix = " [asks the user first]" if action.needs_confirm else ""
        lines.append(f"{action.name}({arguments}) - {action.summary}{suffix}")
    return "\n".join(lines)


def list_actions() -> list[dict]:
    """The catalog as data, for `astra-ai actions --json` and the web interface."""
    return [
        {
            "name": action.name,
            "summary": action.summary,
            "args": action.args,
            "dangerous": action.dangerous,
            "needs_confirm": action.needs_confirm,
        }
        for action in ACTIONS.values()
    ]


# ---------------------------------------------------------------------------
# Reading a plan out of the model's reply
# ---------------------------------------------------------------------------


def _json_objects(text: str) -> list[str]:
    """Every balanced {...} in the text, braces inside strings excluded.

    A scan rather than a single json.loads: the model is asked for bare JSON
    and mostly obeys, but a small model wraps it in a fence, prefixes it with
    "Sure, here is the plan:", or trails off. Recovering the object from that
    is the difference between a working assistant and one that answers "I
    could not understand that" to a perfectly good plan.
    """
    objects = []
    start = None
    depth = 0
    in_string = False
    escaped = False

    for index, char in enumerate(text):
        if start is None:
            if char == "{":
                start = index
                depth = 1
                in_string = False
                escaped = False
            continue

        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                objects.append(text[start:index + 1])
                start = None
    return objects


def _coerce(value: Any, wanted: str) -> Any:
    """Best-effort type conversion for a model's JSON arguments.

    Models emit "50" where the schema says integer and true/"yes" where it
    says boolean. Converting here, in one place, keeps every action function
    from having to accept both. Anything that cannot be converted is passed
    through unchanged, and the action rejects it with its own message.
    """
    if wanted == "integer":
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                return value
        return value
    if wanted == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("true", "yes", "on", "1")
        return value
    if wanted == "string":
        if isinstance(value, str):
            return value
        if isinstance(value, (int, float, bool)):
            return str(value)
        return value
    return value


def parse_plan(text: str) -> dict | None:
    """The plan in the model's reply, or None when there is no usable plan.

    Two shapes are accepted, and nothing else:

        {"action": "set_volume", "args": {"percent": 30}}
        {"answer": "I cannot change the keyboard layout; that is not in the
                    list of things I can do."}

    An object naming an action that is not in ACTIONS is rejected - returning
    None, not a plan with a guessed name - because that is the point of having
    a catalog at all. An object with neither key is not a plan either.

    The returned dictionary carries the action's own summary and danger flags
    so that the caller can show the user what is about to happen without
    looking the action up a second time.
    """
    if not isinstance(text, str) or not text.strip():
        return None

    for candidate in _json_objects(text):
        try:
            obj = json.loads(candidate)
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue

        if "answer" in obj:
            answer = obj.get("answer")
            if isinstance(answer, str) and answer.strip():
                return {"answer": answer.strip()}
            return None

        name = obj.get("action")
        if not isinstance(name, str):
            continue
        name = name.strip()
        if name not in ACTIONS:
            # A named action outside the catalog is a refusal, not a typo to
            # repair: repairing it would let the model reach anything by
            # misspelling it.
            return None

        action = ACTIONS[name]
        raw_args = obj.get("args")
        args: dict = {}
        if isinstance(raw_args, dict):
            for key, value in raw_args.items():
                if key in action.args:
                    args[key] = _coerce(value, action.args[key].get("type", "string"))

        for key, schema in action.args.items():
            if key not in args and schema.get("default") is not None:
                args[key] = schema["default"]

        return {
            "action": name,
            "args": args,
            "summary": action.summary,
            "dangerous": action.dangerous,
            "needs_confirm": action.needs_confirm,
        }
    return None


# ---------------------------------------------------------------------------
# Running a plan
# ---------------------------------------------------------------------------


def _missing_argument(name: str, key: str) -> str:
    return f"the plan for '{name}' is missing the argument '{key}'"


def execute(
    plan: dict,
    confirmed: bool = False,
    provenance: str = _guard.TRUSTED_PROVENANCE,
) -> dict:
    """Run one plan. Never raises; the result says what happened.

    The result always has the same keys:

        ok            the action ran and reported success
        action        the action's name, or "" when the plan was unusable
        output        the human-readable result, or the refusal
        refused       true when execute() declined to run the action
        needs_confirm true when the action is one that needs the user's yes
        error         the one-line failure, or None

    confirmed=True is the user's yes. It is the caller's job to obtain it -
    and the caller is the CLI or the web interface, which has a human in
    front of it - never the model, which only ever produces the plan.

    provenance is where the request came from. "user" is the person at the
    keyboard; anything else - a retrieved document, a web page, a tool's output
    - may only reach observe, so a document that orders the assistant to act is
    refused rather than followed. Every action passes Astra Guard before it
    runs, and every decision is appended to the audit chain.
    """
    result = {
        "ok": False,
        "action": "",
        "output": "",
        "refused": False,
        "needs_confirm": False,
        "error": None,
    }

    if not isinstance(plan, dict):
        result["error"] = "no plan to run"
        result["output"] = result["error"]
        return result

    name = plan.get("action")
    if not isinstance(name, str) or not name.strip():
        if isinstance(plan.get("answer"), str):
            result["error"] = "that plan is an answer, not an action"
        else:
            result["error"] = "the plan names no action"
        result["output"] = result["error"]
        return result
    name = name.strip()

    action = ACTIONS.get(name)
    if action is None:
        result["action"] = name
        result["refused"] = True
        result["error"] = f"refused to run '{name}': it is not in the action catalog"
        result["output"] = result["error"]
        return result

    result["action"] = name
    result["needs_confirm"] = action.needs_confirm

    if action.needs_confirm and not confirmed:
        result["refused"] = True
        result["error"] = (
            f"refused to run '{name}': it is one of the actions that can lose work "
            f"or power the machine off, and the user has not confirmed it"
        )
        result["output"] = result["error"]
        return result

    raw_args = plan.get("args")
    args: dict = {}
    if isinstance(raw_args, dict):
        for key, value in raw_args.items():
            if key in action.args:
                args[key] = _coerce(value, action.args[key].get("type", "string"))

    for key, schema in action.args.items():
        if key not in args and schema.get("default") is not None:
            args[key] = schema["default"]
        if key not in args and schema.get("required", True):
            result["error"] = _missing_argument(name, key)
            result["output"] = result["error"]
            return result

    # Astra Guard decides, after the arguments are resolved so that the target
    # and the effect are the actual ones. This is the enforcement, not a prompt:
    # a refusal here is the action not running.
    try:
        decision = _guard.evaluate(
            name,
            args,
            summary=action.summary,
            provenance=provenance,
            approved=confirmed,
        )
    except _guard.GuardError as exc:
        result["refused"] = True
        result["error"] = str(exc)
        result["output"] = result["error"]
        return result

    result["level"] = decision["level"]

    if not decision["allowed"]:
        _audit(decision, "refused", decision["reason"])
        result["refused"] = True
        result["error"] = decision["reason"]
        result["output"] = result["error"]
        return result

    if decision["level"] in _guard.APPROVAL_LEVELS:
        try:
            _guard.record(decision, outcome="approved")
        except _guard.GuardError as exc:
            result["refused"] = True
            result["error"] = (
                f"refused to run '{name}': {exc}. An action that can change your "
                "work or this machine must leave a record before it runs"
            )
            result["output"] = result["error"]
            return result
    else:
        _audit(decision, "allowed")

    try:
        output = action.func(**args)
    except ActionError as exc:
        result["error"] = str(exc)
        result["output"] = str(exc)
        _audit(decision, "error", str(exc))
        return result
    except Exception as exc:  # noqa: BLE001 - a crash must read as a failure
        result["error"] = f"{name} failed: {exc.__class__.__name__}: {exc}"
        result["output"] = result["error"]
        _audit(decision, "error", result["error"])
        return result

    result["ok"] = True
    result["output"] = _clip(str(output))
    if not _audit(decision, "ok", result["output"]):
        result["output"] = (
            f"{result['output']} (Astra Guard could not append this to the audit log)"
        ).strip()
    return result
