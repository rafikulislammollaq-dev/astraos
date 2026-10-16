# AstraOS

An independent, lightweight Linux desktop distribution built from Debian packages.
**Version 0.2.0 Alpha, codename Nova, architecture amd64 (x86_64).**

AstraOS is a Debian 13 (trixie) derivative with its own package selection, Xfce desktop
configuration, branding, installer configuration and automated ISO build pipeline.
It uses the Debian Linux kernel. It is not a from-scratch kernel, not an official
Debian release, and not a website pretending to be an operating system.

---

## Maturity level: early alpha (live image boots in a VM; CI boots and self-tests it)

| Level | Meaning | Reached? |
|---|---|---|
| 1 | Source tree and static checks pass | Yes |
| 2 | ISO builds in CI | Yes (Build ISO run 38864588609, 2026-10-16: image built in about 18 minutes, 25/25 structural checks, `structural=PASS`, ISO 2,432,696,320 bytes) |
| 3 | ISO boots in a virtual machine | **Yes** (VirtualBox by hand, live session, 2026-10-15; QEMU in CI, run 38881934636, 2026-10-16 — the image's own self-test reported PASS, 39 checks) |
| 4 | Network and browser work out of the box | **Network proven in CI** (run 38881934636: NetworkManager active, an IPv4 address, a real name resolved by DNS); **no browser has been launched in a booted image yet** |
| 5 | Installer runs and installed system boots | Not tested yet |
| 6 | Tested on physical hardware | Not tested yet |
| 7 | Secure Boot, signed images, stable release | Not supported |

This is a learning and prototype build. Do not use it as your main system.

---

## What has been tested

Tested by hand on 2026-10-15 in Oracle VirtualBox on a Windows 11 host
(Intel Core i5-2500S, 16 GB RAM):

- ISO boots from the live menu ("Live system (amd64)").
- Reaches the Xfce desktop with the AstraOS wallpaper and a bottom dock
  (terminal, file manager, browser, search).
- Live user is `astra`, hostname is `astra-live`.
- Network link works: `ping 8.8.8.8` replies with 0% loss.
- Firefox loads websites once DNS is configured (YouTube loaded in the test).

Proven by CI on 2026-10-16 (boot self-test, run 38881934636, commit 8f81e3d):

- The built ISO boots in CI's QEMU — the runner provides no KVM, so the CPU is
  emulated — and the image's own self-test reports `PASS: 39 checks, 0 failed`:
  the console login prompt appears 143.7 s into the guest boot, LightDM is
  active, an Xfce session (xfwm4) runs as the live user, every `astraos-*`
  package is present at its expected version, the hardware, codec and
  compatibility tools and the Flathub remote check out, NetworkManager is
  active with an IPv4 address, and a real name resolves over DNS.
- This boots the kernel and initrd taken from the ISO with the ISO attached as
  the live medium; the ISO's own boot menus (syslinux BIOS, GRUB EFI) are still
  exercised only by hand. The screenshot this run captured through the QEMU
  monitor came back black — a tracked capture defect — so the serial log, not
  the picture, is the evidence today.

Tested from the source tree on 2026-10-16 in WSL on the same hardware:

- The AstraOS HUD renders. Started with the same command the installed shim runs,
  under GTK 3 on a virtual X display, it paints its full layout - the clock, the
  per-core and memory meters, the process and filesystem tables, the traffic
  graph, the world-view panel and the on-screen keyboard - with no warnings.
  Three defects that stopped the very first frame were found and fixed by doing
  this (see `fix(hud)` in the log for 2026-10-16).

Built and proven on GitHub Actions on 2026-10-16 (Build AI engine run #1, about
5 minutes, from the commit that added the workflow):

- The assistant's engine compiles through the assistant's own command,
  `astra-ai setup --build all`, and the built binaries pass the checks this
  hardware taught us: no FMA, BMI2 or F16C instruction, no RPATH into the build
  tree, no missing library.
- The engine loads a real model and answers over HTTP on an *emulated Sandy
  Bridge* (`qemu-x86_64 -cpu SandyBridge`) - the same CPU class as this machine,
  whose missing FMA/BMI2 once killed the process with SIGILL and no output.
- A model downloads with `astra-ai setup --model`, `astra-ai ask` answers and
  stops, `astra-ai work --json` takes a request through the ladder, and the
  worker's JSON grammar is shown to be enforced even when the model is told to
  answer in prose. (The model in this proof is the 360M router-class entry, the
  smallest in the catalogue: a smoke test of the engine, not a test of the
  ladder's answer quality.)

Not tested: the installer, installing to disk, Wi-Fi, GPUs, physical machines,
UEFI boot, audio, printing, Bluetooth, and the assistant's web page.

---

## What is included

Built from Debian 13 (trixie). The image comes from 348 reviewed selections across 10
package lists plus their dependencies and recommended packages; the built live
filesystem holds 182,962 files (2,159 MiB extracted).

| Component | Choice |
|---|---|
| Base | Debian 13 (trixie) |
| Kernel | Debian `linux-image-amd64` (6.12 series), plus kernel headers |
| Init | systemd |
| Desktop | Xfce, configured and branded |
| Session dashboard | AstraOS HUD (`astraos-hud`): one full-screen window with live CPU, memory, network, disk and temperature panels, an on-screen keyboard and an embedded terminal, started from its menu entry or launcher |
| Assistant | `astraos-ai`: an opt-in local assistant with a three-tier model ladder and a shipped skills/knowledge library. No model is bundled and nothing runs until one is installed (`docs/AI.md`) |
| Hardware enablement | VA-API video decode for Intel and AMD (`intel-media-va-driver`, `i965-va-driver`, `mesa-va-drivers`) with `vainfo`; `fwupd` for device firmware updates; `zram-tools` compressed swap; `irqbalance`; `bluez-firmware` |
| Phones and media over USB | MTP for Android phones and cameras in Thunar (`libmtp-runtime`, `mtp-tools`), `adb` and `fastboot` with udev rules |
| Disk compatibility | `ntfs-3g` (read-write Windows disks), `exfatprogs` (SD cards and cameras), `squashfs-tools` |
| Media codecs | `libavcodec-extra`, `ffmpeg`, the GStreamer libav/bad/ugly set, DVD navigation (`libdvdnav4`) |
| Printing | CUPS with the gutenprint and Epson (`escpr`) driver sets |
| Application store | Flatpak with the Flathub remote configured system-wide; no applications preinstalled |
| Windows software | Wine (64-bit applications) and winetricks |
| System tools | `gdebi`, `timeshift`, `inxi`, `speech-dispatcher` |
| Self-test | `astraos-smoke` reports the machine, session, packages and networking on request (kernel command line `astraos.ci=1`); the CI boot test runs it on every build |
| Display manager | LightDM (GTK greeter) |
| Display server | X11 |
| Boot splash | Plymouth, AstraOS theme |
| Installer | Calamares, configured and branded; the CI install exercise is pending its first run |
| Bootloader | GRUB (UEFI) and syslinux (BIOS), hybrid ISO. Secure Boot disabled |
| Networking | NetworkManager with applet, wpa_supplicant |
| Browser | Firefox ESR |
| Office | LibreOffice |
| Firewall | ufw enabled by default: incoming denied except the assistant's page (8765/tcp) and local service discovery (5353/udp), both from the local network only |
| Firmware | Broad set of non-free firmware (about 390 MB compressed) |
| Package format | `.deb` with APT and dpkg |
| Root filesystem | ext4 |

Largest contributors to ISO size: kernel about 108 MB, firmware packages about 390 MB in
total, Wine, Flatpak, the full codec set, Firefox ESR about 80 MB, LibreOffice about
80 MB, graphics libraries (LLVM, Mesa, WebKitGTK), fonts and speech data.

The ISO is about 2.4 GB (2,432,696,320 bytes). Installed size will be larger, because
the ISO stores the system as a compressed squashfs.

---

## Known issues

1. **Secure Boot is not supported.** A machine enforcing it will refuse to boot the
   medium; turn Secure Boot off to try AstraOS.
2. **Copy and paste between the host and a virtual machine needs Guest Additions**,
   which the image does not ship. Right Ctrl releases the mouse; inside the terminal
   copy is Ctrl+Shift+C and paste is Ctrl+Shift+V.
3. **Physical hardware, UEFI boot, and the installer are untested.** The image boots
   in virtual machines — by hand in VirtualBox through the live menu (2026-10-15) and
   in CI under QEMU (run 38881934636) — but nothing has run on physical hardware, no
   boot has gone through UEFI, and Calamares has not been run at all.
4. **The ISO is larger than it needs to be** (about 2.4 GB: APT recommends are on, and
   the codec, Wine and Flatpak sets are included).
5. **`/etc/os-release` may be overwritten by a future upgrade of Debian's `base-files`.**
   Cosmetic: AstraOS's own tools read `/etc/astraos-release`.
6. **The theme is colour-only**; window decorations use the upstream xfwm4 theme.

Fixed defects are recorded in `CHANGELOG.md`. The complete list of limitations, in more
detail than this summary, is `docs/KNOWN_LIMITATIONS.md`.

---

## Requirements to run it

**Virtual machine (recommended):**

- Host: Windows, Linux or macOS with VirtualBox, VMware or QEMU
- 2 or more CPU cores, 4 GB RAM (2 GB minimum), 25 GB virtual disk
- 64-bit x86 host with hardware virtualization enabled
- ISO type: Linux, Debian (64-bit). Skip Unattended Installation.
  Try EFI off first, and turn it on if the VM will not boot.

**Physical hardware:** not tested and not recommended yet.

---

## Quick start in VirtualBox

1. Download the ISO, `.sha256` and `.manifest` from the Build ISO run's artifacts
   (GitHub Actions, `astraos-iso`) and unzip.
2. Verify the download in PowerShell:
   ```powershell
   Get-FileHash .\astraos-0.2.0-alpha-amd64.iso -Algorithm SHA256
   Get-Content .\astraos-0.2.0-alpha-amd64.iso.sha256
   ```
   The two hashes should match.
3. VirtualBox: New. Set name `AstraOS`, pick the ISO, Type Linux, Version Debian (64-bit),
   tick Skip Unattended Installation.
4. Hardware: 4096 MB RAM, 2 CPUs, 25 GB disk. Finish.
5. Start the VM, choose **Live system (amd64)**, wait for the desktop.
6. Open Firefox. 0.2.0 builds configure DNS themselves; nothing to fix first.
7. Press Right Ctrl to release the mouse from the VM.
   In the terminal, copy is Ctrl+Shift+C and paste is Ctrl+Shift+V.

---

## Building the ISO

Without a Linux machine, use CI: run the **Build ISO** workflow manually from the
Actions tab. It takes about 18 minutes to produce the image and then boots it in QEMU
for the image's own self-test (the `smoke-boot` job), producing the `astraos-iso`,
`astraos-build-logs` and `astraos-boot-self-test` artifacts.

On a Debian or Ubuntu host:

```bash
./scripts/validate-environment.sh        # can this host build AstraOS?
./scripts/bootstrap-build-environment.sh # install build dependencies
./scripts/build-iso.sh                   # build the image
```

The ISO is written to `dist/` with a `.sha256` checksum and a `.manifest`.
See `docs/BUILDING.md`.

## Testing

```bash
make check          # or: python3 tests/run.py
```

The static suite checks configuration, package lists, assets, desktop entries,
Calamares safety settings and shell syntax. A green run means the repository is
consistent, not that AstraOS works.

CI goes one step further on every image it builds: the `smoke-boot` job boots the ISO
in QEMU and runs the image's own self-test (`astraos-smoke`, started only when
`astraos.ci=1` is on the kernel command line), keeping the serial log and a screenshot of
the booted desktop as the `astraos-boot-self-test` artifact. The same check runs by
hand with `./scripts/smoke-boot.sh dist/astraos-*.iso` (see `docs/BUILDING.md`).

An `install-boot` job goes further still: it installs the ISO onto a blank disk through
the ISO's own Calamares UI, driven over the QEMU monitor, then boots the installed disk
alone and requires the image's self-test in its installed mode. The exercise exists in
the source as of 2026-10-16 (`scripts/install-boot-test.sh`) and is pending its first
run; `docs/BUILDING.md` describes it.

---

## The assistant's engine, built in CI

Compiling llama.cpp costs about twenty minutes of every core on this hardware, so it does
not happen on this hardware. The **Build AI engine** workflow builds `llama-server` and
`whisper-cli` on GitHub Actions - through the same command a user runs,
`astra-ai setup --build all`, so the workflow cannot drift from the flag list in
`setup.py` - proves the binaries (including actually running the engine on an emulated
Sandy Bridge), and uploads them as the `astra-ai-engine-linux-x86_64-avx` artifact with
`SHA256SUMS.txt` and `BUILD-INFO.txt`.

To install a completed build: open the latest run on the Actions tab, download and unzip
the artifact, copy `llama-server` and `whisper-cli` into `~/.local/share/astraos/ai/bin/`,
and run `astra-ai status`, which prints the path it found. Building on the machine still
works and is still documented in `docs/AI.md`: `astra-ai setup --build all`.

---

## Repository layout

```
astraos/
├── VERSION           release identity
├── Makefile          make check / build / validate / checksums / clean
├── config/           distribution settings, branding, package lists, live-build config and hooks
├── branding/         original artwork and the asset renderer
├── desktop/          Xfce configuration, launchers, autostart, GTK theme
├── apps/             runnable applications packaged from this tree (astraos-hud)
├── packages/         AstraOS .deb packages and their sources
├── system/           identity files and kernel/security default templates
├── installer/        Calamares configuration and branding
├── scripts/          validation, packaging, build and release tooling
├── tests/            static test suite
├── docs/             architecture, build, installation, recovery, limitations, roadmap, blueprints
└── build/  dist/     generated output (git-ignored)
```

The code is mostly build tooling: about half Python and half Shell, with a small amount
of HTML, CSS and Make. The operating system itself comes from Debian packages.

---

## Roadmap

1. ~~Fix DNS so networking works out of the box~~ **Done in 0.2.0**: `resolvconf` was
   removed from the package list and `tests/static/test_packages.py` keeps it out.
2. ~~Confirm the ISO passes structural validation in CI~~ **Done** (every build records
   `structural=PASS`; latest 2026-10-16, run 38864588609).
3. Test the Calamares installer: install to a VM disk and boot the installed system.
4. Reduce ISO size (turn off APT recommends, trim firmware and large optional apps).
5. Add Guest Additions support for VMs.
6. Test on physical hardware.
7. See the AstraOS HUD on a booted ISO's screen. It renders from the source tree
   under GTK 3 on a virtual display (2026-10-16), but no built image has shown it
   on a real screen yet.
8. Run the assistant end to end on this machine with the recommended ladder. The
   engine, the `ask`/`work` path and the worker's JSON grammar are now proven in CI
   (Build AI engine, 2026-10-16, including an emulated Sandy Bridge and the 360M
   model), and the 1.7B executor is downloaded here; what remains is running the
   ladder on this machine's own CPU and reaching its web page from a phone.
9. Exercise the ISO's own boot menu (syslinux and GRUB-EFI) in CI. The current boot
   test extracts the kernel and initrd from the ISO, so it verifies the image; the
   bootloader path itself is still only tested by hand in VirtualBox.

Beyond this list, `docs/ROADMAP.md` holds the staged plan for the assistant as a
platform — permissions and sandboxing, hardware-adaptive model selection, voice,
local knowledge, diagnostics. It is a plan, not a description of the current system;
nothing in it should be read as working until a run, a test or an artifact shows it.

---

## Licensing and attribution

AstraOS is distributed under the GNU General Public License, version 3 or later. See `LICENSE`.

AstraOS is an independent distribution based on Debian GNU/Linux and is not affiliated
with, endorsed by, or an official release of the Debian Project. It includes software
from Debian, the Linux kernel, Xfce, LightDM, Plymouth, GRUB, Calamares, Firefox and many
other projects; each keeps its own copyright and licence, recorded in
`/usr/share/doc/<package>/copyright` on an installed system.

All AstraOS artwork is original to this project.
