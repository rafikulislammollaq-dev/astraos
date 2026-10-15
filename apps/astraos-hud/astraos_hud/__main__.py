"""``python3 -m astraos_hud`` — the development entry point.

This module exists so the application can be run straight out of the source tree,
with no install step and no generated console script:

    cd apps/astraos-hud && python3 -m astraos_hud --windowed

On a real install the shim in /usr/bin does the same thing by putting
/usr/lib/astraos-hud on sys.path and calling :func:`astraos_hud.main.main`.
"""

from __future__ import annotations

from . import main

if __name__ == "__main__":
    raise SystemExit(main.main())
