# Troubleshooting AstraOS

For a system that will not boot, use [`RECOVERY.md`](RECOVERY.md) instead. This document
covers problems in a system that is running.

## First: collect facts

```bash
astraos-info              # release, kernel, hardware, storage, network
systemctl --failed        # anything that failed to start
sudo journalctl -b -p err # errors from this boot
sudo dmesg | tail -50     # kernel messages
```

Most "AstraOS is broken" reports are answered by the first two commands. Check them before
changing anything: a change made without knowing the cause usually adds a second problem.

---

## The live session

**Nothing I do in the live session is saved.**
Correct, and intentional. The live session is non-persistent; the message of the day says
so. Install AstraOS to keep changes.

**The live session is slow.**
The live filesystem is squashfs and is decompressed on the fly, and a virtual machine
without hardware acceleration is slow. Give the VM at least 2 CPUs and 4 GB RAM. On real
hardware, the live session is still slower than an installed system by design.

**The screen resolution is wrong in the live session.**
Settings → Display. In QEMU/KVM with SPICE the shipped `spice-vdagent` follows the client
window, and in VMware the shipped `open-vm-tools` desktop plugins do the same; on other
displays, choose a standard mode. In VirtualBox, install VirtualBox's own Guest Additions
from its CD image — Debian 13 does not package the VirtualBox guest utilities, so AstraOS
cannot ship them (see "Virtual machines" in `README.md` and `KNOWN_LIMITATIONS.md` §2).

**I cannot log in to the live session.**
The live user `astra` has no password. Select the user and press Enter at the empty
password prompt.

---

## The desktop

**The panel is gone or looks wrong.**
Xfce regenerates a default panel when the configuration is invalid. To return to the
AstraOS layout, remove the user's panel configuration and log out and back in:

```bash
mv ~/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml ~/
```

**The wallpaper is not the AstraOS wallpaper.**
Per-user wallpaper wins over the system default. Set it in Settings → Desktop →
Background, and point it at `/usr/share/astraos/wallpapers/`.

**Window decorations look different from the screenshots.**
Correct and documented. AstraOS ships a colour-only GTK theme and no xfwm4 titlebar
theme. See `KNOWN_LIMITATIONS.md` §1.4.

**The clock is wrong.**
Set the timezone; `sudo dpkg-reconfigure tzdata`, or use Settings → Date and Time. If the
time is right but TLS still fails, check `timedatectl` — the hardware clock and the system
clock can disagree.

---

## Audio

```bash
systemctl --user status pipewire wireplumber
pavucontrol                 # check the output device and per-application volume
alsamixer -c 0              # check for a muted or zero-volume channel
```

The most common cause is a muted channel or a virtual machine with no audio device
configured. AstraOS uses PipeWire, not PulseAudio directly.

---

## Networking

**Wi-Fi networks are not listed.**

```bash
nmcli device status
lspci -nnk | grep -A3 -i net
sudo dmesg | grep -i firmware
```

If the interface is missing entirely, the kernel has not bound a driver — usually missing
firmware. See `HARDWARE_COMPATIBILITY.md`.

**The network works but DNS does not.**

```bash
resolvectl status
dig deb.debian.org
cat /etc/resolv.conf
```

Do not disable certificate validation to work around a connectivity problem. That turns a
network fault into a security fault.

**Mouse, keyboard, or a USB device does not work.**
Bluetooth needs `bluetooth.service` running and `blueman` for pairing. For USB, check
`lsusb` and `sudo dmesg | tail -30` for a device that was recognised but not mounted.

---

## The installer

**The installer will not start.**
Run it from a terminal to see the error:

```bash
sudo calamares
```

It needs the live filesystem mounted; if `/run/live/medium` is missing, the live session is
not running properly.

**The installer says the disk is too small.**
The minimum is 8 GB. Use at least 20 GB to have room for updates.

**The installer does not list my disk.**
A disk can be hidden by the firmware (RAID mode), or be in use. In a VM, confirm the virtual
disk was actually added. On real hardware, check the firmware's storage mode: many machines
ship with the controller in a RAID mode that Linux does not see until it is switched to
AHCI, and switching it can stop the existing operating system from booting. Understand the
consequences before changing that setting.

**The installer fails near the end.**
Look at the log it offers to save, and at `journalctl -b | tail -100`. Report the last 50
lines, not the first error message you saw.

**After installing, the live session comes back.**
The installation medium is still attached. Remove the ISO from the virtual optical drive or
unplug the USB, then boot again.

---

## Software and updates

**`apt update` fails with a signature error.**
Check the clock first. Then confirm the AstraOS APT policy is unmodified:

```bash
grep -r . /etc/apt/apt.conf.d/60-astraos-security
```

**A package will not install because of unmet dependencies.**
`sudo apt --fix-broken install`. If that fails, read the actual dependency conflict rather
than forcing the install: `--force-*` options turn a broken package into a broken system.

**Synaptic shows no packages.**
It reads the same APT lists; `sudo apt update` first.

---

## I still cannot fix it

Collect the evidence from the top of this page and see `CONTRIBUTING.md`. Include:

- what you did, what happened, what you expected;
- `astraos-info --json`;
- `systemctl --failed`;
- the relevant log lines.

A report with the actual output is worth twenty reports without it.
