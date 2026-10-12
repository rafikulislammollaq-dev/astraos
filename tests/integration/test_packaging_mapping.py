"""Integration test: the build scripts reference files that exist.

WHY THIS TEST MATTERS
---------------------
`scripts/build-packages.sh` maps repository trees onto installed paths with a series of
`cp` commands written by hand. A rename on either side — say
`astraos-wallpaper-dark-1920x1080.png` becoming `astraos-wallpaper-1080p.png` — silently
breaks packaging. The failure then appears an hour into a build, after several gigabytes
of downloads, or not at all if the copy happens to be guarded.

This test parses the real scripts and asserts every path they reference is on disk, so a
rename fails in seconds on any machine instead of late on a Linux one.

It also verifies the environment can name the specific settings the scripts depend on
rather than hardcoding them, which is the other common way this kind of mapping drifts.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "lib"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

import astraos_env  # noqa: E402
from astraos_testlib import SkipTest  # noqa: E402

DESCRIPTION = "build scripts reference paths that exist"

# Build scripts that stage or copy repository content.
STAGING_SCRIPTS = [
    "scripts/build-packages.sh",
    "scripts/configure-live-build.sh",
]

# `${REPO_ROOT}/foo/bar` or "${REPO_ROOT}/foo/bar" inside a script.
REPO_PATH = re.compile(r'\$\{?REPO_ROOT\}?/([A-Za-z0-9_./@*-]+)')


def _referenced_paths(script: str) -> set[str]:
    """Every repository-relative path a script mentions via ${REPO_ROOT}."""
    found: set[str] = set()
    for line in astraos_env.REPO_ROOT.joinpath(script).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        # Skip comments: they legitimately mention paths that need not exist.
        if stripped.startswith("#"):
            continue
        for match in REPO_PATH.finditer(line):
            candidate = match.group(1)
            candidate = candidate.rstrip('",')
            found.add(candidate)
    return found


def test_build_scripts_reference_existing_paths() -> None:
    """Every ${REPO_ROOT}/... path in the staging scripts must exist.

    Globs are handled by checking the glob itself has at least one match, because a glob
    that matches nothing is the silent-failure case this test exists to catch.
    """
    missing: list[str] = []

    for script in STAGING_SCRIPTS:
        for relative in sorted(_referenced_paths(script)):
            target = REPO_ROOT / relative

            if "*" in relative or "?" in relative or "[" in relative:
                if not list(REPO_ROOT.glob(relative)):
                    missing.append(f"{script}: glob matches nothing: {relative}")
                continue

            # A path may be referenced as a directory prefix of something created later,
            # so accept it if it exists directly or as a directory some file lives under.
            if target.exists():
                continue
            if target.parent.exists():
                # The parent exists but the leaf does not: this is the rename case.
                missing.append(f"{script}: does not exist: {relative}")
            else:
                missing.append(f"{script}: parent directory missing: {relative}")

    assert not missing, (
        "the build scripts reference paths that are not in the repository. A file was "
        "renamed or removed without updating the packaging mapping:\n  "
        + "\n  ".join(sorted(missing))
    )


def test_branding_assets_are_all_mapped_into_a_package() -> None:
    """Every source file under branding/ must be installed by some package.

    An asset that is generated but never packaged is dead weight that misleads: the
    project believes it ships a file it does not.
    """
    packaging = astraos_env.REPO_ROOT.joinpath("scripts/build-packages.sh").read_text(encoding="utf-8")

    # Source trees that packaging copies wholesale, with the target they go to.
    wholesale = {
        "branding/logos": "the ring marks",
        "branding/icons": "the icon theme",
        "branding/plymouth/astraos": "the Plymouth theme",
        "branding/grub/astraos": "the GRUB theme",
        "branding/lightdm": "the LightDM assets",
    }

    unmapped: list[str] = []
    for relative, description in wholesale.items():
        source = REPO_ROOT / relative
        assert source.is_dir(), f"{relative} ({description}) does not exist"

        if relative not in packaging:
            unmapped.append(f"{relative} ({description}) is never copied by build-packages.sh")

    assert not unmapped, (
        "these branding trees exist but no package installs them:\n  "
        + "\n  ".join(unmapped)
    )


def test_generated_assets_are_mapped_by_exact_name() -> None:
    """The generated bitmaps referenced individually must exist and be listed."""
    packaging = astraos_env.REPO_ROOT.joinpath("scripts/build-packages.sh").read_text(encoding="utf-8")

    branding = astraos_env.branding()
    width = branding["BRAND_WALLPAPER_WIDTH"]
    height = branding["BRAND_WALLPAPER_HEIGHT"]

    generated = REPO_ROOT / "branding" / "generated"
    if not generated.is_dir() or not list(generated.glob("*.png")):
        raise SkipTest("generated branding assets are absent; run branding/tools/render_assets.py")

    required = [
        f"astraos-splash-boot-{width}x{height}.png",
        f"astraos-login-background-{width}x{height}.png",
        "astraos-logo-512.png",
    ]

    for name in required:
        assert (generated / name).is_file(), (
            f"{name} is referenced by the packaging step but has not been generated"
        )
        assert name in packaging, (
            f"{name} exists in branding/generated but scripts/build-packages.sh never "
            "installs it, so it would not be in the image"
        )


def test_package_source_directories_are_complete() -> None:
    """Every package directory must have a control template and be built by the script."""
    packaging = astraos_env.REPO_ROOT.joinpath("scripts/build-packages.sh").read_text(encoding="utf-8")

    packages_dir = REPO_ROOT / "packages"
    directories = sorted(p for p in packages_dir.iterdir() if p.is_dir())
    assert directories, "no package source directories found"

    problems: list[str] = []
    for directory in directories:
        name = directory.name
        if not (directory / "control.in").is_file():
            problems.append(f"{name}: no control.in")
        if name not in packaging:
            problems.append(f"{name}: exists but build-packages.sh never builds it")
    assert not problems, (
        "package source problems:\n  " + "\n  ".join(problems)
    )


def test_every_built_package_is_staged_for_live_build() -> None:
    """A package that is built but not staged is a package that is not in the image."""
    packaging = astraos_env.REPO_ROOT.joinpath("scripts/build-packages.sh").read_text(encoding="utf-8")

    assert "packages.chroot" in packaging, (
        "build-packages.sh does not stage the .deb files into live-build's "
        "config/packages.chroot/, so they would never be installed into the image"
    )
    assert "finish_package" in packaging, "no package assembly function found"

    # Each package should appear in a finish_package call.
    packages_dir = REPO_ROOT / "packages"
    for directory in sorted(p for p in packages_dir.iterdir() if p.is_dir()):
        assert f"finish_package {directory.name}" in packaging, (
            f"{directory.name} is never passed to finish_package, so no .deb would be built"
        )


def test_documentation_shipped_in_the_image_exists() -> None:
    """configure-live-build.sh stages documentation into the image; each one must exist.

    Document names appear both in a multi-line for-loop over docs/ and in individual
    `stage_doc` calls, so every *.md token in the staging section is collected rather
    than only the loop list. A per-line pattern would silently check a subset: it would
    miss `stage_doc README.md`, which is exactly how the README once failed to ship.

    Names resolve against docs/ first and then the repository root, because README.md
    lives at the root while the rest live in docs/. The resolution is asserted below to
    keep the two in sync.
    """
    script = astraos_env.REPO_ROOT.joinpath("scripts/configure-live-build.sh").read_text(encoding="utf-8")

    # Comments legitimately mention documents that are not staged by this script.
    code = "\n".join(
        line for line in script.splitlines() if not line.lstrip().startswith("#")
    )

    # A single escaped dot: "\\.md" in a raw string would mean "a literal backslash
    # followed by any character", which matches nothing in this list.
    docs: list[str] = []
    for name in re.findall(r"([A-Za-z0-9_]+\.md)", code):
        if name not in docs:
            docs.append(name)

    assert docs, "configure-live-build.sh stages no documentation into the image"
    assert len(docs) >= 10, (
        f"only {len(docs)} documents are installed into the image; the staging section "
        "appears to have lost entries"
    )

    def resolve(name: str) -> Path:
        for candidate in (REPO_ROOT / "docs" / name, REPO_ROOT / name):
            if candidate.is_file():
                return candidate
        return REPO_ROOT / "docs" / name

    missing = [name for name in docs if not resolve(name).is_file()]
    assert not missing, (
        "these documents are staged into the image but do not exist, so the image would "
        "ship without them:\n  " + "\n  ".join(f"docs/{name} or {name}" for name in missing)
    )

    # The README is not in docs/, so the loop that copies from docs/ cannot ship it.
    readme_staging = re.findall(
        r"stage_doc\s+README\.md\s+\"?\$\{?REPO_ROOT\}?/README\.md\"?", code
    )
    assert readme_staging, (
        "README.md is not staged from the repository root. Copying it from docs/ cannot "
        "work, because docs/README.md does not exist, so the image would ship without a "
        "README and only a warning would be logged"
    )


def test_system_templates_referenced_by_the_build_exist() -> None:
    """Templates rendered by configure-live-build.sh must be present."""
    script = astraos_env.REPO_ROOT.joinpath("scripts/configure-live-build.sh").read_text(encoding="utf-8")

    templates = re.findall(r"system/([A-Za-z0-9_.-]+\.in)", script)
    assert templates, "no system templates are rendered by the build"

    missing = sorted(
        name for name in set(templates) if not (REPO_ROOT / "system" / name).is_file()
    )
    assert not missing, (
        "the build renders these templates but they do not exist:\n  " + "\n  ".join(missing)
    )
