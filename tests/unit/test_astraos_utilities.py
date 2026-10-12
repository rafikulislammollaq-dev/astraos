"""Unit tests for the project's own Python.

The asset renderer and the configuration parser are the two pieces of Python that do real
work. Both are otherwise only exercised indirectly — by rendering an image or reading a
config — and a bug in either produces a subtly wrong result rather than an exception.
These tests exercise their logic directly, and they run anywhere.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "lib"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

import astraos_env  # noqa: E402
from astraos_testlib import SkipTest  # noqa: E402

DESCRIPTION = "unit tests for the configuration parser and the asset renderer"


def _load_renderer():
    """Import branding/tools/render_assets.py without executing its main()."""
    path = REPO_ROOT / "branding" / "tools" / "render_assets.py"
    if not path.is_file():
        raise SkipTest("the asset renderer is not present")
    spec = importlib.util.spec_from_file_location("astraos_render_assets", path)
    if spec is None or spec.loader is None:
        raise SkipTest("the asset renderer could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Configuration parser
# ---------------------------------------------------------------------------

def test_env_parser_reads_the_real_config() -> None:
    config = astraos_env.distribution()
    assert config["ASTRAOS_NAME"] == "AstraOS"
    assert config["ASTRAOS_BASE_RELEASE_CODENAME"] == "trixie"


def test_env_parser_rejects_command_substitution() -> None:
    """Config files must never be able to execute code.

    The build scripts source these files with the shell, so a `$(...)` in a value would
    run. The parser refuses it, which also protects the tooling that reads them.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "evil.env"
        path.write_text('GOOD="value"\nBAD="$(touch /tmp/pwned)"\n', encoding="utf-8")
        try:
            astraos_env.parse_env_file(path)
        except ValueError as exc:
            assert "command substitution" in str(exc)
        else:
            raise AssertionError(
                "the parser accepted a value containing command substitution; these files "
                "are sourced by the shell"
            )


def test_env_parser_rejects_malformed_lines() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "bad.env"
        path.write_text("this is not an assignment\n", encoding="utf-8")
        try:
            astraos_env.parse_env_file(path)
        except ValueError:
            pass
        else:
            raise AssertionError("the parser accepted a line that is not a KEY=value assignment")


def test_env_parser_strips_quotes() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "quotes.env"
        path.write_text('A="double"\nB=\'single\'\nC=bare\n', encoding="utf-8")
        values = astraos_env.parse_env_file(path)
        assert values == {"A": "double", "B": "single", "C": "bare"}


def test_package_list_parser_ignores_comments_and_blanks() -> None:
    lists = astraos_env.package_lists()
    assert lists, "no package lists parsed"
    for filename, packages in lists.items():
        for package in packages:
            assert "#" not in package, f"{filename}: a comment leaked into a package name: {package!r}"
            assert package == package.strip(), f"{filename}: untrimmed entry {package!r}"
            assert package, f"{filename}: an empty entry was parsed"


# ---------------------------------------------------------------------------
# Asset renderer maths
# ---------------------------------------------------------------------------

def test_colour_conversion() -> None:
    renderer = _load_renderer()
    assert renderer.hex_to_rgb("#FF2FB9") == (255.0, 47.0, 185.0)
    assert renderer.hex_to_rgb("FF2FB9") == (255.0, 47.0, 185.0)
    assert renderer.hex_to_rgb("#000000") == (0.0, 0.0, 0.0)

    for bad in ("#FFF", "nonsense", "#GGGGGG", ""):
        try:
            renderer.hex_to_rgb(bad)
        except ValueError:
            continue
        raise AssertionError(f"hex_to_rgb accepted the invalid colour {bad!r}")


def test_clamp_is_bounded() -> None:
    renderer = _load_renderer()
    assert renderer.clamp8(-100.0) == 0
    assert renderer.clamp8(0.0) == 0
    assert renderer.clamp8(254.6) == 255
    assert renderer.clamp8(1e9) == 255
    assert renderer.clamp8(127.4) == 127


def test_mix_interpolates_and_clamps() -> None:
    renderer = _load_renderer()
    black, white = (0.0, 0.0, 0.0), (255.0, 255.0, 255.0)
    assert renderer.mix(black, white, 0.0) == black
    assert renderer.mix(black, white, 1.0) == white
    assert renderer.mix(black, white, 0.5) == (127.5, 127.5, 127.5)
    # Out-of-range t must clamp rather than extrapolate into invalid colours.
    assert renderer.mix(black, white, -5.0) == black
    assert renderer.mix(black, white, 5.0) == white


def test_smoothstep_is_bounded_and_monotonic() -> None:
    renderer = _load_renderer()
    assert renderer.smoothstep(0.0, 1.0, -1.0) == 0.0
    assert renderer.smoothstep(0.0, 1.0, 2.0) == 1.0
    assert renderer.smoothstep(0.0, 1.0, 0.0) == 0.0
    assert renderer.smoothstep(0.0, 1.0, 1.0) == 1.0
    previous = -1.0
    for step in range(11):
        value = renderer.smoothstep(0.0, 1.0, step / 10)
        assert value >= previous, "smoothstep is not monotonic"
        previous = value


def test_smoothstep_handles_equal_edges() -> None:
    """A zero-width edge range must not divide by zero."""
    renderer = _load_renderer()
    assert renderer.smoothstep(1.0, 1.0, 0.5) == 0.0
    assert renderer.smoothstep(1.0, 1.0, 1.5) == 0.0


def test_ring_colour_cycles_through_the_palette() -> None:
    """The angular gradient must visit all three brand colours and close cleanly.

    Comparisons at the segment boundaries use a tolerance rather than exact equality.
    `math.tau / 3` divided back by `math.tau` is not bit-identical to `1/3`, so the
    implementation may select the neighbouring segment and return a colour one part in
    10^16 away from the expected one. That difference is invisible in an 8-bit image, and
    asserting exact equality would be testing floating-point representation rather than
    the gradient.
    """
    import math

    renderer = _load_renderer()
    c1, c2, c3 = (255.0, 92.0, 200.0), (139.0, 61.0, 255.0), (34.0, 230.0, 255.0)

    def close(actual, expected, tolerance=1e-6, label=""):
        for got, want in zip(actual, expected):
            assert abs(got - want) <= tolerance, (
                f"{label}: expected {expected}, got {actual}"
            )

    # The three colours sit at 0, 1/3 and 2/3 of the cycle.
    close(renderer._ring_colour(0.0, c1, c2, c3), c1, label="at angle 0")
    close(renderer._ring_colour(math.tau / 3, c1, c2, c3), c2, label="at one third")
    close(renderer._ring_colour(2 * math.tau / 3, c1, c2, c3), c3, label="at two thirds")

    # A full turn returns to the start, so the ring has no visible seam.
    close(renderer._ring_colour(math.tau, c1, c2, c3), c1, label="after a full turn")

    # Negative angles (which atan2 returns) must be handled by wrapping, not by producing a
    # wrong colour.
    close(
        renderer._ring_colour(-math.tau / 3, c1, c2, c3),
        renderer._ring_colour(2 * math.tau / 3, c1, c2, c3),
        label="negative angle wrapping",
    )

    # Every sampled angle must be a real colour: three finite channels in 0..255.
    for step in range(48):
        colour = renderer._ring_colour(step * math.tau / 48 - math.tau, c1, c2, c3)
        assert len(colour) == 3, "the ring gradient returned the wrong shape"
        for channel in colour:
            assert 0.0 <= channel <= 255.0, f"channel out of range: {colour}"


def test_palette_reads_every_colour_it_uses() -> None:
    """The renderer's palette must resolve from config/branding.env, not hardcoded values."""
    renderer = _load_renderer()
    palette = renderer.Palette()
    branding = astraos_env.branding()

    assert palette.magenta == renderer.hex_to_rgb(branding["BRAND_NEON_MAGENTA"])
    assert palette.pink == renderer.hex_to_rgb(branding["BRAND_NEON_PINK"])
    assert palette.cyan == renderer.hex_to_rgb(branding["BRAND_NEON_CYAN"])
    assert palette.purple == renderer.hex_to_rgb(branding["BRAND_NEON_PURPLE"])
    assert palette.desk_dark == renderer.hex_to_rgb(branding["COLOR_BG_DARK"])
