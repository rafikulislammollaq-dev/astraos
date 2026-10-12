# AstraOS branding assets

Everything in this directory is original work created for the AstraOS project. No
asset is copied from another distribution, and no third-party logo or trademark is
redistributed (plan §7.1, §23).

## Layout

| Path | What it is | Consumed by |
|---|---|---|
| `logos/*.svg` | The AstraOS ring mark: full colour, two monochrome variants, and the wordmark | GRUB, LightDM, documentation, installer |
| `icons/` | A small freedesktop icon theme that inherits from `hicolor` | Xfce panel, menus, Thunar |
| `generated/*.png` | Rendered bitmaps: wallpapers, boot splash, greeter background, ring marks | Plymouth, GRUB, LightDM, Xfce wallpaper |
| `plymouth/astraos/` | Boot splash theme (`script` module) | Plymouth |
| `grub/astraos/` | GRUB menu theme | GRUB |
| `lightdm/` | Greeter appearance and the LightDM policy drop-in | LightDM |
| `preview.html` | Visual index of every generated asset | developers, reviewers |

## The palette has one source of truth

Colours, font choices and asset dimensions live in `config/branding.env`. The PNG
renderer reads that file, so changing the palette and re-rendering updates every
bitmap. Nothing here hard-codes a colour.

Two deliberate visual layers:

* **Brand layer** — neon ring, gradients, bloom. Used where the user sees the OS
  briefly: boot splash, login screen, installer, documentation.
* **Desktop layer** — graphite and restrained cyan, flat, no transparency. Used by
  the panel, windows and menus, because the desktop must stay responsive on modest
  hardware (plan §7.1).

## Regenerating the bitmaps

```bash
python3 branding/tools/render_assets.py             # full size, about a minute
python3 branding/tools/render_assets.py --scale 0.25  # fast smoke test
python3 branding/tools/render_assets.py --only logo   # one asset group
```

The renderer uses only the Python standard library (it implements PNG encoding
itself), so it runs on hosts where no image library is installed — including the
Windows development machine this project started on. Output is deterministic: the
star field uses a fixed seed, so the same source produces the same bytes.

Then rebuild the assets into the packages:

```bash
./scripts/build-packages.sh
```

The packaging script maps these files into their installed locations; that mapping is
in one place, in the `Package content assembly` section of `scripts/build-packages.sh`.

## Licensing

The AstraOS artwork is distributed under the same licence as the project
(GPL-3.0-or-later). Fonts referenced by the wordmark and the greeter are DejaVu fonts,
which are redistributable under the Bitstream Vera licence; they are a hard dependency
of the branding package rather than being bundled.

If you contribute artwork, add it here and put its source (SVG where possible) in the
repository — not only a flattened export. Raster-only sources cannot be re-rendered at
a new resolution.
