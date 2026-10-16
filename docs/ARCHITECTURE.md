# AstraOS architecture

## 1. What kind of system this is

AstraOS is a **distribution**, not a kernel and not a desktop environment. It selects,
configures, brands and packages components that already exist — Debian's userland, the
Linux kernel, Xfce, LightDM, GRUB and Calamares — into a coherent operating system with
its own identity and its own build pipeline.

This is a deliberate architectural decision, recorded in plan §2.1 and §1. An
independent kernel, package manager or desktop environment would each be a multi-year
project, and building all three before the first release would mean never shipping one.

**What is genuinely AstraOS:** the package selection, the desktop configuration, the
identities, the branding, the installer configuration, the security defaults, the
distribution utilities, and the build system that produces all of it reproducibly.

**What is upstream:** the kernel, the C library, the init system, the graphical stack,
the desktop environment, the display manager, the bootloader and the installer engine.

## 2. Boot chain

```
Firmware (UEFI or legacy BIOS)
        │
        ├── UEFI:   EFI/BOOT/BOOTX64.EFI  →  GRUB  →  grub.cfg
        └── BIOS:   isolinux.bin          →  syslinux  →  isolinux.cfg
        │
        ▼
Linux kernel (linux-image-amd64) + initramfs
        │
        ▼
live-boot: finds the medium, mounts /live/filesystem.squashfs over an overlay
        │
        ▼
systemd (from the squashfs)
        │
        ├── live-config: creates the live user, sets the hostname, applies the
        │                boot parameters from the bootloader
        │
        ▼
LightDM  →  lightdm-gtk-greeter  (AstraOS themed, no autologin)
        │
        ▼
xfce4-session  →  Xfce desktop  →  AstraOS panel layout
```

The same GRUB is used for the installed system; Calamares installs it and generates a
new `grub.cfg` for the target.

**The splash must never hide a failure.** Plymouth shows the AstraOS ring, but the
failsafe boot entry drops `quiet splash`, disables kernel modesetting and turns off ACPI
power management, so a graphics or ACPI fault is visible and recoverable (plan §7.4).

## 3. Live image versus installed system

These are different systems that share a filesystem, and confusing them is the source of
most installation bugs.

| | Live image | Installed system |
|---|---|---|
| Root filesystem | squashfs, mounted read-only through an overlay | ext4 (default) on disk |
| Persistence | none | normal |
| User account | `astra`, created at boot by live-config, sudo group, no password | created by the installer with a password the user chooses |
| `machine-id` | cleared at image build time | generated fresh by the installer |
| Root account | locked | locked; administration through sudo |
| Purpose | evaluate and install | daily use |

The live user is **removed** during installation (`removeuser.conf`), because an account
with administrative rights and no password must not exist on an installed system.

## 4. Build architecture

```
config/*.env ─────────────┐
VERSION ──────────────────┤
                          ▼
              scripts/validate-environment.sh      (is this host able to build?)
                          │
                          ▼
              scripts/configure-live-build.sh
                  ├── stages config/live-build/ into build/live-build/
                  ├── renders system/*.in → identity files
                  ├── copies package lists and hooks
                  └── calls scripts/build-packages.sh
                          │
                          ▼
              build-packages.sh
                  ├── renders each packages/*/control.in
                  ├── assembles the file trees (mapping is in one place)
                  ├── builds reproducible .deb files with dpkg-deb
                  └── stages them into config/packages.chroot/
                          │
                          ▼
              lb build  (live-build)
                  ├── debootstrap the pinned Debian base
                  ├── install the package lists + the AstraOS packages
                  ├── run config/live-build/config/hooks/live/*.hook.chroot
                  │     0100 identity      identity files + package assertions
                  │     0300 installer     validates the Calamares configuration
                  │     0400 services      service policy + sysctl
                  │     0500 security      root lock, permissions, no credentials
                  │     0600 cleanup       machine-id, caches, staged tree
                  │     0700 verify        image assertions; FAILS the build
                  ├── compress the chroot into live/filesystem.squashfs
                  ├── run config/live-build/config/hooks/live/*.hook.binary
                  │     0800 disk-info     names the medium; live-build's own .disk/info
                  │                        says "Debian GNU/Linux", a literal in binary_disk
                  └── pack the hybrid ISO
                          │
                          ▼
              scripts/validate-iso.sh       (structural)
              scripts/generate-checksums.sh
              scripts/generate-manifest.sh  (records what was NOT tested)
```

### Why the repository layout differs from the live-build layout

live-build expects `auto/` and `config/` at its working directory. The repository instead
keeps readable source directories (`config/`, `branding/`, `desktop/`, `system/`,
`installer/`, `packages/`) and `configure-live-build.sh` maps them into a working tree
under `build/`.

This means the mapping is auditable in one place instead of being implied by directory
names, and the repository does not have to avoid a name like `config/` for unrelated
purposes. Plan §4 permits this.

### Why the hooks are thin

Files that **can** be owned by a package are owned by a package, so they have proper
conffile semantics and appear in `dpkg -S`. Hooks do only what packages cannot:

1. write files whose paths are owned by other packages as conffiles
   (`/etc/os-release`, `/etc/issue`, `/etc/motd`, `/etc/default/ufw`,
   `/etc/lightdm/lightdm-gtk-greeter.conf`) — see `KNOWN_LIMITATIONS.md` §1.3;
2. run in-chroot actions (`systemctl enable`, `less` permission fixes);
3. write a file that exists only on the ISO surface and is generated by live-build itself,
   so no package can own it: `binary/.disk/info`, which live-build's `binary_disk` fills in
   naming Debian. `0800-disk-info.hook.binary` replaces it in the binary stage with this
   build's own identity — the line carries the build stamp, which a static include in the
   repository cannot produce;
4. **validate**, which is the most important job. The build fails if the image is
   missing its branding, its installer modules, its desktop session or its security
   policy.

## 5. Package architecture

| Package | Owns | Depends on |
|---|---|---|
| `astraos-base` | `/etc/astraos-release`, sysctl defaults, sudo policy, APT policy, firewall policy, `astraos-info`, `astraos-scan-secrets` | bash, coreutils, procps, iproute2, util-linux |
| `astraos-branding` | logos, wallpapers, icon theme, Plymouth theme, GRUB theme, LightDM assets and drop-in | fonts-dejavu-core, hicolor-icon-theme |
| `astraos-desktop` | Xfce system defaults, skeleton home, launchers, GTK theme | xfce4-*, thunar, lightdm |
| `astraos-system-tools` | `astraos-help`, `astraos-welcome`, `astraos-release-info`, `astraos-recovery-guide` | astraos-base |
| `astraos-installer` | `/etc/calamares/`, installer branding | calamares, kpmcore, squashfs-tools, parted, os-prober, grub2-common |

Only five packages exist, and each has a clear reason to exist. Plan §15 forbids adding a
custom application that merely duplicates an existing one.

## 6. Security boundaries

| Boundary | Mechanism |
|---|---|
| Normal user vs administrator | A normal account in the `sudo` group; root locked; no `NOPASSWD` rule |
| Live session vs installed system | The live account is removed during installation |
| Package authenticity | APT signature verification, never disabled; repositories are authenticated Debian archives |
| Network exposure | No listening services installed; firewall policy documented but not enabled by default |
| Boot integrity | **No Secure Boot yet.** Not claimed; the signed chain is carried (2026-10-16) and its first CI boot under enforcing firmware is pending |
| Future AI features | If ever added: normal user permissions, no privileged action without confirmation, never in the boot path (plan §13.6) |

The honest summary: AstraOS 0.1.0 has a sound *configuration* baseline and **no
independent security review**. `SECURITY.md` lists exactly what is and is not claimed.

## 7. Reproducibility

- The base release is pinned in one file (`config/distribution.env`) and verified
  against the live archive before a build.
- Package availability is verified against Debian's actual `Packages.xz` indexes, so an
  invented package name fails at the start of a build rather than an hour in.
- `SOURCE_DATE_EPOCH` is derived from the last commit, so `.deb` output is deterministic.
- `dpkg-deb --build --root-owner-group` removes the builder's identity from the archive.
- Bitmap assets are deterministic: the star field uses a fixed seed.
- The build manifest records the commit, the working-tree state, tool versions and the
  exact live-build options used, including which optional flags were **skipped**.

Byte-for-byte reproducible ISOs are **not** claimed. The package set comes from a moving
archive within the pinned suite, so a build today and a build next week can differ. The
manifest records enough to explain a difference rather than pretending there is none.
