# AstraOS 0.2.0 Alpha "Nova"

The first named release of AstraOS, an independent Linux desktop distribution
built from Debian 13 (trixie) packages.

**This is an alpha.** It boots, it installs itself, and the installed system
comes up on its own. It has not been tested on physical hardware. Do not put it
on the machine you do your work on.

---

## What is in this release

- A themed Xfce desktop: its own wallpaper, panel, icon theme, cursor and LightDM
  greeter, all generated from the assets in `branding/`.
- An assistant that can read the user's documents and run commands, with a
  seven-step confirmation set, a sandbox, undo, and a step budget and a time
  budget per task. The engines are built in CI for both AVX and AVX2 and
  published as release artifacts.
- An installer (Calamares), a recovery path, and an APT archive the installed
  system can update from.
- A CI pipeline that builds the ISO, boots it three ways, installs it onto a
  blank disk and boots the result with no medium attached.

## The evidence

Every claim below names the run that proves it. The logs are attached to this
release, and the runs are public.

| Claim | Evidence | Run |
|---|---|---|
| The ISO builds | `Build ISO` succeeded; 25/25 structural checks passed | 39379045276 (2026-10-20) |
| The live image boots and passes its own self-test | `RESULT PASS`, serial log attached | smoke-boot job, run 39379045276 |
| It boots through its own boot menus | BIOS, UEFI, and UEFI under Secure Boot with the Microsoft keys enrolled | boot-menus job, run 39379045276 |
| It installs itself onto a blank disk | Calamares ran the installer end to end; the screenshots are attached | install-boot job, run 39379045276 |
| The installed system boots alone | No medium attached; the greeter was reached | install-boot job, run 39379045276 |
| The APT archive is real | A fresh `debian:trixie` container updated from it and installed `astraos-system-tools` out of it | build job, run 39379045276 |
| The assistant engine is proven | Built and tested for AVX and AVX2 | release `ai-engine-2026-10-19` |

## How to get it

**Build it yourself.** A Debian 13 host and about 25 GB of disk:

```bash
git clone https://github.com/rafikulislammollaq-dev/astraos.git
cd astraos
make bootstrap
make iso
```

The build takes roughly 18 minutes in CI. It runs the same scripts a local
build does, so the two cannot drift apart.

**Or use the CI artifact.** The `Build ISO` workflow uploads the image as a
workflow artifact, retained for 14 days. Run it yourself from the Actions tab
if you would rather not build it.

**Then boot it.** [docs/INSTALLATION_VIRTUALBOX.md](https://github.com/rafikulislammollaq-dev/astraos/blob/main/docs/INSTALLATION_VIRTUALBOX.md)
has the whole procedure, including what to expect when it goes wrong.
[docs/INSTALLATION_PHYSICAL_PC.md](https://github.com/rafikulislammollaq-dev/astraos/blob/main/docs/INSTALLATION_PHYSICAL_PC.md)
covers real hardware.

## What is not tested

- **Physical hardware.** No install has been run on a real machine. What
  hardware it is expected to work on is written down in
  [docs/HARDWARE_COMPATIBILITY.md](https://github.com/rafikulislammollaq-dev/astraos/blob/main/docs/HARDWARE_COMPATIBILITY.md),
  and that document is a list of expectations, not a list of results.
- **Signed images.** The ISO is not signed. It boots under Secure Boot because
  it uses the Microsoft-signed shim and Debian-signed GRUB and kernel, not
  because AstraOS signs anything itself.
- **A hosted APT archive.** The archive this build produced is unsigned and
  lives in the build artifacts. Where it will be hosted is still open.
- **A browser in a booted image.** The network stack was proven in CI. No
  browser has been launched inside a booted image yet.

The full list, with the reasoning, is in
[docs/KNOWN_LIMITATIONS.md](https://github.com/rafikulislammollaq-dev/astraos/blob/main/docs/KNOWN_LIMITATIONS.md).

## Licence

MIT for the AstraOS-specific work. The base is Debian, and the packages that
come from Debian keep their own licences. The attribution is written out in
[docs/ARCHITECTURE.md](https://github.com/rafikulislammollaq-dev/astraos/blob/main/docs/ARCHITECTURE.md)
and in the `Licensing and attribution` section of the README.

## How to help

[CONTRIBUTING.md](https://github.com/rafikulislammollaq-dev/astraos/blob/main/CONTRIBUTING.md)
lists the specific things that are wanted. The two that would help most:

1. **Someone with physical hardware** who can install it on a spare machine and
   report what happens. That is the single largest untested area.
2. **Someone who knows Calamares well enough to review the installer
   configuration**, which was written by reading the documentation rather than
   by using it every day.

The repository is at
[github.com/rafikulislammollaq-dev/astraos](https://github.com/rafikulislammollaq-dev/astraos).
