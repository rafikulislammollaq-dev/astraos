"""Shared raster primitives for the AstraOS asset generators.

Why this file exists
--------------------
`render_assets.py` writes the large scene art (wallpapers, splash, logos) and already
contains a colour space, a PNG encoder and some anti-aliased primitives. It renders
opaque RGB scenes and nothing else.

The window-decoration and cursor assets need things that file deliberately does not
have: an alpha channel with correct source-over compositing, geometry-aware shape
filling, and a binary writer for the Xcursor container format. Rather than bolt an
unrelated second half onto a scene renderer, the alpha-aware primitives live here and
the two generators share them.

Only the standard library is used, for the same reason as `render_assets.py`: the
development host is Windows and has no imaging library, and the build container must
not need one either.

Alpha convention
----------------
`Canvas` stores **straight (non-premultiplied) RGBA**, which is what PNG colour type 6
expects. The Xcursor container wants **premultiplied ARGB**, so `write_xcursor()`
converts on the way out. Mixing the two up produces cursors with dark fringes on
transparent edges, which is the single most common way a generated cursor theme looks
wrong.
"""

from __future__ import annotations

import math
import struct
from pathlib import Path
from typing import Iterable, Sequence

# Re-use the PNG encoder that the scene renderer already ships rather than writing a
# second, subtly different one. It is the same package and the same file format.
from render_assets import clamp8, hex_to_rgb, lerp, mix, smoothstep  # noqa: F401

RGB = tuple[float, float, float]
Point = tuple[float, float]


class Canvas:
    """A straight-alpha RGBA image buffer with source-over compositing.

    Coordinates are continuous: (0.0, 0.0) is the centre of the top-left pixel and
    (width, height) is the centre of the bottom-right pixel, so a shape drawn at
    x = 3.5 lands exactly on the boundary between two pixels rather than straddling
    them. That convention is what makes the anti-aliasing below behave.
    """

    def __init__(self, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            raise ValueError(f"canvas must have a positive size, got {width}x{height}")
        self.width = width
        self.height = height
        self.px = bytearray(width * height * 4)

    # -- pixel access --------------------------------------------------------

    def get(self, x: int, y: int) -> tuple[float, float, float, float]:
        i = (y * self.width + x) * 4
        return (float(self.px[i]), float(self.px[i + 1]),
                float(self.px[i + 2]), self.px[i + 3] / 255.0)

    def blend(self, x: int, y: int, colour: RGB, alpha: float) -> None:
        """Composite `colour` over the pixel at (x, y) with coverage `alpha`."""
        if not (0 <= x < self.width and 0 <= y < self.height):
            return
        if alpha <= 0.0:
            return
        if alpha > 1.0:
            alpha = 1.0

        i = (y * self.width + x) * 4
        dst_a = self.px[i + 3] / 255.0
        out_a = alpha + dst_a * (1.0 - alpha)
        if out_a <= 0.0:
            return

        for channel in range(3):
            dst_c = self.px[i + channel]
            src_c = colour[channel]
            # Source-over, un-premultiplied: divide the accumulated colour back out.
            self.px[i + channel] = clamp8(
                (src_c * alpha + dst_c * dst_a * (1.0 - alpha)) / out_a
            )
        self.px[i + 3] = clamp8(out_a * 255.0)

    # -- shape filling -------------------------------------------------------

    def fill_shape(self, inside, colour: RGB, alpha: float = 1.0,
                   bounds: tuple[float, float, float, float] | None = None) -> None:
        """Fill every pixel whose centre `inside(px, py)` reports True.

        `inside` is evaluated on a half-pixel grid (centres of pixels), so a caller
        writing an exact geometric predicate gets hard pixel-aligned edges; callers
        wanting smooth edges use `fill_shape_aa` instead.
        """
        x0, y0, x1, y1 = bounds or (0.0, 0.0, float(self.width), float(self.height))
        for y in range(max(int(math.floor(y0)), 0), min(int(math.ceil(y1)), self.height)):
            py = y + 0.5
            for x in range(max(int(math.floor(x0)), 0), min(int(math.ceil(x1)), self.width)):
                px = x + 0.5
                if inside(px, py):
                    self.blend(x, y, colour, alpha)

    def fill_shape_aa(self, sdf, colour: RGB, alpha: float = 1.0, feather: float = 0.5,
                      bounds: tuple[float, float, float, float] | None = None) -> None:
        """Fill using a signed-distance function, anti-aliasing the boundary.

        `sdf(px, py)` returns the signed distance to the shape's outline: negative
        inside, positive outside. `feather` is the half-width of the transition band,
        in pixels.
        """
        if feather <= 0.0:
            feather = 0.5
        x0, y0, x1, y1 = bounds or (0.0, 0.0, float(self.width), float(self.height))
        pad = feather + 1.0
        for y in range(max(int(math.floor(y0 - pad)), 0),
                       min(int(math.ceil(y1 + pad)), self.height)):
            py = y + 0.5
            for x in range(max(int(math.floor(x0 - pad)), 0),
                           min(int(math.ceil(x1 + pad)), self.width)):
                px = x + 0.5
                d = sdf(px, py)
                if d > feather:
                    continue
                coverage = 1.0 - smoothstep(-feather, feather, d)
                if coverage > 0.0:
                    self.blend(x, y, colour, alpha * coverage)

    def stroke_polyline(self, points: Sequence[Point], colour: RGB, width: float,
                        alpha: float = 1.0, caps: bool = True) -> None:
        """Draw an anti-aliased polyline of the given stroke width."""
        half = max(width, 0.1) / 2.0

        def sdf(px: float, py: float) -> float:
            return segment_distance(px, py, points) - half

        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        bounds = (min(xs) - half - 1.0, min(ys) - half - 1.0,
                  max(xs) + half + 1.0, max(ys) + half + 1.0)
        self.fill_shape_aa(sdf, colour, alpha, feather=0.5, bounds=bounds)

    def fill_polygon(self, points: Sequence[Point], colour: RGB, alpha: float = 1.0) -> None:
        """Fill a closed polygon described by its vertices, without anti-aliasing.

        Winding is resolved with the even-odd rule so the caller does not have to care
        about vertex order.
        """
        if len(points) < 3:
            return

        def inside(px: float, py: float) -> bool:
            crossings = False
            n = len(points)
            for i in range(n):
                x1, y1 = points[i]
                x2, y2 = points[(i + 1) % n]
                if (y1 > py) != (y2 > py):
                    x_cross = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
                    if px < x_cross:
                        crossings = not crossings
            return crossings

        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        self.fill_shape(inside, colour, alpha,
                        bounds=(min(xs), min(ys), max(xs), max(ys)))

    def fill_circle(self, cx: float, cy: float, radius: float, colour: RGB,
                    alpha: float = 1.0) -> None:
        self.fill_shape_aa(
            lambda px, py: math.hypot(px - cx, py - cy) - radius,
            colour, alpha,
            bounds=(cx - radius - 1.0, cy - radius - 1.0,
                    cx + radius + 1.0, cy + radius + 1.0),
        )

    def stroke_circle(self, cx: float, cy: float, radius: float, width: float,
                      colour: RGB, alpha: float = 1.0) -> None:
        half = max(width, 0.1) / 2.0
        self.fill_shape_aa(
            lambda px, py: abs(math.hypot(px - cx, py - cy) - radius) - half,
            colour, alpha,
            bounds=(cx - radius - half - 1.0, cy - radius - half - 1.0,
                    cx + radius + half + 1.0, cy + radius + half + 1.0),
        )

    def ring_masked(self, outer_radius: float, inner_radius: float) -> None:
        """Erase a transparent annulus, used to punch arrow holes out of a cursor."""
        self.fill_shape_aa(
            lambda px, py: max(
                inner_radius - math.hypot(px, py),
                math.hypot(px, py) - outer_radius,
            ),
            (0.0, 0.0, 0.0), 0.0, feather=0.5,
        )

    def to_premultiplied_argb(self) -> bytes:
        """Return the buffer as little-endian premultiplied ARGB32, for Xcursor."""
        out = bytearray(len(self.px))
        for i in range(0, len(self.px), 4):
            a = self.px[i + 3]
            if a == 0:
                continue  # already zero
            out[i + 0] = (self.px[i + 2] * a + 127) // 255  # B
            out[i + 1] = (self.px[i + 1] * a + 127) // 255  # G
            out[i + 2] = (self.px[i + 0] * a + 127) // 255  # R
            out[i + 3] = a
        return bytes(out)

    def write_png(self, path: Path) -> None:
        from render_assets import _write_png

        _write_png(path, self.width, self.height, self.px, 4)


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def segment_distance(px: float, py: float, points: Sequence[Point]) -> float:
    """Shortest distance from (px, py) to a polyline.

    `caps=True` at the call sites means the endpoints count as part of the stroke;
    a polyline is drawn as a chain of capsules, which is what a caller's list of
    points means in practice.
    """
    best = float("inf")
    for index in range(len(points) - 1):
        ax, ay = points[index]
        bx, by = points[index + 1]
        dx, dy = bx - ax, by - ay
        length_sq = dx * dx + dy * dy
        if length_sq <= 1e-12:
            d = math.hypot(px - ax, py - ay)
        else:
            t = ((px - ax) * dx + (py - ay) * dy) / length_sq
            t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
            d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
        if d < best:
            best = d
    return best


def polygon_sdf(points: Sequence[Point], scale: float) -> "callable":
    """Build a signed-distance function for a polygon.

    The polygon is supplied in a unit box (0..1 on both axes) and scaled by `scale`,
    so one description can be rasterised at every cursor size without re-authoring it.
    The returned distance is approximate outside the shape near edges, which is
    invisible: it is only ever used for a 1px anti-aliasing band.
    """
    pts = [(x * scale, y * scale) for x, y in points]

    def sdf(px: float, py: float) -> float:
        return segment_distance(px, py, pts + [pts[0]])

    return sdf


def capsule_sdf(ax: float, ay: float, bx: float, by: float, radius: float) -> "callable":
    """Signed distance to a round-capped line segment.

    Fingers, ropes and rounded strokes are all capsules. Drawing a hand as a union of
    capsules instead of one hand-authored outline polygon is what keeps the shape
    readable at 16px: a single polygon with fourteen control points collapses into a
    blob when it is rasterised that small, whereas four capsules stay four fingers.
    """
    def sdf(px: float, py: float) -> float:
        return segment_distance(px, py, [(ax, ay), (bx, by)]) - radius

    return sdf


def union_sdf(*shapes: "callable") -> "callable":
    """Signed distance to the union of several shapes.

    The minimum of the individual distances is exact outside every shape and only
    slightly wrong along a seam, which is invisible inside a one-pixel anti-aliasing
    band and is what lets a hand be drawn from overlapping parts.
    """
    def sdf(px: float, py: float) -> float:
        return min(shape(px, py) for shape in shapes)

    return sdf


def rounded_rect_sdf(x0: float, y0: float, x1: float, y1: float, radius: float
                     ) -> "callable":
    """Signed distance to a rounded rectangle, for anti-aliased panels and buttons."""
    radius = max(0.0, min(radius, (x1 - x0) / 2.0, (y1 - y0) / 2.0))
    cx = (x0 + x1) / 2.0
    cy = (y0 + y1) / 2.0
    half_w = (x1 - x0) / 2.0 - radius
    half_h = (y1 - y0) / 2.0 - radius

    def sdf(px: float, py: float) -> float:
        dx = abs(px - cx) - half_w
        dy = abs(py - cy) - half_h
        outside = math.hypot(max(dx, 0.0), max(dy, 0.0))
        inside = min(max(dx, dy), 0.0)
        return outside + inside - radius

    return sdf


def vertical_gradient(canvas: Canvas, y0: float, y1: float, top: RGB, bottom: RGB,
                      x0: float | None = None, x1: float | None = None) -> None:
    """Paint a vertical gradient into a canvas region, opaque."""
    x_start = 0 if x0 is None else int(math.floor(x0))
    x_end = canvas.width if x1 is None else int(math.ceil(x1))
    span = max(y1 - y0, 1e-6)
    for y in range(max(int(math.floor(y0)), 0), min(int(math.ceil(y1)), canvas.height)):
        t = (y + 0.5 - y0) / span
        t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
        colour = mix(top, bottom, t)
        for x in range(max(x_start, 0), min(x_end, canvas.width)):
            canvas.blend(x, y, colour, 1.0)


def radial_glow(canvas: Canvas, cx: float, cy: float, radius: float, colour: RGB,
                strength: float, centre: float = 0.0) -> None:
    """Additive radial bloom, the effect that makes the neon read as neon.

    `centre` shifts how concentrated the bloom is: 0 is a broad falloff, larger
    values tighten it towards a hard dot.
    """
    x0 = max(int(cx - radius), 0)
    x1 = min(int(cx + radius) + 1, canvas.width)
    y0 = max(int(cy - radius), 0)
    y1 = min(int(cy + radius) + 1, canvas.height)
    sigma = max(radius / 3.0, 0.5)

    for y in range(y0, y1):
        for x in range(x0, x1):
            d = math.hypot(x + 0.5 - cx, y + 0.5 - cy)
            if d > radius:
                continue
            falloff = math.exp(-(d * d) / (2.0 * sigma * sigma))
            if centre > 0.0:
                falloff *= max(0.0, 1.0 - d / radius) ** centre
            k = falloff * strength
            i = (y * canvas.width + x) * 4
            for channel in range(3):
                canvas.px[i + channel] = clamp8(canvas.px[i + channel] + colour[channel] * k)
            if canvas.px[i + 3] < clamp8(k * 255.0):
                canvas.px[i + 3] = clamp8(canvas.px[i + 3] + k * 255.0)


# ---------------------------------------------------------------------------
# Xcursor container writer
# ---------------------------------------------------------------------------

XCURSOR_FILE_HEADER_SIZE = 16
XCURSOR_IMAGE_HEADER_SIZE = 36
XCURSOR_IMAGE_TYPE = 0xFFFD0002
XCURSOR_FILE_VERSION = 0x00010000
XCURSOR_IMAGE_VERSION = 1


def write_xcursor(path: Path, images: Sequence[tuple[int, int, int, Canvas]]) -> int:
    """Write an .xcursor container.

    `images` is a sequence of (nominal_size, hotspot_x, hotspot_y, canvas). Images are
    stored smallest first, which is what libXcursor expects when it picks the best
    match for a requested size.

    Returns the number of images written, so the caller can fail loudly rather than
    shipping a theme with no cursor in it.
    """
    if not images:
        raise ValueError(f"refusing to write an empty cursor theme: {path}")

    ordered = sorted(images, key=lambda item: item[0])

    table_size = XCURSOR_FILE_HEADER_SIZE + 12 * len(ordered)
    chunks: list[bytes] = []
    position = table_size

    for nominal, hot_x, hot_y, canvas in ordered:
        pixels = canvas.to_premultiplied_argb()
        header = struct.pack(
            "<IIIIIIIII",
            XCURSOR_IMAGE_HEADER_SIZE,
            XCURSOR_IMAGE_TYPE,
            nominal,
            XCURSOR_IMAGE_VERSION,
            canvas.width,
            canvas.height,
            max(0, min(hot_x, canvas.width - 1)),
            max(0, min(hot_y, canvas.height - 1)),
            0,  # delay: every AstraOS cursor is a static image, never animated
        )
        chunks.append(header + pixels)
        position += len(header) + len(pixels)

    out = bytearray()
    out += struct.pack("<4sIII", b"Xcur", XCURSOR_FILE_HEADER_SIZE,
                       XCURSOR_FILE_VERSION, len(ordered))

    cursor = table_size
    for chunk in chunks:
        nominal = struct.unpack_from("<I", chunk, 8)[0]
        out += struct.pack("<III", XCURSOR_IMAGE_TYPE, nominal, cursor)
        cursor += len(chunk)

    for chunk in chunks:
        out += chunk

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out))
    return len(ordered)


def read_xcursor(path: Path) -> list[tuple[int, int, int, int]]:
    """Parse an .xcursor back, for verification.

    Returns [(subtype, width, height, hot_x), ...]. This exists so the test suite can
    check that a generated cursor really is a well-formed container, rather than
    trusting that the writer is right.
    """
    data = path.read_bytes()
    if data[:4] != b"Xcur":
        raise ValueError(f"{path.name}: not an Xcursor file")
    header_size, version, toc_count = struct.unpack_from("<III", data, 4)
    if header_size != XCURSOR_FILE_HEADER_SIZE:
        raise ValueError(f"{path.name}: unexpected header size {header_size}")
    if version != XCURSOR_FILE_VERSION:
        raise ValueError(f"{path.name}: unexpected version {version:#010x}")

    found: list[tuple[int, int, int, int]] = []
    for index in range(toc_count):
        entry = XCURSOR_FILE_HEADER_SIZE + 12 * index
        chunk_type, subtype, position = struct.unpack_from("<III", data, entry)
        if chunk_type != XCURSOR_IMAGE_TYPE:
            continue
        end = position + XCURSOR_IMAGE_HEADER_SIZE
        (_size, _type, _sub, _ver, width, height, hot_x, _hot_y, _delay) = struct.unpack(
            "<IIIIIIIII", data[position:end]
        )
        found.append((subtype, width, height, hot_x))

    return found


def hex_rgb(value: str) -> RGB:
    """Public wrapper so callers do not reach into the scene renderer for a colour."""
    text = value.strip()
    # branding.env values are already bare #RRGGBB; tolerate quotes defensively.
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1]
    return hex_to_rgb(text)


def to_hex(colour: RGB) -> str:
    """'#rrggbb' from a float triple, for files that need a literal colour."""
    return "#{:02X}{:02X}{:02X}".format(*(clamp8(c) for c in colour))


def lerp_colour(a: RGB, b: RGB, t: float) -> RGB:
    return mix(a, b, t)


def distinct_sizes(spec: str) -> Iterable[int]:
    for token in spec.split():
        if token.isdigit():
            value = int(token)
            if value > 0:
                yield value