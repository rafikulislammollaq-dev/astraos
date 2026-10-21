# Getting unstuck

keywords: help, support, stuck, problem, doctor, report, bug, reset, restore, recovery, reinstall, diagnostics, system health, share

Three commands cover most of the ways a machine goes wrong, and none of them
needs an account, a network or a password.

**`astraos-doctor` prints the machine's health.** It reads the release, the
kernel, the CPU, the memory, the disks that are nearly full, the swap pressure,
the units that failed, this boot's errors, the addresses and routes, the graphics
card and the assistant's own state - and every line names the command or the file
it came from, so a reader can check the number rather than trust it. It only
reads: it never writes, never asks for a password and never runs anything as
root, so it is safe to run on a machine that is already unwell.

    astraos-doctor

**`astraos-doctor --share` is the same report, redacted.** The user name, the
host name, the home path, the addresses, the MAC addresses, the machine id and
any serial number are replaced, and the page says on its face that it did. That
is the one to paste into a bug report: it keeps the facts and drops the identity.
`--json` is the same thing for a machine to read.

**`astraos-reset --settings` puts the desktop back to how it shipped.** If the
panel will not open, a theme is unreadable or a keyboard shortcut has eaten the
typing, this restores the shipped defaults for the desktop and session. It keeps
every file, it moves the settings it replaces into your own state directory (so
the state before the reset *is* the backup), and it asks for the word `RESET`
before it changes anything.

    astraos-reset --settings

**`astraos-reset --factory` does not erase anything.** It says what to save
first, how to reinstall from the medium, and that the installer is what empties
the disk - because the installer asks for your password and shows which disk it
will erase. A factory reset that hides what it erases is not a reset, it is a
trap.

**If the machine will not boot at all**, `astraos-recovery-guide` prints the
recovery procedure, including how to use the live image to inspect the installed
system *without* erasing anything: mounting the root and the EFI partition,
reading the boot log, and reinstalling the bootloader. The full procedure is in
`docs/RECOVERY.md` in the image.

**If the answer is in here**, the help centre (the "AstraOS Help Centre" entry in
the menu) has every page, searchable, offline. And the assistant (`astra ai`) can
be asked directly - it runs on this machine and reads the same pages.
