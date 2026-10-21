# Coming from Windows to AstraOS

keywords: windows, migration, start menu, task manager, ctrl-alt-del, files, onedrive, printers, app store, virus scanner, keyboard shortcuts, dual boot, ntfs

AstraOS is an independent Linux distribution built on Debian 13 packages, with an Xfce
desktop. Nothing here is a Windows replacement in the sense of running Windows
software; it is a different way of doing the same daily work, and this page is the
honest list of what changes.

**The Start menu** is the button at the top left of the panel (the mouse-shaped
one). It holds the applications, and pressing the `Super` key opens the app finder
instead, where typing the first letters of a program's name is usually faster than
browsing. `Alt+Tab` switches between open windows everywhere, as on Windows.

**Ctrl+Alt+Del does nothing here**, and that is not a broken feature: there is no
Windows-style security screen. For the things that key was good for, the panel has
its own entries - the *Task Manager* (`xfce4-taskmanager`) shows what is running
and what it costs, and *System Monitor* (`gnome-system-monitor`) shows the same
plus memory, disks and network. `Ctrl+Alt+T` opens a terminal, which is the fastest
way into everything else.

**Your files live in your home directory**, in the same folders as elsewhere on
Linux: `Documents`, `Pictures`, `Music`, `Videos`, `Downloads`, and a `Desktop`.
If the machine has a Windows partition, open the file manager (Thunar) and it
appears in the sidebar; click it and it is mounted, with a small icon to unmount
when you are done. Writing to an NTFS volume that Windows hibernated is refused by
the kernel on purpose - that refusal protects the filesystem, and the fix is to
shut Windows down properly (`shutdown /s` in a Windows terminal) before switching.
A USB stick with exFAT or NTFS works in both directions and is the simplest way to
move a folder of documents across.

**There is no Microsoft account, no OneDrive, no Store and no Defender.** Files are
yours, on your disk; nothing is synchronised anywhere unless you set that up
yourself. In exchange there is no background telemetry from a vendor, and the
firewall is on by default: `ufw` blocks everything inbound except the assistant's
page on the private range. That occasionally surprises people - a game on the local
network, a printer that cannot be discovered, a second computer sending files -
and `ufw status verbose` shows exactly what is allowed.

**Software comes from apt**, either in a terminal (`apt install <name>`) or through
Synaptic, a graphical front end for the same thing, which is in the menu as
*Software*. AstraOS's own packages - the assistant, the dashboard, the installer -
come from the AstraOS archive, which is unsigned and, for now, has to be added by
hand; the help page *install-extra-software* has the commands. There is no
proprietary driver store: some hardware needs a driver that Debian ships as a
separate package, and *fix-common-boot-and-graphics-issues* lists the ones that
matter for older machines.

**Printing** is CUPS, set up through *Printers* (`system-config-printer`). It
speaks to most network printers over IPP and to most USB printers over
`usb://`; printers that need a vendor driver will not be found, and the PDF
printer (`printer-driver-cups-pdf`) is there for "print to a file".

**The keyboard** is the one you are used to, with the Windows key doing something
more useful: it opens the app finder. `Print Screen` opens the screenshot tool
(`xfce4-screenshooter`), which can also capture a single window. `Ctrl+Alt+Delete`
is free for whatever you want to bind it to.

**The assistant** is the local one: `astra ai` in a terminal, or the "Astra AI"
entry in the menu, which starts a page on this machine. It runs your requests
locally, needs no account, and nothing it does leaves the machine unless you ask
it to. It is the closest thing AstraOS has to a search box that understands
sentences.

**What to do first**: read *first-thirty-minutes* - it is the short version of
this page, and it points at the rest. And read *what-the-assistant-sends-and-what-
it-does-not* before you type anything private into a chat box, even a local one.
