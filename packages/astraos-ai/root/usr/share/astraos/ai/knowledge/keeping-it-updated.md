# Keeping AstraOS up to date

keywords: update, upgrade, apt, archive, repository, new version, rollback, snapshot, restore, security update, packages, version

An installed AstraOS gets new packages from two places: Debian 13, through the
ordinary Debian sources, and the AstraOS archive, for AstraOS's own packages (the
assistant, the dashboard, the installer, the system tools). Both are reached with
apt - AstraOS does not replace apt, and it never will: a distribution that
replaces the package manager replaces the ecosystem with it.

**What is on offer:**

    astraos-update --check

That lists what both archives have, without changing anything and without a
password, and it prints the command to take it. It never runs the upgrade
itself: an upgrade asks for your password, and a tool that types your password
for you is a tool that can break your system without asking.

**Taking the update:**

    sudo apt update && sudo apt full-upgrade

**Keeping your files safe first.** apt takes the packages; it does not take your
files with them. So before an upgrade:

    astraos-update --snapshot

That copies your home directory into your state directory, with a time stamp in
the name. The second snapshot of the same home is quick, because the copy is
incremental.

**If the upgrade went badly:**

    astraos-update --rollback

It asks first, it puts the files from the newest snapshot back, and it keeps the
state from before the restore - so the restore can itself be undone. It undoes
*your files*. A broken package is a different repair: `astraos-recovery-guide`
prints the procedure, and the installer's own medium is the way back to a clean
system.

**The AstraOS archive.** It is served from the AstraOS repository and is listed
in `/etc/apt/sources.list.d/` once it is enabled. The line ships disabled on
purpose: a line pointing at an archive whose signature cannot be verified makes
`apt update` fail for the whole system. When the archive is signed, the public
key is installed at `/usr/share/keyrings/astraos-archive-keyring.gpg` and the
line is switched on with one command - the instructions are in
`/usr/share/doc/astraos-base/apt-archive.md`.

**Security updates are the reason this matters.** Debian's archive carries the
security fixes for every package in the image. An AstraOS that was installed
three months ago and never updated is running three-month-old packages, and the
firewall in front of it does not make them any safer.
