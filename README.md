# AstraOS

An independent, lightweight Linux desktop distribution built from Debian packages.
**Version 0.2.0 Alpha, codename Nova, architecture amd64 (x86_64).**

AstraOS is a Debian 13 (trixie) derivative with its own package selection, Xfce desktop
configuration, branding, installer configuration and automated ISO build pipeline.
It uses the Debian Linux kernel. It is not a from-scratch kernel, not an official
Debian release, and not a website pretending to be an operating system.

---

## Maturity level: early alpha (live image boots in a VM)

| Level | Meaning | Reached? |
|---|---|---|
| 1 | Source tree and static checks pass | Yes |
| 2 | ISO builds in CI | Yes (Build ISO run #26, 2026-10-13, about 13 minutes, ISO about 2.15 GB) |
| 3 | ISO boots in a virtual machine | **Yes** (VirtualBox, live session, 2026-10-15) |
| 4 | Network and browser work out of the box | **Cause fixed in the source.** The last boot-tested ISO predates the fix; see Known issues |
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

Not tested: the installer, installing to disk, Wi-Fi, GPUs, physical machines,
UEFI boot, audio, printing, Bluetooth, and the on-screen rendering of the AstraOS
HUD and the assistant's web page (both packaged and statically tested only).

---

## What is included

Built from Debian 13 (trixie). The CI build log shows about 1,569 packages unpacked
into the image, which come from 283 reviewed core selections plus their dependencies
and recommended packages.

| Component | Choice |
|---|---|
| Base | Debian 13 (trixie) |
| Kernel | Debian `linux-image-amd64` (6.12 series), plus kernel headers |
| Init | systemd |
| Desktop | Xfce, configured and branded |
| Session dashboard | AstraOS HUD (`astraos-hud`): one full-screen window with live CPU, memory, network, disk and temperature panels, an on-screen keyboard and an embedded terminal, started from its menu entry or launcher |
| Assistant | `astraos-ai`: an opt-in local assistant with a three-tier model ladder and a shipped skills/knowledge library. No model is bundled and nothing runs until one is installed (`docs/AI.md`) |
| Display manager | LightDM (GTK greeter) |
| Display server | X11 |
| Boot splash | Plymouth, AstraOS theme |
| Installer | Calamares, configured and branded (not yet tested) |
| Bootloader | GRUB (UEFI) and syslinux (BIOS), hybrid ISO. Secure Boot disabled |
| Networking | NetworkManager with applet, wpa_supplicant |
| Browser | Firefox ESR |
| Office | LibreOffice |
| Firewall | ufw installed, not enabled by default |
| Firmware | Broad set of non-free firmware (about 390 MB compressed) |
| Package format | `.deb` with APT and dpkg |
| Root filesystem | ext4 |

Largest contributors to ISO size (approximate compressed download sizes):
kernel about 108 MB, firmware packages about 390 MB in total, Firefox ESR about 80 MB,
LibreOffice about 80 MB, graphics libraries (LLVM, Mesa, WebKitGTK), fonts and speech data.

The ISO is about 2.15 GB. Installed size will be larger, because the ISO stores the
system as a compressed squashfs.

---

## Known issues

1. **DNS does not work out of the box in the live session.**
   `/etc/resolv.conf` is empty, so names do not resolve (pinging an IP works,
   pinging `google.com` fails).
   Workaround, run in the AstraOS terminal (note the `v` in `resolv`):

   ```
   echo "nameserver 10.0.2.3" | sudo tee /etc/resolv.conf
   ```

   `10.0.2.3` is VirtualBox NAT's DNS server. On other hosts or on real networks use
   your router's address or `8.8.8.8`. The change is lost on reboot (live session).

   **Fixed in 0.2.0.** The cause was confirmed by unpacking the 0.1.0
   `filesystem.squashfs`: `/etc/resolv.conf` is a **0-byte regular file**, because
   live-build replaces the path instead of leaving the `/run/resolvconf/resolv.conf`
   symlink that `resolvconf(8)` manages. Both authorities were enabled —
   `NetworkManager.service` and `resolvconf.service` are both in
   `multi-user.target.wants` — and each deferred to the other: NetworkManager saw
   `resolvconf` installed and handed DNS over to it, and `resolvconf` found its
   symlink replaced and wrote nothing. Nothing owned the file.

   `resolvconf` has been removed from `config/package-lists/50-networking.list.chroot`.
   NetworkManager writes DNS itself, and Debian 13 treats `resolvconf` as deprecated.
   `tests/static/test_packages.py::test_resolvconf_is_not_installed_alongside_networkmanager`
   fails if it is ever added back, because this class of bug does not stop the build —
   apt resolves the set happily and the image ships broken.

2. Structural validation of the ISO **passed** for build run #26: that image's
   `.manifest` records `structural=PASS`, checked for bootloaders, kernel, initramfs,
   live filesystem and AstraOS contents. What remains untested is everything the
   validator cannot reach from the outside — booting on real hardware, UEFI, the
   installer. The boot test script still reports BLOCKED when no ISO is in `dist/`,
   which is not a pass.
3. Copy and paste between the host and the VM needs VirtualBox Guest Additions, which
   are not part of the image.
4. The ISO is larger than it needs to be (APT recommends enabled, much firmware,
   LibreOffice, compilers).
5. Secure Boot is not supported.
6. `/etc/os-release` may be overwritten by a future upgrade of Debian's `base-files`.
7. Only a colour GTK theme ships, with the upstream xfwm4 window theme.

See `docs/KNOWN_LIMITATIONS.md` for the full list.

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
   Get-FileHash .\astraos-0.1.0-alpha-amd64.iso -Algorithm SHA256
   Get-Content .\astraos-0.1.0-alpha-amd64.iso.sha256
   ```
   The two hashes should match.
3. VirtualBox: New. Set name `AstraOS`, pick the ISO, Type Linux, Version Debian (64-bit),
   tick Skip Unattended Installation.
4. Hardware: 4096 MB RAM, 2 CPUs, 25 GB disk. Finish.
5. Start the VM, choose **Live system (amd64)**, wait for the desktop.
6. In the terminal, run the DNS workaround above, then open Firefox.
7. Press Right Ctrl to release the mouse from the VM.
   In the terminal, copy is Ctrl+Shift+C and paste is Ctrl+Shift+V.

---

## Building the ISO

Without a Linux machine, use CI: run the **Build ISO** workflow manually from the
Actions tab. It takes about 13 minutes and produces the `astraos-iso` and
`astraos-build-logs` artifacts.

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
consistent, not that AstraOS works. Booting the ISO in a VM is the real test.

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
├── docs/             architecture, build, installation, recovery, limitations
└── build/  dist/     generated output (git-ignored)
```

The code is mostly build tooling: about half Python and half Shell, with a small amount
of HTML, CSS and Make. The operating system itself comes from Debian packages.

---

## Roadmap

1. ~~Fix DNS so networking works out of the box~~ **Done in 0.2.0**: `resolvconf` was
   removed from the package list and `tests/static/test_packages.py` keeps it out.
2. ~~Confirm the ISO passes structural validation in CI~~ **Done** (build run #26 records
   `structural=PASS`).
3. Test the Calamares installer: install to a VM disk and boot the installed system.
4. Reduce ISO size (turn off APT recommends, trim firmware and large optional apps).
5. Add Guest Additions support for VMs.
6. Test on physical hardware.
7. Prove the AstraOS HUD on a real screen. It is packaged, launched from the menu and
   covered by static tests, but its rendering has not yet been seen on a display.
8. Run the assistant end to end with a real model
   (`astra-ai setup --model spark-x2.5-1.7b-q4_k_m`), and reach its page from a phone.

---

## Licensing and attribution

AstraOS is distributed under the GNU General Public License, version 3 or later. See `LICENSE`.

AstraOS is an independent distribution based on Debian GNU/Linux and is not affiliated
with, endorsed by, or an official release of the Debian Project. It includes software
from Debian, the Linux kernel, Xfce, LightDM, Plymouth, GRUB, Calamares, Firefox and many
other projects; each keeps its own copyright and licence, recorded in
`/usr/share/doc/<package>/copyright` on an installed system.

All AstraOS artwork is original to this project.
