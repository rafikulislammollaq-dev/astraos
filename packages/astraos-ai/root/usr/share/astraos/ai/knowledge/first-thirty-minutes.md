# The first thirty minutes on AstraOS

keywords: first run, getting started, first boot, greeter, update, upgrade, firewall, backup, assistant, dashboard, help, where to start

AstraOS is an alpha. It installs itself, it boots, and it does not have a
one-click "make it yours" wizard - this page is that wizard, in words. It is
about twenty minutes, and most of it is reading rather than clicking.

**1. Sign in, and look around.** The greeter asks for the account you created
during the install. On the desktop, the panel is at the top and the whisker menu
is the button at the top left. Everything is reachable from there, and `Super`
opens the app finder if you would rather type than browse.

**2. Open the help centre.** "AstraOS Help" in the menu opens a page with every
how-do-I topic, searchable, and it works with no network at all. It is the same
material the assistant reads, so nothing you learn there is second-hand.

**3. Try the assistant.** `astra ai` in a terminal, or the "Astra AI" entry in the
menu, starts a page on this machine. Ask it something small ("what is this
machine's memory?", "open the help centre"). It runs on this machine, needs no
account, and nothing you type leaves the machine - the *what-the-assistant-sends-
and-what-it-does-not* page says exactly what that means. If you have a phone on
the same network, `astra ai start --lan` and the *coming-from-android* page show
how to use it as a microphone.

**4. Update the system.** This needs your password, and the assistant will not do
it for you - that is a rule, not a bug:

    sudo apt update && sudo apt upgrade

**5. Know the firewall is on.** It is, by default, and it blocks everything
inbound except the assistant's page on private ranges. `ufw status verbose` shows
the rules. If something on your network cannot reach the machine, this is the
first place to look.

**6. Install what you actually need.** `sudo apt install <name>` in a terminal, or
the *Software* entry in the menu (Synaptic, a graphical front end for the same
apt). AstraOS's own packages come from the AstraOS archive; the
*install-extra-software* page has the three commands that add it.

**7. Set up a backup before you install anything big.** The
*back-up-and-sync-files-with-rsync* page has a first run you can repeat - a copy
on a second disk is enough to undo most mistakes.

**8. Know what has not been proven.** No install has been run on physical
hardware yet, the images are not signed, and the archive is unsigned. The
complete list is in `docs/KNOWN_LIMITATIONS.md`, and this release's own evidence
is in `docs/RELEASE-0.2.0-alpha.md` - the runs that prove each claim, and the
ones that do not.

That is the whole first half hour. The rest is the help centre, and it is
written for exactly this moment.
