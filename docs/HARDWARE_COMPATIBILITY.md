# Hardware compatibility

> **No hardware has been tested.** Every table below describes what AstraOS 0.1.0 is
> *configured* to support, not what has been shown to work. The project has never booted
> the image on any machine (`KNOWN_LIMITATIONS.md` §2).
>
> Treat this document as a list of expectations to test, not as a compatibility guarantee.

## 1. What is included

AstraOS installs firmware from Debian's `non-free-firmware` component, so the licensing is
handled by Debian's own redistribution arrangements (plan §12, §23):

| Category | Packages |
|---|---|
| Wi-Fi | `firmware-iwlwifi`, `firmware-atheros`, `firmware-realtek`, `firmware-brcm80211`, `firmware-mediatek`, `firmware-ti-connectivity`, `firmware-libertas`, `wireless-regdb` |
| Graphics | `firmware-amd-graphics`, `firmware-nvidia-graphics` |
| Generic | `firmware-linux-free`, `firmware-linux-nonfree`, `firmware-misc-nonfree` |
| Audio | `firmware-sof-signed`, `alsa-firmware-loaders` |
| CPU | `intel-microcode`, `amd64-microcode` |

Graphics drivers are the **open-source** ones only: `i915` (Intel), `amdgpu`/`radeon`
(AMD), `nouveau` (NVIDIA) and the software-rendered fallbacks `fbdev`/`vesa`.

**No proprietary GPU driver is installed or offered.** AstraOS must not download arbitrary
drivers to claim broader compatibility (plan §12). If you want the proprietary NVIDIA
driver, install it yourself from Debian's `non-free` after installation, and understand
that it can break the graphical session if it is done incorrectly.

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

## 3. Expected to be problematic

| Component | Likely outcome | What to do |
|---|---|---|
| Wi-Fi chipsets needing firmware not in the list above | Adapter not detected | Identify with `lspci -nnk`, check `dmesg` for a missing firmware file. Some need out-of-tree drivers AstraOS will not ship. |
| Broadcom Wi-Fi (some models) | Depends on the specific chipset | `firmware-brcm80211` covers many, not all |
| NVIDIA GPUs on newer chips | May fall back to software rendering, or fail to start the session | Boot the failsafe GRUB entry; consider installing the proprietary driver after installation |
| Very new AMD or Intel GPUs | May need a newer kernel than Debian's stable kernel | Not solvable in AstraOS 0.1.0; the kernel is the base release's kernel |
| Fingerprint readers | Almost certainly not supported | Out of scope for 0.1.0 |
| Printers and scanners | CUPS is installed, drivers are not | Test with a specific model; many need `printer-driver-*` packages from Debian |
| Docking stations, Thunderbolt | Untested | Expect partial functionality |
| Touchscreens and pens | Untested; `xserver-xorg-input-wacom` and `libinput` are present | Report results |
| Secure Boot enforcing firmware | **Will refuse to boot** | Not supported in 0.1.0 |

## 4. Report format

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
