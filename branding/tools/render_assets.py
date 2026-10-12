#!/usr/bin/env python3
"""Generate the AstraOS bitmap branding assets.

Why a renderer instead of checked-in PNGs?
  * The art is derived from config/branding.env, so the palette has one source of truth.
  * The generated files are reproducible: same seed, same bytes.
  * No image library is needed, so this runs on any host with Python 3 - including this
    Windows development machine, where the rest of the build toolchain is unavailable.

Only the standard library is used. PNG encoding is implemented here (see _write_png)
rather than pulled from Pillow, because Pillow is not guaranteed to be present in the
build environment and the images are simple raster gradients.

Outputs (into branding/generated/):
  astraos-wallpaper-dark-<W>x<H>.png     desktop wallpaper, dark theme
  astraos-wallpaper-light-<W>x<H>.png    desktop wallpaper, light theme
  astraos-splash-boot-<W>x<H>.png        boot splash / GRUB background
  astraos-login-background-<W>x<H>.png   LightDM greeter background
  astraos-logo-<S>.png                   full-colour ring mark with transparency
  astraos-logo-mono-light-<S>.png        monochrome ring mark, light ink
  astraos-logo-mono-dark-<S>.png         monochrome ring mark, dark ink

Usage:
  python3 branding/tools/render_assets.py                # all assets, default size
  python3 branding/tools/render_assets.py --scale 0.5    # faster, half resolution
  python3 branding/tools/render_assets.py --only logo    # single asset group
"""

from __future__ import annotations

import argparse
import array
import hashlib
import math
import random
import struct
import sys
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

import astraos_env  # noqa: E402

GENERATED_DIR = REPO_ROOT / "branding" / "generated"


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

def hex_to_rgb(value: str) -> tuple[float, float, float]:
    """'#FF2FB9' -> (255.0, 47.0, 185.0)"""
    text = value.strip().lstrip("#")
    if len(text) != 6:
        raise ValueError(f"expected a 6-digit hex colour, got {value!r}")
    return (float(int(text[0:2], 16)), float(int(text[2:4], 16)), float(int(text[4:6], 16)))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def mix(c1: tuple[float, float, float], c2: tuple[float, float, float], t: float):
    """Linear interpolation between two colours, t clamped to [0, 1]."""
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return (lerp(c1[0], c2[0], t), lerp(c1[1], c2[1], t), lerp(c1[2], c2[2], t))


def clamp8(value: float) -> int:
    if value <= 0.0:
        return 0
    if value >= 255.0:
        return 255
    return int(value + 0.5)


def smoothstep(edge0: float, edge1: float, x: float) -> float:
    if edge1 == edge0:
        return 0.0
    t = (x - edge0) / (edge1 - edge0)
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return t * t * (3.0 - 2.0 * t)


# ---------------------------------------------------------------------------
# Minimal PNG encoder
# ---------------------------------------------------------------------------

def _write_png(path: Path, width: int, height: int, pixels: bytearray, channels: int) -> None:
    """Write an 8-bit PNG.

    pixels is a flat row-major buffer of width*height*channels bytes.
    channels is 3 (RGB) or 4 (RGBA). Filter type 0 (None) is used for every scanline;
    the images are gradients, which compress acceptably without predictive filters.
    """
    colour_type = 2 if channels == 3 else 6
    stride = width * channels

    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter: None
        start = y * stride
        raw += pixels[start:start + stride]

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    header = chunk(
        b"IHDR",
        struct.pack(">IIBBBBB", width, height, 8, colour_type, 0, 0, 0),
    )
    compressed = zlib.compress(bytes(raw), 9)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(b"\x89PNG\r\n\x1a\n")
        handle.write(header)
        handle.write(chunk(b"IDAT", compressed))
        handle.write(chunk(b"IEND", b""))


# ---------------------------------------------------------------------------
# Scene primitives
# ---------------------------------------------------------------------------

def _fill_base(
    width: int,
    height: int,
    top_colour,
    bottom_colour,
    blobs: list[tuple[float, float, float, tuple[float, float, float], float]],
) -> bytearray:
    """Fill the canvas with a vertical gradient plus additive radial "nebula" blobs.

    blobs: (cx_ratio, cy_ratio, radius_ratio, colour, strength)
    """
    buf = bytearray(width * height * 3)

    blobs_px = [
        (cx * width, cy * height, max(radius * min(width, height), 1.0), colour, strength)
        for cx, cy, radius, colour, strength in blobs
    ]

    inv_h = 1.0 / max(height - 1, 1)

    for y in range(height):
        t = y * inv_h
        # Slightly non-linear vertical gradient reads more like atmosphere than a ramp.
        tt = t * t * (3.0 - 2.0 * t)
        base_r = lerp(top_colour[0], bottom_colour[0], tt)
        base_g = lerp(top_colour[1], bottom_colour[1], tt)
        base_b = lerp(top_colour[2], bottom_colour[2], tt)

        row = y * width * 3
        for x in range(width):
            r, g, b = base_r, base_g, base_b
            for cx, cy, radius, colour, strength in blobs_px:
                dx = x - cx
                dy = y - cy
                d2 = dx * dx + dy * dy
                if d2 > radius * radius * 9.0:
                    continue
                falloff = math.exp(-d2 / (2.0 * radius * radius))
                if falloff < 0.004:
                    continue
                k = falloff * strength
                r += colour[0] * k
                g += colour[1] * k
                b += colour[2] * k

            i = row + x * 3
            buf[i] = clamp8(r)
            buf[i + 1] = clamp8(g)
            buf[i + 2] = clamp8(b)

    return buf


def _add_stars(buf: bytearray, width: int, height: int, count: int, seed: int,
               max_brightness: float = 1.0, tint=(255.0, 240.0, 255.0)) -> None:
    """Additively draw soft star sprites with a deterministic PRNG."""
    rng = random.Random(seed)
    twinkle_tint = tint

    for _ in range(count):
        cx = rng.random() * width
        cy = rng.random() * height
        # Denser and brighter toward the top of the frame.
        brightness = (1.0 - cy / height) ** 1.7 * rng.uniform(0.25, 1.0) * max_brightness
        if brightness < 0.02:
            continue
        radius = rng.choice((0.8, 1.0, 1.2, 1.6, 2.2, 3.0))
        colour = mix(twinkle_tint, (150.0, 200.0, 255.0), rng.random() * 0.5)

        x0 = max(int(cx - radius * 2), 0)
        x1 = min(int(cx + radius * 2) + 1, width)
        y0 = max(int(cy - radius * 2), 0)
        y1 = min(int(cy + radius * 2) + 1, height)

        for y in range(y0, y1):
            row = y * width * 3
            for x in range(x0, x1):
                dx = x - cx
                dy = y - cy
                d2 = dx * dx + dy * dy
                falloff = math.exp(-d2 / (2.0 * radius * radius))
                if falloff < 0.01:
                    continue
                k = falloff * brightness
                i = row + x * 3
                buf[i] = clamp8(buf[i] + colour[0] * k)
                buf[i + 1] = clamp8(buf[i + 1] + colour[1] * k)
                buf[i + 2] = clamp8(buf[i + 2] + colour[2] * k)


def _ring_colour(angle: float, c1, c2, c3):
    """Angular gradient around the ring: c1 -> c2 -> c3 -> back to c1."""
    tau = math.tau
    t = (angle % tau) / tau
    if t < 1 / 3:
        return mix(c1, c2, t * 3.0)
    if t < 2 / 3:
        return mix(c2, c3, (t - 1 / 3) * 3.0)
    return mix(c3, c1, (t - 2 / 3) * 3.0)


def _draw_ring(
    buf: bytearray,
    width: int,
    height: int,
    cx: float,
    cy: float,
    radius: float,
    stroke: float,
    c1,
    c2,
    c3,
    glow_strength: float = 1.0,
    inner_veil: float = 0.0,
) -> None:
    """Draw the AstraOS neon ring: a bright core stroke with an additive bloom.

    The core is a signed-distance band around `radius`; the glow is a wider gaussian on
    the same distance field, which is what produces the soft neon halo in the reference
    screenshots without needing a blur pass.
    """
    sigma_core = max(stroke * 0.42, 0.7)
    sigma_glow = max(stroke * 7.0, 6.0)

    x0 = max(int(cx - radius - sigma_glow * 3), 0)
    x1 = min(int(cx + radius + sigma_glow * 3) + 1, width)
    y0 = max(int(cy - radius - sigma_glow * 3), 0)
    y1 = min(int(cy + radius + sigma_glow * 3) + 1, height)

    for y in range(y0, y1):
        row = y * width * 3
        dy = y - cy
        for x in range(x0, x1):
            dx = x - cx
            dist = math.sqrt(dx * dx + dy * dy)
            d = dist - radius
            ad = abs(d)

            core = math.exp(-(ad * ad) / (2.0 * sigma_core * sigma_core))
            glow = math.exp(-(d * d) / (2.0 * sigma_glow * sigma_glow)) * 0.55 * glow_strength

            veil = 0.0
            if inner_veil > 0.0 and dist < radius:
                veil = inner_veil * (1.0 - dist / radius)

            if core < 0.004 and glow < 0.004 and veil < 0.004:
                continue

            colour = _ring_colour(math.atan2(dy, dx), c1, c2, c3)
            i = row + x * 3
            for channel in range(3):
                value = buf[i + channel]
                value += colour[channel] * (core + glow)
                if veil > 0.0:
                    value += colour[channel] * veil * 0.30
                buf[i + channel] = clamp8(value)


def _draw_horizon_grid(buf: bytearray, width: int, height: int, horizon: float,
                       colour, strength: float = 0.5) -> None:
    """Synthwave perspective grid below the horizon line, as in reference screen 1.

    Lines converge toward a vanishing point at the centre of the horizon.
    """
    vanishing_x = width / 2.0
    grid_depth = height - horizon
    if grid_depth <= 2:
        return

    # Horizontal lines: spacing grows with distance from the horizon (perspective).
    steps = 22
    for index in range(1, steps + 1):
        t = index / steps
        y = horizon + grid_depth * (t ** 2.6)
        iy = int(y)
        if not (0 <= iy < height):
            continue
        alpha = strength * math.exp(-2.6 * t) * smoothstep(0.0, 0.14, t)
        if alpha < 0.01:
            continue
        row = iy * width * 3
        for x in range(width):
            i = row + x * 3
            for channel in range(3):
                buf[i + channel] = clamp8(buf[i + channel] + colour[channel] * alpha)

    # Radial lines: straight rays from the vanishing point.
    rays = 34
    for index in range(-rays, rays + 1):
        if index == 0:
            continue
        slope = index / rays
        for y in range(int(horizon), height):
            t = (y - horizon) / grid_depth
            x = vanishing_x + slope * (width * 1.7) * t
            ix = int(x)
            if not (0 <= ix < width):
                continue
            alpha = strength * math.exp(-2.2 * t) * smoothstep(0.0, 0.12, t)
            if alpha < 0.01:
                continue
            i = y * width * 3 + ix * 3
            for channel in range(3):
                buf[i + channel] = clamp8(buf[i + channel] + colour[channel] * alpha)


def _apply_vignette(buf: bytearray, width: int, height: int, strength: float = 0.45) -> None:
    """Darken the frame edges. Applied in place to an RGB buffer."""
    cx = width / 2.0
    cy = height / 2.0
    max_d = math.sqrt(cx * cx + cy * cy)

    for y in range(height):
        row = y * width * 3
        dy = y - cy
        for x in range(width):
            dx = x - cx
            d = math.sqrt(dx * dx + dy * dy) / max_d
            factor = 1.0 - strength * (d ** 2.4)
            if factor >= 0.999:
                continue
            i = row + x * 3
            buf[i] = clamp8(buf[i] * factor)
            buf[i + 1] = clamp8(buf[i + 1] * factor)
            buf[i + 2] = clamp8(buf[i + 2] * factor)


# ---------------------------------------------------------------------------
# Palettes derived from config/branding.env
# ---------------------------------------------------------------------------

class Palette:
    def __init__(self) -> None:
        brand = astraos_env.branding()
        self.void = hex_to_rgb(brand["BRAND_VOID"])
        self.void2 = hex_to_rgb(brand["BRAND_VOID_2"])
        self.magenta = hex_to_rgb(brand["BRAND_NEON_MAGENTA"])
        self.pink = hex_to_rgb(brand["BRAND_NEON_PINK"])
        self.purple = hex_to_rgb(brand["BRAND_NEON_PURPLE"])
        self.cyan = hex_to_rgb(brand["BRAND_NEON_CYAN"])
        self.desk_dark = hex_to_rgb(brand["COLOR_BG_DARK"])
        self.desk_mid = hex_to_rgb(brand["COLOR_BG_MID"])
        self.desk_accent = hex_to_rgb(brand["COLOR_ACCENT_PRIMARY"])
        self.light_bg = hex_to_rgb(brand["COLOR_BG_LIGHT"])
        self.light_accent = hex_to_rgb(brand["COLOR_ACCENT_LIGHT"])
        self.text_light = hex_to_rgb(brand["COLOR_TEXT_LIGHT_THEME"])


# ---------------------------------------------------------------------------
# Asset renderers
# ---------------------------------------------------------------------------

def render_wallpaper_dark(path: Path, width: int, height: int, pal: Palette) -> None:
    """Dark desktop wallpaper: nebula over a void, starfield, faint horizon grid."""
    buf = _fill_base(
        width,
        height,
        top_colour=mix(pal.void, pal.purple, 0.30),
        bottom_colour=pal.void,
        blobs=[
            (0.22, 0.20, 0.20, pal.magenta, 1.15),
            (0.55, 0.30, 0.26, pal.purple, 1.35),
            (0.82, 0.62, 0.22, pal.cyan, 0.80),
            (0.40, 0.78, 0.30, mix(pal.purple, pal.void, 0.35), 0.75),
        ],
    )
    _add_stars(buf, width, height, count=int(width * height / 520), seed=20261012)
    _draw_horizon_grid(buf, width, height, horizon=height * 0.80,
                       colour=mix(pal.cyan, pal.pink, 0.45), strength=0.42)
    _apply_vignette(buf, width, height, strength=0.42)
    _write_png(path, width, height, buf, 3)


def render_wallpaper_light(path: Path, width: int, height: int, pal: Palette) -> None:
    """Light desktop wallpaper.

    Not a simple inversion: the light theme keeps the neon identity as a soft
    magenta/violet wash over a bright base, so it still reads as AstraOS while staying
    comfortable in a bright room. Strengths are low so window chrome and text keep
    their contrast.
    """
    base = mix(pal.light_bg, (255.0, 255.0, 255.0), 0.35)
    buf = _fill_base(
        width,
        height,
        top_colour=mix(base, pal.pink, 0.16),
        bottom_colour=mix(base, pal.light_accent, 0.20),
        blobs=[
            (0.24, 0.20, 0.28, pal.pink, 0.26),
            (0.60, 0.30, 0.30, pal.purple, 0.20),
            (0.84, 0.68, 0.26, pal.cyan, 0.16),
            (0.45, 0.85, 0.30, pal.magenta, 0.10),
        ],
    )

    # A gentle vertical darkening stops the image reading as a flat white field.
    for y in range(height):
        t = y / max(height - 1, 1)
        factor = 1.0 - 0.09 * (t ** 1.8)
        row = y * width * 3
        for x in range(width):
            i = row + x * 3
            buf[i] = clamp8(buf[i] * factor)
            buf[i + 1] = clamp8(buf[i + 1] * factor)
            buf[i + 2] = clamp8(buf[i + 2] * factor)

    # Faint ring watermark, bottom left: the mark without shouting.
    _draw_ring(
        buf, width, height,
        cx=width * 0.16, cy=height * 0.82,
        radius=min(width, height) * 0.30,
        stroke=max(min(width, height) * 0.0022, 0.8),
        c1=pal.pink, c2=pal.purple, c3=pal.cyan,
        glow_strength=0.10,
        inner_veil=0.0,
    )

    _apply_vignette(buf, width, height, strength=0.10)
    _write_png(path, width, height, buf, 3)


def render_boot_splash(path: Path, width: int, height: int, pal: Palette) -> None:
    """Boot splash: the AstraOS ring centred on the void, with a horizon grid.

    Matches reference screen 1: the ring is the hero, the grid sits low and faint, and
    the composition is symmetric so it looks correct behind a progress indicator.
    """
    buf = _fill_base(
        width,
        height,
        top_colour=mix(pal.void, pal.purple, 0.16),
        bottom_colour=pal.void,
        blobs=[
            (0.50, 0.46, 0.34, pal.purple, 0.85),
            (0.50, 0.50, 0.18, pal.magenta, 0.45),
            (0.16, 0.16, 0.20, pal.cyan, 0.35),
            (0.86, 0.20, 0.18, pal.pink, 0.30),
        ],
    )
    _add_stars(buf, width, height, count=int(width * height / 900), seed=4711,
               max_brightness=0.75)
    _draw_horizon_grid(buf, width, height, horizon=height * 0.84,
                       colour=mix(pal.cyan, pal.pink, 0.5), strength=0.30)

    radius = min(width, height) * 0.255
    _draw_ring(
        buf, width, height,
        cx=width / 2.0, cy=height * 0.485,
        radius=radius,
        stroke=max(min(width, height) * 0.0055, 1.6),
        c1=pal.pink, c2=pal.purple, c3=pal.cyan,
        glow_strength=1.25,
        inner_veil=1.0,
    )
    _apply_vignette(buf, width, height, strength=0.55)
    _write_png(path, width, height, buf, 3)


def render_login_background(path: Path, width: int, height: int, pal: Palette) -> None:
    """LightDM greeter background: ring offset left, dark enough for a login panel."""
    buf = _fill_base(
        width,
        height,
        top_colour=mix(pal.void, pal.purple, 0.24),
        bottom_colour=pal.void,
        blobs=[
            (0.30, 0.42, 0.30, pal.purple, 1.05),
            (0.24, 0.46, 0.20, pal.magenta, 0.70),
            (0.80, 0.28, 0.22, pal.cyan, 0.55),
        ],
    )
    _add_stars(buf, width, height, count=int(width * height / 700), seed=91210,
               max_brightness=0.85)
    _draw_ring(
        buf, width, height,
        cx=width * 0.28, cy=height * 0.50,
        radius=min(width, height) * 0.20,
        stroke=max(min(width, height) * 0.0045, 1.4),
        c1=pal.pink, c2=pal.purple, c3=pal.cyan,
        glow_strength=1.0,
        inner_veil=0.8,
    )
    # Keep the right-hand third darker so greeter text stays readable (plan §7.3).
    for y in range(height):
        row = y * width * 3
        for x in range(int(width * 0.62), width):
            t = (x - width * 0.62) / max(width * 0.38, 1.0)
            factor = 1.0 - 0.42 * t
            i = row + x * 3
            buf[i] = clamp8(buf[i] * factor)
            buf[i + 1] = clamp8(buf[i + 1] * factor)
            buf[i + 2] = clamp8(buf[i + 2] * factor)
    _apply_vignette(buf, width, height, strength=0.50)
    _write_png(path, width, height, buf, 3)


def render_logo_ring(path: Path, size: int, pal: Palette, mono: str | None = None) -> None:
    """The AstraOS ring mark on a transparent background.

    mono: None for the full neon mark, "light" or "dark" for the simplified
    single-colour variant used where gradients are not supported (plan §9).
    """
    width = height = size
    buf = bytearray(width * height * 4)  # RGBA, fully transparent

    if mono == "light":
        c1 = c2 = c3 = (255.0, 255.0, 255.0)
        glow_strength = 0.35
    elif mono == "dark":
        c1 = c2 = c3 = (18.0, 20.0, 26.0)
        glow_strength = 0.30
    else:
        c1, c2, c3 = pal.pink, pal.purple, pal.cyan
        glow_strength = 1.15

    radius = size * 0.36
    stroke = max(size * 0.022, 1.2)
    cx = cy = size / 2.0

    # Draw the RGB part into a temporary buffer, then convert to RGBA with the ring's
    # own intensity used as the alpha channel so the mark composites cleanly.
    rgb = bytearray(width * height * 3)
    _draw_ring(rgb, width, height, cx, cy, radius, stroke, c1, c2, c3,
               glow_strength=glow_strength, inner_veil=0.0)

    # A clean geometric ring outline so the mark is crisp at small sizes.
    outline = max(size * 0.016, 1.0)
    for y in range(height):
        for x in range(width):
            dx = x + 0.5 - cx
            dy = y + 0.5 - cy
            dist = math.sqrt(dx * dx + dy * dy)
            d = abs(dist - radius)
            coverage = 1.0 - smoothstep(stroke * 0.5, stroke * 0.5 + outline, d)
            if coverage <= 0.0:
                continue
            colour = _ring_colour(math.atan2(dy, dx), c1, c2, c3)
            i3 = (y * width + x) * 3
            i4 = (y * width + x) * 4
            alpha = clamp8(coverage * 255.0)
            if alpha > buf[i4 + 3]:
                buf[i4 + 3] = alpha
            for channel in range(3):
                blended = rgb[i3 + channel] * coverage + colour[channel] * coverage * 0.35
                buf[i4 + channel] = clamp8(blended)

    _write_png(path, width, height, buf, 4)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scale", type=float, default=1.0,
                        help="multiply the configured wallpaper size (default: 1.0)")
    parser.add_argument("--out", type=Path, default=GENERATED_DIR,
                        help="output directory (default: branding/generated)")
    parser.add_argument("--only", choices=("wallpapers", "splash", "logo", "all"),
                        default="all", help="render only one asset group")
    args = parser.parse_args()

    brand = astraos_env.branding()
    pal = Palette()
    out: Path = args.out.expanduser().resolve()

    base_w = int(int(brand["BRAND_WALLPAPER_WIDTH"]) * args.scale)
    base_h = int(int(brand["BRAND_WALLPAPER_HEIGHT"]) * args.scale)
    logo_size = int(int(brand["BRAND_LOGO_SIZE"]) * args.scale) or int(brand["BRAND_LOGO_SIZE"])

    written: list[Path] = []

    def record(path: Path) -> None:
        size = path.stat().st_size
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        try:
            shown = path.relative_to(REPO_ROOT)
        except ValueError:
            shown = path  # an explicit --out outside the repository
        print(f"  wrote {shown}  {size:>9,d} bytes  sha256:{digest}")
        written.append(path)

    print(f"AstraOS asset renderer -> {out}")
    print(f"  size {base_w}x{base_h}, scale {args.scale}")

    if args.only in ("all", "wallpapers"):
        print("rendering wallpapers")
        path = out / f"astraos-wallpaper-dark-{base_w}x{base_h}.png"
        render_wallpaper_dark(path, base_w, base_h, pal)
        record(path)

        path = out / f"astraos-wallpaper-light-{base_w}x{base_h}.png"
        render_wallpaper_light(path, base_w, base_h, pal)
        record(path)

    if args.only in ("all", "splash"):
        print("rendering boot splash and greeter background")
        path = out / f"astraos-splash-boot-{base_w}x{base_h}.png"
        render_boot_splash(path, base_w, base_h, pal)
        record(path)

        path = out / f"astraos-login-background-{base_w}x{base_h}.png"
        render_login_background(path, base_w, base_h, pal)
        record(path)

    if args.only in ("all", "logo"):
        print("rendering ring marks")
        path = out / f"astraos-logo-{logo_size}.png"
        render_logo_ring(path, logo_size, pal)
        record(path)

        path = out / f"astraos-logo-mono-light-{logo_size}.png"
        render_logo_ring(path, logo_size, pal, mono="light")
        record(path)

        path = out / f"astraos-logo-mono-dark-{logo_size}.png"
        render_logo_ring(path, logo_size, pal, mono="dark")
        record(path)

    print(f"done: {len(written)} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
