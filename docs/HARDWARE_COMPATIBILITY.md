# Hardware compatibility

> **No physical hardware has been tested.** Every table below describes what AstraOS is
> *configured* to support, not what has been shown to work. The image has booted only in
> virtual machines — under QEMU in CI (run 38881934636, 2026-10-16) and by hand in
> VirtualBox (2026-10-15) — never on physical hardware (`KNOWN_LIMITATIONS.md` §2).
>
> Treat this document as a list of expectations to test, not as a compatibility guarantee.

## 1. What is included

AstraOS installs firmware from Debian's `non-free-firmware` component, so the licensing is
handled by Debian's own redistribution arrangements (plan §12, §23).

The list is explicit — it is `config/package-lists/20-firmware.list.chroot`, and it is the
only source of firmware in the image. `live-build`'s automatic "install every firmware-*
package" stage is switched off, so nothing arrives without having been chosen. This is what
the categories below cover:

| Category | Packages |
|---|---|
| Wi-Fi | `firmware-iwlwifi`, `firmware-atheros`, `firmware-realtek`, `firmware-brcm80211`, `firmware-mediatek`, `firmware-ti-connectivity`, `firmware-libertas`, `firmware-zd1211`, `firmware-siano`, `firmware-qcom-soc`, `firmware-qcom-media`, `firmware-samsung`, `wireless-regdb` |
| Wired | `firmware-bnx2`, `firmware-bnx2x`, `firmware-cavium`, `firmware-marvell-prestera`, `firmware-myricom`, `firmware-netronome`, `firmware-netxen`, `firmware-qlogic` |
| Graphics | `firmware-amd-graphics`, `firmware-intel-graphics`, `firmware-nvidia-graphics`, `firmware-nvidia-gsp`, `firmware-nvidia-tesla-535-gsp`, `firmware-cirrus` |
| Generic | `firmware-linux-free`, `firmware-linux-nonfree`, `firmware-misc-nonfree` |
| Audio | `firmware-sof-signed`, `firmware-intel-sound`, `firmware-intel-misc`, `alsa-firmware-loaders` |
| CPU | `intel-microcode`, `amd64-microcode` |

Two packages with very old hardware coverage are also deliberately absent,
`firmware-ipw2x00` (Intel PRO/Wireless 2100/2200) and `firmware-ivtv` (Conexant capture
cards): their post-install scripts wait for debconf to accept a licence, which nothing can
do in a non-interactive build, so listing them fails the installation of the entire package
set. Install them on the installed system if you have that hardware.

One category is deliberately **absent**: Broadcom's older chips driven by `b43`, whose
firmware Debian does not redistribute. Debian ships `firmware-b43-installer` from
contrib instead, and that package downloads the firmware from the internet when it is
installed. It cannot be part of the image: the download is not reproducible, it brings a
third-party blob into the image outside Debian's archive, and it is exactly what failed a
build here after several gigabytes had been installed. A user with such a card runs
`apt install firmware-b43-installer` on the installed system, with a network connection,
and that is the only route AstraOS offers for it.

Graphics drivers are the **open-source** ones only: `i915` (Intel), `amdgpu`/`radeon`
(AMD), `nouveau` (NVIDIA) and the software-rendered fallbacks `fbdev`/`vesa`.

**No proprietary GPU driver is installed or offered.** AstraOS must not download arbitrary
drivers to claim broader compatibility (plan §12). If you want the proprietary NVIDIA
driver, install it yourself from Debian's `non-free` after installation, and understand
that it can break the graphical session if it is done incorrectly.

Firmware is only half of hardware support. The other half — the programs that turn a
driver into something the desktop can use — is `config/package-lists/35-hardware.list.chroot`:

| Function | Packages |
|---|---|
| Hardware video decode (VA-API) | `intel-media-va-driver`, `i965-va-driver`, `mesa-va-drivers`, `libva-drm2`, `gstreamer1.0-vaapi`, `vainfo` |
| Device firmware updates | `fwupd` |
| Small-memory machines | `zram-tools` (compressed swap in RAM) |
| Interrupt distribution | `irqbalance` |
| Older Bluetooth dongles | `bluez-firmware` |
| Phones, cameras, players over USB | `libmtp-runtime`, `mtp-tools`, `adb`, `fastboot`, `android-sdk-platform-tools-common` |
| Plugged-in filesystems | `ntfs-3g`, `exfatprogs`, `squashfs-tools` |
| Printer drivers | `printer-driver-gutenprint`, `printer-driver-escpr` |

On a machine where video playback stutters, `vainfo` prints which decode entry points
exist; `fwupdmgr get-updates` is the firmware half; `mtp-detect` explains a phone that
does not appear.

## 2. Expected to work

| Component | Expectation | Confidence |
|---|---|---|
| x86_64 CPU (Intel/AMD, ~2008 or newer) | Should work | High |
| SATA storage | Should work | High |
| NVMe storage | Should work | High |
| USB keyboards, mice, storage | Should work | High |
| VirtualBox virtual hardware | Should work; the primary target | High |
| QEMU/KVM virtual hardware | Should work | Medium |
| Intel integrated graphics | Should work with `i915` | Medium |
| AMD graphics with `amdgpu` | Should work | Medium |
| Wired Ethernet (common chipsets) | Should work | Medium |
| Standard displays over HDMI/DisplayPort/VGA | Should work | Medium |
| Common USB audio devices | Should work with PipeWire | Medium |
| Laptop battery reporting | Should work with `upower` | Medium |
| Hardware video decode (Intel/AMD, via VA-API) | Should work on supported generations; `vainfo` reports what a machine has | Medium |

## 3. Expected to be problematic

| Component | Likely outcome | What to do |
|---|---|---|
| Wi-Fi chipsets needing firmware not in the list above | Adapter not detected | Identify with `lspci -nnk`, check `dmesg` for a missing firmware file. Some need out-of-tree drivers AstraOS will not ship. |
| Broadcom Wi-Fi (newer chipsets) | Depends on the specific chipset | `firmware-brcm80211` covers many, not all |
| Broadcom Wi-Fi with the older `b43` driver | Adapter not detected | Install `firmware-b43-installer` on the installed system, with a network connection. AstraOS cannot ship it: it downloads the firmware rather than containing it. See section 1. |
| NVIDIA GPUs on newer chips | May fall back to software rendering, or fail to start the session | Boot the failsafe GRUB entry; consider installing the proprietary driver after installation |
| Very new AMD or Intel GPUs | May need a newer kernel than Debian's stable kernel | Not solvable in AstraOS 0.1.0; the kernel is the base release's kernel |
| Fingerprint readers | Almost certainly not supported | Out of scope for 0.1.0 |
| Printers and scanners | CUPS plus the gutenprint and Epson (escpr) driver sets are installed | Test with a specific model; some need another `printer-driver-*` from Debian |
| Docking stations, Thunderbolt | Untested | Expect partial functionality |
| Touchscreens and pens | Untested; `xserver-xorg-input-wacom` and `libinput` are present | Report results |
| Secure Boot enforcing firmware | **Will refuse to boot** | Not supported in 0.1.0 |

## 4. Report format

Most of this can be produced by the machine itself. Every AstraOS medium carries a
self-test: add `astraos.ci` to the kernel command line in the boot menu (and
`console=ttyS0,115200n8` if it has a serial port) and the machine boots, checks its
identity, desktop session, packages, networking and the stack above, prints one line per
check and powers off. `/usr/share/astraos/SELF-TEST.txt` inside the image documents it;
the CI boot test runs the same script on every build.

A useful hardware report includes:

```
Machine:      make and model, or VM name and version
Firmware:     UEFI or legacy BIOS; Secure Boot state
CPU / GPU:    from astraos-info
Wi-Fi:        lspci -nnk | grep -A3 -i net
Result:       pass / fail / partial
Evidence:     sudo dmesg | grep -i -E 'firmware|error'
              astraos-info --json
Notes:        exactly what did not work, and at which step
```

`lspci -nnk > hardware.txt` before a reboot gives you the record of what the kernel
detected, including which driver bound to each device.

## 5. Testing on a spare machine

If you intend to test on real hardware:

1. Use a machine you do not depend on, or a separate disk.
2. Back up first. `INSTALLATION_PHYSICAL_PC.md` §1.3 explains why this is not optional.
3. Run the VirtualBox acceptance procedure first. It costs an hour and it finds most of
   the defects without risking anything.
4. Record results in the format above, whether they pass or fail.

## 6. Contributing results

Hardware results — successful ones especially — are one of the most useful contributions
to this project, because they replace an expectation with a measurement. See
`CONTRIBUTING.md`.
