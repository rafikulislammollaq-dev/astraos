# The Time Zone And The Locale

keywords: timezone, time zone, clock, wrong time, timedatectl, set-timezone, locale, language, tzdata, ntp, keyboard layout, setxkbmap

`timedatectl` with no arguments is the whole diagnosis, and it needs no root: it prints
`Local time`, `Universal time`, the `Time zone` currently in force, whether the system
clock is synchronised, and whether the NTP service is active. A right clock in the wrong
zone is a timezone problem; a wrong clock with the right zone is a sync problem, and the
same output distinguishes them. To see every valid zone name run `timedatectl
list-timezones`, which prints several hundred lines of the form `Continent/City`.

Setting the zone is one command, and it needs root: `sudo timedatectl set-timezone
Europe/London`, with the zone name copied exactly from the list. What it changes is
`/etc/localtime`, a symlink into `/usr/share/zoneinfo` that is owned by root, so the
machine asks for your password - correctly, because a wrong zone breaks TLS certificate
checks and log ordering as surely as it breaks the clock in the panel. On a systemd
system this is preferred to the older `sudo dpkg-reconfigure tzdata`, which still works
and rewrites the same file. Time sync is the same shape: `sudo timedatectl set-ntp true`
turns on `systemd-timesyncd`, the one synchronisation daemon AstraOS enables - the image
ships no chrony, ntpsec or openntpd, and those packages declare a conflict against the
systemd one anyway, so installing a second one is a downgrade rather than an upgrade.

The assistant prints these commands and does not run them. It runs as your user account,
it has no password, and its command runner refuses `sudo`, `pkexec`, `su` and `doas`
outright; `timedatectl set-timezone` typed without `sudo` would simply fail with a
permission error. If you ask it to fix the time it will tell you which of the two
problems you have and the exact line to paste into a terminal.

If the clock is wrong by a whole number of hours after the machine has been off, and the
timezone is correct, check whether anything else on the disk uses local time: the usual
cause is a second operating system that sets the hardware clock to local time, where
Debian expects it in UTC. The timezone files cannot repair that disagreement; the fix is
a setting on the other system, not on this one.

The locale is the same story in a different file. `locale` shows what your session is
using, `localectl status` shows what the system is set to, and `/etc/default/locale`
holds the answer for every login - read it with `cat /etc/default/locale`. To change it,
first make sure the locale exists (`sudo dpkg-reconfigure locales` generates it), then
set it with `sudo update-locale LANG=en_GB.UTF-8`, again a root-owned system file. The
keyboard layout that turns what you type into the right characters is checked with
`setxkbmap -query` and is changed in Settings, Keyboard, Layout - a change made there
survives a logout, while `setxkbmap gb` typed in a terminal only lasts until you log out.
