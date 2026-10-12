# AstraOS

**An independent, lightweight Linux desktop operating system.**
Version 0.1.0 Alpha — codename **Nova** — target architecture **amd64** (x86_64).

AstraOS is a real, bootable, installable Linux distribution built from Debian packages
with its own identity, package selection, desktop configuration, installer
configuration and reproducible build pipeline. It is intended to be delivered as a
bootable ISO, run in a virtual machine, installed to a disk, and eventually installed on
compatible physical hardware.

It is **not** a website pretending to be an operating system, and it is **not** a theme
applied to an existing distribution.

---

## Current status — read this first

**The repository is complete and its static checks pass. No ISO has been built yet, and
no ISO has been booted.**

That sentence is the most important one in this file, and it is deliberately blunt. The
project's own rules (`project astra main plan.txt`, §28 Rule 4) forbid reporting a build,
boot or installation that did not happen.

| Stage | Status | Evidence |
|---|---|---|
| Repository structure and configuration | **Done** | `tests/run.py` passes |
| Package selection verified against the real Debian archive | **Done** | 283 packages checked against `dists/trixie/*/Packages.xz` |
| Branding assets generated | **Done** | `branding/generated/*.png`, valid PNGs with verified CRCs |
| Build scripts implemented | **Done** | `scripts/` — see `docs/BUILDING.md` |
| ISO built | **NOT DONE** | Requires a Linux build host; see below |
| ISO booted in a VM | **NOT DONE** | Requires the ISO |
| Installer run | **NOT DONE** | Requires the ISO |
| Installed system booted | **NOT DONE** | Requires the installer run |
| Physical hardware | **NOT DONE** | Not attempted, and not recommended yet |

### Why no ISO was built in this session

The development machine this project started on is a **Windows host**, and its only
Linux environment (WSL2) **cannot start**: Windows' "Virtual Machine Platform" feature is
not enabled. VirtualBox is not installed either. This is measured and recorded in
[`docs/ENVIRONMENT.md`](docs/ENVIRONMENT.md), including the exact commands needed to
unblock it.

The project is therefore built **CI-first**: the ISO is produced by
[`.github/workflows/build-iso.yml`](.github/workflows/build-iso.yml), and the identical
scripts run on any Debian or Ubuntu machine.

---

## What AstraOS is

| Component | Choice | Why |
|---|---|---|
| Base | Debian 13 (trixie), pinned per release branch | Maintenance, security updates, package quality |
| Kernel | Debian's `linux-image-amd64` (6.12 LTS series) | Supported and security-updated; no hand-rolled kernel |
| Init | systemd | The base distribution's init system |
| Desktop | Xfce, configured and branded | Responsive on modest hardware, mature, upgradable |
| Display server | X11 (Wayland-ready, not claimed) | Predictable compatibility for the first release |
| Display manager | LightDM with the GTK greeter | Brandable, simple |
| Installer | Calamares, configured and branded | Maintained upstream installer, real disk safety workflow |
| Bootloader | GRUB, hybrid BIOS + UEFI | Compatibility |
| Package format | `.deb`, managed by APT and dpkg | Base-distribution native |
| Filesystem | ext4 for the root filesystem | Well supported and recoverable |
| Firewall | ufw, policy documented and shipped, not enabled by default | Nothing listens by default; see `docs/SECURITY.md` |

AstraOS uses the Linux kernel. It does **not** claim to be a from-scratch kernel or a
kernel-independent operating system, and it does **not** present itself as an official
Debian release.

---

## Repository layout

```
astraos/
├── VERSION                     flagship release identity, one line per field
├── Makefile                    make check / build / validate / checksums / clean
├── config/
│   ├── distribution.env        the pinned base, repositories, image and desktop settings
│   ├── branding.env            the brand palette, fonts and asset dimensions
│   ├── package-lists/          the reviewed package selection, split by category
│   └── live-build/             Debian Live configuration, hooks and archive definitions
├── branding/                   original artwork: SVG marks, themes and an asset renderer
├── desktop/                    Xfce configuration, launchers, autostart, GTK theme
├── packages/                   the five AstraOS .deb packages and their sources
├── system/                     templates for identity files and kernel/security defaults
├── installer/                  Calamares configuration and branding
├── scripts/                    validation, packaging, building and release tooling
├── tests/                      the static test suite (runs on any host)
├── docs/                       architecture, build, installation, recovery, limitations
└── build/  dist/               generated output; both ignored by git
```

---

## Building

```bash
# On a Debian or Ubuntu host:
./scripts/validate-environment.sh        # can this host build AstraOS?
./scripts/bootstrap-build-environment.sh # install build dependencies
./scripts/build-iso.sh                   # build the image
```

The ISO is written to `dist/`, together with a `.sha256` checksum and a `.manifest`
recording exactly what was built. See [`docs/BUILDING.md`](docs/BUILDING.md).

Or build in CI, without a Linux machine: run the **Build ISO** workflow manually.

## Testing

```bash
make check          # or: python3 tests/run.py
```

The static suite validates configuration, package lists, assets, desktop entries,
Calamares safety settings and shell script syntax. It runs on any host with Python 3.

**It does not build or boot the OS.** A green run means the repository is internally
consistent, not that AstraOS works.

To verify the package selection against the live Debian archive (needs network):

```bash
python3 scripts/verify-package-availability.py
```

---

## Known limitations

AstraOS 0.1.0 Alpha is an early release. The significant limitations are:

- **No image has been built or booted yet**, as described above.
- **Secure Boot is not supported or claimed.** It is disabled in the live image's own
  boot configuration.
- **`/etc/os-release` can be overwritten** by a future upgrade of Debian's `base-files`
  package, because that package owns the path and AstraOS does not yet ship a forked
  `base-files`.
- **The desktop ships a colour-only GTK theme.** Window decorations use the upstream
  xfwm4 `Default` theme rather than a custom AstraOS titlebar theme.
- **No physical hardware has been tested.** Nothing is claimed about Wi-Fi chipsets,
  GPUs or laptops.
- **AI features are not part of this release** and are not in the boot path.

The complete, honest list is in
[`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md).

---

## The visual identity

AstraOS has two deliberate visual layers, described in
[`docs/DESIGN.md`](docs/DESIGN.md) and in [`branding/README.md`](branding/README.md):

- **Brand layer** — the neon ring, gradients and bloom, on the boot splash, the login
  screen, the installer and the wallpapers. This is the identity the project was
  designed around.
- **Desktop layer** — flat graphite and cyan, no blur, no transparency in panel and
  window chrome. The desktop must stay responsive on modest hardware, so the expensive
  effects live where the user only sees them briefly.

Every bitmap is generated from `config/branding.env` by
`branding/tools/render_assets.py`, which uses only the Python standard library. The
palette therefore has one source of truth, and the assets are reproducible.

Open `branding/preview.html` in a browser to see all of them.

---

## Licensing and upstream attribution

AstraOS is distributed under the **GNU General Public License, version 3 or later**.
See [`LICENSE`](LICENSE).

AstraOS is an independent distribution based on **Debian GNU/Linux**. It is not
affiliated with, endorsed by, or an official release of the Debian Project. It includes
software from Debian, the Linux kernel, Xfce, LightDM, Plymouth, GRUB, Calamares and
many other projects; each retains its own copyright and licence, recorded in
`/usr/share/doc/<package>/copyright` on an installed system.

All AstraOS artwork is original to this project. No third-party logo or trademark is
redistributed, and no proprietary asset is included.
