"""The installer branding must satisfy the loader that reads it.

Calamares 3.3's branding constructor parses the descriptor before any page is drawn:
`componentName` must match the directory it sits in, every image and the slideshow
setting must resolve, and a missing key or file is a FATAL exit, not a warning. The
first CI install attempt (run 38924527286, 2026-10-16) ended exactly there — earlier
builds had shipped the same descriptor without anything ever starting the installer, so
nothing had ever read it. These tests pin the pieces that would let that happen again:

  * the descriptor carries a `slideshow` value that names images, not an empty key;
  * every file the slideshow and the `images:` section name is installed next to the
    descriptor by scripts/build-packages.sh;
  * the chroot hook refuses a descriptor the loader would refuse: a wrong component
    name, no slideshow key, or a slideshow file that will not exist at run time.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BRANDING = REPO_ROOT / "installer" / "branding" / "astraos" / "branding.desc"
BUILD_PACKAGES = REPO_ROOT / "scripts" / "build-packages.sh"
HOOK = (
    REPO_ROOT / "config" / "live-build" / "config" / "hooks" / "live"
    / "0300-installer.hook.chroot"
)

DESCRIPTION = "the Calamares branding descriptor satisfies the loader that reads it"

_ASSET = re.compile(r"([A-Za-z0-9._-]+\.(?:png|jpg|jpeg|qml))")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _slideshow_block(text: str) -> str:
    """The `slideshow:` entry and its indented continuation lines, if any."""
    block: list[str] = []
    collecting = False
    for line in text.splitlines():
        if line.startswith("slideshow:"):
            collecting = True
            block.append(line)
            continue
        if collecting:
            if line and not line[0].isspace():
                break
            block.append(line)
    return "\n".join(block)


def _installed_asset_names() -> set[str]:
    """Files build-packages.sh copies directly into the branding directory."""
    text = _text(BUILD_PACKAGES)
    return set(re.findall(r"branding/(?:astraos/)?([A-Za-z0-9._-]+\.(?:png|jpg|jpeg))", text))


def test_the_slideshow_is_an_image_sequence_not_an_empty_key() -> None:
    block = _slideshow_block(_text(BRANDING))
    assert block, (
        "branding.desc has no slideshow key. Calamares 3.3's branding constructor "
        "parses it unconditionally and exits with 'key not found: slideshow' - the "
        "installer never draws its first page (run 38924527286)"
    )
    assert _ASSET.search(block), (
        "the slideshow value names no file: a QML-enabled Calamares needs either an "
        "existing .qml file or a sequence of images, and anything else refuses to "
        "start the installer"
    )


def test_every_named_branding_file_is_installed_next_to_the_descriptor() -> None:
    shipped = _installed_asset_names()
    assert {"logo.png", "welcome.png"} <= shipped, (
        f"scripts/build-packages.sh no longer installs the branding images the "
        f"descriptor names; it installs: {sorted(shipped)}"
    )
    named = set(_ASSET.findall(_text(BRANDING)))
    missing = sorted(named - shipped)
    assert not missing, (
        "branding.desc names files that nothing installs into its directory, so the "
        f"loader would exit at startup: {missing}. "
        f"scripts/build-packages.sh installs: {sorted(shipped)}"
    )


def test_the_component_name_matches_the_directory() -> None:
    assert re.search(r"^componentName:[ \t]*astraos[ \t]*$", _text(BRANDING), re.M), (
        "Calamares refuses a branding component whose componentName does not match "
        "the directory it lives in (installer/branding/astraos)"
    )


def test_the_hook_refuses_a_descriptor_the_loader_would_refuse() -> None:
    hook = _text(HOOK)
    assert "'^componentName:" in hook, (
        "the chroot hook does not check the component name, which Calamares refuses "
        "when it does not match the directory name"
    )
    assert "^slideshow:" in hook, (
        "the chroot hook does not check the slideshow key"
    )
    assert "/usr/share/calamares/branding/astraos/${file}" in hook, (
        "the hook does not check that each slideshow file exists beside the descriptor"
    )
    assert "does not exist" in hook and "refuses to start" in hook, (
        "the hook's failure messages must say what the loader would do, so the next "
        "person reading a build failure knows why the check exists"
    )
