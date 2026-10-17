# Building AstraOS

## 1. Supported build environments

AstraOS image building requires **Linux**. The image is assembled with `debootstrap`,
`live-build`, `mksquashfs` and `xorriso`; none of these exist on Windows or macOS, and
plan §3 explicitly forbids running Linux-only build commands from a Windows shell.

In order of preference:

1. **A Linux host** (Debian 12/13 or Ubuntu 22.04/24.04 recommended).
2. **A Linux virtual machine** on any host.
3. **WSL2** on Windows — works well, but requires the Virtual Machine Platform feature.
4. **CI** — `.github/workflows/build-iso.yml` runs on GitHub Actions.

> **This project was started on a Windows host where WSL2 could not start.** The exact
> measurements, the blocker and the two commands that fix it are in
> [`ENVIRONMENT.md`](ENVIRONMENT.md). Read that first if `make validate` fails.

## 2. Quick start

```bash
# 1. Can this machine build AstraOS?
./scripts/validate-environment.sh

# 2. Install the build dependencies (the only step that elevates privileges)
./scripts/bootstrap-build-environment.sh

# 3. Build
./scripts/build-iso.sh
```

Or with make:

```bash
make validate      # can this host build?
make bootstrap     # install the build dependencies
make build         # build the image
```

## 3. Requirements

| Resource | Minimum | Notes |
|---|---|---|
| Disk | 15 GB free | Build tree (~6 GB), package cache (~2 GB), ISO (~1.5–2 GB) |
| RAM | 2 GB | More makes squashfs compression faster |
| CPU | 2 cores | `mksquashfs` and `xz` are the slow parts |
| Network | Required | Several GB of packages are downloaded |

## 4. What the build does

| Stage | Script | Result |
|---|---|---|
| 1 | `validate-environment.sh` | Refuses to continue on a host that cannot build |
| 2 | `configure-live-build.sh` | Staged build tree, rendered templates, built packages |
| 3 | `build-packages.sh` | Five `.deb` files, staged for live-build |
| 4 | `lb build` | Squashfs + hybrid ISO, with the chroot hooks running inside |
| 5 | `validate-iso.sh` | Structural validation, including live-filesystem contents |
| 6 | `generate-checksums.sh` | `.sha256`, verified against the image |
| 7 | `generate-manifest.sh` | `.manifest` recording exactly what was built |

**Every stage is fatal on failure.** The build never reports success because a file
exists; the scripts check exit statuses and inspect the artifacts (plan §16.2).

## 5. Build outputs

```
dist/
├── astraos-<version>-<stage>-<arch>.iso           the bootable image
├── astraos-<version>-<stage>-<arch>.iso.sha256    its SHA-256, already verified
├── astraos-<version>-<stage>-<arch>.iso.manifest  what was built, and what was NOT tested
└── apt-repo/                                      the APT archive the packages were assembled into

logs/
└── build-20261012T213000Z.log                the full build log

build/                                        ignored by git
├── packages/                                 the built .deb files and their manifest
└── live-build/                               the live-build working tree
```

The image name carries the release: `astraos-<version>-<stage>-<arch>.iso`, with
`<version>` and `<arch>` from `VERSION` and `config/distribution.env` and `<stage>`
lowercased — for 0.2.0 Alpha that is `astraos-0.2.0-alpha-amd64.iso`. The names change
with the release, so they are shown as a pattern here; `ls dist/` shows the exact ones.

The manifest is the honest record. Read the `[validation]` section: it distinguishes
`structural=PASS` from `boot_in_virtualbox=UNTESTED`.

## 6. Useful options

```bash
./scripts/build-iso.sh --no-cache        # force a clean live-build (slower, safer)
./scripts/validate-environment.sh        # dry-run the host checks
./scripts/build-packages.sh --clean      # rebuild the packages from scratch

make clean                               # logs + live-build tree (keeps dist/)
make distclean                           # everything generated, including dist/
```

`make clean` deliberately does **not** delete your built ISO. `make distclean` does, and
says so before it runs.

## 7. Common errors

### "this host CANNOT build an AstraOS image"

Read the failed lines from `validate-environment.sh`. The usual causes: not Linux;
`live-build` not installed; less than 15 GB free; the mirror unreachable.

### `lb build` fails during debootstrap

Almost always the network or the mirror. Check:

```bash
curl -I http://deb.debian.org/debian/dists/trixie/Release
```

If the host is behind a proxy, set `http_proxy`/`https_proxy` for the build.

### "the package lists reference packages that do not exist"

Run the verifier; it names the offending package and which list requested it:

```bash
python3 scripts/verify-package-availability.py
```

Fix the list, or deliberately change the pinned release in `config/distribution.env`.

### The build stops at `0700-verify.hook.chroot`

That hook found something the release depends on missing in the image. The failure names
the exact path. Investigate; do not delete the assertion. It exists because shipping an
image without its installer or its branding is worse than failing the build.

### The build stops at `0300-installer.hook.chroot`

Calamares' module names have changed between versions. The hook prints which module is
missing. Remove it from the sequence in `installer/calamares/settings.conf` if the
functionality genuinely does not exist in the pinned release, or add the package that
provides it to `config/package-lists/60-installer.list.chroot`.

### The build stops in `scripts/validate-iso.sh`

The image is built; this is the repository's own inspection of it, and the two failures seen
so far had different causes:

- **"medium identifies itself as Debian, not AstraOS"** — live-build's `binary_disk` writes
  `.disk/info` itself and the title is a literal in that script, so the medium is named Debian
  unless `0800-disk-info.hook.binary` runs and replaces it. Check that the hook is executable
  *in git* (`100755`, not just on disk — a Windows checkout cannot store the bit) and that it
  ran: `binary_hooks` executes after `binary_disk` and before `binary_checksums`, and the run
  log lists every hook live-build executed.
- **"live filesystem does NOT contain ..."** — either the component really is missing from the
  image, or the validator could not read its listing. The output distinguishes them: the
  validator prints the size it extracted, the number of entries it listed, and the extracted
  tool's own stderr. If it reports a listing with no `squashfs-root/` paths, the extraction
  worked and the listing format changed, which is a defect in the validator rather than in the
  image. The in-chroot hook that asserts the component (`0700-verify.hook.chroot`) runs first
  and names the path it wanted, so it tells you whether the image ever had it.

### "another build appears to be in progress"

Two builds sharing one working directory corrupt each other. If no build is running:

```bash
rm build/live-build/.astraos-build-in-progress
```

### Rerunning a failed build

The build reuses the existing tree so a failure late in the process does not cost the
whole download. To start clean:

```bash
./scripts/configure-live-build.sh --force
```

## 8. Building in CI

`.github/workflows/build-iso.yml` is manually triggered. It validates the repository
first, installs dependencies, builds, validates, computes checksums, writes the manifest
and uploads the ISO plus the manifest as an artifact.

CI-specific notes:

- The job runs on `ubuntu-24.04`, but the image itself is **assembled inside a
  `debian:trixie` container**. The runner's older `debootstrap` writes the pre-bookworm
  security suite name into the new chroot (`trixie/updates`, which does not exist in Debian
  13), and an older `live-build` has no `--bootloaders`, which silently produces a
  UEFI-only image. Building inside the release being assembled removes both mismatches.
- The container runs with `--privileged`, because `live-build` mounts filesystems and
  chroots. It uses the same scripts as a local build, so CI cannot drift from this document.
- The artifact is retained for 14 days. Builds are not archived permanently.
- The workflow summary ends with an explicit statement of what it did **not** test: the
  installer and an installed system. Booting the live image is covered by the
  `smoke-boot` job below, the ISO's own boot menus by the `boot-menus` job under it.

There is a second CI workflow, `.github/workflows/build-ai-engine.yml`, which has nothing
to do with the image: it builds the assistant's runtime (`llama-server`, `whisper-cli`)
through `astra-ai setup --build all`, checks the binaries against the SIGILL class this
hardware measured (no FMA/BMI2/F16C, no RPATH into the build tree), runs the engine on an
emulated Sandy Bridge with a real model, and publishes everything as the
`astra-ai-engine-linux-x86_64-avx` artifact. It runs on every push that changes
`packages/astraos-ai/root/usr`, so the twenty-minute compile never has to happen on the
user's desktop.

### The boot self-test

The `smoke-boot` job (on by default; `smoke_boot` in the manual trigger) is the only
part of CI that runs the image. It:

1. reads the live kernel and initrd out of the freshly built ISO (read-only loop mount);
2. boots them in QEMU with the ISO attached as the live medium, using the same live
   parameters as the ISO's own boot entry — `config/distribution.env` is their single
   definition — plus `console=ttyS0,115200n8`, `astraos.ci=1` and `astraos.phone=1`, and
   attaches a virtio serial port named `org.qemu.guest_agent.0` whose host end is kept
   for step 3;
3. answers the guest while it runs: it drives the phone-page exercise over QEMU's
   forwarded port (pairing, an authorized request, the refusal after revocation —
   `phone-host.log` is the transcript) and pings the QEMU guest agent over the virtio
   serial port (`guest-sync`, `guest-ping`, `guest-info` — `qga-host.log`); the guest
   starts the agent from the port via its package's own udev rule, and the guest's
   self-test reports whether its unit is active;
4. waits for the serial console to report `ASTRAOS-SMOKE: RESULT: PASS`, or gives up as
   soon as the console shows the boot itself failed;
5. takes a screenshot of the booted desktop through the QEMU monitor;
6. uploads `serial.log`, `phone-host.log`, `qga-host.log` and `screenshot.png` as the
   `astraos-boot-self-test` artifact and fails when the result is missing or FAIL — and
   when the image reported PASS but the guest agent never answered the host.

The guest half ships in every ISO at
`config/live-build/config/includes.chroot/usr/local/sbin/astraos-smoke`, behind
`astraos-smoke.service`, which `ConditionKernelCommandLine=astraos.ci=1` keeps inert
during a normal boot. Any AstraOS medium can describe itself: add `astraos.ci=1` to the
kernel command line in the boot menu and the machine boots, checks itself, prints one
line per check, holds the desktop for a moment and powers off. That output — which
kernel, CPU and memory, and exactly which check failed — is what a hardware bug report
needs; see `/usr/share/astraos/SELF-TEST.txt` inside the image.

The same script runs locally against any built ISO:

```bash
./scripts/smoke-boot.sh dist/astraos-*.iso
```

It needs `qemu-system-x86_64`, `python3`, and root (or `sudo`) for the loop mount. KVM
is used when the host allows it; otherwise QEMU emulates the CPU — slower, not
different.

The emulated path is the slow one, and CI runs it. The first TCG attempt (run
38871459329, 2026-10-16) never reported a result — a systemd ordering cycle had the
self-test unit skipped (see `CHANGELOG.md`) — so that run did not measure the boot. The
first green run (38881934636, 2026-10-16) did: login prompt at 143.7 s of guest time,
`RESULT: PASS (39 checks, 0 failed)`, the whole boot job 6m28s on 4 vCPU / 4 GiB. The CI
window (`--timeout 120`) and the guest's own wait for the session both carry generous
margin over that. A host with KVM does not pay the emulation cost.

The screenshot step is not decoration — the roadmap's HUD item rests on a captured
image of the booted desktop — so it is verified: the guest turns blanking off and
repaints the session before it reports its result (its `screenshot-ready` check), and
the host measures each capture and retries a flat image while the guest still holds
the session. A flat capture that survives the retries is still kept, and the
transcript says so. The first green run's image was black this way: QEMU's stdvga
emulation (8.2 on the runner; fixed upstream in 9.0.2) clears the shared framebuffer
when the guest blanks the screen. See `CHANGELOG.md`.

### The install exercise

The sections above boot the image; the `install-boot` job (on by default;
`install_boot` in the manual trigger) is the one that installs it. Two boots, one
exercise:

1. the ISO's live kernel starts with `astraos.ci.install=1` on its command line. The
   exact word matters: the install driver's unit conditions on it, the self-test's
   unit conditions on `astraos.ci=1`, and systemd matches a condition without `=`
   against the beginning of a command line word — so the shared bare prefix
   `astraos.ci` would let each fire during the other's boot, and a self-test that
   screenshots the desktop and powers the machine off in the middle of an install is
   not a self-test;
2. `astraos-install` (the guest half, shipped in every ISO) mounts the CI 9p share,
   copies the presets the host put there over its module configuration, pins the
   Calamares window to 800x520 in the centre of the screen, starts the real
   Calamares, and reports the exit code into the share when it ends;
3. the host drives the wizard over the QEMU monitor: Return advances the pages whose
   defaults are already correct (locale, keyboard, the partition page — the one
   blank disk arrives selected with Erase pre-selected — and the summary, whose Next
   is unconditionally enabled in the pinned Calamares), and the users page gets a
   per-run generated password typed into its two fields. A screendump precedes every
   step, so a coordinate that is wrong is visible in the evidence instead of being
   guessed about;
4. the host converts the installed disk, loop-mounts it, appends the serial console
   and the installed-mode switches (`astraos.ci=1 astraos.ci.installed=1
   username=<live user>`) to every kernel line of the installed GRUB configuration,
   and boots the disk alone — no ISO and no host-supplied kernel: firmware,
   bootloader and kernel all come from the installation;
5. the installed system's self-test runs in its installed mode: with
   `astraos.ci.installed=1` on the command line, the same `astraos-smoke` script
   expects a login greeter instead of a live session, no autologin under
   `/etc/lightdm`, no live account on the system, and the installer's lock-down file
   `/etc/lightdm/lightdm.conf.d/90-astraos-installed.conf` — the installer's own
   checks, made from outside the installer. The host additionally requires the login
   prompt to name the installed account's hostname, and captures a greeter
   screenshot with the same flat-image guard as the self-test above.

The pass conditions are the guests' own: Calamares must write `rc=0` into the share
and its session log must mention the destructive modules (`unpackfs`, `bootloader`),
and the installed self-test must report `RESULT: PASS` in installed mode. Evidence —
both serial logs, the Calamares session log, every UI screendump, the patched
`grub.cfg`, the greeter shot — is uploaded as the `astraos-install-test` artifact.
The roadmap's installer item flips only when a run of this exercise is green; that
run is still pending.

The same script runs locally against any built ISO:

```bash
./scripts/install-boot-test.sh --out out-install dist/astraos-*.iso
```

It needs `qemu-system-x86_64`, `qemu-img`, `python3`, `losetup`, and root (or
`sudo`) for the loop mounts. Like the self-test, KVM is used when the host allows
it; emulation is the fallback — slower, not different.

### The boot menus

The self-test above boots a kernel the host script supplied. The `boot-menus` job
(added 2026-10-16; green the same day, run 38913161772) exercises the other half: the
path a real machine takes. It boots the ISO in QEMU with QEMU's own firmware starting
the machine, so nothing is supplied by the host — the menu is what boots the guest —

1. firmware starts the ISO's El Torito boot record (BIOS) or its EFI system partition
   (UEFI);
2. the bootloader's menu appears, and its default entry is accepted with Enter injected
   through the QEMU monitor (the menu timeout is live-build's default, which the pinned
   release cannot change — see `docs/KNOWN_LIMITATIONS.md` §3.10);
3. the menu entry boots the kernel with the command line the menu itself carries;
4. the live system's login prompt appears on the serial console. That prompt is the
   pass condition, and it can only appear because `console=ttyS0,115200n8` is part of
   `LIVE_APPEND` — the entry, not the test host, produced it.

Two runs per dispatch, one per firmware path (`--medium bios`, `--medium efi`), each
with a 25-minute wait; the EFI run needs the OVMF firmware (`ovmf` package). Since
2026-10-16 there is a third: `--medium secure` boots the UEFI path under OVMF's Secure
Boot firmware with the Microsoft keys enrolled, so only the ISO's signed chain —
Microsoft-signed shim, Debian-signed GRUB, Debian-signed kernel — reaches the login
prompt (source state; its first run failed — run 38924527286 produced no serial output
at all, so nothing past the firmware can be asserted about it yet; the script now keeps
a capture of the guest's screen, `screen.ppm`, so a failure like that carries what the
firmware drew). The ISO's menu entries do not carry
`astraos.ci=1`, so the guest runs no self-test and does not power off: it stops at the
login prompt and the script stops the machine. Evidence (`serial.log`, `qemu.out`, and
on the secure run `firmware.txt` with the firmware hashes) is uploaded as the
`astraos-boot-menus` artifact.

The same script runs locally against any built ISO and needs no root — nothing is
mounted:

```bash
./scripts/boot-menu-test.sh --medium bios   --out out-bios   dist/astraos-*.iso
./scripts/boot-menu-test.sh --medium efi    --out out-efi    dist/astraos-*.iso
./scripts/boot-menu-test.sh --medium secure --out out-secure dist/astraos-*.iso
```

### The package archive (APT repository)

The same job, after the image is built and the build container has stopped, turns the
`.deb` files it produced into an APT archive:

```bash
./scripts/build-apt-repo.sh --debs build/live-build/packages --out dist/apt-repo
```

The tree is the layout apt reads directly: `pool/main/<package>/<file>.deb` for the
files, `dists/stable/main/binary-amd64/Packages` (and `Packages.gz`) as the index, and
`dists/stable/Release` carrying both indices' sizes and SHA-256 hashes. With
`--key FINGERPRINT` the Release is signed as `InRelease`/`Release.gpg` and the public
half is exported as `astraos-archive-keyring.gpg`; the script never generates or stores
a signing key. Without `--key` the output is unsigned, and the script says so in plain
words: that form carries integrity hashes but no authenticity, and belongs only where
the transport is controlled (CI artifacts, a `file://` medium). Before reporting
success the script reads its own index back — every file the index names is opened
again and re-hashed — because an index that does not describe its pool is worse than
no archive. The build job uploads the result as the `astraos-apt-repo` artifact; it is
unsigned because no signing key lives in CI, and no installed system has ever fetched
updates from one yet.

The same job then proves the archive is apt-consumable, not merely well-formed: a fresh
`debian:trixie` container adds the tree as

    deb [trusted=yes] file:/repo stable main

runs `apt-get update` against it and installs `astraos-system-tools` out of the
archive. That package's own depends drags `astraos-base` in with it, and `astraos-base`
ships `/etc/astraos-release`; the step ends by requiring `astraos-release-info` to
report back the exact version dpkg recorded, so apt reading the index, the files
arriving and the installed package describing itself are all exercised at once. What
remains untested is an *installed* AstraOS updating from a hosted archive: the hosting
decision is open, and nothing in CI is a long-lived installed system.

## 9. After a successful build

A structurally valid ISO is **not** a working operating system. Boot it:

→ [`INSTALLATION_VIRTUALBOX.md`](INSTALLATION_VIRTUALBOX.md)

Do not install it on physical hardware until the virtual machine acceptance procedure has
passed. → [`INSTALLATION_PHYSICAL_PC.md`](INSTALLATION_PHYSICAL_PC.md)
