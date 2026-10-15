"""Window-decoration, cursor and icon-theme asset tests.

The failure these exist to catch is specific and has bitten this project before: a
theme names an asset that is not on disk. Nothing reports it at build time. The image
builds, the ISO validates, and the first person to boot it finds the window titlebars
are gone.

So every reference is checked in both directions:

  * every decoration part xfwm4 can ask for exists, in every state it can ask for;
  * the theme the session actually selects has decorations, not just a name;
  * every cursor the Xcursor lookup can request exists and is a well-formed container;
  * the geometry in themerc agrees with the geometry the renderer drew the images at.

The last one is the subtle one. xfwm4 derives a titlebar's height from the drawn title
images, not from themerc, so a theme whose themerc disagrees with its images produces a
clipped or invisible titlebar while every individual file still looks fine.
"""

from __future__ import annotations

import re
import struct
import sys
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(REPO_ROOT / "branding" / "tools"))

import astraos_env  # noqa: E402

GENERATED = REPO_ROOT / "branding" / "generated"
THEMES_DIR = REPO_ROOT / "desktop" / "themes"
SKEL = REPO_ROOT / "desktop" / "skel" / ".config" / "xfce4" / "xfconf" / "xfce-perchannel-xml"

# Every decoration part xfwm4 looks for, and the states it looks for each in.
#
# `toggled` is the maximised window state, and for the maximize/stick/shade buttons it
# is also the engaged state. xfwm4 resolves an asset as <part>-<state>.png: there is no
# such thing as <part>-active-toggled.png, and generating that spelling yields a theme
# in which the restore icon never appears and nothing complains.
DECORATION_PARTS = (
    "title-1", "title-2", "title-3", "title-4", "title-5",
    "top-left", "top-right",
    "bottom-left", "bottom-right",
    "left", "right", "bottom",
    "close", "maximize", "hide", "menu", "stick", "shade",
)
DECORATION_STATES = ("active", "inactive", "toggled")

THEME_NAMES = ("AstraOS-Dark", "AstraOS-Light")


def _branding() -> dict[str, str]:
    return astraos_env.branding()


def _png_size(path: Path) -> tuple[int, int, int]:
    """(width, height, colour_type) read from the IHDR chunk."""
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    width, height, depth, colour_type = struct.unpack(">IIBB", data[16:26])
    if depth != 8:
        raise ValueError(f"unexpected bit depth {depth}")
    return width, height, colour_type


def _assert_valid_png(path: Path) -> tuple[int, int, int]:
    """Parse the whole chunk chain and verify every CRC."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name}: bad PNG signature"

    pos, tags = 8, []
    while pos + 12 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        payload = data[pos + 8:pos + 8 + length]
        crc = struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])[0]
        assert (zlib.crc32(tag + payload) & 0xFFFFFFFF) == crc, f"{path.name}: bad CRC on {tag!r}"
        tags.append(tag.decode())
        pos += 12 + length

    assert tags[0] == "IHDR", f"{path.name}: first chunk is not IHDR"
    assert tags[-1] == "IEND", f"{path.name}: last chunk is not IEND"
    return _png_size(path)


# ---------------------------------------------------------------------------
# Window decorations
# ---------------------------------------------------------------------------

def test_every_decoration_part_exists_in_every_state() -> None:
    """The asset xfwm4 will look for must be the asset that is on disk."""
    for theme in THEME_NAMES:
        directory = GENERATED / "xfwm4" / theme
        assert directory.is_dir(), (
            f"{directory} is missing. Run: python3 branding/tools/render_theme_assets.py"
        )
        missing = [
            f"{part}-{state}.png"
            for part in DECORATION_PARTS
            for state in DECORATION_STATES
            if not (directory / f"{part}-{state}.png").is_file()
        ]
        assert not missing, (
            f"the {theme} decoration set is incomplete, so xfwm4 would fall back and "
            "some part of the window frame would be drawn by no theme at all:\n  "
            + ", ".join(missing)
        )


def test_decoration_assets_are_valid_transparent_pngs() -> None:
    """Decoration parts must have an alpha channel or they cannot be composited."""
    failures: list[str] = []
    for theme in THEME_NAMES:
        for path in sorted((GENERATED / "xfwm4" / theme).glob("*.png")):
            try:
                _, _, colour_type = _assert_valid_png(path)
                assert colour_type == 6, (
                    f"{path.name} has colour type {colour_type}; expected 6 (RGBA). A "
                    "decoration without alpha cannot be drawn over the desktop."
                )
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{path.name}: {exc}")
    assert not failures, "invalid decoration assets:\n  " + "\n  ".join(failures)


def test_titlebar_images_match_the_declared_height() -> None:
    """xfwm4 takes the titlebar height from the image, so the image is the truth.

    themerc has no option for it. A title image one pixel taller or shorter than the
    theme intends produces a titlebar that is clipped or that overlaps the window body.
    """
    branding = _branding()
    expected_height = int(branding["WINDOW_TITLEBAR_HEIGHT"])
    expected_button = int(branding["WINDOW_BUTTON_SIZE"])
    expected_radius = int(branding["WINDOW_CORNER_RADIUS"])

    failures: list[str] = []
    for theme in THEME_NAMES:
        directory = GENERATED / "xfwm4" / theme
        for part in DECORATION_PARTS:
            for state in DECORATION_STATES:
                path = directory / f"{part}-{state}.png"
                if not path.is_file():
                    continue
                width, height, _ = _png_size(path)
                if part.startswith("title-") or part in ("top-left", "top-right"):
                    want = expected_height
                elif part in ("left", "right", "bottom") or part.startswith("bottom-"):
                    want = int(branding["WINDOW_BORDER_WIDTH"])
                else:  # a titlebar button
                    want = expected_button
                    if width != expected_button or height != expected_button:
                        failures.append(
                            f"{path.name}: button is {width}x{height}, "
                            f"WINDOW_BUTTON_SIZE is {expected_button}"
                        )
                    continue
                # The frame edges are not all shaped alike, and checking the wrong
                # axis is what previously reported a correct render as broken.
                #
                #   left/right  the vertical edge running alongside the titlebar: 1px
                #               WIDE, as tall as the titlebar.
                #   bottom and bottom-left/bottom-right the horizontal edge under the
                #               window: 1px HIGH, as wide as the frame (or the corner
                #               radius for the two bottom corners).
                #
                # Asserting height==border width for left/right demanded a 1px-tall
                # vertical edge, which would leave xfwm4 nothing to draw down the side
                # of the titlebar.
                if part in ("left", "right"):
                    if width != want:
                        failures.append(f"{path.name}: width {width}, expected {want}")
                elif height != want:
                    failures.append(f"{path.name}: height {height}, expected {want}")

        for side in ("top-left", "top-right"):
            path = directory / f"{side}-active.png"
            if path.is_file():
                width, _, _ = _png_size(path)
                if width > expected_radius:
                    failures.append(
                        f"{path.name}: corner is {width}px wide but "
                        f"WINDOW_CORNER_RADIUS is {expected_radius}; xfwm4 positions the "
                        "title segments against this width, so the two must agree"
                    )

    assert not failures, "decoration geometry disagrees with config/branding.env:\n  " + \
        "\n  ".join(failures)


def test_themerc_declares_geometry_that_matches_the_drawn_assets() -> None:
    """themerc and the generated images are produced from the same constants."""
    branding = _branding()
    failures: list[str] = []

    for theme in THEME_NAMES:
        themerc = THEMES_DIR / theme / "xfwm4" / "themerc"
        assert themerc.is_file(), f"{themerc} is missing; the theme would not load"
        text = themerc.read_text(encoding="utf-8")

        options = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            options[key.strip()] = value.strip()

        # Title text colours are per-theme, not shared. The dark-surface tokens
        # (COLOR_TEXT #F2EEFF, COLOR_TEXT_FAINT #6B6386) are near-white and would be
        # invisible on the Light theme's #F4F6FA titlebar, so each theme is checked
        # against its own pair. Checking both against one pair is what previously
        # forced the Light themerc to declare unreadable title text.
        if theme.endswith("-Light"):
            text_tokens = ("COLOR_TEXT_LIGHT_THEME", "COLOR_TEXT_DIM_LIGHT_THEME")
        else:
            text_tokens = ("COLOR_TEXT", "COLOR_TEXT_FAINT")

        expected = {
            "button_offset": branding["WINDOW_BUTTON_SPACING"],
            "button_spacing": branding["WINDOW_BUTTON_SPACING"],
            "title_horizontal_offset": branding["WINDOW_TITLE_OFFSET"],
            "active_text_color": branding[text_tokens[0]].lstrip("#"),
            "inactive_text_color": branding[text_tokens[1]].lstrip("#"),
        }
        for key, want in expected.items():
            if key not in options:
                failures.append(f"{theme}/xfwm4/themerc: {key} is not declared")
                continue
            got = options[key]
            if key.endswith("color"):
                if got.lower().lstrip("#") != want.lower().lstrip("#"):
                    failures.append(f"{theme}/xfwm4/themerc: {key}={got}, expected #{want}")
            elif got != want:
                failures.append(f"{theme}/xfwm4/themerc: {key}={got}, expected {want}")

        if options.get("full_width_title", "").lower() != "true":
            failures.append(
                f"{theme}/xfwm4/themerc: full_width_title must be true so the titlebar "
                "spans the window, as docs/DESIGN.md specifies"
            )

    assert not failures, "themerc disagrees with config/branding.env:\n  " + "\n  ".join(failures)


def test_the_selected_window_theme_actually_has_decorations() -> None:
    """The theme name in xfwm4.xml must have a complete decoration set."""
    import xml.etree.ElementTree as ET

    tree = ET.parse(SKEL / "xfwm4.xml")
    selected = None
    for prop in tree.iter("property"):
        if prop.get("name") == "theme":
            selected = prop.get("value")

    assert selected, "xfwm4.xml does not select a window decoration theme"
    directory = GENERATED / "xfwm4" / selected
    assert directory.is_dir(), (
        f"the session selects the xfwm4 theme {selected!r} but "
        f"branding/generated/xfwm4/{selected} does not exist. xfwm4 falls back silently "
        "in that case, which is how a distribution ends up looking unbranded."
    )
    assert (THEMES_DIR / selected / "xfwm4" / "themerc").is_file(), (
        f"the session selects {selected!r} but that theme ships no themerc"
    )


# ---------------------------------------------------------------------------
# Cursor theme
# ---------------------------------------------------------------------------

# The cursors an X client can ask for by name. A theme missing any of these leaves the
# X server drawing its built-in bitmap pointer, with nothing to indicate why.
REQUIRED_CURSORS = (
    "default", "left_ptr", "arrow", "xterm", "text", "pointer", "hand", "grab",
    "grabbing", "crosshair", "cross", "move", "wait", "progress", "not-allowed",
    "ns-resize", "ew-resize", "nesw-resize", "nwse-resize", "size-bdiag", "size-fdiag",
    "n-resize", "s-resize", "e-resize", "w-resize", "ne-resize", "nw-resize",
    "se-resize", "sw-resize", "col-resize", "row-resize", "v_double_arrow",
    "h_double_arrow", "sb_h_double_arrow", "sb_v_double_arrow",
    "up-arrow", "down-arrow", "left-arrow", "right-arrow",
    "sb_up_arrow", "sb_down_arrow", "sb_left_arrow", "sb_right_arrow",
    "zoom-in", "zoom-out", "pencil", "copy", "alias", "link", "help", "context-menu",
)


def test_every_standard_cursor_is_present() -> None:
    for theme in ("AstraOS", "AstraOS-Light"):
        directory = GENERATED / "cursors" / theme
        assert directory.is_dir(), (
            f"{directory} is missing. Run: python3 branding/tools/render_theme_assets.py"
        )
        missing = [name for name in REQUIRED_CURSORS if not (directory / name).is_file()]
        assert not missing, (
            f"the {theme} cursor theme is missing cursors the X server will ask for; "
            "X11 falls back to its built-in pointer for each one:\n  " + ", ".join(missing)
        )


def test_cursors_are_well_formed_xcursor_containers() -> None:
    """Parse each container back rather than trusting the writer.

    A truncated or mis-offset .xcursor is ignored by libXcursor in complete silence, so
    the only way to know is to read the file back.
    """
    from raster import read_xcursor

    branding = _branding()
    want_sizes = {int(s) for s in branding["CURSOR_SIZES"].split()}

    for theme in ("AstraOS", "AstraOS-Light"):
        directory = GENERATED / "cursors" / theme
        if not directory.is_dir():
            continue
        failures: list[str] = []
        for path in sorted(directory.iterdir()):
            if not path.is_file():
                continue
            try:
                images = read_xcursor(path)
                assert images, f"{path.name}: contains no images"
                sizes = {subtype for subtype, _w, _h, _hot in images}
                missing = want_sizes - sizes
                assert not missing, (
                    f"{path.name}: missing sizes {sorted(missing)}; a client asking for "
                    "one of those sizes gets the built-in cursor"
                )
                for subtype, width, height, hot_x in images:
                    assert width == height, (
                        f"{path.name}: {subtype}px image is {width}x{height}"
                    )
                    assert 0 <= hot_x < width, (
                        f"{path.name}: {subtype}px hotspot x={hot_x} is outside the image"
                    )
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{path.name}: {exc}")
        assert not failures, "malformed cursor files:\n  " + "\n  ".join(failures)


def test_the_pointer_hotspot_is_at_the_tip() -> None:
    """A pointer whose hotspot is in the middle of the shape cannot be aimed."""
    import struct

    path = GENERATED / "cursors" / "AstraOS" / "default"
    if not path.is_file():
        return

    data = path.read_bytes()
    _, _, toc = struct.unpack_from("<III", data, 4)
    for index in range(toc):
        _, subtype, position = struct.unpack_from("<III", data, 16 + 12 * index)
        _s, _t, _sb, _v, width, height, hot_x, hot_y, _d = struct.unpack(
            "<IIIIIIIII", data[position:position + 36]
        )
        assert hot_x <= width * 0.25, (
            f"the {subtype}px pointer hotspot is at x={hot_x} of {width}; it should be at "
            "the tip of the arrow, which is the difference between aiming and guessing"
        )
        assert hot_y <= height * 0.25, (
            f"the {subtype}px pointer hotspot is at y={hot_y} of {height}; it should be at "
            "the tip of the arrow"
        )


def test_the_selected_cursor_theme_exists() -> None:
    """The name in xsettings.xml must have cursors, or X11 quietly reverts."""
    import xml.etree.ElementTree as ET

    tree = ET.parse(SKEL / "xsettings.xml")
    selected = None
    for prop in tree.iter("property"):
        if prop.get("name") == "CursorThemeName":
            selected = prop.get("value")

    assert selected, "xsettings.xml does not select a cursor theme"
    assert (GENERATED / "cursors" / selected).is_dir(), (
        f"the session selects the cursor theme {selected!r} but "
        f"branding/generated/cursors/{selected} does not exist"
    )


def test_the_icon_theme_declares_its_cursor_theme() -> None:
    """An icon theme that carries cursors must say so with a Cursor Theme key."""
    index = REPO_ROOT / "branding" / "icons" / "index.theme"
    assert index.is_file(), "branding/icons/index.theme is missing"
    text = index.read_text(encoding="utf-8")
    assert "Cursor Theme=AstraOS" in text, (
        "the icon theme installs the cursors but does not declare them, so nothing "
        "looks the cursor theme up and X11 keeps using its built-in pointers"
    )


# ---------------------------------------------------------------------------
# Packaging
# ---------------------------------------------------------------------------

def test_packaging_installs_every_generated_asset() -> None:
    """Each generated asset group must have a mapping in the packaging script."""
    packaging = (REPO_ROOT / "scripts" / "build-packages.sh").read_text(encoding="utf-8")

    for reference in (
        "branding/generated/cursors",
        "branding/generated/xfwm4",
        "AstraOS-Dark",
        "AstraOS-Light",
        "/usr/share/themes",
        "/usr/share/icons/AstraOS/cursors",
    ):
        assert reference in packaging, (
            f"scripts/build-packages.sh never mentions {reference}, so that asset would "
            "be built and then never reach the image"
        )


def test_packaging_refuses_to_install_an_incomplete_decoration_theme() -> None:
    """A theme with missing images must stop the build, not ship a broken titlebar."""
    packaging = (REPO_ROOT / "scripts" / "build-packages.sh").read_text(encoding="utf-8")
    assert "themerc" in packaging, (
        "scripts/build-packages.sh does not require themerc, so a theme could be "
        "installed with images but no descriptor and xfwm4 would find nothing"
    )
    assert "xfwm4 decorations missing" in packaging, (
        "scripts/build-packages.sh does not fail when the generated decoration set is "
        "absent; it would install a theme name with no images behind it"
    )


# ---------------------------------------------------------------------------
# GTK theme
# ---------------------------------------------------------------------------

def test_both_gtk_themes_are_complete_enough_to_load() -> None:
    """A GTK theme needs an index.theme naming a stylesheet that exists."""
    for theme in THEME_NAMES:
        index = THEMES_DIR / theme / "index.theme"
        assert index.is_file(), f"{theme}: index.theme is missing"

        text = index.read_text(encoding="utf-8")
        assert "Inherits=" in text, (
            f"{theme}: index.theme declares no Inherits, so widgets the theme does not "
            "style would fall back to the GTK default rather than to Adwaita"
        )

        referenced = re.findall(r"^gtk-[34]\.0/gtk\.css$", text, re.MULTILINE)
        for version in ("3.0", "4.0"):
            css = THEMES_DIR / theme / f"gtk-{version}" / "gtk.css"
            if not css.is_file():
                continue
            assert f"gtk-{version}/gtk.css" in text, (
                f"{theme}: index.theme does not list gtk-{version}/gtk.css, so GTK is "
                "never told the stylesheet exists"
            )
            assert css.stat().st_size > 4096, (
                f"{theme}: gtk-{version}/gtk.css is only {css.stat().st_size} bytes, "
                "which is a stub rather than a theme"
            )


def test_gtk_themes_only_use_palette_from_branding_env() -> None:
    """An invented hex is a colour nobody chose, and it drifts from the identity."""
    branding = _branding()
    allowed = {
        value.lstrip("#").lower()
        for value in branding.values()
        if re.fullmatch(r"#[0-9A-Fa-f]{6}", value)
    }
    assert allowed, "config/branding.env declares no colours to check against"

    failures: list[str] = []
    for theme in THEME_NAMES:
        for version in ("3.0", "4.0"):
            css = THEMES_DIR / theme / f"gtk-{version}" / "gtk.css"
            if not css.is_file():
                continue
            text = css.read_text(encoding="utf-8")
            # rgba()/rgb() components are composed from the same tokens and are covered
            # by the CSS author's own comments, so only bare hex literals are checked.
            for hex_value in re.findall(r"#([0-9A-Fa-f]{6})\b", text):
                if hex_value.lower() not in allowed:
                    failures.append(
                        f"{theme}/gtk-{version}/gtk.css: #{hex_value} is not a colour in "
                        "config/branding.env"
                    )
    assert not failures, "colours outside the documented palette:\n  " + "\n  ".join(failures)


def test_gtk_themes_reference_no_missing_image() -> None:
    """url() to a file that is not installed gives a silently blank background."""
    failures: list[str] = []
    for theme in THEME_NAMES:
        for version in ("3.0", "4.0"):
            css = THEMES_DIR / theme / f"gtk-{version}" / "gtk.css"
            if not css.is_file():
                continue
            text = css.read_text(encoding="utf-8")
            for reference in re.findall(r"url\(\s*[\"']?([^\"')]+)", text):
                if reference.startswith(("http://", "https://", "data:")):
                    continue
                name = Path(reference).name
                # GTK resolves url() in a theme against the theme's own directory tree
                # and the icon theme; anything not shipped by either is a blank image.
                candidates = list(THEMES_DIR.rglob(name)) + list(
                    (REPO_ROOT / "branding" / "icons").rglob(name)
                ) + list(GENERATED.rglob(name))
                if not candidates:
                    failures.append(
                        f"{theme}/gtk-{version}/gtk.css: url({reference}) names a file "
                        "that is not in the theme, the icon theme or the generated assets"
                    )
    assert not failures, "missing images referenced by the GTK themes:\n  " + "\n  ".join(failures)