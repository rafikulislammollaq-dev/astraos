# Changelog

All notable changes to AstraOS are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the
project uses [semantic versioning](https://semver.org/spec/v2.0.0.html) with the
following meaning for this project:

- **MAJOR** — a change that requires reinstalling, or that breaks package compatibility.
- **MINOR** — new functionality in a backwards-compatible way.
- **PATCH** — fixes and internal changes.

Because AstraOS is a distribution, a MINOR or MAJOR release also pins a new Debian base.
The pinned base is recorded in `VERSION` and `config/distribution.env`.

---

## [Unreleased]

### Fixed

- The image verification hook reported "an initramfs is in /boot" as FAIL for an image that
  had one, one assertion before the ISO would have been packed. The check asked
  `ls /boot/initrd.img-* /boot/initrd-*`: with nullglob off — it is off in dash, which is
  /bin/sh in this image — the pattern that matches nothing is passed on as its own literal
  text, `ls` reports "cannot access '/boot/initrd-*'" and the whole assertion fails. The same
  hook then opened that initramfs and found the AstraOS theme inside it. The check now loops
  over both names and tests each one, and `tests/static/test_scripts.py` rejects a command
  that is handed more than one glob — verified against the line that failed, and against the
  loop that replaced it.

- The chroot's apt configuration listed the pinned release suite in
  `config/archives/astraos.list.chroot` while live-build also wrote it from the mirror
  options, so every apt run reported each target as "configured multiple times" — inside the
  build and on any live system, where a user would see the warning without being able to act
  on it. The file now pins only the update and security suites, which live-build cannot add
  for this base release (it writes the pre-2017 "<suite>/updates" spelling, which Debian 13
  does not have).

- The credential scan stopped a real image build without saying what it had found. The
  hook searched `/etc` for the text `BEGIN PGP PRIVATE KEY` and printed the pattern it had
  searched for rather than the file that matched, so the build log held no path to
  investigate; a text search also cannot tell a leaked key from a file that merely *names*
  the armor format, which is what it matched. The check is now `astraos-scan-secrets`, a
  tool shipped in `astraos-base` and run by `0500-security.hook.chroot`, and it reports
  every match with its path and its dpkg owner. It recognises a key by its shape — a line
  that is exactly an armor header, followed before the block ends by the matching footer or
  by base64 payload — so magic(5) entries, compiled-in parser constants and documentation
  lines are reported as notes instead of failing the build. The scan also covers `/root`,
  `/home`, `/srv`, `/opt`, `/usr/local`, `/var/lib` and `/usr/share/astraos` instead of
  `/etc` alone, and it recognises the PKCS#8 armors (`-----BEGIN PRIVATE KEY-----` and
  `-----BEGIN ENCRYPTED PRIVATE KEY-----`) and the pre-2.0 `PGP SECRET KEY` spelling, none
  of which was in the fixed list of patterns it replaced. The tool is exercised against
  fixture trees by `tests/security/test_secret_scan.py`, including the magic(5) shape that
  failed the build and the requirement that a failure names the file.
- The repository scan in `tests/static/test_repository.py` used the same text search and had
  the same weakness: naming an armor header in a comment or in documentation was reported as
  a committed key. It now uses the shape rule too, so it still catches a key written into a
  file — including one missing its final line — and no longer requires an exception list to
  be told apart from a paragraph about keys.

- The security hook searched `/etc/sudoers.d` for the word `NOPASSWD` and matched the
  shipped policy's own sentence saying that no such rule exists, so a correct image was
  refused with "a passwordless sudo rule is present in /etc/sudoers.d". Both hooks now look
  for a *rule* — the pattern cannot reach past a comment marker — and a test pins it against
  the shipped policy in both directions: it must ignore the explanation, and it must still
  match a real passwordless rule. `tests/security/test_security_config.py` had always
  ignored comment lines for exactly this reason; the hooks had not.

- The installer verification hook required an *unquoted* `defaultFileSystemType: ext4` in
  the Calamares partitioning policy, while the configuration the installer package ships
  writes the value the other way YAML allows — quoted. Hooks run last, so the build died
  there with "partition.conf does not select ext4 as the default root filesystem" after
  every package had been installed, and the only way to find it was another full build.
  Both spellings are accepted now, and `tests/static/test_hook_assertions.py` compares the
  hook's pattern with the file the repository ships, in both directions: the pattern must
  still be the one the hook uses, and it must match (or, for a refusal, not match) the
  shipped file. The same module pins the partitioning-safety assertions.
- The image verification hook asserted that `/usr/bin/ssh` did not exist, while
  `config/package-lists/50-networking.list.chroot` deliberately selects `openssh-client`.
  No build could satisfy both, so the check would have failed at the very end of the next
  build. The property the project documents is that nothing *listens*: both hooks now test
  for the ssh server, and `docs/SECURITY.md` states that the client is present, is not a
  service and is never enabled. A test rejects any hook that requires a binary the package
  selection puts in the image.

- `astraos-branding`'s post-install script selected the boot-splash theme with
  `plymouth-set-default-theme`, which rewrites `/etc/plymouth/plymouthd.conf` — a file the
  `plymouth` package owns. A maintainer script runs inside the dpkg run that is configuring
  that very package, so dpkg found a configuration file that no longer matched the copy it
  had unpacked and stopped to ask which version to keep. Nothing answers that during a
  build, and the image build failed at the end of the chroot stage with "end of file on
  stdin at conffile prompt", after the entire base system had been installed. The theme is
  now selected by `config/live-build/config/hooks/live/0120-plymouth.hook.chroot`, which
  runs after every package is installed and configured; the hook rebuilds the initramfs,
  since the initramfs carries its own copy of the theme, and aborts the build if the theme,
  the tool or the rebuild is missing. The verify hook asserts both the selected theme and
  its presence in the initramfs, and a test rejects any package maintainer script that calls
  a tool rewriting another package's configuration file (verified to fail against the
  postinst as it was).

- The desktop defaults were installed into `/etc/xdg/xfce4/xfconf/xfce-perchannel-xml/`,
  which belongs to Debian's Xfce packages: `libxfce4ui-common` owns the keyboard shortcuts
  file and `xfce4-settings` and `xfce4-session` own two more. Two packages cannot own the
  same path, and dpkg stopped the image build with "trying to overwrite". The panel layout,
  keyboard shortcuts, window-manager settings and wallpaper are now seeded through
  `/etc/skel`, which this project owns and which populates the live account and every account
  the installer creates. A test rejects a mapping back into the upstream directory.
- The installer list requested `calamares-settings-debian`, whose `/etc/calamares` tree is the
  same one `astraos-installer` owns — the second "trying to overwrite" in the same build.
  Nothing needs it: upstream `calamares` neither depends nor recommends it, only the
  `live-task-*` metapackages do. It is gone from the list, and `astraos-installer` now
  declares `Conflicts` and `Replaces` against it, so a future dependency chain produces a
  clean conflict instead of a half-finished unpack.
- `astraos-installer` declared `Depends: kpmcore`, which is a source package in Debian 13,
  not an installable binary (the library is `libkpmcore12`). apt resolved nothing and failed
  the image build after every package had been downloaded. The availability verifier checked
  only the package lists, never the dependencies the `.deb` files declare, so it now checks
  those too — including `Recommends` and alternative groups — and reports which file and
  field a bad name came from. AstraOS's own package names are excluded from that check
  because they are built by this repository.
- The AstraOS packages were staged one directory too deep. `build-packages.sh` wrote them to
  `build/live-build/live-build/config/packages.chroot`, while live-build only reads
  `config/packages.chroot` directly under its working directory. All five `.deb` files were
  built correctly and then left out of the image, so the image had no `astraos-info`, no
  branding and no installer. The identity hook caught it by asserting that the AstraOS
  packages are present after installation, and a test now rejects the repeated path segment.
- The image contained every `firmware-*` package in the Debian archive, not the reviewed
  selection in `config/package-lists/20-firmware.list.chroot`: live-build scans the archive
  and installs them all unless told not to. It also pulled in the contrib packages
  `firmware-b43-installer` and `firmware-b43legacy-installer`, which download Broadcom
  firmware from the internet in their post-install scripts; that download failed and stopped
  the build after several gigabytes had been installed. The sweep is now switched off
  (`--firmware-chroot false`), the list is authoritative and carries the hardware coverage
  the sweep provided, and the b43 gap is documented in `docs/HARDWARE_COMPATIBILITY.md`
  rather than papered over.
- A package list asked for two conflicting time daemons. `ntpsec` declares
  `Conflicts: time-daemon`, which `systemd-timesyncd` provides, so apt could not resolve the
  package set and failed after downloading all of it. `systemd-timesyncd` is the one AstraOS
  ships; a test now rejects any second time daemon.
- The `astraos-installer` control paragraph carried a comment block explaining its
  `Conflicts` and `Replaces` fields. A Debian control file has no comment syntax: dpkg-deb
  read the `#` as a field name and stopped the package build with "field name '#' must be
  followed by colon", after all five AstraOS packages had been assembled. The fields stay
  where they are; the explanation moved here and into `config/package-lists/60-installer.list.chroot`,
  which already documents why Debian's settings package is not wanted. A static test now
  checks every control template against the grammar dpkg-deb accepts — a field, an indented
  continuation, or a blank line — instead of finding out on a runner.
- The image build ran with the option set of whichever live-build happened to be installed.
  The pinned release (live-build 20250505 for Debian 13) renamed `--binary-images` to
  `--binary-image` and `--binary-compression` to `--chroot-squashfs-compression-type`, and
  removed `--tasks`, `--syslinux-timeout`, `--updates-chroot-security` and the volatile
  mirror option. The configuration now handles both spellings, and a test rejects any option
  passed without a `supports` probe. The option list was read out of the live-build package
  itself rather than guessed; the pinned release is also the one that has `--bootloaders`,
  which is what legacy BIOS boot support depends on.
- The chroot's apt failed with "The repository 'security.debian.org/debian-security
  trixie/updates Release' does not have a Release file", which stopped the build after
  bootstrapping had succeeded. The security and update suites now come from the repository's
  own archive list, which pins `trixie-security` and `trixie-updates` by name, and
  live-build's own generation of those two lines is switched off. Having two sources for the
  same suite had also produced a screenful of "configured multiple times" warnings on every
  apt run inside the chroot.
- CI assembled the image with the Ubuntu runner's older `debootstrap` and `live-build`,
  which is what produced the two problems above. The image is now built inside a
  `debian:trixie` container, so the toolchain is the release being assembled and the build
  no longer depends on the runner's distribution.
- `scripts/build-packages.sh` printed progress on stdout while `finish_package` and
  `stage_package` return a path through command substitution, so the package list captured a
  log line and the staging step looked for a file named after it. Progress goes to stderr,
  and a test enforces the split for any script that captures its own function's output.
- `auto/build` recursed: live-build runs `auto/<command>` as part of `lb <command>`, so the
  `lb build` inside `auto/build` re-ran `auto/build`, and the first build that reached the
  live-build stage died in a loop. The file is gone; the log capture and the
  ISO-existence check it performed now live in `scripts/build-iso.sh`, the process that
  starts live-build and can therefore wrap it. A test rejects any auto script that runs its
  own live-build command without the `noauto` positional.
- The auto scripts were linted as bash although live-build runs them with sh. That hid a
  `${PIPESTATUS[0]}` in `auto/build` which made every image build die with `Bad
  substitution` under dash before any package was downloaded. ShellCheck's dialect is now
  chosen per file: sh for the automatic scripts and the chroot hooks, bash for the rest.
- The image build validated a staging directory with `dpkg-deb --info` and discarded the
  error, which produced "dpkg-deb rejected the control directory for astraos-base" with no
  explanation. It now reads the produced `.deb` back and checks the name and version in it.
- Every script was committed without the executable bit, because it was first committed
  from Windows, which cannot store one. Nothing noticed locally — the files still run in
  Git Bash — and it broke the first real build on Linux, where
  `sudo ./scripts/bootstrap-build-environment.sh` failed with "command not found". Worse,
  live-build executes the chroot hooks from the checkout, so an unset bit would have failed
  the build rather than any check. The bit is now set for all 29 shebang files, and
  `tests/static/test_scripts.py` asserts the mode recorded in the git index, which is the
  only place it survives a Windows checkout.
- An absent ShellCheck was reported as a passing test. It is now reported as a skip with a
  reason, per the rule that an unperformed check is never a pass.
- `astraos-info` reported an inactive firewall as `active`. The `case` patterns were
  `*active*` and `*inactive*`, and `*active*` also matches `Status: inactive`, so the first
  match won and a fresh install — where ufw is shipped disabled by design — printed
  `firewall active`. The patterns are now anchored to the `Status:` prefix, and
  `tests/security/test_security_config.py` runs the real tool with a stub `ufw` on `PATH`
  so the reported state is checked behaviourally rather than by reading the source.
- ShellCheck findings, which only appear where ShellCheck is installed (the CI runner, not
  the development host): dead `REPO_ROOT`/`SCRIPT_DIR` assignments in
  `bootstrap-build-environment.sh` and `generate-checksums.sh`, and a `for` loop in
  `0600-cleanup.hook.chroot` written with a single-item list. That loop now preserves
  `/etc/astraos-release`, `/etc/lsb-release` and `/etc/os-release` as build provenance.
- Documentation staging: `README.md` was listed for installation into
  `/usr/share/doc/astraos/` but was copied from `docs/README.md`, which does not exist,
  so the image would have shipped with only a warning logged and no README — breaking the
  attribution pointer in `astraos-release-info`. The staging step now resolves each
  document's source path explicitly, and the packaging test asserts that `README.md` is
  taken from the repository root. Found by `tests/integration/test_packaging_mapping.py`
  on an unbuilt tree; no image has been built, so no shipped artifact is affected.

## [0.1.0] Alpha — codename Nova — unreleased

The first development release. **No image has been built or booted yet.** The status of
every deliverable is recorded in `README.md` and `docs/KNOWN_LIMITATIONS.md`.

### Added

**Distribution**
- Independent distribution identity: `/etc/os-release`, `/etc/astraos-release`,
  `/etc/lsb-release`, `/etc/issue`, `/etc/motd`, generated from version-controlled
  templates so the identity has one source of truth.
- Pinned Debian base: Debian 13 (trixie), amd64, with `trixie-updates` and
  `trixie-security` suites enabled and backports deliberately excluded.
- Package selection organised into eight reviewable lists: core, kernel, firmware,
  graphics, desktop, applications, networking and installer.
- Distribution utilities: `astraos-info`, `astraos-help`, `astraos-welcome`,
  `astraos-release-info`, `astraos-recovery-guide`.
- Five `.deb` packages: `astraos-base`, `astraos-branding`, `astraos-desktop`,
  `astraos-system-tools`, `astraos-installer`.

**Desktop**
- Xfce configuration applied through the documented mechanisms, so the desktop stays
  user-configurable and upgradable with upstream packages.
- Two-panel layout: a top status bar and a bottom launcher dock with a workspace
  switcher.
- Keyboard shortcuts for the launcher, terminal, file manager, browser, system
  information, screenshots, screen lock and task manager.
- AstraOS-Dark GTK theme (colour-only, built on Adwaita), AstraOS icon theme,
  Xfce skeleton defaults.
- Default applications: Firefox ESR, Thunar, xfce4-terminal, Mousepad, Atril,
  Ristretto, Parole, Xarchiver, Synaptic, GParted.

**Branding**
- Original AstraOS ring mark in colour and two monochrome variants, plus a wordmark.
- A dependency-free asset renderer (`branding/tools/render_assets.py`) that generates
  every bitmap from `config/branding.env` using only the Python standard library.
- Plymouth boot splash, GRUB menu theme, LightDM greeter theming, dark and light
  wallpapers, login background, and a brand preview page.

**Installer**
- Calamares configuration with a documented module sequence, and safety properties
  asserted at build time: the target disk is never assumed, erasing is never the
  default, partition labels are always shown, and the summary step precedes the
  destructive phase.
- Installer branding.
- No fixed or shared credentials; no autologin; the live-session account is removed
  from the installed system.

**Build system**
- `scripts/validate-environment.sh` — refuses to build on a host that cannot.
- `scripts/build-packages.sh` — builds the AstraOS packages reproducibly, driven by
  `SOURCE_DATE_EPOCH`.
- `scripts/configure-live-build.sh` — stages the live-build tree, renders templates and
  builds the packages.
- `scripts/build-iso.sh` — the single build entry point, fatal on any stage failure.
- `scripts/validate-iso.sh` — structural image validation, including inspection of the
  live filesystem contents.
- `scripts/verify-package-availability.py` — verifies every configured package against
  the real Debian archive index.
- CI: a pull-request validation workflow and a manually triggered ISO build workflow.

**Security**
- Documented sysctl defaults, sudo policy with no passwordless rules, APT signature
  policy, and a documented firewall policy that is not enabled by default.
- In-image assertions that fail the build if a passwordless sudo rule, an embedded
  private key, a disabled APT verification setting or an SSH server is present.

**Testing**
- A static test suite (`tests/run.py`) covering configuration consistency, package
  selection, branding asset validity and cross-references, desktop entries, Calamares
  safety settings, repository structure, secret scanning and shell script validation.

### Known limitations

See `docs/KNOWN_LIMITATIONS.md` for the complete list. The most significant:

- No image has been built or booted.
- Secure Boot is not supported and not claimed.
- `/etc/os-release` can be overwritten by an upgrade of Debian's `base-files`.
- The desktop theme does not include window decorations.
- No physical hardware has been tested.

### Notes

- AstraOS uses the Debian-supplied Linux kernel. It is not a from-scratch kernel, and
  the project does not present it as one.
- No AI feature is included, and nothing in the boot path depends on a network service.
