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

### Added

- **The installer is exercised end to end in CI, against the real Calamares UI
  (source; its first run is pending).** `scripts/install-boot-test.sh` boots the built
  ISO in QEMU with `astraos.ci.install=1` on its command line, installs it onto a blank
  20 GiB disk through the ISO's own installer, and then boots that disk alone — no
  medium attached — and requires the image's own self-test in its installed mode. The
  switch is deliberately not the self-test's: the install driver's unit conditions on
  the exact word `astraos.ci.install=1`, and the self-test's unit was tightened from
  the bare prefix `astraos.ci` to the exact word `astraos.ci=1`, because systemd
  matches a condition without `=` against the beginning of a command line word — the
  shared prefix would have let each run during the other's boot, and a self-test that
  screenshots the desktop and powers the machine off mid-install would eat the disk.
  The wizard is driven from outside: Return advances the pages whose defaults are
  correct (the one blank disk arrives selected with Erase pre-selected, through
  CI-only presets appended to copies of the shipped module configs — never edited
  into them, never duplicated), a per-run password generated on the host is typed
  into the users page's two password fields, and a screendump precedes every step so
  a wrong coordinate is visible in the evidence instead of guessed about. The
  installed half runs the self-test's new installed-mode branch — a login greeter
  instead of a live session, no autologin, no live account, and the installer's
  lock-down file verified from outside the installer — and the host additionally
  requires the login prompt to name the installed account's hostname. The guest half
  (`astraos-install` and its unit) ships in every ISO and starts only when its exact
  word is on the command line. The workflow gained the `install-boot` job
  (`install_boot` in the manual trigger; evidence uploaded as
  `astraos-install-test`). The first run is the proof, and it will be recorded here
  when it happens.

- **The firewall is on by default (source; its first CI run is pending).** The decision
  recorded in the roadmap — ufw shipped disabled by design — is reversed: a firewall
  that waits to be enabled protects exactly the users who never enable it. `ENABLED=yes`
  now ships in `/etc/ufw/ufw.conf`, and the exceptions live in `/etc/ufw/user.rules`
  (IPv4) and `/etc/ufw/user6.rules` (IPv6): the assistant's page (`8765/tcp`,
  pairing-gated) and mDNS (`5353/udp`, what finds printers), both only from the private
  ranges. Everything else inbound is dropped and logged. DHCP replies were already
  allowed by ufw's own `before.rules`, which answers the old "it could break the
  installer's network" reason rather than ignoring it. The self-test now checks the
  active state, the deny default and the page rule, and the caller probes a port no rule
  allows while the guest watches it — with the firewall up, nothing may arrive, and the
  guest fails its own check if anything does. `/etc/ufw/astraos-policy.conf` explains
  every rule where it lives; `docs/SECURITY.md` §3 and `docs/KNOWN_LIMITATIONS.md` §3.5
  record the scope (private ranges only) and how to widen it.

- **The screenshot capture is made real (source; its first run is pending).** The
  first green boot self-test's captured image was a flat black with only the cursor
  although the session was healthy — QEMU's stdvga emulation (fixed upstream in 9.0.2,
  not in the 8.2 the CI runner ships) clears the shared framebuffer when the guest
  blanks the screen, and unblanking then stays black. The guest now turns blanking off
  (`xset s off`, `s noblank`), forces the display on (`xset dpms force on`, `-dpms`)
  and repaints the whole screen (`xrefresh`) as its `screenshot-ready` check right
  before it reports its result; the host measures every capture's standard deviation,
  retries while the guest still holds the session, keeps the shot with the most
  content, and says so in the transcript when even that is flat. The image utilities
  the guest uses (`x11-xserver-utils`, `x11-utils`) already ship. The first run that
  captures the desktop for real is the proof, and it will be recorded here when it
  happens.

- **The ISO's own boot menus are exercised (source; its first CI run is pending).** It
  is the menu, not the host, that boots the guest now: `scripts/boot-menu-test.sh`
  boots the built ISO with QEMU's own firmware starting the machine — no kernel, no
  initrd, no command line supplied — accepts the bootloader menu's default entry with
  Enter injected through the QEMU monitor, and passes only when the live system's login
  prompt appears on the serial console. Two media: `bios` (syslinux via the ISO's El
  Torito boot record, plain SeaBIOS) and `efi` (GRUB via OVMF attached as a matched
  pflash code + variable-store pair; the system firmware files are never written to —
  the variable store is always a private copy). The pass condition can only be met if
  the shipped menu entries carry the serial console, so `console=ttyS0,115200n8` is now
  part of `LIVE_APPEND` in `config/live-build/auto/config` — deliberate for real
  hardware as well: a machine with a serial port gets boot messages and a login prompt
  there. `astraos.ci` stays out of `LIVE_APPEND` (it would power real desktops off) and
  out of the menu script; the existing mirror test and the new
  `tests/static/test_boot_menu.py` hold both ends. The workflow gained a `boot-menus`
  job (both media per dispatch, the UEFI run still performed when the BIOS run failed,
  evidence uploaded as `astraos-boot-menus`). The first CI run is the proof, and it
  will be recorded here when it happens.

- **The assistant's page can now be reached from a phone — by pairing.** The roadmap's
  Stage 1 phone-page item got its first slice: `astra-ai serve --lan` opens the page to
  the local network, but every request from anything that is not the computer itself is
  refused (HTTP 401) until the phone enters the six-digit code shown by `astra-ai pair`.
  A code lives ten minutes, pairs exactly one phone, counts its wrong tries (five, then
  a one-minute cooling-off), and the paired token can be revoked at any time with
  `astra-ai unpair`; the computer itself is never asked to pair. The page grew the
  pairing screen (a code input when the server says pairing is needed), tokens live in
  the phone's browser only, and nothing is written to disk — stopping the server
  revokes every phone. The boot self-test exercises the whole arc over QEMU's
  forwarded port — this computer serves without pairing, the phone is refused
  unpaired, pairs with the code, gets a served request, and is refused again after
  revocation — with the host side of that exercise recorded in `phone-host.log` beside
  `serial.log`. Honest first-slice scope: plain HTTP on the local network (no TLS yet),
  bearer tokens, and the firewall default stays undecided (see the roadmap's firewall
  item). Unit and static tests pin the gate, the code policy, the page and the evidence
  markers; the first boot-self-test run carrying the phone section is the CI proof, and
  it will be recorded here when it happens.

- **The first green boot self-test.** 2026-10-16, run 38881934636 (commit 8f81e3d): the
  built ISO booted under QEMU on a runner with no KVM — pure CPU emulation — and the
  image's own self-test reported `RESULT: PASS (39 checks, 0 failed)`. The guest reached
  the console login prompt 143.7 s in; the checks confirm LightDM active, an Xfce session
  (xfwm4) running as the live user, every `astraos-*` package at its expected version,
  the hardware, codec and compatibility tools, the Flathub remote, NetworkManager active
  with an IPv4 address, and a real name resolved by DNS — the check that pins the DNS
  defect entry below. Job times: build 18m43s, boot 6m28s; the guest ran 4 vCPU / 4 GiB.
  The evidence artifact is `astraos-boot-self-test` (`serial.log` is the record; the
  screenshot captured through the QEMU monitor came back black — a capture defect, so it
  is not usable as visual evidence yet, and making the capture real is tracked on the
  roadmap). The test starts the kernel and initrd taken from the ISO with the ISO
  attached as the live medium; the ISO's own boot menus (syslinux BIOS, GRUB EFI) are
  still exercised only by hand. The README's maturity table and "What has been tested",
  `docs/KNOWN_LIMITATIONS.md` §1.1/§2 and the roadmap's Stage 1 entry record it in the
  same commit.

- **The image can prove that it boots.** The ISO is no longer only built and inspected:
  `.github/workflows/build-iso.yml` gained a `smoke-boot` job (on by default) that boots
  the freshly built ISO in QEMU, waits for the image's own self-test, takes a screenshot
  of the booted desktop through the QEMU monitor and fails the workflow unless the image
  reported PASS. The QEMU command line is built from `config/distribution.env`, so the
  boot test cannot drift from the ISO's own boot entry, and it adds `console=ttyS0` plus
  `astraos.ci=1` (below). KVM is used when the runner provides it, emulation is the
  fallback; `scripts/smoke-boot.sh` is the driver and runs locally against any built ISO.
  The evidence — `serial.log`, `screenshot.png`, `qemu.out` — is uploaded as the
  `astraos-boot-self-test` artifact, and the build job's summary no longer claims booting
  is untested, because the workflow now boots it. (The README's "What has been tested"
  list records the proof: the first green run is the entry above.)

- **Every image carries a self-test it runs on request.** `astraos-smoke.service` (gated
  on `ConditionKernelCommandLine=astraos.ci`) runs `/usr/local/sbin/astraos-smoke` after
  the desktop is up: release identity, LightDM + Xfce session, every AstraOS package, the
  hardware and compatibility stack, the commands (HUD, assistant, all-in-one, Windows
  bridge, wine, ffmpeg, flatpak), the Flathub remote, and that a real name resolves. It
  prints one line per check to the serial console, holds the desktop for the screenshot
  and powers off; a normal boot never runs it. Any medium carrying this release can
  describe the machine it is on — what a hardware bug report needs.
  `/usr/share/astraos/SELF-TEST.txt` documents it, `docs/BUILDING.md` §8 covers the CI
  side, and `tests/static/test_smoke_boot.py` pins the output contract, the kernel
  condition, the explicit executable bit at staging time, and the rule that the QEMU boot
  mirrors `distribution.env` instead of retyping the live identity.

- **Hardware enablement beyond the kernel and firmware**
  (`config/package-lists/35-hardware.list.chroot`): VA-API video decode for Intel and AMD
  (plus `vainfo`), `fwupd` for device firmware updates, `zram-tools` (the biggest
  responsiveness win on the 4 GB machines this release targets), `irqbalance`,
  `bluez-firmware`, MTP/Android tools (`libmtp-runtime`, `mtp-tools`, `adb`, `fastboot`,
  the platform-tools udev rules), filesystem tools (`ntfs-3g`, `exfatprogs`,
  `squashfs-tools`) and two printer driver families (gutenprint, escpr).

- **Compatibility with the files and programs people already have**
  (`config/package-lists/45-compatibility.list.chroot`): the full codec set
  (`libavcodec-extra`, `ffmpeg`, GStreamer libav/bad/ugly, DVD navigation), Flatpak with
  the desktop portals and keyring integration, Wine (64-bit out of the box) with
  winetricks, `gdebi`, `timeshift`, `inxi`, `speech-dispatcher`.
  `0900-compat.hook.chroot` points the system-wide Flatpak remote at Flathub: a pointer
  only — no application is installed at build time and nothing is downloaded at boot —
  recorded in `/usr/share/astraos/COMPAT-REPORT.txt`, with the boot self-test checking
  the remote exists. Every name in both lists was verified against the Debian trixie
  archive; `libdvdread8` is virtual there (the time_t transition renamed it), so
  `libdvdnav4` pulls the read library at the soname the release actually ships.

### Fixed

- **The firewall's port check reads the `ufw status` listing ufw actually prints (its
  first run proved the firewall and failed on its own spelling).** Run 38903678646
  ended the boot self-test at `51 checks, 1 failed`: `firewall-page-allowed` demanded
  `8765/tcp … ALLOW IN …` from plain `ufw status`, but the shipped ufw (0.36.2,
  `backend_iptables.py`) blanks the direction column outside verbose mode — a check
  that could never pass, while the behaviour it stands for was proven in the same run:
  the host's probe of an unallowed port died at the firewall, the guest recorded no
  arrival, and the assistant's page answered a private-range connection. The check now
  reads `ufw status verbose` (one call, shared with the default-policy check) and
  prints the rows it saw when it fails.

- **The installer's configuration is made true (source; its first end-to-end run is
  pending).** Every key in `installer/calamares/settings.conf` and `users.conf` was
  checked against the exact Calamares Debian 13 ships (the 3.3.14 sources), and three
  kinds of false statement came out. The sequence listed `finished` inside the exec
  phase — a done page no user would ever see, because Calamares' own ViewManager calls
  "no finished step after an exec" a weird state; the done page is now its own `show:`
  phase, as upstream's configuration has it, and `quit-at-end: false` (now stated
  explicitly) keeps it on screen until the user asks for the reboot. Two settings keys
  no Calamares in the pinned suite reads (`requirePassword`, `showPicker`) were
  removed. And `users.conf` claimed a user policy it did not have: the key that was
  supposed to keep root disabled was read by nothing (the module's default is
  `setRootPassword: true`, so the installer had been offering to set a root password,
  against plan §13.1), the shell sat under a dead top-level key instead of the `user:`
  submap, and with no `passwordRequirements` configured the module's own
  `passwordStatus()` reports the empty string as valid: an installation with no
  password was possible. `setRootPassword: false`, `user:`/`shell:` and
  `passwordRequirements: minLength: 1` replace them, the dead `username:` block is
  gone, and the build hook now refuses an image whose users.conf would offer a root
  password or accept an empty one. The first run that carried the slice
   (38909791960) died at the end of the chroot stage on the hook's own new assertion: it
   used `grep -A4E`, which GNU grep reads as `-A 4E` — "invalid context length argument"
   — so the pattern never ran and an image whose packages and other assertions were all
   in place was refused. The assertion is two plain greps now, verified against the
   shipped file before it was committed, and `tests/static/test_hook_assertions.py`
   both pins the patterns and refuses that flag shape; the installer's first end-to-end
   run is still pending.

- **`astra doctor` no longer reads "Status: inactive" as active.** Its pattern was the
  unanchored `*"active"*`, which also matches "inactive" — the same defect the security
  tests pin in `astraos-info`. The firewall being on by default makes the misreport rarer
  but not less false; both tools now anchor on `"Status: active"*`, and the test suite
  pins both.

- **The phone exercise's host driver (source; its first green run is pending).** The
  first run that carried it (run 38894494223) booted, reached the desktop, and the guest
  passed `phone-armed` and `phone-localhost` — then the host half died silently at its
  first request: it loaded the pairing page through the QEMU port forward and parsed the
  HTML body as JSON, so the uncaught `JSONDecodeError` ended the driver before its first
  transcript line, and the four pairing checks that depend on the host failed. The driver
  now tolerates a non-JSON body (only the page is one), logs any unexpected failure
  instead of dying invisibly, and its stderr is kept with the evidence; the pairing arc
  itself was never in question and needs a clean re-run to prove.

- **The boot self-test's kernel command line carried `findiso=/live/filesystem.squashfs`,
  and the first CI boot of a built image died because of it** (run 38864588609,
  2026-10-16). `findiso` is live-boot's parameter for an ISO *file* sitting on a
  filesystem: the guest loop-mounts exactly the named file and reads it as ISO9660.
  Pointed at the squashfs inside the medium, the guest loop-mounted the squashfs, isofs
  rejected it (`ISOFS: Unable to identify CD-ROM format`) and live-boot reported "Unable
  to find a medium containing a live file system" before the self-test could run. The
  parameter is removed; the ISO is attached as a CD-ROM and found by live-boot's own
  device scan, which is also how the ISO's own boot entry finds it - the by-hand
  VirtualBox boot of the previous image had already proven that path. The driver now also
  stops waiting as soon as the serial console shows `BOOT FAILED!` or a kernel panic
  instead of burning its whole timeout, its window carries margin over the measured
  emulated boot (the first green run clocks it — entry above), and
  `tests/static/test_smoke_boot.py` fails if `findiso` is ever added back or if the
  driver stops mirroring `LIVE_APPEND`.

- **The second CI boot reached the login prompt and never ran its self-test** (run
  38871459329, 2026-10-16). The findiso fix worked - the serial console shows the live
  system booting to `astra-live login:` - but systemd deleted the self-test unit's start
  job on the way: `Job astraos-smoke.service/start deleted to break ordering cycle`,
  `[ SKIP ] Ordering cycle found, skipping astraos-smoke.service`. The unit was
  `WantedBy=multi-user.target` while ordered `After=graphical.target`; a unit is started
  as part of the transaction of the target that wants it (which orders it before that
  target), and graphical.target is itself ordered after multi-user.target - a circle,
  and systemd breaks circles by silently deleting jobs. `[Install]` now says
  `WantedBy=graphical.target`, the target the unit already orders after; the unit's
  header comment and `tests/static/test_smoke_boot.py` record the cycle so it cannot
  return silently. The same run was the first TCG boot attempted in CI, and it never
  reported a result: the unit had been skipped by the cycle, and the serial log simply
  ends at the login prompt. That run did not establish the emulated boot's duration;
  the next run did — login prompt at 143.7 s. The workflow's self-test window is now
  120 minutes (job ceiling 150), the guest gets 4 cores and 4 GiB, the guest script
  waits for the session itself, and the unit's start timeout covers that wait. The
  README's tested-claims list was held until a run reported PASS — the next one did
  (entry above), and the README and limitations documents now record it.

- **The live session had no working DNS: `/etc/resolv.conf` was a 0-byte file.** Pinging
  an IP worked; pinging a name did not. Two authorities were both enabled —
  `NetworkManager.service` and `resolvconf.service` — and each deferred to the other:
  NetworkManager saw `resolvconf` installed and handed name resolution over to it, and
  `resolvconf` found the `/run/resolvconf/resolv.conf` symlink it manages replaced by an
  empty regular file (live-build replaces the path), so it wrote nothing. Nothing owned
  the file. The fix is that the image no longer installs `resolvconf` at all:
  NetworkManager writes `/etc/resolv.conf` itself, which is the Debian 13 way and the
  reason `resolvconf` is deprecated. This class of defect does not stop a build — apt
  resolves the set happily and the image ships broken — so
  `tests/static/test_packages.py::test_resolvconf_is_not_installed_alongside_networkmanager`
  fails if it is ever added back, the boot self-test resolves a real name as one of its
  checks, and the assistant's `set-dns` knowledge file teaches the diagnosis.

- The validator then failed that image on eight "live filesystem does NOT contain" checks at
  once, while a ninth passed. Nothing was missing: the squashfs held 152,556 inodes including
  every path the checks looked for, and the image verification hook had already confirmed the
  same paths inside the chroot it was built from. The defect was the shape of the check.
  `validate-iso.sh` sets `set -o pipefail` and piped the ~6 MB `unsquashfs -l` listing into
  `grep -q`, which exits the moment it matches: `printf` on the other side of the pipe died of
  SIGPIPE, and pipefail reported the *successful* match as a failed pipeline — exit status
  141. Every component whose match sat before the end of the listing was reported missing, and
  only the one pattern that happened to land near the end survived, which is why one check
  passing looked like evidence that the other eight were right. Listings are now written to
  files and read from them; `grep -q` reading a file cannot race. The boot-path listing, the
  `.disk/info` discovery and the squashfs listing all follow that rule, the listings share one
  work directory removed by an exit trap, and a listing with no `squashfs-root/` paths is
  reported once, as what it is, instead of nine times as a missing image. In the repository:
  `tests/static/test_scripts.py` rejects a pipeline into `grep -q` in any script that enables
  pipefail (the three other places with that shape — `bootstrap-build-environment.sh`,
  `validate-environment.sh` and `astraos-welcome` — were fixed the same way), and
  `tests/integration/test_iso_validator.py` runs the real validator against a stubbed
  `xorriso`/`unsquashfs`: it checks that every component is found in a listing whose matches
  come first, that a component which really is absent is still reported, and that one missing
  component does not become eight.

- The image's own `.disk/info` announced it as `Debian GNU/Linux 0.1.0 "Trixie" - Snapshot
  amd64 LIVE Binary 20261013-18:47`, and the validator refused it as a possibly unmodified
  Debian image — correctly, because the medium was naming Debian. The title is a literal in
  live-build's `binary_disk` (the `debian` case and the fallback case both set
  `TITLE="Debian GNU/Linux"`), no `lb` option changes it, and the only value that script
  takes from the image is `VERSION_ID` — this project's version number appearing inside a
  Debian sentence. `0800-disk-info.hook.binary` now writes the medium description in the
  binary stage, after `binary_disk` and before `binary_checksums` and `binary_iso`, taking the
  identity from the staged `distribution.env` so it cannot drift from the release, and it
  fails the build if a medium would still start with `Debian`. The hook's real output is put
  through the validator's real check by `tests/integration/test_iso_validator.py`.

- The validator's "the astraos-base package" check looked for `/var/lib/dpkg/status`, which
  exists on every Debian system: it passed on an image with no AstraOS package in it at all,
  so it was the one check that looked healthy while proving nothing. It now looks for
  `/var/lib/dpkg/info/astraos-base`, which dpkg writes only for a package it has installed.

- The 2026-10-13 CI build assembled a complete 2.0 GB live image — boot path, kernel,
  initramfs and live filesystem all present, live-build itself reporting
  "Build completed successfully" — and then the repository's own validator failed it on
  nine "live filesystem does NOT contain" checks at once. The validator, not the image,
  was wrong: it extracted the squashfs onto a path `mktemp --suffix=` had already created,
  xorriso wrote nothing onto the existing file and still exited 0, and the empty result
  was then listed by `unsquashfs`, which failed, whose error was discarded. Nine components
  were reported missing from a filesystem that was never read. The extraction now targets
  a directory that does not pre-exist, keeps each tool's stderr, verifies the size it got,
  and reports the tool's own diagnostic when something fails — and the `.disk/info`
  check beside it, which had the same shape (extract to `/dev/stdout`, discard the
  diagnostic, report "unavailable"), extracts to a real file the same way. Every
  extraction in the validator now produces either the data or the reason it could not.

- The same CI build spent ~24 of its 31 minutes, and 1.9 GB of its log, inside apt's http
  method: one queued item (`gstreamer1.0-gl` from the security mirror) printed
  `W: Tried to start delayed item ..., but failed` 12.7 million times in a hot loop while
  every other item on both mirrors fetched normally — a stuck pipelined connection, with
  the method retrying the start attempt without backoff. The build's `--apt-options` now
  carry transport-only Acquire settings (`http`/`https` `Pipeline-Depth=0`,
  `ForceIPv4=true`, `Retries=3`), which remove the pipelined queue that can strand an
  item, the instant-failing IPv6 connect path that can poison one, and turn transient
  fetch failures into a bounded retry. These change how a download is fetched, never what
  is fetched or whether signatures are verified.

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

The first development release. **No image has passed structural validation or been
booted yet.** The status of
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

- No image has passed structural validation, and none has been booted.
- Secure Boot is not supported and not claimed.
- `/etc/os-release` can be overwritten by an upgrade of Debian's `base-files`.
- The desktop theme does not include window decorations.
- No physical hardware has been tested.

### Notes

- AstraOS uses the Debian-supplied Linux kernel. It is not a from-scratch kernel, and
  the project does not present it as one.
- No AI feature is included, and nothing in the boot path depends on a network service.
