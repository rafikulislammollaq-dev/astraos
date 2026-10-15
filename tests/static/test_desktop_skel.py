"""Desktop skeleton tests: the files a first login reads.

WHAT THIS FILE EXISTS FOR

A 0.2.0 live session looked like Debian, not AstraOS, on top of the AstraOS wallpaper.
Nothing had failed to build. Every file was present, the ISO validated, and the
decorations, the wallpaper and the window theme were visibly AstraOS - but the taskbar
was Debian's stock one, and the desktop therefore read as "nothing new".

The cause was a file shape. The taskbar layout in xfce4-panel.xml was nested inside a
`<property name="config">` wrapper, so it landed at /config/panels/panel-1/... and the
per-plugin settings sat at the channel root as /plugin-N/... . xfce4-panel 4.20 (Debian
13) reads /panels/panel-1/... and /plugins/plugin-N/... . It does not migrate the
wrapper and it does not warn about properties it does not recognise: it simply saw no
panel, and built Debian's default layout instead.

That is the worst kind of bug in a desktop configuration - total, silent, and visible
only to somebody who knows what the screen was supposed to look like - so it gets a
test rather than a comment. The paths asserted below are the ones xfce4-panel itself
writes, and they are asserted structurally, through a parser, because a grep for
"plugin-3" passes on the broken file too.

The rest of the file defends the same class of mistake elsewhere in the skeleton: a
channel file whose name disagrees with its channel, a panel that pins a launcher the
image does not ship. Both are invisible until somebody logs in.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

DESCRIPTION = "the desktop skeleton is written where the session actually reads it"

REPO_ROOT = Path(__file__).resolve().parents[2]

SKEL_XFCONF = REPO_ROOT / "desktop" / "skel" / ".config" / "xfce4" / "xfconf" / "xfce-perchannel-xml"
PANEL_FILE = SKEL_XFCONF / "xfce4-panel.xml"
LAUNCHERS = REPO_ROOT / "desktop" / "launchers"

# The designed taskbar, left to right. Two invisible expandable separators push the
# Start button and the task buttons into the middle of the bar; the tray cluster stays
# on the right. Changing the bar means changing this list, which is the point.
EXPECTED_PLUGIN_TYPES = (
    "separator",
    "whiskermenu",
    "docklike",
    "separator",
    "systray",
    "pulseaudio",
    "power-manager-plugin",
    "clock",
    "showdesktop",
)

# Launchers that come from Debian packages, not from this repository. They are pinned
# by the panel, and the package list is what guarantees them; the repository cannot
# check them here without building an image.
DEBIAN_LAUNCHERS = {
    "thunar.desktop",
    "xfce4-terminal.desktop",
    "firefox-esr.desktop",
    "mousepad.desktop",
}


def _properties(node: ET.Element) -> dict[str, ET.Element]:
    """Direct <property> children by name.

    xfconf's XML uses one element name for everything - every node is a <property> -
    so the name attribute is the only structure there is.
    """
    return {child.get("name"): child for child in node.findall("property")}


def _panel_channel() -> ET.Element:
    return ET.parse(PANEL_FILE).getroot()


def _panel_one() -> dict[str, ET.Element]:
    root = _panel_channel()
    panels = _properties(root)["panels"]
    return _properties(panels)


def _plugins() -> dict[str, ET.Element]:
    return _properties(_properties(_panel_channel())["plugins"])


def test_every_skel_channel_is_a_channel_named_after_its_file() -> None:
    """A channel file that declares another channel is silently never read.

    xfconf looks up a channel by the name inside the file, and the session only asks
    for the channels it uses. A file written under the wrong name is dead weight that
    looks like configuration.
    """
    files = sorted(SKEL_XFCONF.glob("*.xml"))
    assert files, f"no xfconf channel files found in {SKEL_XFCONF}"

    for path in files:
        root = ET.parse(path).getroot()
        assert root.tag == "channel", f"{path.name}: root element is <{root.tag}>, not <channel>"
        assert root.get("version") == "1.0", f"{path.name}: unexpected xfconf version"
        assert root.get("name") == path.stem, (
            f"{path.name} declares channel {root.get('name')!r}. The file name is what a "
            "reader expects the channel to be; a mismatch means one of the two is wrong."
        )


def test_panel_layout_sits_at_the_channel_root() -> None:
    """The 0.2.0 regression: /config/panels/... instead of /panels/... ."""
    root = _panel_channel()
    names = set(_properties(root))

    assert "panels" in names, (
        "xfce4-panel.xml has no root-level `panels` property. xfce4-panel 4.20 reads "
        "/panels/panel-N, so the panel definitions would not be found and Debian's "
        "stock layout would be built instead - silently."
    )
    assert "plugins" in names, (
        "xfce4-panel.xml has no root-level `plugins` property; plugin types and their "
        "settings would not be read."
    )

    assert "config" not in names, (
        "xfce4-panel.xml wraps its layout in a `config` property again. That is the "
        "0.2.0 bug: the layout lands at /config/panels/... and xfce4-panel 4.20, which "
        "reads /panels/..., builds Debian's default layout without a word."
    )
    stale = sorted(name for name in names if name and name.startswith("plugin-"))
    assert not stale, (
        f"xfce4-panel.xml has plugin nodes at the channel root ({', '.join(stale)}). "
        "Per-plugin settings belong under /plugins/plugin-N, whose value is the plugin "
        "type; at the channel root they are read by nothing."
    )


def test_there_is_exactly_one_panel() -> None:
    """One bar, at the bottom. A second panel is Debian's default, not the design."""
    panels = _panel_one()
    assert list(panels) == ["panel-1"], (
        f"the panel channel defines {sorted(panels)}; the AstraOS desktop is one bar "
        "and the second panel of Debian's default layout is exactly what 0.2.0 was "
        "showing."
    )


def test_the_panel_is_the_designed_bar() -> None:
    """Bottom edge, 44px, full width, locked - the Windows-11-style taskbar."""
    panel = _panel_one()["panel-1"]
    props = _properties(panel)

    assert props["position"].get("value") == "p=10;x=0;y=0", (
        "the panel is not on the bottom edge (position p=10). p=6 is the top edge, "
        "which is where Debian's default bar sits."
    )
    assert props["size"].get("value") == "44", (
        "the panel is not 44px tall. 44 is the taskbar height the AstraOS window "
        "buttons and icons are sized against."
    )
    assert props["length"].get("value") == "100", "the panel does not span the screen"
    assert props["position-locked"].get("value") == "true", (
        "the panel can be dragged out of place by accident"
    )
    assert props["background-style"].get("value") == "0", (
        "the panel does not use the theme background, so it would not share the "
        "AstraOS surface colour with the windows"
    )


def test_plugin_ids_and_plugin_types_agree() -> None:
    """The bar's left-to-right order is the plugin-ids array, and each id must exist."""
    panel = _panel_one()["panel-1"]
    ids = [value.get("value") for value in _properties(panel)["plugin-ids"].findall("value")]
    plugins = _plugins()

    expected_ids = [str(index) for index in range(1, len(EXPECTED_PLUGIN_TYPES) + 1)]
    assert ids == expected_ids, (
        f"the panel references plugin ids {ids}, expected {expected_ids} (contiguous, "
        "in the design's order). Gaps make xfce4-panel warn and leave a blank slot, and "
        "the configured plugins would not all appear."
    )

    for index, expected in enumerate(EXPECTED_PLUGIN_TYPES, start=1):
        node = plugins.get(f"plugin-{index}")
        assert node is not None, f"plugin-{index} is referenced but not defined"
        assert node.get("value") == expected, (
            f"plugin-{index} is {node.get('value')!r}, expected {expected!r}: the value "
            "of the plugin node IS its type, and the bar's layout would change"
        )
        assert node.get("type") == "string", (
            f"plugin-{index} does not declare its type as a string, so the plugin type "
            "would not be read"
        )

    assert sorted(plugins) == [f"plugin-{index}" for index in range(1, len(EXPECTED_PLUGIN_TYPES) + 1)], (
        f"the plugins property defines {sorted(plugins)}, which does not match the ids "
        "the panel references"
    )


def test_plugin_settings_are_the_designed_ones() -> None:
    """Three settings that were silently dead in 0.2.0, asserted through the parser.

    A grep for any of these strings passes on the broken file as well - they were all
    present, at a path nothing reads. Structure is the assertion.
    """
    plugins = _plugins()

    start = _properties(plugins["plugin-2"])
    assert start["button-icon"].get("value") == "astraos-logo", (
        "the Start button does not use the AstraOS ring logo"
    )
    assert start["show-button-title"].get("value") == "false", (
        "the Start button shows a text label; the design is an icon-only button"
    )

    dock = _properties(plugins["plugin-3"])
    pinned = [value.get("value") for value in dock["pinned"].findall("value")]
    assert pinned, "no applications are pinned to the taskbar"

    clock = _properties(plugins["plugin-8"])
    assert clock["digital-time-format"].get("value") == "%H:%M:%S", (
        "the clock is not formatted with seconds; the ticking mono clock is a "
        "deliberate part of the identity"
    )


def test_pinned_launchers_that_come_from_this_repository_exist() -> None:
    """A pin for a launcher the image does not ship is an app that cannot be started."""
    text = PANEL_FILE.read_text(encoding="utf-8")
    referenced = set(re.findall(r"value=\"([A-Za-z0-9_.+-]+\.desktop)\"", text))
    assert referenced, "the panel does not reference any launcher"

    ours = referenced - DEBIAN_LAUNCHERS
    missing = sorted(name for name in ours if not (LAUNCHERS / name).is_file())
    assert not missing, (
        f"the panel pins {missing}, which are neither Debian packages' launchers nor "
        f"files in {LAUNCHERS.relative_to(REPO_ROOT)}. The icons would appear and do "
        "nothing."
    )
