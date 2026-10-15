# Fixing Common Boot And Graphics Problems

keywords: desktop, panel missing, stock desktop, no sound, pipewire, pavucontrol, brightness, backlight, video group, virtualbox, guest additions, resolution, xrandr, x11, wayland, graphics, xorg

**The desktop looks like plain Xfce - no AstraOS panel, no wallpaper, no theme.** The
AstraOS panel, wallpaper, keyboard shortcuts and theme are seeded from `/etc/skel` into
a home directory when the account is created, so a fresh install has them and an account
that already existed on the machine does not. The other half of it is that Xfce reads
those defaults only at the first login of a new account; after that, whatever is in
`~/.config/xfce4/xfconf/xfce-perchannel-xml/` wins. So log out and back in first - that
alone is the fix most of the time. If the panel is still missing, the panel's own channel
file has gone invalid and Xfce has regenerated a default; move it aside with
`mv ~/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml ~/` and log out and back
in again, and Xfce rebuilds one. That `mv` is yours to run, and it is worth knowing what
it costs: any panel item you had added by hand goes with it and has to be added back.

**No sound.** AstraOS uses PipeWire, not PulseAudio directly - the image installs
`pipewire`, `pipewire-alsa`, `pipewire-pulse` and `pavucontrol`. Check the user services
first: `systemctl --user status pipewire wireplumber`. If either is not running,
`systemctl --user restart pipewire wireplumber` brings them back, and no root is needed
for any of it. Then open `pavucontrol` and look at two things: which output device is
selected, and whether the application you expect to hear is not muted in its stream. A
muted channel is the most common cause of all, which is what `alsamixer -c 0` is for -
`m` toggles mute, and a column showing `MM` is muted. In a virtual machine, check that
the machine has an audio controller at all, because a VM with no sound hardware
configured produces exactly this symptom with nothing wrong in the guest.

**Brightness.** The kernel exposes the backlight at
`/sys/class/backlight/<device>/brightness`, and writing to it is a root-owned operation
unless a udev rule grants your account access - which on Debian it does for members of
the `video` group. If the brightness keys do nothing and a tool reports that it cannot
change the backlight, check `groups`: if `video` is not listed, the fix is
`sudo usermod -aG video $USER` followed by logging out and back in. None of
`brightnessctl` or `light` is installed by default, so `astra install brightnessctl` is
the other half of the answer, and it is one you type. Under X11 there is also
`xrandr --brightness 0.8`, which dims the whole screen in software rather than lowering
the backlight - useful on a desktop, powerless to save battery, and gone on logout.

**VirtualBox: no clipboard, no shared folders, wrong resolution.** The VirtualBox Guest
Additions are deliberately not part of the image; that is why copy and paste between
host and guest does not work out of the box. In the VirtualBox window, Devices, Insert
Guest Additions CD image, then run the installer from the mounted CD - it needs root, so
it is your command to type. After a reboot, `xrandr` lists the virtual outputs, and
resizing the VirtualBox window (or View, Virtual Screen 1, then a resolution) is honoured
because the additions provide the driver. While you are in the machine's Display
settings, VMSVGA is the graphics controller to choose for a Linux guest, and give it as
much video memory as the dialog allows; the older VBoxVGA and VBoxSVGA choices are what
produce a stuck low resolution.

**Wayland or X11.** AstraOS's desktop is Xfce on X11 in this release; the graphics list
is X11 only and the documentation says so, so a program that requires Wayland is not
going to run, and an X11 program runs everywhere. If someone tells you to switch the
session to Wayland, that is future work, not an option in front of you - and if the
graphics fail outright, the failsafe entry in the GRUB menu is the supported first step,
because it disables kernel modesetting and the ACPI workarounds.

**Where to look when the graphics fail at boot.** `astraos-recovery-guide` prints the
recovery steps for login loops, no boot and broken updates, and it is installed. For a
graphics fault specifically, the X server's own log is more specific than the journal;
it is written by the session at `~/.local/share/xorg/Xorg.0.log` on this system, since X
runs as your user rather than as root. `systemctl --failed` and
`journalctl -b -p err` cover the rest, and every one of those commands is read-only.
