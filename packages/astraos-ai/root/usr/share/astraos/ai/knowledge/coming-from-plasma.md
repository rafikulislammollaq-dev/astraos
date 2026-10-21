# Coming from Plasma (or Mint, or Ubuntu) to AstraOS

keywords: plasma, kde, arch, pacman, aur, mint, ubuntu, debian, apt, discover, flatpak, snap, wayland, x11, system settings, kde connect, firewalld

Plasma users arrive with good habits and a wrong assumption: that AstraOS is
another Arch. It is not. AstraOS is an independent distribution built on **Debian 13
(trixie)** packages, so the package manager is `apt`, there is no AUR, and the
release is not rolling. The rest of this page is the honest list of differences.

**The package manager is apt.** `apt update && apt upgrade` is the equivalent of
`pacman -Syu`; `apt install <name>` is `pacman -S <name>`; `apt search <text>` is
`pacman -Ss`. Synaptic is in the menu as *Software*: it is the same apt, with a
graphical front end. AstraOS's own packages - the assistant, the dashboard, the
installer - come from the AstraOS archive, which is unsigned for now and has to be
added by hand; the *install-extra-software* page has the commands.

**Flatpak is here; Snap is not.** Flatpak is installed, with the portals and the
keyring it needs, and the Flathub remote is pointed at Flathub by the build - a
pointer, nothing more: nothing is downloaded until you install something from it.
There is no Snap in this image, and no `snapd`.

**The desktop is Xfce, not Plasma.** That is the biggest difference and it is
deliberate: Xfce is lighter on old machines and it is what this image has been
tested with. Concretely:

  * there is no Activities overview and no KRunner. `Super` opens the Xfce app
    finder instead, which searches installed programs by name - the closest thing
    to KRunner, and much dumber;
  * the panel is an Xfce panel, and the window buttons and the clock are panel
    plugins. A Plasma layout is not something you can switch to;
  * settings live in the Xfce *Settings Manager* (`xfce4-settings`), not in
    Plasma's *System Settings*. Display, network, power and the rest are under
    their own names;
  * the session is **X11**, not Wayland. That is a choice made for old graphics
    hardware, and it is written down in `docs/KNOWN_LIMITATIONS.md`;
  * screenshots are `xfce4-screenshooter` (the `Print Screen` key opens it), and
    the clipboard manager is `xfce4-clipman`.

**KDE applications can be installed from Debian**, and some of them work. Mixing a
Plasma session with an Xfce one is possible and is not something this project has
tested; if you do it, do it on a machine you can reinstall.

**The firewall is ufw, not firewalld.** It is **on by default**, with a deny
policy for everything inbound except the assistant's page on the private range.
`ufw status verbose` shows what is allowed. If something on your network cannot
reach the machine - a printer, a game, a file share - that is usually why.

**KDE Connect is not installed.** The phone story on AstraOS is the assistant's
own page: `astra ai start --lan` prints a pairing code, the phone opens the
address it shows, and the phone becomes the assistant's microphone and keyboard.
The *coming-from-android* page has the details, including the warning about doing
this on a network you trust.

**Wine and winetricks are installed**, so a Windows application that works under
Wine can usually be run: `wine <setup.exe>`, and `winetricks` for the things
Wine needs. This is compatibility work, not a promise: a game with an anti-cheat
or a launcher will not work, and AstraOS does not pretend otherwise.

**What AstraOS adds on top of Debian** is the assistant (`astra ai`), the
dashboard, the offline help centre ("AstraOS Help"), the installer that puts
AstraOS on a disk with your own account, and an archive of AstraOS's own packages
so an installed system can receive updates.

**What to do first**: read *first-thirty-minutes*, then *install-extra-software*
if you want a specific program, and *what-the-assistant-sends-and-what-it-does-
not* before you type anything private into a chat box.
