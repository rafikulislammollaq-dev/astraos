"""AstraOS HUD — full-screen session dashboard.

Package layout note
-------------------
The application is installed as a plain importable package under
``/usr/lib/astraos-hud`` and launched by a one-line shim in ``/usr/bin``:

    #!/usr/bin/env python3
    import sys; sys.path.insert(0, '/usr/lib/astraos-hud')
    from astraos_hud import main; main.main()

Nothing here imports GTK at module scope. ``import astraos_hud.systemdata`` must
keep working on a build host with no PyGObject installed at all — the data layer
is exercised by the static tests and by the packaging build, and a package that
can only be imported on a machine with GTK is a package that cannot be checked.

Modules
-------
``systemdata``  every /proc, /sys and socket reading. Standard library only.
``widgets``     the custom Cairo drawing widgets (meters, graph, globe, table).
``layout``      the six-region grid, panel chrome and the single sampling tick.
``main``        argument parsing, single-instance guard, Gtk.main().
"""

from __future__ import annotations

from typing import Any

__all__ = ["__version__", "APP_NAME", "main"]

#: Kept in step with the repository VERSION file (0.1.0 for the Nova alpha).
__version__ = "0.1.0"

APP_NAME = "AstraOS HUD"


def main(argv: Any = None) -> int:
    """Run the HUD. Imported lazily so the package stays GTK-free on import."""
    from . import main as _main

    return _main.main(argv)
