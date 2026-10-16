"""Entry point for astraos-hud.

Installed as an importable package under ``/usr/lib/astraos-hud`` and started by
a POSIX shell shim in ``/usr/bin`` that puts that directory on PYTHONPATH and
runs ``python3 -m astraos_hud`` - the same entry point the source tree is run
with during development, so there is exactly one code path:

    ASTRAOS_HUD_LIB="/usr/lib/astraos-hud"
    PYTHONPATH="${ASTRAOS_HUD_LIB}${PYTHONPATH:+:${PYTHONPATH}}"
    exec python3 -m astraos_hud "$@"

This module therefore owns exactly three things: the command line, the
single-instance guard, and the Gtk.main() call. Everything else lives in
``layout`` (the window) and ``systemdata`` (the sampling), so that a failure in
either can be reported here in one sentence instead of as a traceback in a
full-screen window the user cannot close.

The single-instance guard
-------------------------
A second HUD would be a second full-screen overlay fighting the first for the
pointer, each running its own sampler and its own shell. So the process takes an
advisory lock on a file in /tmp (world-writable and always present — the
XDG_RUNTIME_DIR is not guaranteed to exist in every session, and nothing outside
/tmp is written) and exits immediately if it is already held. The lock is
released by the kernel when the process dies, so a HUD killed by a session
restart cannot leave a stale lock behind.
"""

from __future__ import annotations

import argparse
import errno
import os
import signal
import sys
from typing import List, Optional, Tuple

# gi is imported here rather than at package scope so that `import astraos_hud`
# (and therefore `import astraos_hud.systemdata`) keeps working on a host with no
# PyGObject at all — the build host, and the static tests.
try:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gdk, GLib, Gtk  # noqa: E402

    _IMPORT_ERROR: Optional[BaseException] = None
except (ImportError, ValueError) as error:  # pragma: no cover - depends on the host
    gi = None  # type: ignore[assignment]
    Gdk = GLib = Gtk = None  # type: ignore[assignment]
    _IMPORT_ERROR = error

from . import __version__  # noqa: E402
from . import systemdata as sd  # noqa: E402

LOCK_PATH_TEMPLATE = "/tmp/astraos-hud-{uid}.lock"

DESCRIPTION = "AstraOS full-screen HUD dashboard"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="astraos-hud",
        description=DESCRIPTION,
        epilog="Keys: Escape hides the HUD, F11 toggles fullscreen, Ctrl+Q quits.",
    )
    parser.add_argument("--version", action="version",
                        version=f"astraos-hud {__version__}")
    parser.add_argument("--fullscreen", action="store_true", default=True,
                        help="cover the screen (default)")
    parser.add_argument("--windowed", dest="fullscreen", action="store_false",
                        help="open as an ordinary window instead")
    parser.add_argument("--overlay", action="store_true",
                        help="ask xfwm4 for a DOCK window: no decorations, no alt-tab entry")
    parser.add_argument("--escape-quits", action="store_true",
                        help="close the HUD on Escape instead of hiding it")
    parser.add_argument("--interval", type=int, default=sd.HUD_SAMPLE_INTERVAL_MS,
                        metavar="MS",
                        help=f"sampling interval in milliseconds (default {sd.HUD_SAMPLE_INTERVAL_MS})")
    parser.add_argument("--no-network", action="store_true",
                        help="never open a socket: the PING column shows N/A")
    parser.add_argument("--endpoints", default=sd.ENDPOINTS_FILE, metavar="PATH",
                        help="endpoint map for the world view (default %(default)s)")
    parser.add_argument("--debug", action="store_true",
                        help="report sampling time and overruns on stderr")
    return parser


def acquire_lock() -> Tuple[Optional[object], bool]:
    """Take the single-instance lock.

    Returns ``(handle, acquired)``. ``handle`` is None when no lock file could be
    opened at all — in which case the HUD still starts, because refusing to run
    because /tmp is odd would be a worse failure than two overlays. ``acquired``
    is False only when another process genuinely holds the lock.

    fcntl is POSIX-only, which is fine: this application only ever runs on a
    Debian desktop. Where it is missing the guard is skipped rather than fatal.
    """
    try:
        import fcntl
    except ImportError:  # pragma: no cover - not a Debian target
        return None, True
    path = LOCK_PATH_TEMPLATE.format(uid=os.getuid())
    try:
        handle = open(path, "a+", encoding="utf-8")
    except OSError:
        return None, True
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        handle.close()
        if error.errno in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK):
            return None, False  # another HUD is running
        return None, True
    try:
        handle.seek(0)
        handle.truncate()
        handle.write(f"{os.getpid()}\n")
        handle.flush()
    except OSError:
        pass
    return handle, True


def main(argv: Optional[List[str]] = None) -> int:
    """Run the HUD. Returns a process exit status; never raises."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if _IMPORT_ERROR is not None:
        print(f"astraos-hud: PyGObject/GTK 3 bindings are unavailable: {_IMPORT_ERROR}",
              file=sys.stderr)
        print("astraos-hud: install python3-gi, python3-gi-cairo and gir1.2-gtk-3.0.",
              file=sys.stderr)
        return 1

    if not Gdk.Display.get_default():  # type: ignore[union-attr]
        print("astraos-hud: no X display is available (is DISPLAY set?).", file=sys.stderr)
        return 1

    lock, acquired = acquire_lock()
    if not acquired:
        print("astraos-hud: another HUD instance is already running; not starting a second.",
              file=sys.stderr)
        return 0

    from . import layout  # imported late: layout needs Gtk, and so does this guard

    layout.install_css()

    collector = sd.Collector(network_enabled=not args.no_network, endpoints_path=args.endpoints)
    window = layout.HudWindow(
        collector=collector,
        fullscreen=args.fullscreen,
        interval_ms=args.interval,
        escape_quits=args.escape_quits,
        overlay=args.overlay,
    )

    # SIGINT/SIGTERM have to be handled through GLib: a Python-level handler
    # installed while Gtk.main() owns the loop would never run, so the HUD would
    # ignore Ctrl+C from a console and would have to be killed.
    def _on_signal() -> bool:
        window.destroy()
        return True

    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, _on_signal)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, _on_signal)

    if args.debug:
        GLib.timeout_add(5000, _report_timing, window)

    window.show_hud()
    window.start_ticking()

    try:
        Gtk.main()  # type: ignore[union-attr]
    finally:
        collector.close()
        if lock is not None:
            lock.close()
    return 0


def _report_timing(window) -> bool:
    """--debug: sampling should be a fraction of the tick budget, and it is worth
    being able to prove that on the machine it actually runs on."""
    print(
        f"astraos-hud: tick {window._last_tick_seconds * 1000:.1f} ms, "
        f"{window._tick_overruns} overrun(s) so far",
        file=sys.stderr,
    )
    return True


if __name__ == "__main__":  # pragma: no cover - development entry point
    raise SystemExit(main())
