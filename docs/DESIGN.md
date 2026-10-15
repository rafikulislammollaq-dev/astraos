# AstraOS design language

AstraOS has **two visual layers**, and keeping them separate is a deliberate engineering
decision rather than an aesthetic preference.

## 0. Why two layers

The reference designs for AstraOS are neon: glowing rings, gradient light, translucent
panels, blur. Reproducing all of that in the *desktop chrome* would mean a compositing
blur pass on every menu, panel repaint and window switch, which is exactly what makes a
desktop feel slow on a low-end GPU, a software-rendered virtual machine, or an older
laptop.

Plan Â§7.1 states the desktop must "avoid excessive transparency and blur effects that may
degrade performance on low-end computers". So the identity is concentrated where the user
sees it only briefly â€” boot, login, installer, wallpaper, documentation â€” and the desktop
chrome is flat, high-contrast and cheap.

| Layer | Where | Technique |
|---|---|---|
| **Brand** | Boot splash, login screen, installer, wallpapers, docs | Neon ring, gradient, bloom, starfield |
| **Desktop** | Panel, windows, menus, dialogs, file manager | Flat graphite and cyan, 1px hairlines, no blur |

## 1. Palette

Defined once in `config/branding.env`. The asset renderer and the GTK theme both read it,
and a test asserts the theme actually uses the configured accent.

### Brand layer

| Token | Value | Use |
|---|---|---|
| `BRAND_VOID` | `#05030A` | Background |
| `BRAND_VOID_2` | `#0B0716` | Raised background |
| `BRAND_NEON_MAGENTA` | `#FF2FB9` | Primary accent |
| `BRAND_NEON_PINK` | `#FF5CC8` | Ring highlight |
| `BRAND_NEON_PURPLE` | `#8B3DFF` | Secondary accent |
| `BRAND_NEON_CYAN` | `#22E6FF` | Tertiary accent, links, data |

Signature gradient: `#FF5CC8 â†’ #8B3DFF â†’ #22E6FF`.

### Desktop layer

| Token | Value | Use |
|---|---|---|
| `COLOR_BG_DARK` | `#12141A` | Window and panel background |
| `COLOR_BG_MID` | `#1A1E26` | Menu, header bar |
| `COLOR_BG_RAISED` | `#232833` | Cards, popovers |
| `COLOR_HAIRLINE` | `#2E3542` | Borders and separators |
| `COLOR_TEXT_DARK_THEME` | `#E8ECF2` | Body text |
| `COLOR_TEXT_DIM` | `#9A93B8` | Secondary text |
| `COLOR_ACCENT_PRIMARY` | `#22E6FF` | Selection, focus |
| `COLOR_ACCENT_SECONDARY` | `#3D8BFF` | Secondary actions |
| `COLOR_ACCENT_OK` | `#2EE6C9` | Success |
| `COLOR_ACCENT_WARN` | `#FFB020` | Warning |
| `COLOR_ACCENT_DANGER` | `#FF4D4D` | Error, destructive |

Light theme: `COLOR_BG_LIGHT` `#F4F6FA`, text `#1A1E26`, accent `#0F6FB8`. The light
wallpaper keeps the neon identity as a *soft wash* over a bright base rather than
inverting the dark one, so it still reads as AstraOS without becoming uncomfortable.

## 2. Typography

| Role | Font | Notes |
|---|---|---|
| UI and headings | DejaVu Sans | Present on every Debian system; the branding package requires it, so the desktop never falls back to an unbranded default |
| Mono, labels, data | DejaVu Sans Mono | Terminal, clocks, metrics, micro-labels |
| Greeter | DejaVu Sans 11 | Same family, so the greeter and the desktop match |

DejaVu is chosen because it is redistributable under the Bitstream Vera licence, and
because it is already in the base distribution â€” a bundled font would be a licence and
packaging liability for no visual gain.

Micro-labels are uppercase with wide tracking; numerals in clocks and metrics use a
monospace face so digits do not jitter as they change.

## 3. Geometry and depth

- Radii: 8px controls, 14â€“22px panels, 999px pills.
- Borders: 1px hairlines. Focus adds `outline: 1px solid @accent` â€” always visible, because
  keyboard navigation is an accessibility requirement (plan Â§7.5).
- Depth comes from a single subtle drop shadow in the window manager's compositor, not from
  layered blur.
- Panel backgrounds are **solid**, not translucent. This is stated explicitly in
  `desktop/skel/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml`, which is copied
  into every new account's home directory, with the reason. (The defaults live under
  `/etc/skel` rather than `/etc/xdg/xfce4` because Debian's Xfce packages own files in that
  directory.)

## 4. Layout

One bar, at the bottom, 44px tall, full width. This is the Windows 11 arrangement, because
the people this distribution is built for arrive from Windows and already know where the
Start button is.

- **Centre:** the ring Start button (whiskermenu, icon-only) followed by the task buttons
  — docklike, one icon per application, a dot for running instances, pinned launchers for
  Files, Terminal, Firefox, Editor and Welcome. Two invisible expandable separators push
  that cluster to the middle of the bar. The centre is not perfectly centred, because the
  right-hand cluster is wider; Windows 11 has the same asymmetry.
- **Right:** the notification tray, volume, battery, the ticking mono clock (`%H:%M:%S`)
  and the show-desktop sliver.
- **Workspace switching** keeps the keyboard habits (Super+arrows, Ctrl+Alt+arrows). The
  workspace pager stays available from the panel's preferences rather than on the bar.

The 0.1.0 two-bar layout — a 30px top panel with the window list, over a 40px bottom dock
— was removed in 0.2.0. Two bars cost vertical space on the 1366×768 screens this
distribution has to run on, and they split the same information across two places. The
HUD identity is carried by the wallpaper, the window decorations, the neon terminal and
the boot splash instead.

**The layout is a file, and the file has to be where xfce4-panel looks.** The panel
definitions live at the channel root (`/panels/panel-N`) and each plugin under
`/plugins/plugin-N`, whose value is the plugin's type. A wrapper property — which 0.2.0
had — is not migrated and not reported: xfce4-panel simply finds no panel and builds
Debian's default layout instead, which is how a live session came to show a stock top bar
over the AstraOS wallpaper. `tests/static/test_desktop_skel.py` asserts the paths.

## 5. The ring mark

The AstraOS logo is a single ring with an angular pinkâ†’purpleâ†’cyan gradient, a soft bloom,
and one orbiting arc. It appears as:

- an SVG mark, in colour and in two monochrome variants (`branding/logos/`);
- a rendered PNG for tools that cannot use SVG (`branding/generated/`);
- the boot splash's hero element, centred, with a faint horizon grid below it.

All artwork is original to AstraOS. No third-party logo or trademark is redistributed
(plan Â§7.1, Â§23).

## 6. Motion

- 180ms transitions for hover, focus and panel open.
- The boot splash ring pulses slowly rather than spinning: Plymouth's script module has no
  access to the generated arc geometry, and a pulse avoids shipping an animation frame
  sequence that would add megabytes for a boot that lasts a few seconds.
- No motion in panel or window chrome beyond the compositor's own transitions, for the
  performance reason in Â§0.

## 7. What is deliberately not done

- **No custom window decorations.** The GTK theme is colour-only; titlebars use the
  upstream xfwm4 `Default` theme. See `KNOWN_LIMITATIONS.md` Â§1.4.
- **No blur or transparency in desktop chrome.** Â§0.
- **No imitation of another operating system's interface.** AstraOS does not copy Windows,
  macOS or another distribution's layout, icons or trademarks.
- **No hardcoded theme names that do not exist on disk.** A theme name with no assets
  produces invisible titlebars, so the xfwm4 theme is set to something guaranteed to be
  installed.

## 8. Previewing the design

```bash
python3 branding/tools/render_assets.py    # regenerate the bitmaps
# then open branding/preview.html in a browser
```

The preview page shows every generated asset together with the palette swatches.
