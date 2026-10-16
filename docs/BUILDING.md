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
├── astraos-0.1.0-alpha-amd64.iso             the bootable image
├── astraos-0.1.0-alpha-amd64.iso.sha256      its SHA-256, already verified
└── astraos-0.1.0-alpha-amd64.iso.manifest    what was built, and what was NOT tested

logs/
└── build-20261012T213000Z.log                the full build log

build/                                        ignored by git
├── packages/                                 the built .deb files and their manifest
└── live-build/                               the live-build working tree
```

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
   definition — plus `console=ttyS0,115200n8` and `astraos.ci=1`;
3. waits for the serial console to report `ASTRAOS-SMOKE: RESULT: PASS`;
4. takes a screenshot of the booted desktop through the QEMU monitor;
5. uploads `serial.log` and `screenshot.png` as the `astraos-boot-self-test` artifact
   and fails when the result is missing or FAIL.

The guest half ships in every ISO at
`config/live-build/config/includes.chroot/usr/local/sbin/astraos-smoke`, behind
`astraos-smoke.service`, which `ConditionKernelCommandLine=astraos.ci` keeps inert
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

### The boot menus

The self-test above boots a kernel the host script supplied. The `boot-menus` job
(added 2026-10-16; its first CI run was pending at the time of writing) exercises the
other half: the path a real machine takes. It boots the ISO in QEMU with QEMU's own
firmware starting the machine, so nothing is supplied by the host — the menu is what
boots the guest —

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
with a 25-minute wait; the EFI run needs the OVMF firmware (`ovmf` package). The ISO's
menu entries do not carry `astraos.ci`, so the guest runs no self-test and does not
power off: it stops at the login prompt and the script stops the machine. Evidence
(`serial.log`, `qemu.out`) is uploaded as the `astraos-boot-menus` artifact.

The same script runs locally against any built ISO and needs no root — nothing is
mounted:

```bash
./scripts/boot-menu-test.sh --medium bios --out out-bios dist/astraos-*.iso
./scripts/boot-menu-test.sh --medium efi  --out out-efi  dist/astraos-*.iso
```

## 9. After a successful build

A structurally valid ISO is **not** a working operating system. Boot it:

→ [`INSTALLATION_VIRTUALBOX.md`](INSTALLATION_VIRTUALBOX.md)

Do not install it on physical hardware until the virtual machine acceptance procedure has
passed. → [`INSTALLATION_PHYSICAL_PC.md`](INSTALLATION_PHYSICAL_PC.md)
