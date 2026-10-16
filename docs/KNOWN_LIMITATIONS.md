# AstraOS 0.1.0 Alpha — known limitations

This document exists so that nobody has to discover a limitation the hard way. It lists
what is not done, what is not tested, and what is known to be wrong. Per plan §25,
defects are not hidden because they make the release look less polished.

**AstraOS 0.1.0 is an alpha release. It is not suitable for a computer you depend on,
and it should not be installed on a machine holding data you cannot lose.**

---

## 1. Release-level limitations

### 1.1 The image boots in CI; it has never been installed, and never booted on physical hardware

**No image has ever been installed to a disk, and no image has ever booted on physical
hardware.** What has happened, with the record:

- **2026-10-16, the HUD on screen (run 38919644411, commit 8e40d99): PASS.** The
  image's self-test reported `RESULT: PASS (52 checks, 0 failed)` — the same firewall,
  phone and capture checks as the run below, plus the new `hud-on-screen` — and the
  capture carries the dashboard itself: a 1280×800 PNG (104,723 bytes) holding the
  HUD's clock, system and terminal panels, memory and filesystem bars, and the
  endpoint card reading "NO ENDPOINT". The install exercise in the same dispatch
  failed before the guest booted — QEMU refused the driver's `usb-tablet` for want of
  a USB controller — and the fix is recorded in `CHANGELOG.md` (2026-10-16); the
  retry is pending. Evidence artifacts: `astraos-boot-self-test` (the capture is
  `screenshot.png`), `astraos-boot-menus`, `astraos-install-test` (`qemu1.out` holds
  the refusal).
- **2026-10-16, full CI boot self-test with the firewall, the phone arc and a real
  screenshot (run 38913161772, commit 0e47f4d): PASS (51 checks, 0 failed).** The
  same emulated boot now carries the firewall checks (ufw active, the deny default,
  the assistant's page reachable on the private range, a watched port left unreached
  under the host's probe), the phone-pairing arc with the host transcript in
  `phone-host.log`, and a screenshot of the real desktop; the boot self-test job took
  9m47s, and the `boot-menus` job (6m41s) booted the ISO through QEMU's own firmware —
  syslinux on BIOS, GRUB on UEFI — with both serial logs reaching the live system's
  `astra-live login:` prompt. Evidence artifacts: `astraos-boot-self-test`,
  `astraos-boot-menus`.
- **2026-10-16, CI boot self-test (run 38881934636, commit 8f81e3d): PASS.** The built ISO
  booted under `qemu-system-x86_64` on a GitHub runner that provides no KVM — the CPU was
  emulated — and the image's own self-test reported `RESULT: PASS (39 checks, 0 failed)`:
  the console login prompt 143.7 s into the guest boot, LightDM active, an Xfce session
  (xfwm4) running as the live user, every `astraos-*` package at its expected version, the
  hardware, codec and compatibility tools, the Flathub remote, NetworkManager active with
  an IPv4 address, and a real name resolved by DNS. The evidence artifact is
  `astraos-boot-self-test` (`serial.log` is the record; the screenshot captured through
  the QEMU monitor came back black — a capture defect, fixed and proven green in the
  run above). The test starts the kernel and initrd taken from the ISO and attaches
  the ISO as the live medium; the ISO's own boot menus went green in CI on 2026-10-16
  (the `boot-menus` job, `scripts/boot-menu-test.sh` — the run above).
- **2026-10-16, CI build (run 38864588609): structural validation PASS** — 25/25 checks,
  `structural=PASS` in the build manifest, image 2,432,696,320 bytes.
- **2026-10-15, VirtualBox by hand:** the image booted from the live menu to the Xfce
  desktop; the README's "What has been tested" records the details.

An automated end-to-end exercise now exists in the source (2026-10-16):
`scripts/install-boot-test.sh`, run by CI as the `install-boot` job, installs the ISO
onto a blank disk by driving the ISO's own Calamares UI over the QEMU monitor and then
boots that disk alone. It is **pending its first run**; until a run record exists,
nothing in this section changes.

**Consequence:** statements about the live system booting in a virtual machine, and about
the live session's networking, are now backed by recorded runs. Everything about
*installing* — the installer, the installed system, disk encryption — and everything about
*physical hardware* and *UEFI booting* is still a statement of *intent backed by
configuration*, not a report of a test. The build manifest records those items as
`UNTESTED`.

### 1.2 Secure Boot is not supported

Since 2026-10-16 the source carries the signed chain — `--uefi-secure-boot enable` in
`config/live-build/auto/config`, Debian's signed shim and GRUB — and
`scripts/boot-menu-test.sh --medium secure` boots the ISO under OVMF's Secure Boot
firmware with the Microsoft keys enrolled, but **its first run is pending**: the boot
path has not been verified under Secure Boot on any machine yet, and a machine enforcing
Secure Boot must still be treated as one that refuses the medium.

The claim flips — here, in `README.md`, in `docs/SECURITY.md` and in the build manifest —
only when that run is green and the firmware configurations that boot are documented. Do
not tell anyone Secure Boot works before then.

### 1.3 `/etc/os-release` can be overwritten by an upgrade

Debian's `base-files` package owns `/etc/os-release`, `/usr/lib/os-release`, `/etc/issue`,
`/etc/issue.net` and `/etc/motd` as configuration files. A package of AstraOS's own
cannot ship those paths without a dpkg file conflict, and declaring `Replaces: base-files`
would remove the base system.

AstraOS therefore writes them at image build time. **An upgrade of `base-files` can
overwrite them**, after which `/etc/os-release` would identify the system as Debian.

The fix is for AstraOS to ship its own `base-files` variant or to use `dpkg-divert`.
That work is not done.

Unaffected: `/etc/astraos-release` is owned by the `astraos-base` package and is safe, and
`astraos-info` and `astraos-release-info` read it, so the AstraOS version is still
reported correctly even if `/etc/os-release` is clobbered.

### 1.4 The desktop theme does not include window decorations

`AstraOS-Dark` is a **colour-only** GTK theme built on Adwaita. It does not ship an xfwm4
titlebar theme, a Metacity theme or a cursor theme. Window decorations therefore use the
upstream `Default` xfwm4 theme, which is a different look from the reference designs.

Window managers cannot be pointed at a theme name that has no decoration assets on disk
without producing invisible or missing titlebars, so the name is written to a theme that
is guaranteed to be installed rather than to one that looks better and breaks.

### 1.5 Version 0.1.0 has no independent security response

AstraOS has no security team. It inherits Debian's response for components taken from
Debian. The AstraOS-specific packages are the project's own responsibility, and there is
one maintainer.

---

## 2. Untested areas

Rows marked **UNTESTED** have never been exercised. Rows marked **CI** were exercised
only inside CI, under QEMU emulation (runs 38881934636 and 38913161772, 2026-10-16) —
never on physical hardware.

| Area | Status | What testing it requires |
|---|---|---|
| Booting the live ISO | **CI PASS** (the ISO's kernel and initrd, the ISO as the live medium) | Physical hardware |
| Legacy BIOS boot | **CI PASS** (the syslinux menu, run 38913161772) | Physical hardware |
| UEFI boot | **CI PASS** (the GRUB menu, run 38913161772) | Physical hardware |
| Live desktop startup | **CI PASS** (LightDM active, Xfce session as `astra`) | Booting the image by hand and interacting |
| Mouse, keyboard and display resolution in the live session | UNTESTED | Booting the image |
| Live session applications (browser, file manager, terminal) | UNTESTED | Booting the image |
| Network recognition in the live session | **CI PASS** (NetworkManager active, IPv4 address, DNS resolution) | Physical hardware |
| Suspending and resuming | UNTESTED | Bare metal, ideally a laptop |
| Rebooting and shutting down | **CI, partly** (the self-test powers the machine off cleanly; reboot untested) | Booting the image |
| Installer launch | UNTESTED | Booting the image |
| Installer completing on a virtual disk | UNTESTED | A disposable virtual disk |
| Installed system booting without the ISO | UNTESTED | Completing an installation |
| Logging in to the installed system | UNTESTED | Completing an installation |
| Software installation and system updates on the installed system | UNTESTED | Completing an installation |
| Disk encryption through the installer | UNTESTED | A VM, and then verifying with `lsblk` and `cryptsetup status` |
| Dual-boot alongside an existing system | UNTESTED | A VM with two operating systems |
| Any physical hardware | UNTESTED | See `HARDWARE_COMPATIBILITY.md` |
| Accessibility: screen reader, magnification, high contrast | UNTESTED | Booting the image |
| Printer support | UNTESTED | Booting the image with a printer available |

---

## 3. Known functional gaps

### 3.1 No persistence in the live session

The live session is non-persistent. Changes are lost on reboot. The live session's message
of the day says so. There is no persistence option in the boot menu.

### 3.2 X11 only

AstraOS uses X11. The configuration is written so a Wayland transition is possible later,
but **no Wayland session exists or is claimed**. The `xfce4-session` package used here is
the X11 session.

### 3.3 WiFi and firmware coverage is unverified

Firmware for common chipsets is included from Debian's `non-free-firmware` component, but
**no wireless adapter has been tested**. Some chipsets will need firmware that is not
included, and a few will need out-of-tree drivers which AstraOS deliberately does not
ship. See `HARDWARE_COMPATIBILITY.md`.

### 3.4 Proprietary GPU drivers are not included

The desktop uses open-source drivers only. NVIDIA cards will work through `nouveau`,
which is slower than the proprietary driver and, on newer chips, may not work at all.

### 3.5 The firewall's inbound exceptions cover private address ranges only

The firewall is on by default and inbound is denied. The two exceptions — the
assistant's page (`8765/tcp`) and mDNS discovery (`5353/udp`) — are scoped to the
private address ranges (`192.168.0.0/16`, `10.0.0.0/8`, `172.16.0.0/12`, and
`fc00::/7`, `fe80::/10`). A network that hands the phone a *global* IPv6 address is
therefore not covered until the user widens the rule:

    sudo ufw allow 8765/tcp

`/etc/ufw/astraos-policy.conf` (shipped in the image) says the same thing where the
rules live. The default-on decision, its reasons and the self-test exercise that
proves it are recorded in `docs/ROADMAP.md`; the exercise was added 2026-10-16. Its
first run (38903678646) proved the behavioural half — under the host's probe a port
no rule allows stayed unreached while the assistant's page answered a private-range
connection — and failed one static check that demanded a `ufw status` spelling ufw
never prints; the check now reads the verbose listing, and run 38913161772 (commit
0e47f4d) carries the fix and the proof: `RESULT: PASS (51 checks, 0 failed)` with the
firewall checks green and the host's probe unreached.

### 3.6 The installer module set is minimal

The Calamares sequence covers welcome, locale, keyboard, partition, users, summary,
partitioning, unpacking, machineid, fstab, locale, users, display manager, network
configuration, hardware clock, services, bootloader and completion.

Notably **absent**: an OEM setup mode, a package chooser, and any form of network
installation. These are deliberate omissions for the first release.

### 3.7 `apt` is not configured for AstraOS repositories

There is no AstraOS package repository. The installed system receives updates from Debian
directly. AstraOS's own five packages can be updated only by rebuilding and reinstalling
them. This is acceptable for an alpha but must change before a stable release.

### 3.8 The AstraOS tools are English-only

`astraos-info`, `astraos-help`, `astraos-welcome`, `astraos-release-info` and
`astraos-recovery-guide` are written in English with no translation catalogue. The
installer is translated because Calamares is.

### 3.9 The GRUB theme was not visually verified

The GRUB theme and the Plymouth splash were rendered and their files validated, but
**neither has been displayed on a screen**. Font rendering and scaling in a themed GRUB
menu vary by firmware and resolution, and this is a common source of "the boot menu is
invisible" reports. Both fall back to plain colours rather than an image, so an unreadable
menu is unlikely — but unverified.

### 3.10 The boot menu timeout is live-build's default

The pinned live-build (20250505 for Debian 13) has no option for the boot menu timeout: the
`--syslinux-timeout` option that older releases provided was removed, and the rest of its
option list contains nothing equivalent. The configuration script probes for it, so the
build manifest records it as a skipped option instead of silently ignoring the setting.

The consequence is that the menu waits for however long live-build's own bootloader
template says. The failsafe entry, which boots without `quiet splash` and with ACPI and
power management disabled (plan §7.4), is therefore easier or harder to reach than intended
depending on that default. The fix is to ship our own bootloader template with an explicit
timeout; it is deferred because it cannot be verified without booting an image.

### 3.11 Desktop defaults apply to new accounts only

The AstraOS panel layout, wallpaper, keyboard shortcuts and window-manager settings are
seeded from `/etc/skel` into each new account's home directory. An account that already
exists keeps its own settings, and changing anything in the Xfce settings editor makes Xfce
write its own complete file, which then wins.

This is a deliberate trade-off. The alternative is writing to
`/etc/xdg/xfce4/xfconf/xfce-perchannel-xml/`, which is where Xfce looks for system-wide
defaults — but those paths belong to Debian's Xfce packages (`libxfce4ui-common`,
`xfce4-settings`, `xfce4-session`), and dpkg refuses to let a second package own the same
file: the image build stops with "trying to overwrite". Seeding `/etc/skel` is the mechanism
Xfce and Debian both use for defaults that must not fight the packaged files.

The live session's user and any user the installer creates are both new accounts, so a fresh
install gets the AstraOS desktop; a pre-existing account does not.

### 3.12 The AI assistant ships without a model

AstraOS now includes an AI assistant (`astraos-ai`, documented in `docs/AI.md`), and the
limitation that remains is deliberate: **no model and no runtime are installed with the
image**. The assistant is a command and a local page; the model, `llama.cpp` and the
speech tools arrive only when the user runs `astra-ai setup`, because a small model is
about a gigabyte and a distribution should not spend a user's bandwidth and disk on one
unasked.

Three consequences worth stating plainly:

* **A fresh install cannot answer anything yet.** The page loads, explains what to run,
  and the assistant reports "not installed" rather than failing. This is the state every
  new user meets, and it is a design decision rather than a bug.
* **The model is chosen for the hardware, not for the leaderboard.** The catalogue is
  1B–3B Q4 models. A 7B model would be a better assistant on the machine this was
  developed on only if it finished a sentence in a sitting, and it does not.
* **Nothing about the assistant is required by anything else.** No boot unit, no login
  path, no networking, no package management and no recovery tool depends on it, which is
  the property the plan asked for before any AI feature was allowed in.

Speech is split in the same way. Speaking works as soon as a text-to-speech tool is
present, and `espeak-ng` is installed with the image so the assistant is audible out of
the box — an older voice, chosen because it is in Debian, needs no model file and answers
immediately. Recognising speech needs `whisper.cpp`, which is a build, so it is not
installed by default; a phone on the same network can supply a microphone without it.
A neural voice (Piper and a voice model) is not supported yet.

### 3.13 Plymouth's theme file is written at image build time

`plymouth-set-default-theme` selects the boot-splash theme by editing
`/etc/plymouth/plymouthd.conf`. That file belongs to the `plymouth` package, which ships it
as a configuration file.

AstraOS therefore does **not** call the tool from `astraos-branding`'s post-install script.
That script runs inside the very same dpkg run that configures `plymouth`, so dpkg found a
file that no longer matched the copy it had unpacked and stopped to ask which version to
keep — a question that nothing answers during a build:

```
Configuration file '/etc/plymouth/plymouthd.conf'
*** plymouthd.conf (Y/I/N/O/D/Z) [default=N] ? dpkg: error processing package plymouth
(--configure): end of file on stdin at conffile prompt
```

The theme is selected by `config/live-build/config/hooks/live/0120-plymouth.hook.chroot`
instead, which runs after every package has been installed and configured. The consequence
is the same one recorded in §1.3 for the identity files: **an upgrade of `plymouth` may
later report `/etc/plymouth/plymouthd.conf` as locally modified**, and keeping the AstraOS
theme across such an upgrade is not guaranteed. The build aborts if the theme, the tool or
the initramfs rebuild is missing, so an image is either branded or not built at all.

### 3.14 The credential scan cannot see everything

`astraos-scan-secrets` runs at image build time (`0500-security.hook.chroot`) and refuses
the build when it finds an armored private key. Three limits are known and deliberate:

- **`/usr/share/doc` is out of scope.** Debian ships *example* keys in the documentation of
  some packages — the `openvpn` examples contain a sample CA, server and client keys — and a
  sample in a manual is not a credential. Flagging those would make the check unrunnable, so
  the scan covers `/etc`, `/root`, `/home`, `/srv`, `/opt`, `/usr/local`, `/var/lib` and
  `/usr/share/astraos`.
- **A key inside an archive, a firmware blob or any other binary is not detected as a key.**
  Binary files that mention the armor text are reported as *notes* instead of findings,
  because a compiled-in parser constant (the one in `ssh-keygen`, for example) contains the
  same text and nothing distinguishes them by text alone. What is detected is the shape of an
  armored block: a line that is exactly an armor header, followed before the block ends by
  the matching footer or by base64 payload. A key pasted into the *middle* of a line —
  inside a string literal, say — is therefore not detected either: both the image scan and
  the repository scan require the header to be a line of its own, which is how a key is
  written into a file.
- **A key generated after the hook has run is not seen.** Nothing in AstraOS generates one
  into the image, and the SSH host keys that OpenSSH creates on a real installation are the
  case plan §10.4 wants: they belong to the machine, not to the image.

An encrypted key is reported like any other, and so is a block that lost its last line to a
bad copy. Files that only *mention* a format are printed with their path and dpkg owner and
do not fail the build; that output is the audit trail for the decision to let them through.

---

## 4. Reporting these

If you can test something in this list, the result is valuable whether it passes or
fails. See `CONTRIBUTING.md`. A report saying "UEFI boot in VirtualBox failed with this
screenshot and this log" is more useful than a report saying it did not work.
