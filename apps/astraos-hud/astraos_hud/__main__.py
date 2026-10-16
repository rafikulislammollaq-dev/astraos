"""``python3 -m astraos_hud`` — the development entry point.

This module exists so the application can be run straight out of the source tree,
with no install step and no generated console script:

    cd apps/astraos-hud && python3 -m astraos_hud --windowed

On a real install the shim in /usr/bin runs exactly this module
(``python3 -m astraos_hud``), so there is one entry point rather than two.

The import is ``from .main import main``, not ``from . import main``. The package
``__init__`` binds a *function* named ``main`` as its public entry point, and a
function bound on the package shadows the ``main`` submodule for ``from . import
main`` - which therefore returned the function, so ``main.main()`` raised
AttributeError and the HUD could not start at all. Naming the submodule reaches
the module unambiguously.
"""

from __future__ import annotations

from .main import main

if __name__ == "__main__":
    raise SystemExit(main())
