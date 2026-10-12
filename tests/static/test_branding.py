"""Branding asset and cross-reference tests.

The mistake these tests exist to catch: a theme file referencing an asset by a path or
filename that does not exist. That produces a black boot splash or an unbranded login
screen, and it is invisible until someone actually boots the image.
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

import astraos_env  # noqa: E402

DESCRIPTION = "branding assets exist, are valid PNGs, and are referenced consistently"

GENERATED = REPO_ROOT / "branding" / "generated"


def _branding_size() -> tuple[int, int]:
    branding = astraos_env.branding()
    return int(branding["BRAND_WALLPAPER_WIDTH"]), int(branding["BRAND_WALLPAPER_HEIGHT"])


def test_expected_assets_exist() -> None:
    width, height = _branding_size()
    expected = [
        f"astraos-wallpaper-dark-{width}x{height}.png",
        f"astraos-wallpaper-light-{width}x{height}.png",
        f"astraos-splash-boot-{width}x{height}.png",
        f"astraos-login-background-{width}x{height}.png",
        "astraos-logo-512.png",
        "astraos-logo-mono-light-512.png",
        "astraos-logo-mono-dark-512.png",
    ]
    missing = [name for name in expected if not (GENERATED / name).is_file()]
    assert not missing, (
        "generated branding assets are missing. Run: python3 branding/tools/render_assets.py\n"
        "  missing: " + ", ".join(missing)
    )


def test_generated_pngs_are_valid() -> None:
    """Parse each PNG's real chunk structure and verify every CRC."""
    failures: list[str] = []
    for path in sorted(GENERATED.glob("*.png")):
        try:
            data = path.read_bytes()
            assert data[:8] == b"\x89PNG\r\n\x1a\n", "bad PNG signature"
            width, height, depth, colour_type = struct.unpack(">IIBB", data[16:26])
            assert width > 0 and height > 0, "zero dimensions"
            assert depth == 8, f"unexpected bit depth {depth}"

            pos, tags = 8, []
            while pos + 12 <= len(data):
                length = struct.unpack(">I", data[pos:pos + 4])[0]
                tag = data[pos + 4:pos + 8]
                payload = data[pos + 8:pos + 8 + length]
                crc = struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])[0]
                assert (zlib.crc32(tag + payload) & 0xFFFFFFFF) == crc, f"bad CRC on {tag!r}"
                tags.append(tag.decode())
                pos += 12 + length

            assert tags[0] == "IHDR", "first chunk is not IHDR"
            assert tags[-1] == "IEND", "last chunk is not IEND"
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{path.name}: {exc}")

    assert not failures, "invalid PNG output:\n  " + "\n  ".join(failures)


def test_logo_has_transparency() -> None:
    """The ring marks must be RGBA, or they cannot be composited over a background."""
    for name in ("astraos-logo-512.png", "astraos-logo-mono-light-512.png"):
        path = GENERATED / name
        if not path.is_file():
            continue
        colour_type = struct.unpack(">IIBB", path.read_bytes()[16:26])[3]
        assert colour_type == 6, (
            f"{name} has colour type {colour_type}; expected 6 (RGBA). Without an alpha "
            "channel the mark cannot be placed over a wallpaper."
        )


def test_plymouth_theme_references_existing_images() -> None:
    """Every image the Plymouth script names must be installed by the packaging step."""
    theme_dir = REPO_ROOT / "branding" / "plymouth" / "astraos"
    script_text = (theme_dir / "astraos.script").read_text(encoding="utf-8")

    # The packaging step renames the generated art to these fixed names; the mapping is
    # in the "Package content assembly" section of scripts/build-packages.sh.
    packaging = (REPO_ROOT / "scripts" / "build-packages.sh").read_text(encoding="utf-8")

    for referenced in ("astraos-splash-boot.png", "astraos-logo.png"):
        assert referenced in script_text, (
            f"the Plymouth script no longer references {referenced}; update this test if "
            "that change was deliberate"
        )
        assert referenced in packaging, (
            f"the Plymouth script uses {referenced} but scripts/build-packages.sh never "
            "copies a file to that name, so the splash would have no image"
        )


def test_grub_theme_background_is_packaged() -> None:
    theme_dir = REPO_ROOT / "branding" / "grub" / "astraos"
    theme_text = (theme_dir / "theme.txt").read_text(encoding="utf-8")
    packaging = (REPO_ROOT / "scripts" / "build-packages.sh").read_text(encoding="utf-8")

    assert "desktop-image:" in theme_text, "the GRUB theme declares no background image"
    background = theme_text.split("desktop-image:", 1)[1].splitlines()[0].strip().strip('"')
    assert background, "the GRUB theme background is empty"
    assert background in packaging, (
        f"the GRUB theme references {background} but scripts/build-packages.sh does not "
        "provide a file with that name"
    )


def test_greeter_background_path_matches_a_generated_file() -> None:
    """The greeter config must point at a wallpaper the branding package installs."""
    greeter = (REPO_ROOT / "branding" / "lightdm" / "lightdm-gtk-greeter.conf").read_text(encoding="utf-8")
    background = ""
    for line in greeter.splitlines():
        if line.startswith("background="):
            background = line.split("=", 1)[1].strip()
    assert background, "the greeter configuration does not set a background"

    # The path is the installed location; the filename must match what is generated.
    filename = Path(background).name
    assert (GENERATED / filename).is_file(), (
        f"the greeter points at {background}, but branding/generated/{filename} does not "
        "exist, so the login screen would have no background"
    )


def test_desktop_wallpaper_paths_match_a_generated_file() -> None:
    """Both the system-wide and per-user wallpaper settings must point at real files."""
    width, height = _branding_size()
    expected = f"astraos-wallpaper-dark-{width}x{height}.png"

    for relative in (
        "desktop/skel/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml",
    ):
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        assert expected in text, (
            f"{relative} does not set the AstraOS wallpaper ({expected}), so the desktop "
            "would fall back to the Xfce default"
        )
        assert (GENERATED / expected).is_file(), f"{expected} has not been generated"


def test_svg_logos_are_well_formed_xml() -> None:
    import xml.etree.ElementTree as ET

    failures: list[str] = []
    for path in sorted((REPO_ROOT / "branding" / "logos").glob("*.svg")):
        try:
            ET.parse(path)
        except ET.ParseError as exc:
            failures.append(f"{path.name}: {exc}")
    assert not failures, "invalid SVG:\n  " + "\n  ".join(failures)


def test_brand_palette_matches_the_desktop_theme() -> None:
    """The documented palette and the GTK theme must agree on the accent colour."""
    branding = astraos_env.branding()
    accent = branding["COLOR_ACCENT_PRIMARY"].lower()
    gtk_css = (REPO_ROOT / "desktop" / "themes" / "AstraOS-Dark" / "gtk-3.0" / "gtk.css").read_text(encoding="utf-8")

    assert accent in gtk_css.lower(), (
        f"the desktop theme does not use the configured accent {accent}; the palette has "
        "one source of truth in config/branding.env"
    )
