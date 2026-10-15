"""Custom Cairo drawing widgets for the AstraOS HUD.

Why hand-drawn widgets at all
-----------------------------
The HUD is a dense instrument panel, not a document: it needs block meters,
multi-line waveforms, a rolling traffic graph and a point map that do not exist
in any GTK stock widget, and it needs all of them to look identical everywhere.
Every widget here paints with Cairo inside a ``draw`` handler, which is also the
only way plan §7.1's performance rule can be honoured — there is no compositing,
no blur pass and no texture reload, just rectangles, polylines and text on a
context that the toolkit has already handed us.

Two rules the drawing code follows, both from docs/DESIGN.md §0 and §7:

* Flat, near-opaque surfaces separated by 1px hairlines. The "frosted" look of
  the reference designs is produced with colour and a border, never with a blur
  filter — GTK3 has no ``backdrop-filter``, and blur is exactly the effect that
  makes a desktop feel slow on a software-rendered VM.
* Glow is reserved for the accent edge of a live value (the leading edge of a
  filled meter, the newest point of the traffic graph, a plotted endpoint). It is
  drawn as two or three concentric strokes at falling alpha, which costs almost
  nothing, and never as a full-surface effect.

Text is drawn through Pango when it is available, because the HUD needs
tabular figures (a clock whose digits jitter as the seconds change looks broken)
and letter spacing on the micro-labels. If PangoCairo is somehow unavailable the
helpers fall back to Cairo's toy text API rather than failing to draw at all.

Colours come from :data:`astraos_hud.systemdata.PALETTE`, which mirrors
``config/branding.env``. Nothing in this module hard-codes a colour literal.
"""

from __future__ import annotations

import math
import time
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402  (version must be pinned first)

try:  # PangoCairo comes from python3-gi-cairo; without it the toy text API is used.
    from gi.repository import PangoCairo  # noqa: E402

    _HAVE_PANGO = True
except (ImportError, ValueError):  # pragma: no cover - depends on the installed bindings
    PangoCairo = None  # type: ignore[assignment]
    _HAVE_PANGO = False

from . import systemdata as sd  # noqa: E402

Colour = Tuple[float, float, float, float]


# ---------------------------------------------------------------------------
# Colour and text helpers
# ---------------------------------------------------------------------------

def rgba(token: str, alpha: float = 1.0) -> Colour:
    """Resolve a branding.env token name (or a literal '#RRGGBB') to a Cairo colour."""
    red, green, blue = sd.hex_to_rgb(sd.PALETTE.get(token, token))
    return (red, green, blue, max(0.0, min(1.0, float(alpha))))


def font_description(pixels: float, *, mono: bool = True, bold: bool = False) -> "Pango.FontDescription":
    """A pixel-sized font description. Absolute sizes keep type identical at any scale."""
    description = Pango.FontDescription()
    description.set_family(sd.FONT_MONO if mono else sd.FONT_UI)
    description.set_absolute_size(max(1.0, float(pixels)) * Pango.SCALE)
    description.set_weight(Pango.Weight.BOLD if bold else Pango.Weight.NORMAL)
    return description


def _text(cr, text: str, x: float, y: float, pixels: float, colour: Colour,
          *, mono: bool = True, bold: bool = False, align: str = "left",
          tracking: float = 0.0, max_width: Optional[float] = None) -> float:
    """Draw one line of text and return the width it occupied.

    `y` is the text baseline, matching Cairo and Pango conventions, so callers
    position rows by baseline rather than guessing at ascent.
    """
    if not text:
        return 0.0
    if _HAVE_PANGO:
        layout = PangoCairo.create_layout(cr)
        description = font_description(pixels, mono=mono, bold=bold)
        layout.set_font_description(description)
        layout.set_text(text)
        if tracking:
            # Micro-labels are uppercase with wide tracking (DESIGN.md §2); Pango
            # expresses that as an absolute letter spacing in Pango units.
            layout.set_attributes(Pango.AttrLetterSpacing.new(int(tracking * Pango.SCALE)))
        if max_width is not None:
            layout.set_ellipsize(Pango.EllipsizeMode.END)
            layout.set_width(int(max_width * Pango.SCALE))
        width, height = layout.get_pixel_size()
        if align == "right":
            x -= width
        elif align == "centre":
            x -= width / 2.0
        cr.set_source_rgba(*colour)
        cr.move_to(x, y - height * 0.8)
        PangoCairo.show_layout(cr, layout)
        return float(width)

    # Toy fallback: no Pango, so no ellipsize or tracking, but still readable.
    cr.set_source_rgba(*colour)
    cr.select_font_face(sd.FONT_MONO if mono else sd.FONT_UI, 0, 2 if bold else 0)
    cr.set_font_size(max(1.0, float(pixels)))
    if align == "right":
        x -= cr.text_extents(text)[4]
    cr.move_to(x, y)
    cr.show_text(text)
    return float(cr.text_extents(text)[4])


def ellipsize(cr, text: str, pixels: float, max_width: float) -> str:
    """Trim `text` to fit `max_width` at `pixels`, adding an ellipsis when cut."""
    if not text or max_width <= 0:
        return ""
    if _measure(cr, text, pixels) <= max_width:
        return text
    trimmed = text
    while trimmed and _measure(cr, trimmed + "…", pixels) > max_width:
        trimmed = trimmed[:-1]
    return (trimmed + "…") if trimmed else ""


def _measure(cr, text: str, pixels: float) -> float:
    if not text:
        return 0.0
    if _HAVE_PANGO:
        layout = PangoCairo.create_layout(cr)
        layout.set_font_description(font_description(pixels))
        layout.set_text(text)
        return float(layout.get_pixel_size()[0])
    cr.save()
    cr.set_font_size(max(1.0, float(pixels)))
    width = float(cr.text_extents(text)[4])
    cr.restore()
    return width


def hairline(cr, x: float, y: float, width: float, height: float, colour: Colour) -> None:
    """A 1px rectangle outline, nudged half a pixel so it lands on one device row."""
    cr.set_source_rgba(*colour)
    cr.set_line_width(1.0)
    cr.rectangle(x + 0.5, y + 0.5, max(0.0, width - 1.0), max(0.0, height - 1.0))
    cr.stroke()


def accent_edge(cr, x: float, y: float, width: float, height: float, colour: Colour) -> None:
    """The only glow in the HUD: a short bright edge at the leading end of a value.

    Three strokes at falling alpha read as a soft edge at any size and cost less
    than a tenth of a millisecond. This is deliberately the sole use of glow in
    the whole application (plan §7.1).
    """
    for spread, alpha in ((2.0, 0.10), (1.0, 0.22), (0.0, 0.95)):
        cr.set_source_rgba(colour[0], colour[1], colour[2], alpha)
        cr.set_line_width(2.0 + spread * 2.0)
        cr.move_to(x - spread, y - spread * 0.5)
        cr.line_to(x - spread, y + height + spread * 0.5)
        cr.stroke()


class DrawingArea(Gtk.DrawingArea):
    """A DrawingArea that repaints only when told there is new data.

    GTK3 would happily queue a draw on every expose; on a full-screen overlay
    that means repainting six regions while the user is typing in the terminal.
    Everything here therefore sets an explicit minimum height and never calls
    queue_draw() on its own except from set_* methods.
    """

    def __init__(self, minimum_height: int = 0, minimum_width: int = 0) -> None:
        super().__init__()
        if minimum_height:
            self.set_size_request(minimum_width, minimum_height)
        self.set_has_tooltip(False)


# ---------------------------------------------------------------------------
# Meters
# ---------------------------------------------------------------------------

class MeterBar(DrawingArea):
    """A hairline-framed horizontal bar with an optional caption on the left.

    Used for the MEMORY occupancy line, each mounted volume in the FILESYSTEM
    strip and the mount summary at the very bottom of the screen.
    """

    def __init__(self, *, show_percent: bool = True, height: int = 10) -> None:
        super().__init__(minimum_height=height)
        self._value: Optional[float] = None
        self._caption = ""
        self._detail = ""
        self._show_percent = show_percent
        self._colour_token = "COLOR_HUD_TEAL"
        self.set_size_request(-1, height)

    def set_value(self, percent: Optional[float], *, caption: str = "", detail: str = "",
                  colour_token: str = "COLOR_HUD_TEAL") -> None:
        """Update the bar. `None` means unmeasured: the bar stays empty and the
        caption keeps its dash, which is how the HUD avoids a confident 0%."""
        self._value = None if percent is None else sd.clamp(percent, 0.0, 100.0)
        self._caption = caption
        self._detail = detail
        self._colour_token = colour_token
        self.queue_draw()

    def do_draw(self, cr) -> None:  # noqa: N802 - GObject virtual method
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        if width <= 0 or height <= 0:
            return

        caption_width = 0.0
        if self._caption:
            pixels = max(8.0, min(12.0, height * 0.8))
            caption_width = _text(cr, self._caption, 0.0, height - 2.0, pixels,
                                  rgba("COLOR_TEXT_DIM"), max_width=width * 0.55) + 8.0

        bar_x = caption_width
        bar_width = max(1.0, (width - caption_width - 46.0) if self._show_percent else (width - caption_width))
        bar_y = 1.0
        bar_height = max(2.0, height - 2.0)

        cr.set_source_rgba(*rgba("COLOR_SURFACE_RAISED"))
        cr.rectangle(bar_x, bar_y, bar_width, bar_height)
        cr.fill()

        if self._value is None:
            hairline(cr, bar_x, bar_y, bar_width, bar_height, rgba("COLOR_HAIRLINE_BASE"))
        else:
            filled = bar_width * (self._value / 100.0)
            colour = rgba(self._colour_token)
            cr.set_source_rgba(colour[0], colour[1], colour[2], 0.85)
            cr.rectangle(bar_x, bar_y, max(1.0, filled), bar_height)
            cr.fill()
            if filled > 2.0:
                accent_edge(cr, bar_x + filled, bar_y, 2.0, bar_height, colour)
            hairline(cr, bar_x, bar_y, bar_width, bar_height, rgba("COLOR_HAIRLINE_BASE"))

        if self._show_percent:
            text = sd.PENDING if self._value is None else f"{self._value:4.0f}%"
            _text(cr, text, width, height - 2.0, max(8.0, min(12.0, height * 0.8)),
                  rgba("COLOR_TEXT" if self._value is not None else "COLOR_TEXT_FAINT"), align="right")

        if self._detail:
            _text(cr, self._detail, bar_x, height - 2.0, max(7.0, min(11.0, height * 0.7)),
                  rgba("COLOR_TEXT_FAINT"), max_width=bar_width)


class BlockMeter(DrawingArea):
    """The block-style occupancy indicator from the reference ('USING 1.6 OF 7.8 GB').

    Memory is shown as discrete blocks rather than a bar because a desktop
    monitor is read at a glance from across a room: whole blocks are legible at
    that distance, a smoothly varying bar is not.
    """

    def __init__(self, blocks: int = 5) -> None:
        super().__init__(minimum_height=14)
        self._blocks = max(1, int(blocks))
        self._percent: Optional[float] = None
        self._caption = ""
        self._detail = ""

    def set_value(self, percent: Optional[float], caption: str = "", detail: str = "") -> None:
        self._percent = None if percent is None else sd.clamp(percent, 0.0, 100.0)
        self._caption = caption
        self._detail = detail
        self.queue_draw()

    def do_draw(self, cr) -> None:  # noqa: N802
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        if width <= 0 or height <= 0:
            return

        caption_width = 0.0
        if self._caption:
            caption_width = _text(cr, self._caption, 0.0, height * 0.5, 11.0,
                                  rgba("COLOR_TEXT"), bold=False, max_width=width * 0.5) + 10.0

        # Blocks grow left to right from the caption, the way the reference does.
        available = max(0.0, width - caption_width)
        block = max(4.0, min(18.0, height * 0.75))
        gap = max(3.0, block * 0.45)
        per_block = block + gap
        count = max(1, min(self._blocks, int((available - gap) / per_block) or 1))
        x = caption_width
        y = (height - block) / 2.0

        filled = 0.0 if self._percent is None else self._percent / 100.0 * count
        colour = rgba("COLOR_HUD_TEAL")
        for index in range(count):
            partial = sd.clamp(filled - index, 0.0, 1.0)
            if self._percent is None:
                cr.set_source_rgba(*rgba("COLOR_SURFACE_RAISED"))
                cr.rectangle(x, y, block, block)
                cr.fill()
                hairline(cr, x, y, block, block, rgba("COLOR_HAIRLINE_BASE"))
            elif partial >= 1.0:
                cr.set_source_rgba(colour[0], colour[1], colour[2], 0.9)
                cr.rectangle(x, y, block, block)
                cr.fill()
                if index == int(math.floor(filled - 0.001)):
                    accent_edge(cr, x + block, y, 2.0, block, colour)
            elif partial > 0.0:
                cr.set_source_rgba(colour[0], colour[1], colour[2], 0.35)
                cr.rectangle(x, y, block, block)
                cr.fill()
                cr.set_source_rgba(colour[0], colour[1], colour[2], 0.9)
                cr.rectangle(x, y, block * partial, block)
                cr.fill()
                accent_edge(cr, x + block * partial, y, 2.0, block, colour)
            x += per_block

        if self._detail:
            _text(cr, self._detail, width, height * 0.5, 11.0, rgba("COLOR_TEXT_DIM"),
                  align="right", max_width=available - count * per_block)


class Waveform(DrawingArea):
    """One jagged load trace per physical core, as in the reference's CPU block.

    The trace is real history, not decoration: every tick appends the percentage
    just measured, and the deque is bounded so a HUD left open for a week draws
    the same 120 points as one opened for a minute.
    """

    def __init__(self, capacity: int = 120, height: int = 34) -> None:
        super().__init__(minimum_height=height)
        self._history: List[float] = []
        self._capacity = max(2, int(capacity))
        self._value: Optional[float] = None
        self.set_size_request(-1, height)

    def push(self, percent: Optional[float]) -> None:
        """Append one sample. `None` samples are skipped, not stored as zero."""
        if percent is None:
            return
        self._value = percent
        self._history.append(percent)
        if len(self._history) > self._capacity:
            del self._history[: len(self._history) - self._capacity]
        self.queue_draw()

    def clear(self) -> None:
        self._history.clear()
        self._value = None
        self.queue_draw()

    def do_draw(self, cr) -> None:  # noqa: N802
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        if width <= 2 or height <= 2:
            return
        baseline = height - 6.0

        cr.set_source_rgba(*rgba("COLOR_HAIRLINE_BASE", 0.6))
        cr.set_line_width(1.0)
        cr.move_to(0.5, baseline + 0.5)
        cr.line_to(width - 0.5, baseline + 0.5)
        cr.stroke()

        if not self._history:
            return
        step = width / float(max(1, self._capacity - 1))
        points = self._history
        offset = width - step * (len(points) - 1)
        colour = rgba("COLOR_HUD_TEAL")

        cr.set_source_rgba(colour[0], colour[1], colour[2], 0.18)
        cr.set_line_width(1.0)
        cr.move_to(offset, baseline)
        for index, value in enumerate(points):
            cr.line_to(offset + step * index, baseline - (baseline - 2.0) * (value / 100.0))
        cr.line_to(offset + step * (len(points) - 1), baseline)
        cr.close_path()
        cr.fill()

        cr.set_source_rgba(colour[0], colour[1], colour[2], 0.95)
        cr.set_line_width(1.4)
        for index, value in enumerate(points):
            x = offset + step * index
            y = baseline - (baseline - 2.0) * (value / 100.0)
            if index == 0:
                cr.move_to(x, y)
            else:
                cr.line_to(x, y)
        cr.stroke()


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

class DataTable(DrawingArea):
    """A monospaced column table with an uppercase header row.

    TOP PROCESSES, the TEMP/MIN/MAX/TASKS micro-columns, the NETWORK STATUS
    columns and the CLIPBOARD row all use this one widget: the HUD needs its
    labels to line up to the pixel across four separate regions, which is far
    easier to guarantee with a single drawing routine than with four layouts.
    """

    def __init__(self, columns: Sequence[Tuple[str, float, str]], *, row_height: int = 15,
                 header: bool = True, height: int = 0) -> None:
        super().__init__(minimum_height=height)
        # columns: (title, width fraction, alignment 'left'|'right'|'centre')
        self._columns = list(columns)
        self._rows: List[List[str]] = []
        self._row_height = max(10, int(row_height))
        self._header = header
        self.set_size_request(-1, height or (self._row_height * (2 if header else 1)))

    def set_rows(self, rows: Iterable[Sequence[str]]) -> None:
        self._rows = [list(row) for row in rows]
        wanted = self._row_height * ((1 if self._header else 0) + max(1, len(self._rows))) + 2
        self.set_size_request(-1, wanted)
        self.queue_draw()

    def do_draw(self, cr) -> None:  # noqa: N802
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        if width <= 0:
            return

        fractions = [fraction for _, fraction, _ in self._columns] or [1.0]
        total = sum(fractions) or 1.0
        offsets: List[float] = []
        cursor = 0.0
        for fraction in fractions:
            offsets.append(width * cursor / total)
            cursor += fraction
        spans = [width * fraction / total for fraction in fractions]

        y = 0.0
        if self._header:
            for index, (title, _fraction, align) in enumerate(self._columns):
                _text(cr, title, offsets[index] + (spans[index] if align == "right" else 0.0),
                      11.0, 10.0, rgba("COLOR_TEXT_FAINT"), align=align,
                      tracking=1.0, max_width=spans[index])
            y = 15.0
            cr.set_source_rgba(*rgba("COLOR_HAIRLINE_BASE"))
            cr.set_line_width(1.0)
            cr.move_to(0.0, y + 0.5)
            cr.line_to(width, y + 0.5)
            cr.stroke()
            y += 3.0

        for row in self._rows:
            if y > height:
                break
            for index, cell in enumerate(row[:len(self._columns)]):
                _title, _fraction, align = self._columns[index]
                x = offsets[index] + (spans[index] if align == "right" else
                                      (spans[index] / 2.0 if align == "centre" else 0.0))
                colour = "COLOR_TEXT" if index == 0 or align != "right" else "COLOR_TEXT_DIM"
                if cell in (sd.NA, sd.PENDING):
                    colour = "COLOR_TEXT_FAINT"
                _text(cr, str(cell), x, y + self._row_height * 0.72, 11.0, rgba(colour),
                      align=align, max_width=spans[index] - 3.0)
            y += self._row_height


class TrafficGraph(DrawingArea):
    """The rolling up/down graph: two traces over the last HUD_TRAFFIC_SAMPLES ticks.

    Upload is teal, download is the body text colour, matching the reference.
    The vertical scale is derived from the visible window rather than fixed, so
    an idle link shows a flat pair of lines near the baseline instead of being
    scaled to nothing, and a burst fills the panel honestly.
    """

    def __init__(self, height: int = 96, sample_hint: int = sd.HUD_TRAFFIC_SAMPLES,
                 formatter=None, floor: float = 64.0 * 1024.0,
                 scale_caption: str = "MAX") -> None:
        super().__init__(minimum_height=height)
        self._up: List[float] = []
        self._down: List[float] = []
        self._capacity = max(2, int(sample_hint))
        self._up_now: Optional[float] = None
        self._down_now: Optional[float] = None
        self._interface = ""
        # `formatter` and `floor` let the same widget draw a second, different
        # unit (the gateway latency panel passes milliseconds and a 1 ms floor),
        # instead of maintaining a second copy of the same rolling-trace code.
        self._format = formatter or sd.format_rate
        self._floor = max(1e-6, float(floor))
        self._scale_caption = scale_caption
        self.set_size_request(-1, height)

    def push(self, up: Optional[float], down: Optional[float], interface: str = "") -> None:
        """Append one tick of traffic. Unmeasured ticks are skipped, not zeroed."""
        self._interface = interface or self._interface
        if up is None or down is None:
            return
        self._up_now, self._down_now = up, down
        self._up.append(up)
        self._down.append(down)
        if len(self._up) > self._capacity:
            del self._up[: len(self._up) - self._capacity]
            del self._down[: len(self._down) - self._capacity]
        self.queue_draw()

    def do_draw(self, cr) -> None:  # noqa: N802
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        if width <= 4 or height <= 8:
            return

        label_room = 52.0
        graph_width = max(4.0, width - label_room)
        top = 14.0
        bottom = height - 4.0
        span = max(4.0, bottom - top)

        peak = max(self._up + self._down) if (self._up or self._down) else 0.0
        # A fixed floor keeps an idle link from being magnified into noise.
        scale = max(peak * 1.15, self._floor)

        cr.set_source_rgba(*rgba("COLOR_HAIRLINE_BASE"))
        cr.set_line_width(1.0)
        cr.move_to(0.5, bottom + 0.5)
        cr.line_to(graph_width, bottom + 0.5)
        cr.stroke()

        _text(cr, f"{self._format(scale).split(' ')[0]} {self._scale_caption}", graph_width - 2.0,
              top - 2.0, 9.0, rgba("COLOR_TEXT_FAINT"), align="right")

        if not self._up:
            _text(cr, "COLLECTING", 6.0, top + span / 2.0, 10.0, rgba("COLOR_TEXT_FAINT"))
            return

        step = graph_width / float(max(1, self._capacity - 1))
        offset = graph_width - step * (len(self._up) - 1)

        def trace(values: Sequence[float], token: str, fill: bool) -> None:
            colour = rgba(token)
            cr.set_line_width(1.4)
            if fill:
                cr.set_source_rgba(colour[0], colour[1], colour[2], 0.12)
                cr.move_to(offset, bottom)
                for index, value in enumerate(values):
                    cr.line_to(offset + step * index,
                               bottom - span * sd.clamp(value / scale, 0.0, 1.0))
                cr.line_to(offset + step * (len(values) - 1), bottom)
                cr.close_path()
                cr.fill()
                return
            cr.set_source_rgba(colour[0], colour[1], colour[2], 0.95)
            for index, value in enumerate(values):
                x = offset + step * index
                y = bottom - span * sd.clamp(value / scale, 0.0, 1.0)
                if index == 0:
                    cr.move_to(x, y)
                else:
                    cr.line_to(x, y)
            cr.stroke()
            last_x = offset + step * (len(values) - 1)
            last_y = bottom - span * sd.clamp(values[-1] / scale, 0.0, 1.0)
            accent_edge(cr, last_x, last_y, 2.0, 2.0, colour)

        trace(self._up, "COLOR_HUD_TEAL", False)
        trace(self._down, "COLOR_TEXT", False)

        if self._interface:
            _text(cr, self._interface, graph_width - 2.0, height - 1.0, 9.0,
                  rgba("COLOR_TEXT_FAINT"), align="right")

        # Current values are printed at the trailing edge, one per trace.
        if self._down_now is not None:
            y = bottom - span * sd.clamp(self._down_now / scale, 0.0, 1.0)
            _text(cr, f"▼ {self._format(self._down_now)}", width, y + 3.0, 9.0, rgba("COLOR_TEXT"))
        if self._up_now is not None:
            y = bottom - span * sd.clamp(self._up_now / scale, 0.0, 1.0)
            _text(cr, f"▲ {self._format(self._up_now)}", width, y + 3.0, 9.0, rgba("COLOR_HUD_TEAL"))


class FilesystemStrip(DrawingArea):
    """The bottom FILESYSTEM band: every mounted volume, its use, and a bar.

    Unreadable volumes are drawn as such rather than dropped. A disk that has
    gone away is exactly the thing a user opens a dashboard to find out.
    """

    def __init__(self, height: int = 92) -> None:
        super().__init__(minimum_height=height)
        self._mounts: Sequence[sd.MountInfo] = ()
        self._unreadable = 0
        self.set_size_request(-1, height)

    def set_mounts(self, mounts: Sequence[sd.MountInfo], unreadable: int = 0) -> None:
        self._mounts = list(mounts)
        self._unreadable = unreadable
        self.queue_draw()

    def do_draw(self, cr) -> None:  # noqa: N802
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        if width <= 0 or height <= 0 or not self._mounts:
            if not self._mounts:
                _text(cr, "NO MOUNTED VOLUMES FOUND", 0.0, 14.0, 10.0, rgba("COLOR_TEXT_FAINT"))
            return

        # Two columns of chips when the strip is wide enough, matching the
        # reference's grid of mounted-folder tiles.
        columns = 2 if width > 620 else 1
        column_width = width / columns
        row_height = 20.0
        rows_per_column = max(1, int((height - 4.0) / row_height))
        pixels = 10.0

        for index, mount in enumerate(self._mounts):
            column = index // rows_per_column
            row = index % rows_per_column
            if column >= columns:
                break
            x = column * column_width
            y = row * row_height

            # Right-hand third is reserved for the numbers: name | bar | used/total | %
            name_width = column_width * 0.40
            bar_x = x + name_width
            bar_width = column_width * 0.22
            used_width = column_width * 0.30
            percent_x = x + column_width * 0.96

            name = mount.mountpoint if mount.mountpoint == "/" else mount.mountpoint
            _text(cr, ellipsize(cr, name, pixels, name_width - 4.0), x, y + 11.0, pixels,
                  rgba("COLOR_TEXT"))

            if not mount.readable:
                _text(cr, "unreadable", bar_x, y + 11.0, 9.0, rgba("COLOR_HUD_RED"),
                      max_width=column_width - name_width - 4.0)
                continue

            bar_y = y + 3.0
            cr.set_source_rgba(*rgba("COLOR_SURFACE_RAISED"))
            cr.rectangle(bar_x, bar_y, bar_width, 7.0)
            cr.fill()
            filled = bar_width * ((mount.percent or 0.0) / 100.0)
            token = "COLOR_HUD_RED" if (mount.percent or 0.0) >= 90.0 else "COLOR_HUD_TEAL"
            colour = rgba(token)
            if filled > 0:
                cr.set_source_rgba(colour[0], colour[1], colour[2], 0.85)
                cr.rectangle(bar_x, bar_y, max(1.0, filled), 7.0)
                cr.fill()
                accent_edge(cr, bar_x + filled, bar_y, 2.0, 7.0, colour)
            hairline(cr, bar_x, bar_y, bar_width, 7.0, rgba("COLOR_HAIRLINE_BASE"))

            _text(cr, f"{sd.format_bytes(mount.used_bytes)} / {sd.format_bytes(mount.total_bytes)}",
                  x + column_width * 0.92, y + 11.0, 9.0, rgba("COLOR_TEXT_DIM"),
                  align="right", max_width=used_width)
            _text(cr, sd.PENDING if mount.percent is None else f"{mount.percent:.0f}%",
                  percent_x, y + 11.0, 9.0,
                  rgba("COLOR_TEXT_FAINT" if mount.percent is None else token),
                  align="right", max_width=column_width * 0.08)

        if self._unreadable:
            _text(cr, f"{self._unreadable} VOLUME(S) UNREADABLE", 0.0, height - 1.0, 9.0,
                  rgba("COLOR_HUD_RED"))


class GlobeView(DrawingArea):
    """The WORLD VIEW panel: an orthographic globe with the configured endpoints.

    Coordinates are never guessed. AstraOS ships no geolocation database and the
    HUD makes no outbound request to find one, so a plotted point only appears
    for endpoints listed in /etc/astraos/hud-endpoints.conf (see
    :class:`astraos_hud.systemdata.Endpoint`). With no such file the globe keeps
    its graticule and says NO ENDPOINT DATA instead of showing a plausible dot
    in a plausible country.

    The projection is centred on the mean of the plotted points, so the visible
    hemisphere always faces the data instead of facing the null island.
    """

    def __init__(self, height: int = 130) -> None:
        super().__init__(minimum_height=height)
        self._endpoints: Dict[str, sd.Endpoint] = {}
        self._caption = "NO ENDPOINT DATA"
        self.set_size_request(-1, height)

    def set_endpoints(self, endpoints: Dict[str, sd.Endpoint], caption: str = "") -> None:
        self._endpoints = dict(endpoints)
        self._caption = caption or ("NO ENDPOINT DATA" if not endpoints else "")
        self.queue_draw()

    def do_draw(self, cr) -> None:  # noqa: N802
        width = self.get_allocated_width()
        height = self.get_allocated_height()
        if width <= 4 or height <= 4:
            return

        centre_x = width * 0.42
        centre_y = height * 0.5 - 2.0
        radius = max(8.0, min(width * 0.40, height * 0.44))

        cr.set_source_rgba(*rgba("COLOR_SURFACE_RAISED"))
        cr.arc(centre_x, centre_y, radius, 0.0, 2.0 * math.pi)
        cr.fill()

        points = list(self._endpoints.values())
        centre_lat = sum(point.latitude for point in points) / len(points) if points else 20.0
        centre_lon = sum(point.longitude for point in points) / len(points) if points else 0.0

        cr.save()
        cr.arc(centre_x, centre_y, radius, 0.0, 2.0 * math.pi)
        cr.clip()
        cr.set_line_width(1.0)
        cr.set_source_rgba(*rgba("COLOR_HAIRLINE_BASE"))
        for step in range(-60, 61, 30):
            self._meridian(cr, centre_x, centre_y, radius, float(step), centre_lat)
            self._parallel(cr, centre_x, centre_y, radius, float(step))
        cr.restore()

        cr.set_source_rgba(*rgba("COLOR_HAIRLINE_HOT", 0.35))
        cr.set_line_width(1.0)
        cr.arc(centre_x, centre_y, radius, 0.0, 2.0 * math.pi)
        cr.stroke()

        colour = rgba("COLOR_HUD_TEAL")
        for point in points:
            projected = self._project(point.latitude, point.longitude, centre_lat, centre_lon,
                                      centre_x, centre_y, radius)
            if projected is None:
                continue  # on the far side of the globe
            x, y = projected
            for spread, alpha in ((5.0, 0.10), (3.0, 0.18), (1.5, 0.55)):
                cr.set_source_rgba(colour[0], colour[1], colour[2], alpha)
                cr.arc(x, y, spread, 0.0, 2.0 * math.pi)
                cr.fill()
            cr.set_source_rgba(colour[0], colour[1], colour[2], 1.0)
            cr.arc(x, y, 2.0, 0.0, 2.0 * math.pi)
            cr.fill()

        text_x = min(width - 4.0, centre_x + radius + 10.0)
        if text_x < centre_x + radius + 60.0:
            text_x = 4.0
        if points:
            _text(cr, points[0].label[:14].upper(), text_x, height * 0.45, 10.0,
                  rgba("COLOR_TEXT"), max_width=width - text_x - 2.0)
            _text(cr, f"{points[0].latitude:+.2f} {points[0].longitude:+.2f}", text_x,
                  height * 0.45 + 13.0, 9.0, rgba("COLOR_TEXT_DIM"), max_width=width - text_x - 2.0)
            _text(cr, points[0].address, text_x, height * 0.45 + 25.0, 9.0,
                  rgba("COLOR_TEXT_FAINT"), max_width=width - text_x - 2.0)
        else:
            _text(cr, "NO ENDPOINT DATA", text_x, height * 0.45, 10.0,
                  rgba("COLOR_TEXT_FAINT"), max_width=width - text_x - 2.0)
            _text(cr, "edit /etc/astraos/hud-endpoints.conf", text_x, height * 0.45 + 12.0, 8.5,
                  rgba("COLOR_TEXT_FAINT"), max_width=width - text_x - 2.0)

    def _meridian(self, cr, cx: float, cy: float, radius: float, longitude: float,
                  centre_lat: float) -> None:
        previous = None
        for step in range(-90, 91, 5):
            projected = self._project(float(step), longitude, centre_lat, longitude, cx, cy, radius)
            if projected is None:
                previous = None
                continue
            if previous is None:
                cr.move_to(*projected)
            else:
                cr.line_to(*projected)
            previous = projected
        cr.stroke()

    def _parallel(self, cr, cx: float, cy: float, radius: float, latitude: float) -> None:
        previous = None
        for step in range(-180, 181, 5):
            projected = self._project(latitude, float(step), 0.0, 0.0, cx, cy, radius)
            if projected is None:
                previous = None
                continue
            if previous is None:
                cr.move_to(*projected)
            else:
                cr.line_to(*projected)
            previous = projected
        cr.stroke()

    @staticmethod
    def _project(latitude: float, longitude: float, centre_lat: float, centre_lon: float,
                 cx: float, cy: float, radius: float) -> Optional[Tuple[float, float]]:
        """Orthographic projection; returns None when the point faces away."""
        lat = math.radians(latitude)
        lon = math.radians(longitude)
        lat0 = math.radians(centre_lat)
        lon0 = math.radians(centre_lon)
        cos_c = (math.sin(lat0) * math.sin(lat) + math.cos(lat0) * math.cos(lat) * math.cos(lon - lon0))
        if cos_c < 0.0:
            return None
        x = cx + radius * math.cos(lat) * math.sin(lon - lon0)
        y = cy - radius * (math.cos(lat0) * math.sin(lat) - math.sin(lat0) * math.cos(lat) * math.cos(lon - lon0))
        return x, y


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

class ClockDisplay(Gtk.Label):
    """The oversized HH:MM:SS clock at the top of the left column.

    Two details make it read as an instrument rather than as text:

    * tabular figures via the OpenType ``tnum`` feature, so the digits do not
      change width as the seconds tick — a proportional 1 next to a wide 0 makes
      the whole clock twitch once a second;
    * a monospace face at a fixed pixel size, which is the only reason the value
      can be trusted to be aligned with the labels under it.

    The seconds field is what makes the HUD obviously alive, so it is never
    hidden; the size adapts to the panel width instead.
    """

    def __init__(self) -> None:
        super().__init__()
        self.set_justify(Gtk.Justification.LEFT)
        self.set_xalign(0.0)
        self._size = 64
        self._text = ""

    def set_time(self, epoch: float) -> None:
        stamp = time.localtime(epoch)
        text = time.strftime("%H:%M:%S", stamp)
        if text == self._text:
            return
        self._text = text
        self._refresh()

    def resize_for(self, width: int) -> None:
        """Pick a clock size that fits the column, clamped to the reference's 56-72px."""
        size = int(sd.clamp(width * 0.19, 56.0, 72.0))
        if size != self._size:
            self._size = size
            self._refresh()

    def _refresh(self) -> None:
        features = "tnum 1"  # tabular figures; ignored harmlessly if unsupported
        self.set_markup(
            "<span font_family='%s' font_features='%s' font_size='%dpx'>%s</span>"
            % (sd.FONT_DISPLAY, features, self._size, self._text or "--:--:--")
        )


class PromptLabel(Gtk.Label):
    """The live shell prompt shown at the bottom of the TERMINAL region.

    It mirrors the shell the HUD actually starts, so a user can see the same
    identity the embedded terminal will report. Values come from the process
    environment, never from a template with the hostname typed in.
    """

    def __init__(self) -> None:
        super().__init__()
        self.set_xalign(0.0)
        self.set_ellipsize(Pango.EllipsizeMode.END)
        self.set_text("")

    def set_prompt(self, user: str, host: str, path: str) -> None:
        prompt = f"{user or sd.NA}@{host or sd.NA}:{path or '~'}$ "
        self.set_markup(
            "<span font_family='%s' font_size='10px' foreground='%s'>%s</span>"
            % (sd.FONT_MONO, sd.PALETTE["COLOR_HUD_TEAL"], GLib.markup_escape_text(prompt))
        )


# ---------------------------------------------------------------------------
# On-screen keyboard
# ---------------------------------------------------------------------------

#: (label, keyval name, character, width) — width is the column span in the grid.
#: The layout is the reference's: the shell users of a headless-friendly desktop
#: expect, with BACK/ENTER/SHIFT/arrows in their familiar places.
KEY_ROWS: Tuple[Tuple[Tuple[str, Optional[str], Optional[str], int], ...], ...] = (
    (
        ("ESC", "KEY_Escape", None, 1), ("~`", None, "~", 1),
        ("1", None, "1", 1), ("2", None, "2", 1), ("3", None, "3", 1), ("4", None, "4", 1),
        ("5", None, "5", 1), ("6", None, "6", 1), ("7", None, "7", 1), ("8", None, "8", 1),
        ("9", None, "9", 1), ("0", None, "0", 1), ("-", None, "-", 1), ("=", None, "=", 1),
        ("BACK", "KEY_BackSpace", None, 2),
    ),
    (
        ("TAB", "KEY_Tab", None, 1), ("Q", None, "q", 1), ("W", None, "w", 1),
        ("E", None, "e", 1), ("R", None, "r", 1), ("T", None, "t", 1), ("Y", None, "y", 1),
        ("U", None, "u", 1), ("I", None, "i", 1), ("O", None, "o", 1), ("P", None, "p", 1),
        ("[", None, "[", 1), ("]", None, "]", 1), ("ENTER", "KEY_Return", None, 2),
    ),
    (
        ("CAPS", "KEY_Caps_Lock", None, 1), ("A", None, "a", 1), ("S", None, "s", 1),
        ("D", None, "d", 1), ("F", None, "f", 1), ("G", None, "g", 1), ("H", None, "h", 1),
        ("J", None, "j", 1), ("K", None, "k", 1), ("L", None, "l", 1),
        (";", None, ";", 1), ("'", None, "'", 1), ("SHIFT", "KEY_Shift_L", "SHIFT", 2),
    ),
    (
        ("SHIFT", "KEY_Shift_L", "SHIFT", 1), ("Z", None, "z", 1), ("X", None, "x", 1),
        ("C", None, "c", 1), ("V", None, "v", 1), ("B", None, "b", 1), ("N", None, "n", 1),
        ("M", None, "m", 1), (",", None, ",", 1), (".", None, ".", 1), ("/", None, "/", 1),
        ("SHIFT", "KEY_Shift_L", "SHIFT", 2), ("↑", "KEY_Up", None, 1),
    ),
    (
        ("CTRL", "KEY_Control_L", "CTRL", 1), ("FN", None, None, 1),
        ("SPACE", None, " ", 8), ("ALT GR", "KEY_ISO_Level3_Shift", "ALTGR", 2),
        ("CTRL", "KEY_Control_L", "CTRL", 1),
        ("←", "KEY_Left", None, 1), ("↓", "KEY_Down", None, 1), ("→", "KEY_Right", None, 1),
    ),
)


class OnScreenKeyboard(Gtk.Grid):
    """A real on-screen keyboard: its keys are delivered as key events.

    The HUD is often the only way to type on a machine reached over a remote
    desktop, a serial console or a tablet, so these buttons cannot be a picture
    of a keyboard. Each press synthesises a Gdk key event pair and hands it to
    whichever widget currently has the focus - the embedded terminal, a text
    view, or a GTK entry - through Gtk.Widget.event(), so the receiving widget
    handles it exactly as if a physical key had arrived. No xdotool, no
    subprocess, no XTEST extension.

    With nothing focused, the key is copied to the clipboard instead of being
    dropped, which makes the keyboard usable while the user is dragging windows
    and has not yet clicked into the terminal.
    """

    def __init__(self) -> None:
        super().__init__()
        self.set_column_spacing(3)
        self.set_row_spacing(3)
        self.set_hexpand(True)
        self._target: Optional[Gtk.Widget] = None
        self._shift = False
        self._caps = False
        self._modifiers = 0
        self._buttons: Dict[str, Gtk.Button] = {}
        self._build()

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        for row_index, row in enumerate(KEY_ROWS):
            for column_index, (label, keyval_name, character, span) in enumerate(row):
                button = Gtk.Button(label=label)
                button.set_hexpand(True)
                button.set_can_focus(True)
                button.get_style_context().add_class("hud-key")
                button.connect("clicked", self._on_key, keyval_name, character, label)
                self.attach(button, column_index, row_index, span, 1)
                self._buttons.setdefault(label, button)

    def set_target(self, widget: Optional[Gtk.Widget]) -> None:
        """Remember which widget should receive synthesised keys."""
        self._target = widget

    def _resolve_target(self, widget: Optional[Gtk.Widget] = None) -> Optional[Gtk.Widget]:
        """The widget keys should go to: the caller's, ours, or the window's focus."""
        for candidate in (widget, self._target):
            if isinstance(candidate, Gtk.Widget) and candidate.get_can_focus():
                return candidate
        toplevel = self.get_toplevel()
        focus = toplevel.get_focus() if isinstance(toplevel, Gtk.Window) else None
        return focus if isinstance(focus, Gtk.Widget) else None

    def paste_text(self, text: str, widget: Optional[Gtk.Widget] = None) -> bool:
        """Deliver a block of text to the focused widget. True if it was consumed.

        Each receiving widget gets the fastest route that is still real: Vte pastes
        through its own clipboard API, a Gtk.TextView or Gtk.Entry has its buffer
        filled directly, and anything else falls back to one key event per
        character — which is what makes the PASTE button work on a plain GTK
        widget the HUD has never seen before.
        """
        target = self._resolve_target(widget)
        if target is None or not text:
            return False

        if hasattr(target, "paste_clipboard"):  # Vte.Terminal
            Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)
            target.paste_clipboard()
            return True

        buffer_factory = getattr(target, "get_buffer", None)
        if callable(buffer_factory) and self._accepts_text(target):
            buffer = buffer_factory()
            if hasattr(buffer, "insert_at_cursor"):
                buffer.insert_at_cursor(text)
                return True

        for character in text[:4096]:
            keyval = Gdk.unicode_to_keyval(ord(character)) or 0
            if not keyval:
                continue
            for event_type in (Gdk.EventType.KEY_PRESS, Gdk.EventType.KEY_RELEASE):
                target.event(self._event(event_type, keyval, character, 0,
                                         target.get_window() if hasattr(target, "get_window") else None))
        return True

    # -- key delivery ------------------------------------------------------

    def _on_key(self, _button: Gtk.Button, keyval_name: Optional[str], character: Optional[str],
                label: str) -> None:
        if label == "SHIFT":
            self._shift = not self._shift
            self._sync_latches()
            return
        if label == "CAPS":
            self._caps = not self._caps
            self._sync_latches()
            return
        if label == "FN":
            # The Fn key is a firmware-level modifier; X has no keycode for it.
            return
        if label in ("CTRL", "ALTGR"):
            self._modifiers ^= {"CTRL": Gdk.ModifierType.CONTROL_MASK,
                                "ALTGR": Gdk.ModifierType.MOD5_MASK}[label]
            self._sync_latches()
            return

        keyval = 0
        if keyval_name:
            keyval = getattr(Gdk, keyval_name, 0)
        text = character
        if character is not None and character.isalpha():
            text = character.upper() if (self._shift != self._caps) else character

        # Shift is reported for exactly the keys it would modify on a real
        # keyboard: a shifted letter or a shifted symbol, never a bare arrow.
        shift_active = self._shift or (
            self._caps and character is not None and character.isalpha()
        )
        self._deliver(keyval, text, self._state_mask(shift_active))
        # CTRL/ALT/SHIFT/CAPS are one-shot modifiers, exactly like a real
        # keyboard: pressing CTRL and then typing must not leave CTRL stuck down.
        self._modifiers = 0
        self._shift = False
        self._sync_latches()

    def _state_mask(self, shift_override: bool = False) -> int:
        mask = self._modifiers
        if shift_override:
            mask |= Gdk.ModifierType.SHIFT_MASK
        return int(mask)

    def _deliver(self, keyval: int, text: Optional[str], state: int) -> None:
        target = self._resolve_target()
        if target is None:
            if text:
                # Nothing has the keyboard yet, so the key is not dropped: it goes
                # to the clipboard, which is what the user would have to do by
                # hand anyway.
                Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)
            return
        if not keyval:
            keyval = Gdk.unicode_to_keyval(ord(text[0])) if text else 0
        if not keyval:
            return
        window = target.get_window() if hasattr(target, "get_window") else None
        for event_type in (Gdk.EventType.KEY_PRESS, Gdk.EventType.KEY_RELEASE):
            target.event(self._event(event_type, keyval, text, state, window))

    @staticmethod
    def _accepts_text(target: Gtk.Widget) -> bool:
        """False for a read-only widget, so PASTE cannot garble the Vte-fallback notice."""
        editable = getattr(target, "get_editable", None)
        return not callable(editable) or editable() is not False

    @staticmethod
    def _event(event_type, keyval: int, text: Optional[str], state: int,
               window=None) -> "Gdk.EventKey":
        event = Gdk.EventKey()
        event.type = event_type
        # GTK fills in the X event from the target widget during dispatch; the
        # window is set when it is available so Vte's own lookup succeeds.
        event.window = window
        event.send_event = True
        event.time = getattr(Gdk, "CURRENT_TIME", int(time.time() * 1000) & 0xFFFFFFFF)
        event.state = state
        event.keyval = keyval
        event.length = len(text or "")
        event.string = text or ""
        return event

    def _sync_latches(self) -> None:
        for name, active in (("SHIFT", self._shift), ("CAPS", self._caps),
                             ("CTRL", bool(self._modifiers & Gdk.ModifierType.CONTROL_MASK)),
                             ("ALT GR", bool(self._modifiers & Gdk.ModifierType.MOD5_MASK))):
            button = self._buttons.get(name)
            if button is not None:
                button.get_style_context().add_class("hud-key-active" if active else "hud-key")
                if not active:
                    button.get_style_context().remove_class("hud-key-active")
