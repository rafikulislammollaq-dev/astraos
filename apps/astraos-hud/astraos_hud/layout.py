"""The AstraOS HUD's six-region grid, its panel chrome and its single tick.

Region layout
-------------
docs/DESIGN.md screen 6 (docs/reference/Screenshot 2026-10-12 195529.png) is the
locked visual identity, and config/branding.env turns it into ``HUD_COLUMNS =
"1,1,4,1,1,2"``. That token is the authority here.

    weight 1  PANEL / SYSTEM   clock, date, uptime, per-core load, TEMP/MIN/MAX/
                               TASKS, MEMORY, SWAP, TOP PROCESSES, CLIPBOARD
    weight 1  TERMINAL         shell identity, load, cwd, restart, prompt line
    weight 4  MAIN SHELL       the embedded terminal
    weight 1  PANEL            network status, world view, endpoint
    weight 1  -                per-interface traffic, disk I/O
    weight 2  NETWORK          traffic graph, totals, latency history, thermals

    bottom    FILESYSTEM       mounted volumes plus the mount summary bar
    bottom    -                the on-screen keyboard

The header labels reproduce the reference strip exactly: PANEL…SYSTEM at the
left, TERMINAL…MAIN SHELL across the terminal band, PANEL…NETWORK across the
network band.

Gtk.Grid has no per-column weight, so the weights are realised the only way a
grid can express them: one hidden unit column per weight unit, with each region
attached across a span of units. That is what makes the terminal four times the
width of the system column without hard-coding pixel sizes.

One tick, one sampler
---------------------
Every panel is updated from a single ``GLib.timeout_add`` callback that calls
:class:`astraos_hud.systemdata.Collector.collect` once and hands the resulting
immutable snapshot to the widgets. No widget reads /proc. That is not a style
preference: the alternative is a hundred file reads a second spread across six
regions whose repaint timing none of them controls, and a tick that overruns
blocks the terminal the user is typing in.

The tick is wrapped so an unexpected exception inside a sampler or a widget can
never escape into the GLib main loop, where it would tear down the whole HUD —
the one application whose failure takes the desktop's overview mode with it.
"""

from __future__ import annotations

import os
import shlex
import time
from collections import deque
from typing import Deque, List, Optional, Tuple
from urllib.parse import unquote, urlparse

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402  (version must be pinned first)

from . import systemdata as sd  # noqa: E402
from . import widgets as W  # noqa: E402

# Vte 3.91 is the GTK3 namespace in Debian trixie. It is requested, not assumed:
# an image assembled without gir1.2-vte-3.91 must still start, show the fallback
# and say why, rather than dying inside require_version at import time.
VTE_VERSION = "3.91"
try:  # pragma: no cover - depends on what the installed image provides
    gi.require_version("Vte", VTE_VERSION)
    from gi.repository import Vte

    HAVE_VTE = True
except (ValueError, ImportError):  # pragma: no cover
    Vte = None  # type: ignore[assignment]
    HAVE_VTE = False

HAVE_VTE_NOTE = (
    f"Vte {VTE_VERSION} is unavailable in this session (gir1.2-vte-3.91 is not "
    "installed), so the embedded terminal is disabled."
)

WINDOW_TITLE = "AstraOS HUD"


def column_weights() -> Tuple[int, ...]:
    """The HUD_COLUMNS token, as integers.

    Read through systemdata's mirror of config/branding.env rather than imported
    from the repository, because at run time the repository is not there. A
    malformed value falls back to the documented 1,1,4,1,1,2 instead of raising
    during window construction.
    """
    weights: List[int] = []
    for piece in str(sd.HUD_COLUMNS).split(","):
        try:
            value = int(piece.strip())
        except ValueError:
            return (1, 1, 4, 1, 1, 2)
        if value > 0:
            weights.append(value)
    return tuple(weights) if len(weights) >= 2 else (1, 1, 4, 1, 1, 2)


def _compact_rate(value: Optional[float]) -> str:
    """Short rate for a narrow column: '1.4M', '812K', '—' when unmeasured."""
    if value is None:
        return sd.PENDING
    if value >= 1024.0 * 1024.0:
        return f"{value / (1024.0 * 1024.0):.1f}M"
    if value >= 1024.0:
        return f"{value / 1024.0:.0f}K"
    return f"{value:.0f}B"


def _short_path(path: str, home: Optional[str] = None) -> str:
    """'~/src' instead of '/home/user/src' — the shell's own convention."""
    home = home or os.environ.get("HOME") or ""
    if home and path == home:
        return "~"
    if home and path.startswith(home + os.sep):
        return "~" + path[len(home):]
    return path


# ---------------------------------------------------------------------------
# Panel chrome
# ---------------------------------------------------------------------------

def build_css() -> str:
    """The HUD's stylesheet, generated from branding.env tokens.

    Flat near-opaque surfaces separated by 1px hairlines. That is not a
    downgrade from the reference's frosted panels: GTK3 has no backdrop-filter,
    and plan §7.1 forbids the compositing pass a blur would need, so the depth is
    produced with colour and a border — which is what branding.env says in the
    comment above its own HUD section.
    """
    palette = sd.PALETTE

    def css(token: str, alpha: float = 1.0) -> str:
        red, green, blue = sd.hex_to_rgb(palette[token])
        return f"rgba({int(red * 255)},{int(green * 255)},{int(blue * 255)},{alpha})"

    return f"""
    window.hud {{ background-color: {css('COLOR_VOID')}; }}
    .hud-panel {{
        background-color: {css('COLOR_SURFACE')};
        border: 1px solid {css('COLOR_HAIRLINE_BASE')};
    }}
    .hud-label {{
        color: {css('COLOR_TEXT_FAINT')};
        font-family: "{sd.FONT_MONO}";
        font-size: 9px;
    }}
    .hud-value {{
        color: {css('COLOR_TEXT')};
        font-family: "{sd.FONT_MONO}";
        font-size: 9px;
    }}
    .hud-body {{
        color: {css('COLOR_TEXT')};
        font-family: "{sd.FONT_MONO}";
        font-size: 10px;
    }}
    .hud-note {{ color: {css('COLOR_TEXT_DIM')}; font-size: 10px; }}
    .hud-chip {{
        background-color: {css('COLOR_SURFACE_RAISED')};
        border: 1px solid {css('COLOR_HAIRLINE_BASE')};
        border-radius: 4px;
        color: {css('COLOR_TEXT')};
        font-family: "{sd.FONT_MONO}";
        font-size: 9px;
        padding: 2px 8px;
        min-height: 16px;
    }}
    .hud-chip:hover {{ border-color: {css('COLOR_HAIRLINE_HOT')}; }}
    .hud-chip:focus {{ border-color: {css('COLOR_HAIRLINE_HOT')}; }}
    .hud-key {{
        background-color: {css('COLOR_SURFACE_RAISED')};
        border: 1px solid {css('COLOR_HAIRLINE_BASE')};
        border-radius: 4px;
        color: {css('COLOR_TEXT_DIM')};
        font-family: "{sd.FONT_MONO}";
        font-size: 9px;
        padding: 1px 4px;
        min-height: 18px;
    }}
    .hud-key:hover {{ color: {css('COLOR_TEXT')}; border-color: {css('COLOR_HAIRLINE_HOT')}; }}
    .hud-key:focus {{ border-color: {css('COLOR_HAIRLINE_HOT')}; }}
    .hud-key-active {{
        background-color: {css('COLOR_HAIRLINE_HOT')};
        color: {css('COLOR_VOID')};
    }}
    .hud-terminal {{ background-color: {css('COLOR_VOID_2')}; color: {css('COLOR_TEXT')}; }}
    """


def install_css(screen: Optional[Gdk.Screen] = None) -> None:
    """Apply the generated stylesheet screen-wide, at GTK's user priority.

    800 (GTK_STYLE_PROVIDER_PRIORITY_USER) is deliberate: it outranks the theme's
    own 600 so the HUD keeps AstraOS's palette on a machine whose GTK theme is
    something else, while a user's ~/.config/gtk-3.0/gtk.css — loaded at the same
    priority, later — can still override the HUD.
    """
    screen = screen or Gdk.Screen.get_default()
    if screen is None:
        return  # no display: nothing to style, and nothing to crash
    provider = Gtk.CssProvider()
    provider.load_from_data(build_css().encode("utf-8"))
    Gtk.StyleContext.add_provider_for_screen(screen, provider, 800)


class Panel(Gtk.Box):
    """One labelled region: a micro-label top-left, a value top-right, content below.

    The header is what makes the HUD read as an instrument panel rather than as a
    pile of windows, and it is built from plain GTK labels so that every header in
    the application shares one baseline, one font and one size.
    """

    def __init__(self, title: str = "", value: str = "", *, spacing: int = 4) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
        self.get_style_context().add_class("hud-panel")
        self.set_border_width(6)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._title = self._header_label(title, "hud-label", align=0.0)
        self._value = self._header_label(value, "hud-value", align=1.0)
        header.pack_start(self._title, True, True, 0)
        header.pack_end(self._value, False, False, 0)
        self.pack_start(header, False, False, 0)

        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.pack_start(self.body, True, True, 0)

    @staticmethod
    def _header_label(text: str, style: str, align: float) -> Gtk.Label:
        label = Gtk.Label(label=text.upper())
        label.get_style_context().add_class(style)
        label.set_xalign(align)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_single_line_mode(True)
        return label

    def set_title(self, text: str) -> None:
        self._title.set_text(text.upper())

    def set_value(self, text: str) -> None:
        self._value.set_text(text.upper())


def body_label(text: str = "", *, style: str = "hud-body", wrap: bool = False,
               xalign: float = 0.0) -> Gtk.Label:
    label = Gtk.Label(label=text)
    label.get_style_context().add_class(style)
    label.set_xalign(xalign)
    label.set_line_wrap(wrap)
    return label


# ---------------------------------------------------------------------------
# Terminal
# ---------------------------------------------------------------------------

class TerminalPane(Gtk.Box):
    """A real shell, embedded in the MAIN SHELL region.

    Vte is used when it is present, and a read-only Gtk.TextView takes its place
    when it is not. The fallback is not decoration: an image assembled without
    gir1.2-vte-3.91 must still start and must still say plainly what is missing
    and which command would have run, rather than showing an empty black box that
    looks like a broken application.

    The shell gets an explicit environment instead of an inherited one: TERM has
    to name a real terminal or the shell falls back to an 80-column dumb terminal
    inside a wide panel, and GTK/GDK variables are dropped because a child that
    believes it shares the HUD's own X connection misbehaves in ways that are
    miserable to debug.
    """

    def __init__(self, shell: Optional[str] = None, working_directory: Optional[str] = None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.shell = shell or os.environ.get("SHELL") or "/bin/bash"
        self.working_directory = working_directory or os.environ.get("HOME") or os.getcwd()
        self.terminal = None
        self.fallback: Optional[Gtk.TextView] = None
        self.pid: Optional[int] = None
        self.running = False
        self.status_note: str = ""
        self._started_at: Optional[float] = None

        if HAVE_VTE:
            self._build_vte()
        else:
            self._build_fallback(HAVE_VTE_NOTE)

    # -- construction ------------------------------------------------------

    def _build_vte(self) -> None:  # pragma: no cover - needs a Vte session
        self.terminal = Vte.Terminal()
        self.terminal.set_scrollback_lines(5000)
        self.terminal.set_scroll_on_output(True)
        self.terminal.set_scroll_on_keystroke(True)
        self.terminal.set_mouse_autohide(True)
        self.terminal.set_allow_hyperlink(False)
        try:
            self.terminal.set_colors(
                foreground=sd.hex_to_rgb(sd.PALETTE["COLOR_TEXT"]),
                background=sd.hex_to_rgb(sd.PALETTE["COLOR_VOID_2"]),
                cursor=sd.hex_to_rgb(sd.PALETTE["COLOR_HUD_TEAL"]),
            )
        except (AttributeError, TypeError):
            pass  # colour APIs move between Vte versions; the shell theme is optional
        self.terminal.connect("child-exited", self._on_child_exited)
        self.terminal.connect("size-allocate", lambda *_a: self._resize_pty())
        self.pack_start(self.terminal, True, True, 0)
        self.start()

    def _build_fallback(self, reason: str) -> None:
        view = Gtk.TextView()
        view.set_editable(False)
        view.set_monospace(True)
        view.set_cursor_visible(False)
        view.set_wrap_mode(Gtk.WrapMode.CHAR)
        view.get_style_context().add_class("hud-terminal")
        view.get_buffer().set_text(self._fallback_text(reason))
        self.fallback = view
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.add(view)
        self.pack_start(scroller, True, True, 0)

    def _fallback_text(self, reason: str) -> str:
        command = " ".join(shlex.quote(part) for part in (self.shell,))
        return "\n".join([
            "",
            "  ASTRA OS   main shell",
            "  " + "-" * 44,
            "",
            f"  {reason}",
            "",
            "  The shell that would run here:",
            "",
            f"      {command}",
            f"      cwd:   {self.working_directory}",
            "",
            "  Every other panel on this screen is live; only the embedded",
            "  terminal is unavailable. Install gir1.2-vte-3.91 and restart",
            "  the session to enable it.",
            "",
        ])

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> bool:
        """Spawn the shell. Returns False when it could not be started."""
        if not HAVE_VTE or self.terminal is None:
            return False
        argv = [self.shell]
        cwd = self.working_directory if os.path.isdir(self.working_directory) else None
        try:
            # Argument order matters more than it looks. The Python binding for
            # Vte.Terminal.spawn_async() is:
            #
            #   (pty_flags, working_directory, argv, envv, spawn_flags,
            #    child_setup, timeout: int, cancellable, callback, user_data)
            #
            # `timeout` is an int and is NOT optional (-1 means the library
            # default; G_MAXINT waits indefinitely), and the old pre-0.60 shape
            # that put user_data before cancellable is gone. This call used to
            # pass None for the timeout and -1 for the cancellable, which raised
            # TypeError on the first conversion - swallowed by the handler below
            # and reported as "the shell could not be started", so the embedded
            # terminal silently stayed black on every machine that had Vte.
            # The callback was also landing in user_data, so _on_spawned never
            # ran even when the spawn would otherwise have succeeded.
            self.terminal.spawn_async(
                Vte.PtyFlags.DEFAULT,
                cwd,
                argv,
                self._child_environment(),
                GLib.SpawnFlags.SEARCH_PATH_FROM_ENVP,
                None,
                -1,
                None,
                self._on_spawned,
                None,
            )
        except (GLib.Error, TypeError) as error:
            self._on_spawned(self.terminal, None, error)
            return False
        return True

    def restart(self) -> None:
        if self.terminal is None:
            self._append_fallback(f"\n  Vte is unavailable; there is no shell to restart.\n")
            return
        self.terminal.reset(True, True)  # pragma: no cover
        self.start()

    def _on_spawned(self, _terminal, pid, error, *_unused) -> None:  # pragma: no cover
        if error is not None or pid is None:
            self.running = False
            self.pid = None
            message = getattr(error, "message", None) or "unknown error"
            self.status_note = message
            self._append_fallback(
                f"\n  The shell could not be started: {message}\n"
                f"  Tried: {self.shell} in {self.working_directory}\n"
            )
            return
        self.pid = int(pid)
        self.running = True
        self._started_at = time.time()

    def _on_child_exited(self, _terminal, status) -> None:  # pragma: no cover
        self.running = False
        # Vte hands over the exit status itself, not a waitpid() word.
        self._append_fallback(
            f"\n  [process exited with status {status} after "
            f"{self.elapsed()}]\n"
        )

    def _resize_pty(self) -> None:  # pragma: no cover
        """Tell Vte its real character grid so full-screen programs reflow."""
        if self.terminal is None:
            return
        try:
            columns = self.terminal.get_column_count()
            rows = self.terminal.get_row_count()
            if columns > 0 and rows > 0:
                self.terminal.set_size(columns, rows)
        except (AttributeError, TypeError):
            pass  # a Vte build without the grid accessors: keep its own default

    def _append_fallback(self, text: str) -> None:
        """Surface a shell lifecycle message even when there is no Vte to print it."""
        if self.fallback is not None:
            buffer = self.fallback.get_buffer()
            buffer.insert_at_cursor(text)

    def _child_environment(self) -> dict:
        """A clean, honest environment for the shell."""
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith(("GTK_", "GDK_", "GIO_", "VTE_"))}
        environment.update({
            "TERM": "xterm-256color",
            "COLORTERM": "truecolor",
            "ASTRAOS_HUD": "1",
        })
        return environment

    # -- introspection for the TERMINAL panel ------------------------------

    def grid_size(self) -> str:
        if self.terminal is None:
            return sd.NA
        try:  # pragma: no cover
            return f"{self.terminal.get_column_count()}×{self.terminal.get_row_count()}"
        except AttributeError:  # pragma: no cover
            return sd.NA

    def current_directory(self) -> str:
        """The shell's working directory, read from Vte when it knows it.

        Vte exposes this as a URI property; where it is absent the directory the
        shell was started in is still the truthful answer, so it is used rather
        than inventing a path.
        """
        if self.terminal is not None:  # pragma: no cover
            try:
                uri = self.terminal.get_current_directory_uri()
            except (AttributeError, TypeError):
                uri = None
            if uri:
                parsed = urlparse(uri)
                if parsed.scheme == "file":
                    return unquote(parsed.path)
        return self.working_directory

    def elapsed(self) -> str:
        return sd.format_duration(None if self._started_at is None else time.time() - self._started_at)

    def status_text(self) -> str:
        """One-line state for the TERMINAL region's header value."""
        if not HAVE_VTE:
            return "VTE UNAVAILABLE"
        if self.running:
            return f"RUNNING PID {self.pid}"
        if self.status_note:
            # The reason the spawn failed used to be written to status_note and
            # then never read by anything, so a machine with Vte installed that
            # could not start a shell showed a black panel and the bare words
            # SHELL NOT RUNNING. With Vte present there is no fallback TextView
            # to write into either (see _append_fallback), which left the
            # failure with no channel to the screen at all. The header is the
            # one surface that always exists, so it carries the reason.
            return f"SHELL NOT RUNNING - {self.status_note.upper()}"
        return "SHELL EXITED" if self.pid is not None else "SHELL NOT RUNNING"


# ---------------------------------------------------------------------------
# The HUD window
# ---------------------------------------------------------------------------

class HudWindow(Gtk.Window):
    """The HUD: six regions across the top, the filesystem strip and keyboard below."""

    def __init__(self, *, collector: sd.Collector, fullscreen: bool = True,
                 interval_ms: int = sd.HUD_SAMPLE_INTERVAL_MS, escape_quits: bool = False,
                 overlay: bool = False) -> None:
        super().__init__(title=WINDOW_TITLE)
        self._collector = collector
        self._interval_ms = max(200, int(interval_ms))
        self._escape_quits = escape_quits
        self._fullscreen = fullscreen
        self._tick_source = 0
        self._keyboard_target: Optional[Gtk.Widget] = None
        self._last_tick_seconds = 0.0
        self._tick_overruns = 0
        self._wave_labels: List[Gtk.Label] = []
        self._waves: List[W.Waveform] = []

        self.set_decorated(False)
        self.set_resizable(True)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        if overlay:
            # DOCK makes xfwm4 treat the HUD as a panel-like surface: no
            # decorations, no alt-tab entry, never covered by an ordinary window.
            self.set_type_hint(Gdk.WindowTypeHint.DOCK)
        self.get_style_context().add_class("hud")
        self.set_default_size(1280, 800)
        if fullscreen:
            self.fullscreen()

        self._build()
        self.connect("key-press-event", self._on_key_press)
        self.connect("destroy", self._on_destroy)

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        weights = column_weights()
        units = sum(weights)

        grid = Gtk.Grid()
        grid.set_row_spacing(1)
        grid.set_column_spacing(1)
        grid.set_hexpand(True)
        grid.set_vexpand(True)
        self.add(grid)

        builders = (
            self._build_system_panel,
            self._build_terminal_panel,
            self._build_shell_panel,
            self._build_status_panel,
            self._build_links_panel,
            self._build_traffic_panel,
        )
        left = 0
        for weight, builder in zip(weights, builders):
            builder(grid, left, weight)
            left += weight

        # The bottom strip follows the same weights: the filesystem band takes the
        # system + terminal + shell units, the keyboard the network units.
        keyboard_left = left - weights[-1] - weights[-2]
        filesystem = Panel("FILESYSTEM")
        self._build_filesystem(filesystem)
        grid.attach(filesystem, 0, 1, max(1, keyboard_left), 1)

        keyboard = Panel("")
        self._keyboard = W.OnScreenKeyboard()
        keyboard.body.add(self._keyboard)
        grid.attach(keyboard, keyboard_left, 1, units - keyboard_left, 1)

    # -- region 1: PANEL / SYSTEM ------------------------------------------

    def _build_system_panel(self, grid: Gtk.Grid, left: int, span: int) -> None:
        panel = Panel("PANEL", "SYSTEM")
        grid.attach(panel, left, 0, span, 1)
        self._system_panel = panel

        self._clock = W.ClockDisplay()
        panel.body.add(self._clock)
        panel.connect("size-allocate",
                      lambda *_a: self._clock.resize_for(panel.get_allocated_width()))

        self._date_row = W.DataTable(
            (("DATE", 0.30, "left"), ("UPTIME", 0.28, "left"), ("TYPE", 0.20, "left"),
             ("CPUMIN", 0.22, "right")),
            row_height=14,
        )
        panel.body.add(self._date_row)

        usage_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        usage_row.add(body_label("CPU USAGE"))
        self._cpu_model = body_label("", style="hud-note")
        self._cpu_model.set_xalign(1.0)
        self._cpu_model.set_ellipsize(Pango.EllipsizeMode.END)
        usage_row.pack_end(self._cpu_model, True, True, 0)
        panel.body.add(usage_row)

        # One waveform per physical core, capped at four rows so a many-thread
        # machine cannot push MEMORY and TOP PROCESSES off the panel.
        self._wave_holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        panel.body.add(self._wave_holder)

        self._micro_columns = W.DataTable(
            (("TEMP", 0.25, "left"), ("MIN", 0.25, "left"), ("MAX", 0.25, "left"),
             ("TASKS", 0.25, "right")),
            row_height=14,
        )
        panel.body.add(self._micro_columns)

        memory_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        memory_row.add(body_label("MEMORY"))
        self._memory_detail = body_label("", style="hud-note")
        self._memory_detail.set_xalign(1.0)
        self._memory_detail.set_ellipsize(Pango.EllipsizeMode.END)
        memory_row.pack_end(self._memory_detail, True, True, 0)
        panel.body.add(memory_row)

        self._memory_blocks = W.BlockMeter(blocks=5)
        panel.body.add(self._memory_blocks)

        self._swap_bar = W.MeterBar(height=8)
        panel.body.add(self._swap_bar)

        self._processes = W.DataTable(
            (("PID", 0.24, "left"), ("NAME", 0.36, "left"), ("CPU%", 0.20, "right"),
             ("MEM%", 0.20, "right")),
            row_height=14,
        )
        panel.body.add(self._processes)

        panel.body.add(body_label("CLIPBOARD ACCESS"))
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        copy_button = Gtk.Button(label="COPY")
        paste_button = Gtk.Button(label="PASTE")
        for button in (copy_button, paste_button):
            button.get_style_context().add_class("hud-chip")
            button.set_hexpand(True)
            buttons.pack_start(button, True, True, 0)
        copy_button.connect("clicked", self._on_copy)
        paste_button.connect("clicked", self._on_paste)
        panel.body.add(buttons)

        self._status_note = body_label("", style="hud-note", wrap=True)
        panel.body.add(self._status_note)

    # -- region 2: TERMINAL ------------------------------------------------

    def _build_terminal_panel(self, grid: Gtk.Grid, left: int, span: int) -> None:
        panel = Panel("TERMINAL")
        grid.attach(panel, left, 0, span, 1)
        self._terminal_panel = panel

        self._shell_table = W.DataTable(
            (("SHELL", 0.55, "left"), ("GRID", 0.45, "right")),
            row_height=14,
        )
        panel.body.add(self._shell_table)

        self._load_table = W.DataTable(
            (("LOAD 1", 0.34, "left"), ("LOAD 5", 0.33, "left"), ("LOAD 15", 0.33, "right")),
            row_height=14,
        )
        panel.body.add(self._load_table)

        self._cwd_label = body_label("", style="hud-note", wrap=True)
        panel.body.add(self._cwd_label)

        restart = Gtk.Button(label="RESTART SHELL")
        restart.get_style_context().add_class("hud-chip")
        restart.connect("clicked", lambda _b: self._restart_shell())
        panel.body.pack_start(restart, False, False, 0)

        panel.body.pack_start(Gtk.Box(), True, True, 0)  # pushes the prompt to the bottom
        self._prompt = W.PromptLabel()
        panel.body.pack_end(self._prompt, False, False, 0)

    # -- region 3: MAIN SHELL ---------------------------------------------

    def _build_shell_panel(self, grid: Gtk.Grid, left: int, span: int) -> None:
        panel = Panel("", "MAIN SHELL")
        grid.attach(panel, left, 0, span, 1)
        self._shell_panel = panel
        self._terminal = TerminalPane()
        panel.body.add(self._terminal)
        self._shell_footer = body_label("", style="hud-note")
        panel.body.pack_end(self._shell_footer, False, False, 0)
        if self._terminal.terminal is not None:  # pragma: no cover - needs Vte
            self._terminal.terminal.connect("focus-in-event", self._on_focus_in)

    # -- region 4: PANEL (network status + world view) --------------------

    def _build_status_panel(self, grid: Gtk.Grid, left: int, span: int) -> None:
        panel = Panel("PANEL")
        grid.attach(panel, left, 0, span, 1)
        self._network_panel = panel

        panel.body.add(body_label("NETWORK STATUS"))
        self._network_status = W.DataTable(
            (("STATE", 0.32, "left"), ("IPV4", 0.44, "left"), ("PING", 0.24, "right")),
            row_height=14,
        )
        panel.body.add(self._network_status)

        panel.body.add(body_label("WORLD VIEW"))
        self._globe = W.GlobeView(height=112)
        panel.body.add(self._globe)

        panel.body.add(body_label("ENDPOINT"))
        self._endpoint_table = W.DataTable(
            (("GATEWAY", 0.6, "left"), ("LABEL", 0.4, "right")),
            row_height=14,
        )
        panel.body.add(self._endpoint_table)

    # -- region 5: per-interface links ------------------------------------

    def _build_links_panel(self, grid: Gtk.Grid, left: int, span: int) -> None:
        panel = Panel("", "")
        grid.attach(panel, left, 0, span, 1)
        self._links_panel = panel

        panel.body.add(body_label("INTERFACES"))
        self._interfaces = W.DataTable(
            (("IFACE", 0.40, "left"), ("DOWN", 0.30, "right"), ("UP", 0.30, "right")),
            row_height=14,
        )
        panel.body.add(self._interfaces)

        panel.body.add(body_label("DISK"))
        self._disk_table = W.DataTable(
            (("READ", 0.5, "left"), ("WRITE", 0.5, "right")),
            row_height=14,
        )
        panel.body.add(self._disk_table)

    # -- region 6: NETWORK (traffic graph + latency) ----------------------

    def _build_traffic_panel(self, grid: Gtk.Grid, left: int, span: int) -> None:
        panel = Panel("", "NETWORK")
        grid.attach(panel, left, 0, span, 1)
        self._traffic_panel = panel

        panel.body.add(body_label("NETWORK TRAFFIC"))
        self._traffic_rates = W.DataTable(
            (("UP", 0.5, "left"), ("DOWN", 0.5, "right")), header=False, row_height=14,
        )
        panel.body.add(self._traffic_rates)

        self._traffic_graph = W.TrafficGraph(height=88)
        panel.body.add(self._traffic_graph)

        self._traffic_total = W.MeterBar(height=9, show_percent=False)
        panel.body.add(self._traffic_total)

        panel.body.add(body_label("GATEWAY LATENCY"))
        # The latency panel is the same rolling-graph widget with a different
        # formatter: one graph implementation, two units, no duplicated drawing.
        self._latency_graph = W.TrafficGraph(
            height=58,
            formatter=lambda value: f"{value:.0f}ms",
            floor=1.0,
            scale_caption="MAX PING",
        )
        panel.body.add(self._latency_graph)

        self._thermal_label = body_label("", style="hud-note", wrap=True)
        panel.body.add(self._thermal_label)

    # -- bottom strip: FILESYSTEM -----------------------------------------

    def _build_filesystem(self, panel: Panel) -> None:
        self._filesystems = W.FilesystemStrip(height=96)
        panel.body.add(self._filesystems)
        self._mount_bar = W.MeterBar(height=10)
        panel.body.pack_end(self._mount_bar, False, False, 0)

    # -- clipboard ---------------------------------------------------------

    def _on_copy(self, _button: Gtk.Button) -> None:
        """COPY: bring the PRIMARY selection (what a terminal marks) to the clipboard.

        Gtk.Clipboard is used directly rather than an intermediate entry field,
        which is what makes the pair work with the embedded terminal, with other
        AstraOS windows and with xfce4-clipman's clipboard manager alike. store()
        is called so the value survives the HUD being closed.
        """
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        text = Gtk.Clipboard.get(Gdk.SELECTION_PRIMARY).wait_for_text()
        if not text and self._terminal.terminal is not None:  # pragma: no cover
            try:
                text = self._terminal.terminal.get_text_selected() or None
            except AttributeError:
                text = None
        if not text:
            self._status_note.set_text("NOTHING SELECTED TO COPY")
            return
        clipboard.set_text(text, -1)
        clipboard.store()
        self._status_note.set_text(f"COPIED {len(text)} CHARACTERS TO CLIPBOARD")

    def _on_paste(self, _button: Gtk.Button) -> None:
        """PASTE: send the clipboard into whatever currently has the keyboard."""
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        text = clipboard.wait_for_text()
        if not text:
            self._status_note.set_text("CLIPBOARD IS EMPTY")
            return
        target = self._keyboard_target or self.get_focus()
        if self._keyboard.paste_text(text, target):
            self._status_note.set_text(f"PASTED {len(text)} CHARACTERS")
        else:
            self._status_note.set_text("CLICK THE TERMINAL FIRST")

    # -- focus tracking for the on-screen keyboard -------------------------

    def _on_focus_in(self, widget: Gtk.Widget, _event) -> None:
        self._keyboard_target = widget
        self._keyboard.set_target(widget)

    # -- the tick ----------------------------------------------------------

    def start_ticking(self) -> None:
        """Begin sampling. One timer drives the entire application."""
        if self._tick_source:
            return
        self._tick_once()  # paint immediately rather than after a blank second
        self._tick_source = GLib.timeout_add(self._interval_ms, self._tick_once)

    def _tick_once(self) -> bool:
        """One collection pass. Returns True so GLib keeps the timer alive.

        The broad excepts are deliberate and are the reason this HUD cannot take a
        session down: an unexpected error in a sampler or a widget is reported in
        the status line and the tick continues, because a dashboard that vanishes
        is worse than one that shows a stale number.
        """
        started = time.perf_counter()
        try:
            snapshot = self._collector.collect()
        except Exception as error:  # noqa: BLE001 - see docstring
            self._status_note.set_text(f"SAMPLER ERROR: {error}")
            return True
        try:
            self._apply(snapshot)
        except Exception as error:  # noqa: BLE001
            self._status_note.set_text(f"DISPLAY ERROR: {error}")
            return True

        elapsed = time.perf_counter() - started
        self._last_tick_seconds = elapsed
        if elapsed > (self._interval_ms / 1000.0) * 0.5:
            self._tick_overruns += 1
        return True

    # -- applying a snapshot ----------------------------------------------

    def _apply(self, snapshot: sd.SystemSnapshot) -> None:
        """Push one snapshot into every panel. No sampling happens in here."""
        self._clock.set_time(snapshot.timestamp)
        self._cpu_model.set_text(snapshot.identity.cpu_model)

        uptime = snapshot.load.uptime_seconds
        self._date_row.set_rows([[
            time.strftime("%d %b %Y", time.localtime(snapshot.timestamp)),
            sd.format_uptime(uptime),
            "LINUX",
            f"{uptime / 60:.0f}" if uptime is not None else sd.NA,
        ]])

        self._apply_cpu(snapshot)
        self._apply_memory(snapshot)
        self._apply_processes(snapshot)
        self._apply_network(snapshot)
        self._apply_filesystems(snapshot)
        self._apply_shell(snapshot)

    def _apply_cpu(self, snapshot: sd.SystemSnapshot) -> None:
        rows = list(snapshot.cpu_core_rows[:4])

        # Grow or shrink the waveform stack to match this machine's core count.
        while len(self._waves) < len(rows):
            holder = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            label = body_label("", style="hud-note")
            holder.pack_start(label, False, False, 0)
            waveform = W.Waveform(capacity=sd.HUD_TRAFFIC_SAMPLES, height=28)
            waveform.set_hexpand(True)
            holder.pack_start(waveform, True, True, 0)
            self._wave_holder.add(holder)
            self._waves.append(waveform)
            self._wave_labels.append(label)
        while len(self._waves) > len(rows):
            self._wave_holder.remove(self._wave_holder.get_children()[-1])
            self._waves.pop()
            self._wave_labels.pop()

        core_count = len(snapshot.cpu.cores) if snapshot.cpu else 0
        for index, waveform in enumerate(self._waves):
            value = rows[index]
            waveform.push(value)
            first = index * 2 + 1
            last = min(first + 1, max(1, core_count))
            label = f"#{first}-{last}" if last > first else f"#{first}"
            average = f"{value:.0f}%" if value is not None else sd.PENDING
            self._wave_labels[index].set_text(f"{label}  AVG {average}")

        temperatures = snapshot.temperatures
        hottest = [t.celsius for t in temperatures if t.celsius is not None]
        self._micro_columns.set_rows([[
            temperatures[0].label if temperatures else "TEMP",
            f"{temperatures[0].celsius:.0f}°C" if temperatures and temperatures[0].celsius is not None else sd.NA,
            f"{max(hottest):.0f}°C" if hottest else sd.NA,
            str(snapshot.load.tasks) if snapshot.load.tasks is not None else sd.NA,
        ]])

        battery = snapshot.battery
        self._system_panel.set_value(
            f"SYSTEM {battery.percent:.0f}%" if battery.present and battery.percent is not None else "SYSTEM"
        )

    def _apply_memory(self, snapshot: sd.SystemSnapshot) -> None:
        memory = snapshot.memory
        used, total = sd.format_bytes(memory.used_bytes), sd.format_bytes(memory.total_bytes)
        self._memory_blocks.set_value(memory.percent, caption="MEMORY",
                                      detail=f"USING {used} OUT OF {total}")
        self._memory_detail.set_text(f"{used} / {total}")
        self._swap_bar.set_value(
            memory.swap_percent,
            caption="SWAP",
            detail=(f"{sd.format_bytes(memory.swap_used_bytes)} OF {sd.format_bytes(memory.swap_total_bytes)}"
                    if memory.swap_total_bytes else "NO SWAP CONFIGURED"),
            colour_token=("COLOR_HUD_TEAL" if (memory.swap_percent or 0.0) < 50.0
                          else "COLOR_HUD_RED"),
        )

    def _apply_processes(self, snapshot: sd.SystemSnapshot) -> None:
        self._processes.set_rows([
            [
                str(process.pid),
                process.name or "?",
                sd.PENDING if process.cpu_percent is None else f"{process.cpu_percent:.1f}%",
                sd.PENDING if process.mem_percent is None else f"{process.mem_percent:.1f}%",
            ]
            for process in snapshot.processes
        ])

    def _apply_network(self, snapshot: sd.SystemSnapshot) -> None:
        network = snapshot.network

        # A gateway that does not answer, and a probe the session may not run at
        # all, are different situations and are shown differently.
        if network.ping_ms is not None:
            ping = f"{network.ping_ms:.0f}ms"
        elif network.gateway and not network.ping_supported:
            ping = "NO ICMP"
        else:
            ping = sd.NA
        self._network_status.set_rows([[network.state, network.ipv4 or sd.NA, ping]])
        self._network_panel.set_value(network.interface or "NETWORK")

        gateway_endpoint = snapshot.endpoints.get(network.gateway) if network.gateway else None
        self._globe.set_endpoints(dict(snapshot.endpoints))
        self._endpoint_table.set_rows([[
            network.gateway or sd.NA,
            (gateway_endpoint.label[:16] if gateway_endpoint else sd.NA),
        ]])

        self._interfaces.set_rows([
            [traffic.name, _compact_rate(traffic.rx_bytes_per_second),
             _compact_rate(traffic.tx_bytes_per_second)]
            for traffic in network.interfaces[:6]
        ] or [[sd.NA, sd.NA, sd.NA]])

        self._disk_table.set_rows([[_compact_rate(snapshot.disk_read_rate),
                                    _compact_rate(snapshot.disk_write_rate)]])

        self._traffic_rates.set_rows([[
            f"UP {sd.format_rate(network.tx_bytes_per_second)}",
            f"DOWN {sd.format_rate(network.rx_bytes_per_second)}",
        ]])
        self._traffic_graph.push(network.tx_bytes_per_second, network.rx_bytes_per_second,
                                 network.interface or "")
        self._traffic_total.set_value(
            None, caption="TOTAL",
            detail=f"{sd.format_bytes(network.total_tx_bytes)} OUT · "
                   f"{sd.format_bytes(network.total_rx_bytes)} IN",
        )
        self._latency_graph.push(network.ping_ms, network.ping_ms, "GATEWAY")

        self._thermal_label.set_text(
            " · ".join(f"{t.label} {t.celsius:.0f}°C" for t in snapshot.temperatures
                       if t.celsius is not None) or "NO TEMPERATURE SENSORS EXPOSED"
        )

        load = snapshot.load
        self._load_table.set_rows([[
            f"{load.one:.2f}" if load.one is not None else sd.NA,
            f"{load.five:.2f}" if load.five is not None else sd.NA,
            f"{load.fifteen:.2f}" if load.fifteen is not None else sd.NA,
        ]])

    def _apply_filesystems(self, snapshot: sd.SystemSnapshot) -> None:
        filesystems = snapshot.filesystems
        self._filesystems.set_mounts(filesystems.mounts, filesystems.unreadable)
        fullest = max(filesystems.mounts, key=lambda mount: mount.percent or 0.0, default=None)
        if fullest is None:
            self._mount_bar.set_value(None, caption="MOUNT")
            return
        self._mount_bar.set_value(
            fullest.percent,
            caption=f"MOUNT {_short_path(fullest.mountpoint)}",
            detail=f"USING {sd.format_bytes(fullest.used_bytes)} OF {sd.format_bytes(fullest.total_bytes)}",
            colour_token=("COLOR_HUD_RED" if (fullest.percent or 0.0) >= 90.0
                          else "COLOR_HUD_TEAL"),
        )

    def _apply_shell(self, snapshot: sd.SystemSnapshot) -> None:
        self._terminal_panel.set_value(self._terminal.status_text())
        self._shell_table.set_rows([[os.path.basename(self._terminal.shell),
                                     self._terminal.grid_size()]])
        cwd = self._terminal.current_directory()
        self._cwd_label.set_text(f"CWD {_short_path(cwd)}")
        self._prompt.set_prompt(snapshot.identity.user, snapshot.identity.hostname,
                                _short_path(cwd))
        self._shell_footer.set_text(f"{snapshot.identity.kernel} · shell up {self._terminal.elapsed()}")
        focus = self.get_focus()
        if focus is not None:
            self._keyboard_target = focus

    def _restart_shell(self) -> None:
        self._terminal.restart()
        self._status_note.set_text("SHELL RESTART REQUESTED")

    # -- window behaviour --------------------------------------------------

    def _on_key_press(self, _widget: Gtk.Widget, event: Gdk.EventKey) -> bool:
        """Escape hides (or quits), F11 toggles fullscreen, Ctrl+Q quits.

        GTK delivers key events to the focused child first, so when the embedded
        terminal holds the keyboard these are the terminal's own Escape and F11 —
        which is exactly what makes the on-screen keyboard's ESC key usable for
        sending Escape to a running program.
        """
        keyval = event.keyval
        if keyval == Gdk.KEY_F11:
            self.toggle_fullscreen()
            return True
        if keyval == Gdk.KEY_Escape:
            self.destroy() if self._escape_quits else self.hide()
            return True
        if keyval == Gdk.KEY_q and event.state & Gdk.ModifierType.CONTROL_MASK:
            self.destroy()
            return True
        return False

    def toggle_fullscreen(self) -> None:
        self._fullscreen = not self._fullscreen
        if self._fullscreen:
            self.fullscreen()
        else:
            self.unfullscreen()

    def _on_destroy(self, *_args) -> None:
        if self._tick_source:
            GLib.source_remove(self._tick_source)
            self._tick_source = 0
        self._collector.close()
        if Gtk.main_level():
            Gtk.main_quit()

    def show_hud(self) -> None:
        self.show_all()
        self.present()
