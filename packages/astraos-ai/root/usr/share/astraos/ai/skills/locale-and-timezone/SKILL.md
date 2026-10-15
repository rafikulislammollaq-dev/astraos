# Set The Locale And Timezone

keywords: locale, timezone, time zone, timedatectl, set-timezone, keyboard layout, setxkbmap, time, clock, language, tzdata, wrong time

requires: setxkbmap

when: the clock or the date is wrong, the user wants a different timezone or language, or the keyboard types the wrong symbols

---

## Steps
1. Report what is set now: run_command `timedatectl`. It prints `Local time`, `Universal time`, `Time zone`, `System clock synchronized` and whether the NTP service is active. This is the fact the whole task starts from, and it needs no root.
2. List the valid zone names: run_command `timedatectl list-timezones`. It prints several hundred lines of the form `Continent/City`. If the user named a city, ask them to pick the exact line from that output - never assume the spelling, because a wrong zone name silently sets the wrong time.
3. Check the keyboard layout of this session: run_command `setxkbmap -query`. It prints the `layout`, `variant`, `model` and `options` X11 is actually using, which is the only way to know what the physical keys will produce.
4. Apply a layout to the running session when asked: run_command `setxkbmap gb` for a British layout, `setxkbmap us` for a US one. This lasts until the user logs out, and it is the correct action for "the wrong symbols are coming out" right now. Making it permanent is the user's job in Settings, Keyboard, Layout.
5. Read the system locale by asking the user to run `cat /etc/default/locale` in their own terminal, and read back what it prints. The assistant does not read or write anything under `/etc`, `/boot`, `/usr` or `/var`: its command runner refuses those paths on purpose, and this is the step where that rule shows up.
6. Get the rest of the locale picture: run_command `localectl status`, which reports the system locale, the console keymap and the X11 layout as systemd sees them.
7. Setting the time zone needs root, so STOP. Do not run `sudo timedatectl set-timezone` and do not run `timedatectl set-timezone` on its own - the first is refused by this assistant and the second fails with a permission error. Instead print the exact command for the user to run: `sudo timedatectl set-timezone Europe/London`, and say why it is theirs to type: it changes `/etc/localtime`, which is a system file, so it needs their password, and this assistant runs as their user with no password and no root.
8. Give the same treatment to time sync: `sudo timedatectl set-ntp true` when the clock is drifting, and to the locale: `sudo dpkg-reconfigure locales` to generate the locale, then `sudo update-locale LANG=en_GB.UTF-8` once it exists. Print them, explain them, and let the user run them.
9. Close with a summary: what is set now, what should change, and the exact commands to change it, in order. Nothing was changed by the assistant.

## Notes

This skill prints commands; it does not run anything that changes the system. That is not caution for its own sake - `set-timezone`, `set-ntp`, `localectl set-locale` and `localectl set-keymap` all write files owned by root, and a program running as the user cannot do them. The honest answer to "why won't you just do it" is one sentence: it needs your password, and I have no business having it.

A wrong clock with a right timezone is an NTP problem, not a timezone one; a right clock in the wrong zone is the opposite. `timedatectl` says which, in the same output, so step 1 settles the diagnosis before anything is proposed.

`sudo dpkg-reconfigure tzdata` is the older Debian way and still works, but `timedatectl set-timezone` is preferred on a systemd system and does not need the locale regenerated. The hardware clock is set from the system clock on shutdown by default on a normal Debian install, so changing the timezone is enough; there is no separate step for the RTC.
