"""The astraos-hud package installs the application where its launcher looks.

WHY THIS FILE EXISTS

The HUD is a runnable application whose source lives in `apps/astraos-hud`, not in
the package's own `root/` tree, so the packaging step copies it into the image. Three
things have to agree and none of them is checked by anything else:

  * the directory the packaging script copies the source into,
  * the directory the `/usr/bin/astraos-hud` shim puts on `PYTHONPATH`,
  * the command the desktop launcher runs.

If the shim's `ASTRAOS_HUD_LIB` and the packaging destination drift apart, the only
symptom is an `ImportError` when a user clicks the launcher on a built image - a
failure that the static suite would otherwise report as a pass, because the file is
present and the script is syntactically valid. If the launcher names a command that
no package installs, the menu item does nothing. This module pins all three to each
other, the way `test_desktop_skel.py` pins the panel layout to the file xfce4-panel
reads.
"""

from __future__ import annotations

import importlib
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DESCRIPTION = "the astraos-hud package installs the application where its launcher looks"

PACKAGE = REPO_ROOT / "packages" / "astraos-hud"
SHIM = PACKAGE / "root" / "usr" / "bin" / "astraos-hud"
CONTROL = PACKAGE / "control.in"
SOURCE = REPO_ROOT / "apps" / "astraos-hud" / "astraos_hud"
PACKAGING = REPO_ROOT / "scripts" / "build-packages.sh"
LAUNCHER = REPO_ROOT / "desktop" / "launchers" / "astraos-hud.desktop"

#: Where the application is installed and imported from. Both the shim and the packaging
#: script have to name this exact directory.
INSTALL_DIR = "/usr/lib/astraos-hud"


def _without_comments(path: Path) -> str:
    return "\n".join(
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )


def test_the_hud_package_has_a_control_file_a_shim_and_a_source_tree() -> None:
    """The pieces that only exist together: a package, a command and something to run."""
    assert PACKAGE.is_dir(), f"{PACKAGE.relative_to(REPO_ROOT)} does not exist"
    assert CONTROL.is_file(), f"{CONTROL.relative_to(REPO_ROOT)} is missing"
    assert SHIM.is_file(), (
        f"{SHIM.relative_to(REPO_ROOT)} is missing. The desktop launcher runs 'astraos-hud', "
        "so the command has to ship in a package."
    )
    assert SOURCE.is_dir(), (
        f"{SOURCE.relative_to(REPO_ROOT)} does not exist, so there is nothing to package"
    )
    assert (SOURCE / "__init__.py").is_file(), (
        "the application source has no package __init__.py, so it cannot be imported as "
        "'astraos_hud'"
    )


def test_the_shim_loads_the_application_from_where_it_is_installed() -> None:
    """The shim's library path must equal the install directory, character for character."""
    text = SHIM.read_text(encoding="utf-8")
    match = re.search(r'^ASTRAOS_HUD_LIB="([^"]+)"\s*$', text, re.M)
    assert match, (
        "the shim does not set ASTRAOS_HUD_LIB to a directory, so the reason it exists is "
        "gone"
    )
    assert match.group(1) == INSTALL_DIR, (
        f"the shim loads the application from {match.group(1)!r}, but it is installed under "
        f"{INSTALL_DIR!r}. The launcher would fail with ImportError on a built image."
    )
    assert re.search(r"^exec\s+python3\s+-m\s+astraos_hud\b", text, re.M), (
        "the shim does not run `python3 -m astraos_hud`, so it would not start the "
        "application through the single entry point the source tree also uses"
    )


def test_the_packaging_script_agrees_with_the_shim() -> None:
    """The copy destination in build-packages.sh is the shim's library path."""
    code = _without_comments(PACKAGING)

    assert INSTALL_DIR in code, (
        f"scripts/build-packages.sh never mentions {INSTALL_DIR}, so the application would "
        "be built and then never reach the path the launcher imports it from"
    )

    source_reference = "apps/astraos-hud/astraos_hud"
    assert source_reference in code, (
        f"scripts/build-packages.sh does not copy {source_reference} into the package; the "
        ".deb would contain a shim with nothing behind it"
    )

    # The copy must go *into* the install directory, not merely name it.
    assert re.search(
        r"cp\s+-a\s+\"\$\{REPO_ROOT\}/apps/astraos-hud/astraos_hud\"\s+\"\$\{HUD_STAGE\}"
        + re.escape(INSTALL_DIR)
        + r"/\"",
        code,
    ), (
        f"scripts/build-packages.sh does not copy the application source into "
        f"{INSTALL_DIR}/ in the staged package; check the cp that assembles astraos-hud"
    )


def test_the_package_is_built_and_staged() -> None:
    """A package tree that is never assembled is dead weight."""
    code = _without_comments(PACKAGING)
    assert "stage_package astraos-hud" in code, (
        "scripts/build-packages.sh never stages astraos-hud"
    )
    assert 'finish_package astraos-hud' in code, (
        "scripts/build-packages.sh stages astraos-hud but never builds the .deb, so it would "
        "not reach config/packages.chroot and the image would ship without it"
    )


def test_the_control_file_requires_the_bindings_the_application_imports() -> None:
    """The application imports GTK, Pango and PangoCairo; the package must require them.

    `python3-gi` and `gir1.2-gtk-3.0` provide the GTK and Pango typelibs, and
    `python3-gi-cairo` provides PangoCairo, which widgets.py imports to draw tabular
    text. A missing one is a HUD that cannot draw, and apt cannot infer the requirement
    because the imports are dynamic.
    """
    control = CONTROL.read_text(encoding="utf-8")
    for dependency in ("python3-gi", "python3-gi-cairo", "gir1.2-gtk-3.0"):
        assert dependency in control, (
            f"astraos-hud does not declare a dependency on {dependency}, so a minimal image "
            "could install a HUD that fails to draw"
        )


def test_the_hud_is_launchable_and_runs_the_shipped_command() -> None:
    """The launcher exists, runs 'astraos-hud', and that command ships in a package."""
    assert LAUNCHER.is_file(), f"{LAUNCHER.relative_to(REPO_ROOT)} is missing"
    text = LAUNCHER.read_text(encoding="utf-8")
    assert re.search(r"^Exec=astraos-hud\s*$", text, re.M), (
        "the launcher's Exec line does not run 'astraos-hud' by itself"
    )
    assert re.search(r"^Icon=\S+", text, re.M), "the launcher names no icon"

    shipped = {
        path.name
        for path in (REPO_ROOT / "packages").rglob("usr/bin/astraos-*")
        if path.is_file()
    }
    assert "astraos-hud" in shipped, (
        "no package installs /usr/bin/astraos-hud, so the launcher would do nothing"
    )


def test_the_module_entry_point_starts_the_application() -> None:
    """`python3 -m astraos_hud` must actually reach the implementation's main().

    This is a regression test for a real defect that shipping the package exposed. The
    package binds a *function* named ``main`` in its ``__init__`` and keeps the
    implementation in a ``main`` submodule; a function bound on the package shadows the
    submodule, so ``from . import main`` returned the function and ``main.main()`` raised
    ``AttributeError`` before the HUD could start. Every file was present and every other
    check passed - only running the entry point the launcher uses catches it.
    """
    source_path = REPO_ROOT / "apps" / "astraos-hud"
    result = subprocess.run(
        [sys.executable, "-m", "astraos_hud", "--version"],
        cwd=source_path, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (
        "`python3 -m astraos_hud --version` failed, so the /usr/bin/astraos-hud shim, "
        "which runs exactly this, would not start the HUD:\n"
        + (result.stderr or result.stdout)
    )
    assert "astraos-hud" in result.stdout, (
        "the HUD's entry point did not print its version line; stdout was "
        f"{result.stdout!r}"
    )


def test_the_application_still_imports_without_gtk() -> None:
    """The package must be importable on a host with no PyGObject, which is how it is tested.

    This is the property that lets the data layer and the packaging build be checked
    without a display: `astraos_hud.__init__` may not import GTK at module scope. If a
    future edit moves `import gi` to the top of the package, every static check that
    touches it stops working on the build host.
    """
    source_path = str(REPO_ROOT / "apps" / "astraos-hud")
    sys.path.insert(0, source_path)
    try:
        module = importlib.import_module("astraos_hud")
    finally:
        sys.path.remove(source_path)

    assert getattr(module, "__version__", None), (
        "astraos_hud imports but declares no __version__; the release identity check in "
        "test_config.py reads it"
    )
