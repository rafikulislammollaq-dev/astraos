#!/usr/bin/env python3
"""Generate the AstraOS window-decoration and cursor theme assets.

What this produces
------------------
The reference screenshots in docs/reference/ show neon window chrome and a matching
pointer. docs/KNOWN_LIMITATIONS.md 1.4 recorded that AstraOS shipped a colour-only
GTK theme and no window decorations at all, so every window fell back to xfwm4's
upstream `Default` theme. That was a deliberate choice at the time — pointing xfwm4 at
a theme name whose assets are not on disk produces missing titlebars, which is worse
than an ugly titlebar. This generator is what makes the better-looking option safe:
the decoration assets now exist, so the theme can be named.

  xfwm4 decoration set, for each of AstraOS-Dark and AstraOS-Light:
    title-1..5-{active,inactive}[-toggled].png   the stretchable titlebar segments
    top-left/top-right-{active,inactive}.png      the rounded outer corners
    bottom-left/bottom-right-{active,inactive}.png
    left/right/bottom-{active,inactive}.png       the 1px frame edges
    close/maximize/hide/menu/stick/shade-*.png    the titlebar buttons

  Xcursor theme, installed as an icon theme that carries cursors:
    cursors/AstraOS/*.xcursor                    one file per standard cursor name

Why generated rather than drawn
-------------------------------
Two failure modes are worth more than the file size of a checked-in binary would be:

  * A theme file referencing an asset that is not installed produces a black splash, a
    blank login screen or invisible titlebars, and none of it is visible until a human
    boots the image. Generating from config/branding.env makes the palette one source
    of truth and makes a missing asset impossible.
  * xfwm4 derives the titlebar height from the drawn title images, not from themerc. If
    a hand-drawn image and the declared metric disagree, the titlebar is clipped. Here
    both come from the same WINDOW_* constants.

Only the standard library is used, so this runs on the Windows development machine as
well as in the build container.

Usage:
  python3 branding/tools/render_theme_assets.py
  python3 branding/tools/render_theme_assets.py --only cursors
  python3 branding/tools/render_theme_assets.py --out /tmp/astraos-theme
"""

from __future__ import annotations

import argparse
import hashlib
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import astraos_env  # noqa: E402

import raster  # noqa: E402
from raster import Canvas, RGB, distinct_sizes, hex_rgb, mix, to_hex, write_xcursor  # noqa: E402


# ---------------------------------------------------------------------------
# Theme palette
# ---------------------------------------------------------------------------

class ThemePalette:
    """One window-decoration colour scheme.

    The dark scheme takes its accents from the brand palette; the light scheme swaps
    the neon magenta for the light-theme accent, because a magenta glow on a white
    titlebar is not an accent, it is a legibility problem.
    """

    def __init__(self, brand: dict[str, str], light: bool = False) -> None:
        self.light = light

        self.void = hex_rgb(brand["COLOR_VOID"])
        self.surface = hex_rgb(brand["COLOR_SURFACE"])
        self.surface_raised = hex_rgb(brand["COLOR_SURFACE_RAISED"])
        self.text = hex_rgb(brand["COLOR_TEXT"])
        self.text_faint = hex_rgb(brand["COLOR_TEXT_FAINT"])
        self.hairline_hot = hex_rgb(brand["COLOR_HAIRLINE_HOT"])

        if not light:
            self.surface_top = mix(self.surface_raised, self.text, 0.06)
            self.surface_bottom = mix(self.surface, self.void, 0.35)
            self.edge_hot = self.hairline_hot
            self.edge_base = hex_rgb(brand["COLOR_HAIRLINE_BASE"])
            self.ink = self.text
            self.ink_dim = self.text_faint
            self.glow_strength = 0.55
        else:
            accent = hex_rgb(brand["COLOR_ACCENT_LIGHT"])
            self.surface_top = mix(hex_rgb(brand["COLOR_BG_LIGHT_RAISED"]), accent, 0.05)
            self.surface_bottom = mix(hex_rgb(brand["COLOR_BG_LIGHT"]), accent, 0.03)
            self.edge_hot = accent
            self.edge_base = mix(hex_rgb(brand["COLOR_HAIRLINE_BASE"]), (255.0, 255.0, 255.0), 0.84)
            self.ink = hex_rgb(brand["COLOR_TEXT_LIGHT_THEME"])
            self.ink_dim = mix(hex_rgb(brand["COLOR_TEXT_LIGHT_THEME"]),
                               (255.0, 255.0, 255.0), 0.52)
            self.glow_strength = 0.22


# ---------------------------------------------------------------------------
# Window decoration geometry
# ---------------------------------------------------------------------------

class Metrics:
    """Window decoration geometry, read once from config/branding.env."""

    def __init__(self, brand: dict[str, str]) -> None:
        self.title_height = int(brand["WINDOW_TITLEBAR_HEIGHT"])
        self.border = int(brand["WINDOW_BORDER_WIDTH"])
        self.button = int(brand["WINDOW_BUTTON_SIZE"])
        self.button_spacing = int(brand["WINDOW_BUTTON_SPACING"])
        self.radius = int(brand["WINDOW_CORNER_RADIUS"])

        # The width of each of the five titlebar segments. xfwm4 stretches the middle
        # three and keeps the outer two at their natural size, so the fixed ends carry
        # the rounded corners' flat continuations and the segments stay small.
        self.segment = 32

        # Guard against a bad configuration producing a theme that cannot be drawn.
        if self.title_height < 12 or self.title_height > 96:
            raise ValueError(
                f"WINDOW_TITLEBAR_HEIGHT={self.title_height} is outside the range an "
                "xfwm4 titlebar can be drawn at"
            )
        if self.button < 8 or self.button > 64:
            raise ValueError(f"WINDOW_BUTTON_SIZE={self.button} is out of range")
        if self.radius > self.title_height // 2:
            self.radius = self.title_height // 2
        if self.border < 1:
            self.border = 1


# ---------------------------------------------------------------------------
# Titlebar painting
# ---------------------------------------------------------------------------

def _title_surface(canvas: Canvas, pal: ThemePalette, active: bool) -> None:
    """Fill a titlebar segment with the scheme's vertical gradient."""
    raster.vertical_gradient(
        canvas, 0.0, float(canvas.height),
        pal.surface_top, pal.surface_bottom,
    )

    # The hot edge: a 1px accent line along the top, with a short additive falloff
    # beneath it. This is the "hot edge lighting" of docs/DESIGN.md and it is what
    # makes a focused window readable at a glance.
    edge = pal.edge_hot if active else pal.edge_base
    strength = 1.0 if active else 0.85
    for x in range(canvas.width):
        canvas.blend(x, 0, edge, strength)

    if active and pal.glow_strength > 0.0:
        falloff_rows = min(4, canvas.height - 1)
        for row in range(1, falloff_rows + 1):
            alpha = pal.glow_strength * (1.0 - row / (falloff_rows + 1.0))
            for x in range(canvas.width):
                canvas.blend(x, row, edge, alpha * 0.45)

    # The bottom hairline closes the bar off against the window body.
    bottom = mix(edge, pal.surface_bottom, 0.45 if active else 0.2)
    for x in range(canvas.width):
        canvas.blend(x, canvas.height - 1, bottom, 0.9)


def _corner_sdf(width: int, height: int, radius: int, side: str, square: bool):
    """Signed distance for a titlebar corner piece.

    `side` is 'left' or 'right'; `square` is the maximised state, where the window
    touches the screen edge and the corners must not be rounded.
    """
    if square or radius <= 0:
        def inside_box(px: float, py: float) -> float:
            return min(px, width - px, py, height - py)
        return inside_box

    outer = raster.rounded_rect_sdf(0.0, 0.0, float(width), float(height), float(radius))
    if side == "left":
        def sdf(px: float, py: float) -> float:
            # Only the top-left corner is rounded; the piece is a full-height strip.
            return max(outer(px, py), px - float(radius))
    else:
        def sdf(px: float, py: float) -> float:
            return max(outer(px, py), float(width - radius) - px)
    return sdf


def _paint_corner(canvas: Canvas, pal: ThemePalette, metrics: Metrics,
                  side: str, active: bool, square: bool) -> None:
    raster.vertical_gradient(canvas, 0.0, float(canvas.height),
                             pal.surface_top, pal.surface_bottom)
    edge = pal.edge_hot if active else pal.edge_base
    for y in range(canvas.height):
        if y == 0:
            # The top row only exists where the corner is not transparent.
            for x in range(canvas.width):
                if _corner_sdf(canvas.width, canvas.height, metrics.radius,
                               side, square)(x + 0.5, y + 0.5) <= 0.0:
                    canvas.blend(x, y, edge, 1.0 if active else 0.85)
            continue
        if y > 2 and active:
            continue
        alpha = 0.45 * (1.0 - y / 3.0)
        for x in range(canvas.width):
            if _corner_sdf(canvas.width, canvas.height, metrics.radius,
                           side, square)(x + 0.5, y + 0.5) <= 0.0:
                canvas.blend(x, y, edge, max(alpha, 0.0))

    if active:
        bottom = mix(edge, pal.surface_bottom, 0.45)
        for x in range(canvas.width):
            if _corner_sdf(canvas.width, canvas.height, metrics.radius,
                           side, square)(x + 0.5, canvas.height - 0.5) <= 0.0:
                canvas.blend(x, canvas.height - 1, bottom, 0.9)

    # Clip everything to the corner shape, which is what turns the strip into a
    # rounded cap.
    sdf = _corner_sdf(canvas.width, canvas.height, metrics.radius, side, square)
    _clip_to_sdf(canvas, sdf)


def _clip_to_sdf(canvas: Canvas, sdf) -> None:
    """Zero the alpha of every pixel outside the shape, without touching its colour."""
    for y in range(canvas.height):
        for x in range(canvas.width):
            if sdf(x + 0.5, y + 0.5) > 0.0:
                i = (y * canvas.width + x) * 4
                canvas.px[i + 3] = 0


# ---------------------------------------------------------------------------
# Titlebar buttons
# ---------------------------------------------------------------------------

def _glyph_paths(name: str) -> list[list[tuple[float, float]]]:
    """Titlebar button glyphs on a fixed 12x12 design grid.

    Coordinates come back unscaled, in grid units. The caller scales them once, into
    the button box. Scaling here as well was the bug that clipped the right and bottom
    edges of every square glyph at 5x the intended size, so the maximise button drew as
    a bare corner.

    Every glyph is built from the same grid so a 16px button and a 32px button show the
    same mark rather than two different ones.
    """
    def pt(x: float, y: float) -> tuple[float, float]:
        return (x, y)

    def line(*coords: float) -> list[tuple[float, float]]:
        return [pt(coords[i], coords[i + 1]) for i in range(0, len(coords), 2)]

    def rect(x0: float, y0: float, x1: float, y1: float) -> list[tuple[float, float]]:
        return line(x0, y0, x1, y0, x1, y1, x0, y1, x0, y0)

    if name == "close":
        return [line(1.5, 1.5, 10.5, 10.5), line(10.5, 1.5, 1.5, 10.5)]

    if name == "maximize":
        return [rect(1.0, 1.0, 11.0, 11.0)]

    if name == "maximize-toggled":
        # The restore mark: the rear square peeking above a front square that is
        # broken at the corner, which is how every other desktop draws it.
        return [line(1.0, 4.0, 1.0, 1.0, 8.0, 1.0),
                line(4.0, 11.0, 11.0, 11.0, 11.0, 4.0, 8.0, 4.0)]

    if name == "hide":
        return [line(1.0, 9.0, 11.0, 9.0)]

    if name == "menu":
        return [line(1.5, 3.0, 10.5, 3.0), line(1.5, 6.0, 10.5, 6.0),
                line(1.5, 9.0, 10.5, 9.0)]

    if name == "stick":
        # A pin: diamond head over a stem, with a base bar so it reads at 16px.
        return [line(6.0, 0.5, 3.5, 3.5, 8.5, 3.5, 6.0, 0.5, 6.0, 11.5),
                line(3.0, 11.5, 9.0, 11.5)]

    if name == "shade":
        return [line(1.0, 8.5, 6.0, 3.0, 11.0, 8.5), line(6.0, 3.0, 6.0, 11.5)]

    return [line(2.0, 6.0, 10.0, 6.0), line(6.0, 2.0, 6.0, 10.0)]


BUTTONS = ("close", "maximize", "hide", "menu", "stick", "shade")

# xfwm4 loads every decoration asset as `<name>-<state>.<ext>`, where state is one of
# active, inactive or toggled. It is NOT `<name>-<state>-toggled`: generating that
# spelling produced a theme in which the restore icon silently never appeared, because
# nothing ever asks for a file by that name. `toggled` is the state a maximised window
# draws in, and the state a toggle button draws when it is engaged.
XFWM4_STATES = ("active", "inactive", "toggled")


def _render_button(path: Path, name: str, pal: ThemePalette, state: str) -> None:
    """One titlebar button.

    The glyph is drawn twice: a wider pass in the outline colour and a narrower pass in
    the ink colour. That is the standard way to get a crisp outlined mark at any size
    without a separate outline asset, and it is what keeps a 16px button legible.
    """
    size = 18
    canvas = Canvas(size, size)

    # An engaged toggle button is drawn in the accent, which is how a stuck window or a
    # shaded window reads as different from an ordinary one.
    engaged = state == "toggled" and name in ("maximize", "stick", "shade")
    glyph_name = f"{name}-toggled" if engaged else name
    paths = _glyph_paths(glyph_name)

    if state == "inactive":
        ink = pal.ink_dim
    elif engaged:
        ink = pal.edge_hot
    else:
        ink = pal.ink
    outline = pal.void if not pal.light else mix(pal.ink, (255.0, 255.0, 255.0), 0.75)

    inset = max(size * 0.14, 1.0)
    scaled = [[(inset + x * (size - 2 * inset) / 12.0,
                inset + y * (size - 2 * inset) / 12.0) for x, y in glyph]
             for glyph in paths]

    stroke = max(size * 0.085, 1.0)
    for outline_path in scaled:
        canvas.stroke_polyline(outline_path, outline, stroke + max(stroke * 0.9, 1.0), 1.0)
    for ink_path in scaled:
        canvas.stroke_polyline(ink_path, ink, stroke, 1.0)

    canvas.write_png(path)


def render_xfwm4_theme(out_dir: Path, theme_name: str, pal: ThemePalette,
                       metrics: Metrics) -> list[Path]:
    """Write the complete decoration set for one theme."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    title_h = metrics.title_height
    radius = metrics.radius

    for state in XFWM4_STATES:
        # A maximised window is still the focused window: it keeps the accent edge but
        # loses the rounded corners, because its edges are against the screen.
        active = state in ("active", "toggled")
        square = state == "toggled"

        # Five titlebar segments. The middle one is what xfwm4 tiles, so it carries no
        # horizontal structure at all.
        for index in range(1, 6):
            canvas = Canvas(metrics.segment, title_h)
            _title_surface(canvas, pal, active)
            path = out_dir / f"title-{index}-{state}.png"
            canvas.write_png(path)
            written.append(path)

        # Outer top corners.
        for side in ("left", "right"):
            canvas = Canvas(max(radius, 1), title_h)
            _paint_corner(canvas, pal, metrics, side, active, square=square)
            path = out_dir / f"top-{side}-{state}.png"
            canvas.write_png(path)
            written.append(path)

        # Bottom corners: square, on every state.
        for side in ("left", "right"):
            canvas = Canvas(max(radius, 1), metrics.border)
            edge = pal.edge_hot if active else pal.edge_base
            base = mix(pal.surface_bottom, edge, 0.45 if active else 0.25)
            raster.vertical_gradient(canvas, 0.0, float(metrics.border), base, base)
            path = out_dir / f"bottom-{side}-{state}.png"
            canvas.write_png(path)
            written.append(path)

        # 1px frame edges.
        for name, width, height in (
            ("left", metrics.border, title_h),
            ("right", metrics.border, title_h),
            ("bottom", 1, metrics.border),
        ):
            canvas = Canvas(max(width, 1), max(height, 1))
            edge = pal.edge_hot if active else pal.edge_base
            base = mix(pal.surface_bottom, edge, 0.45 if active else 0.25)
            raster.vertical_gradient(canvas, 0.0, float(canvas.height), base, base)
            path = out_dir / f"{name}-{state}.png"
            canvas.write_png(path)
            written.append(path)

        # Titlebar buttons.
        for button in BUTTONS:
            path = out_dir / f"{button}-{state}.png"
            _render_button(path, button, pal, state)
            written.append(path)

    return written


# ---------------------------------------------------------------------------
# Cursors
# ---------------------------------------------------------------------------

# The classic pointer outline, in a unit box with y pointing down. This is the shape
# the X11 core cursor has had since the 1980s; a distribution that redraws it into
# something unrecognisable makes the pointer harder to aim, not better looking.
ARROW_UNIT = [
    (0.000, 0.000), (0.000, 0.760), (0.205, 0.570), (0.345, 0.855),
    (0.470, 0.800), (0.330, 0.520), (0.560, 0.510),
]

def _stroke_and_fill(canvas: Canvas, unit_points, size: float, offset_y: float,
                     ink: RGB, outline: RGB, stroke: float) -> None:
    """Outline pass then fill pass for a unit-box polygon, as with the buttons."""
    pts = [(x * size, y * size + offset_y) for x, y in unit_points]
    closed = pts + [pts[0]]
    canvas.stroke_polyline(closed, outline, stroke + max(stroke * 0.85, 1.1), 1.0)
    canvas.fill_polygon(pts, ink, 1.0)


def _draw_arrow(canvas: Canvas, size: int, pal: dict) -> None:
    s = float(size)
    _stroke_and_fill(canvas, ARROW_UNIT, s * 0.82, s * 0.06,
                     pal["ink"], pal["outline"], max(s * 0.075, 1.0))
    # A brighter leading edge on the pointer's left side, the way every desktop theme
    # lifts the tip off the background.
    for y in range(canvas.height):
        x = int(s * 0.02)
        if 0 <= x < canvas.width:
            rgba = canvas.get(x, y)
            if rgba[3] > 0.2:
                canvas.blend(x, y, pal["highlight"], 0.55)


def _draw_ibeam(canvas: Canvas, size: int, pal: dict) -> None:
    s = float(size)
    ink, outline = pal["ink"], pal["outline"]
    stroke = max(s * 0.09, 1.2)
    cx, cy = s / 2.0, s / 2.0
    top, bottom = s * 0.10, s * 0.90
    serif = s * 0.17

    canvas.stroke_polyline([(cx, top), (cx, bottom)], outline, stroke + max(stroke, 1.2), 1.0)
    canvas.stroke_polyline([(cx, top), (cx, bottom)], ink, stroke, 1.0)
    for y in (top, bottom):
        canvas.stroke_polyline([(cx - serif, y), (cx + serif, y)], outline,
                               stroke + max(stroke, 1.2), 1.0)
        canvas.stroke_polyline([(cx - serif, y), (cx + serif, y)], ink, stroke, 1.0)


def _draw_crosshair(canvas: Canvas, size: int, pal: dict) -> None:
    s = float(size)
    ink, outline = pal["ink"], pal["outline"]
    stroke = max(s * 0.075, 1.1)
    cx = cy = s / 2.0
    gap = s * 0.20
    arm = s * 0.42
    segments = [
        [(cx, cy - arm), (cx, cy - gap)],
        [(cx, cy + gap), (cx, cy + arm)],
        [(cx - arm, cy), (cx - gap, cy)],
        [(cx + gap, cy), (cx + arm, cy)],
    ]
    for seg in segments:
        canvas.stroke_polyline(seg, outline, stroke + max(stroke, 1.2), 1.0)
    for seg in segments:
        canvas.stroke_polyline(seg, ink, stroke, 1.0)


def _draw_ring(canvas: Canvas, size: int, pal: dict, ticks: int = 0,
               forbidden: bool = False) -> None:
    s = float(size)
    ink, outline = pal["ink"], pal["outline"]
    cx = cy = s / 2.0
    radius = s * 0.34
    width = max(s * 0.10, 1.4)

    canvas.stroke_circle(cx, cy, radius, width + max(width * 0.8, 1.2), outline, 1.0)
    canvas.stroke_circle(cx, cy, radius, width, ink, 1.0)

    if forbidden:
        d = s * 0.24
        canvas.stroke_polyline([(cx - d, cy + d), (cx + d, cy - d)], outline,
                               width + max(width * 0.8, 1.2), 1.0)
        canvas.stroke_polyline([(cx - d, cy + d), (cx + d, cy - d)], pal["danger"], width, 1.0)

    if ticks:
        for index in range(ticks):
            angle = (index / ticks) * math.tau
            x0 = cx + math.cos(angle) * radius * 0.42
            y0 = cy + math.sin(angle) * radius * 0.42
            x1 = cx + math.cos(angle) * radius * 0.80
            y1 = cy + math.sin(angle) * radius * 0.80
            canvas.stroke_polyline([(x0, y0), (x1, y1)], outline,
                                   width + max(width * 0.8, 1.2), 1.0)
            canvas.stroke_polyline([(x0, y0), (x1, y1)], ink, width * 0.8, 1.0)


def _draw_arrow_axis(canvas: Canvas, size: int, pal: dict, angle: float,
                     heads: int = 2, thin: bool = False) -> None:
    """A double- or single-headed arrow along `angle`, in radians (0 = right)."""
    s = float(size)
    ink, outline = pal["ink"], pal["outline"]
    stroke = max(s * (0.055 if thin else 0.075), 1.0)
    cx = cy = s / 2.0
    reach = s * 0.36
    head = s * (0.16 if thin else 0.20)

    dx, dy = math.cos(angle), math.sin(angle)
    nx, ny = -dy, dx

    x0, y0 = cx - dx * reach, cy - dy * reach
    x1, y1 = cx + dx * reach, cy + dy * reach

    canvas.stroke_polyline([(x0, y0), (x1, y1)], outline, stroke + max(stroke, 1.3), 1.0)
    canvas.stroke_polyline([(x0, y0), (x1, y1)], ink, stroke, 1.0)

    for tip, sign in (((x1, y1), 1.0), ((x0, y0), -1.0)):
        if (heads == 2) or (heads == 1 and sign > 0):
            base = (tip[0] - dx * head * sign, tip[1] - dy * head * sign)
            for colour, width in ((outline, stroke + max(stroke, 1.3)), (ink, stroke)):
                canvas.stroke_polyline(
                    [(base[0] + nx * head * 0.55, base[1] + ny * head * 0.55),
                     tip,
                     (base[0] - nx * head * 0.55, base[1] - ny * head * 0.55)],
                    colour, width, 1.0,
                )


def _draw_move(canvas: Canvas, size: int, pal: dict) -> None:
    """The four-way move pointer: a cross with a tail on the leading arm."""
    s = float(size)
    ink, outline = pal["ink"], pal["outline"]
    stroke = max(s * 0.075, 1.1)
    cx = cy = s / 2.0
    arm = s * 0.34
    gap = s * 0.13

    segments = [
        [(cx, cy - arm), (cx, cy - gap)],
        [(cx, cy + gap), (cx, cy + arm)],
        [(cx - arm, cy), (cx - gap, cy)],
        [(cx + gap, cy), (cx + arm, cy)],
    ]
    for seg in segments:
        canvas.stroke_polyline(seg, outline, stroke + max(stroke * 1.4, 1.2), 1.0)
    for seg in segments:
        canvas.stroke_polyline(seg, ink, stroke, 1.0)

    # The stub tail, offset up-left, which is what distinguishes move from crosshair.
    canvas.stroke_polyline([(cx - arm, cy - arm), (cx - gap, cy - gap)],
                           outline, stroke + max(stroke * 1.4, 1.2), 1.0)
    canvas.stroke_polyline([(cx - arm, cy - arm), (cx - gap, cy - gap)], ink, stroke, 1.0)


def _draw_hand(canvas: Canvas, size: int, pal: dict, closed: bool = False) -> None:
    """A pointing hand, built as a union of capsules.

    Drawing the palm and each finger as its own shape, then running an outline pass
    over the whole union before the ink pass, produces a single clean silhouette.
    A hand authored as one outline polygon loses its fingers entirely below 24px,
    which is exactly the size a pointer is actually used at.
    """
    s = float(size)
    w, h = s, s

    if closed:
        # A closed hand: the fingers stop short of the palm so the knuckles read.
        fingers = [
            (0.34, 0.30, 0.42, 0.62),
            (0.43, 0.32, 0.51, 0.64),
            (0.52, 0.34, 0.60, 0.64),
            (0.61, 0.38, 0.68, 0.64),
        ]
        palm = raster.rounded_rect_sdf(w * 0.28, h * 0.58, w * 0.72, h * 0.92, w * 0.10)
        thumb = raster.capsule_sdf(w * 0.68, h * 0.60, w * 0.40, h * 0.68, w * 0.075)
    else:
        # A pointing hand: index extended, the rest folded, thumb across the palm.
        fingers = [
            (0.40, 0.10, 0.46, 0.62),
            (0.50, 0.20, 0.56, 0.62),
            (0.59, 0.26, 0.65, 0.62),
            (0.67, 0.34, 0.73, 0.63),
        ]
        palm = raster.rounded_rect_sdf(w * 0.30, h * 0.56, w * 0.74, h * 0.92, w * 0.10)
        thumb = raster.capsule_sdf(w * 0.22, h * 0.56, w * 0.42, h * 0.70, w * 0.078)

    finger_radius = w * 0.062
    shapes = [palm, thumb] + [raster.capsule_sdf(w * a, h * b, w * c, h * d, finger_radius)
                              for a, b, c, d in fingers]

    outline_w = max(s * 0.035, 1.0)

    # The union is evaluated once per pass; the grown pass is the outline, and because
    # it is the union rather than the parts, the internal seams are filled in rather
    # than drawn as stray lines across the palm.
    grown = raster.union_sdf(
        palm, thumb,
        *[raster.capsule_sdf(w * a, h * b, w * c, h * d, finger_radius + outline_w)
          for a, b, c, d in fingers],
    )
    canvas.fill_shape_aa(grown, pal["outline"], 1.0)
    canvas.fill_shape_aa(raster.union_sdf(*shapes), pal["ink"], 1.0)

    if not closed:
        # Knuckle creases, so the folded fingers are distinguishable from the index.
        for x0, y0, x1, y1 in ((0.50, 0.30, 0.50, 0.54),
                               (0.59, 0.36, 0.59, 0.54),
                               (0.67, 0.44, 0.67, 0.55)):
            canvas.stroke_polyline([(w * x0, h * y0), (w * x1, h * y1)],
                                   pal["outline"], max(s * 0.030, 0.9), 0.7)


def _draw_magnifier(canvas: Canvas, size: int, pal: dict, plus: bool) -> None:
    s = float(size)
    ink, outline = pal["ink"], pal["outline"]
    cx, cy = s * 0.44, s * 0.42
    radius = s * 0.26
    width = max(s * 0.075, 1.1)

    canvas.stroke_polyline([(cx + radius * 0.72, cy + radius * 0.72),
                            (s * 0.86, s * 0.86)],
                           outline, width + max(width * 1.5, 1.3), 1.0)
    canvas.stroke_polyline([(cx + radius * 0.72, cy + radius * 0.72),
                            (s * 0.86, s * 0.86)], ink, width, 1.0)

    canvas.stroke_circle(cx, cy, radius, width + max(width, 1.2), outline, 1.0)
    canvas.stroke_circle(cx, cy, radius, width, ink, 1.0)

    inner = radius * 0.52
    marks = [[(cx - inner, cy), (cx + inner, cy)]]
    if plus:
        marks.append([(cx, cy - inner), (cx, cy + inner)])
    for mark in marks:
        canvas.stroke_polyline(mark, outline, width + max(width, 1.2), 1.0)
        canvas.stroke_polyline(mark, ink, width, 1.0)


def _draw_pencil(canvas: Canvas, size: int, pal: dict) -> None:
    s = float(size)
    ink, outline = pal["ink"], pal["outline"]
    width = max(s * 0.08, 1.1)
    body = [(s * 0.24, s * 0.80), (s * 0.30, s * 0.56), (s * 0.70, s * 0.16),
            (s * 0.84, s * 0.30), (s * 0.44, s * 0.70), (s * 0.24, s * 0.80)]
    canvas.stroke_polyline(body, outline, width + max(width * 1.3, 1.2), 1.0)
    canvas.stroke_polyline(body[:-1], ink, width, 1.0)
    canvas.stroke_polyline([(s * 0.30, s * 0.56), (s * 0.44, s * 0.70)],
                           outline, width + max(width * 1.3, 1.2), 1.0)
    canvas.stroke_polyline([(s * 0.30, s * 0.56), (s * 0.44, s * 0.70)], ink, width, 1.0)


def _draw_single_glyph(canvas: Canvas, size: int, pal: dict, mark: str) -> None:
    """plus / minus / question, drawn from the same crosshair skeleton."""
    s = float(size)
    ink, outline = pal["ink"], pal["outline"]
    width = max(s * 0.08, 1.2)
    cx = cy = s / 2.0
    arm = s * 0.24

    strokes: list[list[tuple[float, float]]] = []
    if mark in ("plus", "question"):
        strokes.append([(cx - arm, cy), (cx + arm, cy)])
        strokes.append([(cx, cy - arm), (cx, cy + arm)])
    elif mark == "minus":
        strokes.append([(cx - arm, cy), (cx + arm, cy)])

    if mark == "question":
        # A short tail, so the mark is distinguishable from a plain plus at 16px.
        strokes.append([(cx + arm, cy), (cx + arm, cy + arm * 0.9)])

    for stroke in strokes:
        canvas.stroke_polyline(stroke, outline, width + max(width * 1.4, 1.2), 1.0)
    for stroke in strokes:
        canvas.stroke_polyline(stroke, ink, width, 1.0)


def _draw_document(canvas: Canvas, size: int, pal: dict, arrow: bool = False,
                   link: bool = False) -> None:
    """copy / alias / link, distinguished only by the corner detail."""
    s = float(size)
    ink, outline = pal["ink"], pal["outline"]
    width = max(s * 0.065, 1.0)
    x0, y0, x1, y1 = s * 0.20, s * 0.10, s * 0.72, s * 0.84

    def rect_points(xa: float, ya: float, xb: float, yb: float):
        return [(xa, ya), (xb, ya), (xb, yb), (xa, yb), (xa, ya)]

    for colour, w in ((outline, width + max(width * 1.4, 1.2)), (ink, width)):
        canvas.stroke_polyline(rect_points(x0, y0, x1, y1), colour, w, 1.0)
        for row in (0.36, 0.54, 0.70):
            canvas.stroke_polyline([(x0 + s * 0.08, s * row), (x1 - s * 0.10, s * row)],
                                   colour, w * 0.8, 0.95)

    if arrow:
        head = s * 0.16
        canvas.stroke_polyline([(x1 - head * 0.4, s * 0.74), (s * 0.86, s * 0.86),
                                (x1 - head * 0.4, s * 0.98)], outline,
                               width + max(width * 1.4, 1.2), 1.0)
        canvas.stroke_polyline([(x1 - head * 0.4, s * 0.74), (s * 0.86, s * 0.86),
                                (x1 - head * 0.4, s * 0.98)], ink, width, 1.0)
    elif link:
        canvas.stroke_circle(s * 0.52, s * 0.52, s * 0.11, width + 1.0, outline, 1.0)
        canvas.stroke_circle(s * 0.52, s * 0.52, s * 0.11, width, ink, 1.0)


def _draw_help(canvas: Canvas, size: int, pal: dict) -> None:
    canvas.stroke_circle(size / 2.0, size / 2.0, size * 0.38,
                         max(size * 0.075, 1.1), pal["outline"], 1.0)
    canvas.stroke_circle(size / 2.0, size / 2.0, size * 0.38,
                         max(size * 0.075, 1.1), pal["ink"], 1.0)
    s = float(size)
    width = max(s * 0.07, 1.0)
    cx = s / 2.0
    for colour, w in ((pal["outline"], width + max(width * 1.4, 1.2)), (pal["ink"], width)):
        canvas.stroke_polyline(
            [(cx - s * 0.12, s * 0.40), (cx, s * 0.32), (cx + s * 0.12, s * 0.42),
             (cx, s * 0.54), (cx, s * 0.62)], colour, w, 1.0)
        canvas.stroke_circle(cx, s * 0.70, s * 0.045, w, colour, 1.0)


def _draw_context_menu(canvas: Canvas, size: int, pal: dict) -> None:
    s = float(size)
    width = max(s * 0.075, 1.1)
    panel = raster.rounded_rect_sdf(s * 0.10, s * 0.16, s * 0.62, s * 0.86, s * 0.08)
    canvas.fill_shape_aa(panel, pal["outline"], 1.0)
    inner = raster.rounded_rect_sdf(s * 0.14, s * 0.20, s * 0.58, s * 0.82, s * 0.06)
    canvas.fill_shape_aa(inner, pal["ink"], 1.0)
    for colour, w in ((pal["outline"], width + max(width, 1.2)), (pal["ink"], width)):
        for row in (0.36, 0.50, 0.64, 0.76):
            canvas.stroke_polyline([(s * 0.22, s * row), (s * 0.50, s * row)], colour, w, 1.0)
        canvas.stroke_polyline([(s * 0.66, s * 0.44), (s * 0.86, s * 0.44),
                                (s * 0.74, s * 0.62)], colour, w, 1.0)


# name -> (drawer, hotspot as a fraction of the nominal size, extra arguments)
CURSORS: dict[str, tuple] = {
    "default": (_draw_arrow, (0.10, 0.07), ()),
    "arrow": (_draw_arrow, (0.10, 0.07), ()),
    "left_ptr": (_draw_arrow, (0.10, 0.07), ()),
    "xterm": (_draw_ibeam, (0.50, 0.50), ()),
    "text": (_draw_ibeam, (0.50, 0.50), ()),
    "crosshair": (_draw_crosshair, (0.50, 0.50), ()),
    "cross": (_draw_crosshair, (0.50, 0.50), ()),
    "diamond_cross": (_draw_crosshair, (0.50, 0.50), ()),
    "move": (_draw_move, (0.50, 0.50), ()),
    "wait": (_draw_ring, (0.50, 0.50), (8,)),
    "progress": (_draw_ring, (0.50, 0.50), (4,)),
    "not-allowed": (_draw_ring, (0.50, 0.50), (0, True)),
    "forbidden": (_draw_ring, (0.50, 0.50), (0, True)),
    "no-drop": (_draw_ring, (0.50, 0.50), (0, True)),

    "ns-resize": (_draw_arrow_axis, (0.50, 0.50), (math.pi / 2, 2)),
    "n-resize": (_draw_arrow_axis, (0.50, 0.50), (-math.pi / 2, 1)),
    "s-resize": (_draw_arrow_axis, (0.50, 0.50), (math.pi / 2, 1)),
    "sb_v_double_arrow": (_draw_arrow_axis, (0.50, 0.50), (math.pi / 2, 2, True)),
    "v_double_arrow": (_draw_arrow_axis, (0.50, 0.50), (math.pi / 2, 2)),
    "ew-resize": (_draw_arrow_axis, (0.50, 0.50), (0.0, 2)),
    "e-resize": (_draw_arrow_axis, (0.50, 0.50), (0.0, 1)),
    "w-resize": (_draw_arrow_axis, (0.50, 0.50), (math.pi, 1)),
    "sb_h_double_arrow": (_draw_arrow_axis, (0.50, 0.50), (0.0, 2, True)),
    "h_double_arrow": (_draw_arrow_axis, (0.50, 0.50), (0.0, 2)),
    "nesw-resize": (_draw_arrow_axis, (0.50, 0.50), (-math.pi / 4, 2)),
    "size-bdiag": (_draw_arrow_axis, (0.50, 0.50), (-math.pi / 4, 2)),
    "nwse-resize": (_draw_arrow_axis, (0.50, 0.50), (math.pi / 4, 2)),
    "size-fdiag": (_draw_arrow_axis, (0.50, 0.50), (math.pi / 4, 2)),
    "ne-resize": (_draw_arrow_axis, (0.50, 0.50), (-math.pi / 4, 1)),
    "sw-resize": (_draw_arrow_axis, (0.50, 0.50), (-math.pi / 4, 1)),
    "se-resize": (_draw_arrow_axis, (0.50, 0.50), (math.pi / 4, 1)),
    "nw-resize": (_draw_arrow_axis, (0.50, 0.50), (math.pi / 4, 1)),
    "col-resize": (_draw_arrow_axis, (0.50, 0.50), (0.0, 2, True)),
    "row-resize": (_draw_arrow_axis, (0.50, 0.50), (math.pi / 2, 2, True)),

    "up-arrow": (_draw_arrow_axis, (0.50, 0.90), (-math.pi / 2, 1)),
    "down-arrow": (_draw_arrow_axis, (0.50, 0.10), (math.pi / 2, 1)),
    "left-arrow": (_draw_arrow_axis, (0.90, 0.50), (math.pi, 1)),
    "right-arrow": (_draw_arrow_axis, (0.10, 0.50), (0.0, 1)),
    "sb_up_arrow": (_draw_arrow_axis, (0.50, 0.92), (-math.pi / 2, 1, True)),
    "sb_down_arrow": (_draw_arrow_axis, (0.50, 0.08), (math.pi / 2, 1, True)),
    "sb_left_arrow": (_draw_arrow_axis, (0.92, 0.50), (math.pi, 1, True)),
    "sb_right_arrow": (_draw_arrow_axis, (0.08, 0.50), (0.0, 1, True)),

    "pointer": (_draw_hand, (0.50, 0.86), ()),
    "hand": (_draw_hand, (0.50, 0.86), ()),
    "hand2": (_draw_hand, (0.50, 0.86), ()),
    "grab": (_draw_hand, (0.50, 0.86), ()),
    "grabbing": (_draw_hand, (0.50, 0.86), (True,)),
    "all-scroll": (_draw_move, (0.50, 0.50), ()),

    "zoom-in": (_draw_magnifier, (0.50, 0.50), (True,)),
    "zoom-out": (_draw_magnifier, (0.50, 0.50), (False,)),
    "plus": (_draw_single_glyph, (0.50, 0.50), ("plus",)),
    "minus": (_draw_single_glyph, (0.50, 0.50), ("minus",)),
    "question-arrow": (_draw_single_glyph, (0.50, 0.50), ("question",)),

    "pencil": (_draw_pencil, (0.30, 0.84), ()),
    "copy": (_draw_document, (0.50, 0.50), (False, False)),
    "alias": (_draw_document, (0.50, 0.50), (True, False)),
    "link": (_draw_document, (0.50, 0.50), (False, True)),
    "help": (_draw_help, (0.50, 0.50), ()),
    "whatsis": (_draw_help, (0.50, 0.50), ()),
    "context-menu": (_draw_context_menu, (0.86, 0.44), ()),
}


def render_cursor_theme(out_dir: Path, brand: dict[str, str], light: bool = False
                        ) -> tuple[int, int]:
    """Write every cursor in the set, at every configured size.

    Returns (files written, total images embedded).
    """
    sizes = sorted(set(distinct_sizes(brand["CURSOR_SIZES"])))
    if not sizes:
        raise ValueError("config/branding.env declares no usable CURSOR_SIZES")

    if light:
        surface = hex_rgb(brand["COLOR_BG_LIGHT_RAISED"])
        ink = hex_rgb(brand["COLOR_TEXT_LIGHT_THEME"])
        outline = mix(ink, surface, 0.12)
        highlight = mix(ink, surface, 0.45)
        danger = hex_rgb(brand["COLOR_ACCENT_DANGER"])
    else:
        surface = hex_rgb(brand["COLOR_VOID"])
        ink = hex_rgb(brand["COLOR_TEXT"])
        outline = surface
        highlight = hex_rgb(brand["BRAND_NEON_CYAN"])
        danger = hex_rgb(brand["COLOR_HUD_RED"])

    pal = {"ink": ink, "outline": outline, "highlight": highlight, "danger": danger}

    out_dir.mkdir(parents=True, exist_ok=True)
    files = 0
    images = 0

    for name, (drawer, hotspot, args) in sorted(CURSORS.items()):
        rendered: list[tuple[int, int, int, Canvas]] = []
        for size in sizes:
            canvas = Canvas(size, size)
            drawer(canvas, size, pal, *args)
            rendered.append((size, int(round(hotspot[0] * size)),
                             int(round(hotspot[1] * size)), canvas))
        images += write_xcursor(out_dir / name, rendered)
        files += 1

    return files, images


# ---------------------------------------------------------------------------
# Cursor theme descriptor
# ---------------------------------------------------------------------------

CURSOR_THEME_NAME = "AstraOS"

CURSOR_INDEX = """\
[Icon Theme]
Name=AstraOS
Comment=AstraOS cursor theme
Inherits=
"""

CURSOR_THEME_FILE = """\
[Icon Theme]
Name=AstraOS
Comment=AstraOS pointer, generated by branding/tools/render_theme_assets.py
Inherits=
"""


def write_cursor_descriptors(icon_theme_root: Path) -> list[Path]:
    """Write the index.theme files that make the cursors loadable.

    Two files are needed and neither is obvious:

      <icon theme>/cursors/AstraOS/index.theme
          declares the cursor sub-theme that libXcursor actually reads.

      <icon theme>/cursors/index.theme
          names the sub-theme for the icon-theme lookup.

    An icon theme that carries cursors also needs `Cursor Theme=AstraOS` in its own
    top-level index.theme; that key lives in branding/icons/index.theme.
    """
    written: list[Path] = []

    sub = icon_theme_root / "cursors" / CURSOR_THEME_NAME
    sub.mkdir(parents=True, exist_ok=True)
    path = sub / "index.theme"
    path.write_text(CURSOR_THEME_FILE, encoding="utf-8")
    written.append(path)

    path = icon_theme_root / "cursors" / "index.theme"
    path.write_text(CURSOR_INDEX, encoding="utf-8")
    written.append(path)

    return written


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path,
                        default=REPO_ROOT / "branding" / "generated",
                        help="output directory (default: branding/generated)")
    parser.add_argument("--only", choices=("xfwm4", "cursors", "all"), default="all",
                        help="render only one asset group")
    args = parser.parse_args()

    brand = astraos_env.branding()
    metrics = Metrics(brand)
    out: Path = args.out.expanduser().resolve()

    written: list[Path] = []

    def record(path: Path) -> None:
        """Report a written asset, or the summary of a directory of assets."""
        try:
            shown = path.relative_to(REPO_ROOT)
        except ValueError:
            shown = path

        if path.is_dir():
            files = sorted(p for p in path.rglob("*") if p.is_file())
            total = sum(p.stat().st_size for p in files)
            print(f"  wrote {shown}  {len(files)} files  {total:>9,d} bytes total")
        else:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
            print(f"  wrote {shown}  {path.stat().st_size:>9,d} bytes  sha256:{digest}")
        written.append(path)

    print(f"AstraOS theme asset renderer -> {out}")
    print(f"  titlebar {metrics.title_height}px, button {metrics.button}px, "
          f"radius {metrics.radius}px")

    if args.only in ("all", "xfwm4"):
        for theme_name, light in (("AstraOS-Dark", False), ("AstraOS-Light", True)):
            pal = ThemePalette(brand, light=light)
            target = out / "xfwm4" / theme_name
            files = render_xfwm4_theme(target, theme_name, pal, metrics)
            print(f"rendered {len(files)} xfwm4 assets for {theme_name}")
            record(target)

    if args.only in ("all", "cursors"):
        target = out / "cursors" / CURSOR_THEME_NAME
        files, images = render_cursor_theme(target, brand, light=False)
        print(f"rendered {files} cursors, {images} images total, sizes "
              f"{' '.join(str(s) for s in sorted(set(distinct_sizes(brand['CURSOR_SIZES']))))}")
        record(target)

        light_target = out / "cursors" / (CURSOR_THEME_NAME + "-Light")
        files, images = render_cursor_theme(light_target, brand, light=True)
        print(f"rendered light cursor theme: {files} cursors")
        record(light_target)

    print(f"done: {len(written)} output path(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())