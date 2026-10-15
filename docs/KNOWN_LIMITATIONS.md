# AstraOS 0.1.0 Alpha — known limitations

This document exists so that nobody has to discover a limitation the hard way. It lists
what is not done, what is not tested, and what is known to be wrong. Per plan §25,
defects are not hidden because they make the release look less polished.

**AstraOS 0.1.0 is an alpha release. It is not suitable for a computer you depend on,
and it should not be installed on a machine holding data you cannot lose.**

---

## 1. Release-level limitations

### 1.1 No image has been built that passed validation, and none has been booted

The development machine is a Windows host whose WSL2 Linux environment cannot start, so
image building happens in CI (`.github/workflows/build-iso.yml`). The state of the first
deliverable, stated exactly:

- **No image has been built that passed structural validation.**
- **2026-10-13, CI build (run 38411369641):** live-build completed successfully and
  produced a 2.0 GB `astraos-0.1.0-alpha-amd64.iso` with the UEFI loader, the legacy BIOS
  loader, GRUB configuration, kernel, initramfs and live filesystem all present. The build
  was then failed by the repository's own structural validator, which could not read the
  squashfs it had extracted (a defect in the validator's extraction, fixed the same day —
  see the changelog). The image contents were therefore never inspected and the artifact
  was rejected. The same build also spent ~24 minutes with apt's http method retrying one
  stalled download in a 12.7-million-line loop; the transport settings that prevent that
  are now set in the build configuration.
- **2026-10-13, CI build (run 38449590880):** the earlier fixes held. The chroot hooks
  passed, the image was packed (2.05 GB, `file(1)` reporting a bootable ISO 9660 image), and
  this time the validator read the live filesystem: it extracted 1894 MiB, matching
  `mksquashfs`'s own report of the filesystem it had built. It failed on nine checks, and all
  nine were defects in the checks or in the medium's identity rather than in the image: eight
  were a pipeline race in the validator's own component checks, and one was the medium naming
  Debian. All of them are repaired (see the changelog), and the medium's description is now put
  through the validator's own check by `tests/integration/test_iso_validator.py`, so the
  branding half is verified without spending a build on it. The build log for this run is 715 KB rather than 1.9 GB, which is the apt
  transport fix working.
- **No image has passed structural validation yet.** The next CI build tests the pipeline
  race repair, the medium identity hook and the corrected package check together.
- **No ISO has ever been booted in a virtual machine;** the installer has never been run;
  no installed system has ever booted. See `docs/INSTALLATION_VIRTUALBOX.md` for the
  procedure that changes this.

**Consequence:** every statement in this repository about booting or installing is a
statement of *intent backed by configuration*, not a report of a test. The build manifest
records these items as `UNTESTED`.

### 1.2 Secure Boot is not supported

Secure Boot is **disabled** in the live image's own boot configuration and the boot path
has never been verified under Secure Boot on any machine.

A `shim` and signed GRUB are installed for UEFI installations, because they are harmless,
but this does **not** mean Secure Boot works. Do not tell anyone it does.

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

Everything in this list is **UNTESTED**. None of it is known to work.

| Area | Status | What testing it requires |
|---|---|---|
| Booting the live ISO | UNTESTED | A virtual machine or spare hardware |
| Legacy BIOS boot | UNTESTED | A VM configured for BIOS |
| UEFI boot | UNTESTED | A VM configured for UEFI |
| Live desktop startup | UNTESTED | Booting the image |
| Mouse, keyboard and display resolution in the live session | UNTESTED | Booting the image |
| Live session applications (browser, file manager, terminal) | UNTESTED | Booting the image |
| Network recognition in the live session | UNTESTED | Booting the image |
| Suspending and resuming | UNTESTED | Bare metal, ideally a laptop |
| Rebooting and shutting down | UNTESTED | Booting the image |
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

### 3.5 The firewall is not enabled by default

Nothing listens on the network by default: there is no SSH server, no web server, and no
remote administration daemon. Enabling a firewall during the live session can break the
network the user needs to install, so it is left off with a documented policy in
`/etc/ufw/astraos-policy.conf`.

An application that starts listening is therefore not protected by a host firewall,
which is the same position the other major desktop distributions take.

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
