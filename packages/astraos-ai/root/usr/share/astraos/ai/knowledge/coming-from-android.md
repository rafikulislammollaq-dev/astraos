# Coming from Android to AstraOS

keywords: android, phone, mobile, tablet, pair, microphone, keyboard, mtp, adb, fastboot, files, transfer, play store, notifications, backup

Android is a phone operating system and AstraOS is a desktop distribution, so the
honest way to start is: the two do different things. What a phone is good at -
being carried, being a camera, being a second screen - still applies. What this
page describes is how the phone and the computer help each other.

**The phone can be the assistant's microphone and keyboard.** Start the assistant on
the machine with `astra ai start --lan` (or `astra ai serve --lan`; both print the
same notice) and it prints a pairing code. On the phone, open the address it shows -
it is this machine's address on the local network, ending in `:8765` - enter the
code, and the page on the phone becomes the assistant's ear and mouth. Whatever you
say or type there is handled on the machine, by the model running on the machine.
That is the whole point: a desktop with no microphone or a broken one can still be
talked to, and the transcript stays local.

**The pairing is deliberate, not a convenience.** The page is served without a
password and without TLS, so it is only safe on a network you trust - a home
network, not a café. The assistant prints that warning itself, and the phone can be
unpaired again with `astra ai unpair`, which revokes every phone at once. The
transcript of what the phone said is written to the assistant's journal on this
machine, like everything else the assistant does.

**Files move over USB with MTP.** Plug the phone in, unlock it, and it appears in
the file manager (Thunar) as a device; copy files in either direction. The
packages that make this work (`libmtp-runtime`, `mtp-tools`) are in the image.
For anything larger, a network share or a tool such as `rsync` is the better
answer - the *back-up-and-sync-files-with-rsync* page has the commands, and
`adb` and `fastboot` are installed for the cases that need them.

**Android apps do not run here.** There is no compatibility layer in this release
and no attempt to pretend otherwise; the application set is what Debian and the
AstraOS archive provide. The phone stays the better place for the apps that only
exist there.

**There is no notification bridge.** AstraOS does not yet mirror the phone's
notifications to the desktop, and it does not yet push the desktop's to the phone.
What the pairing gives you is the assistant's page, not a mirror of either device.
This is written down as open work rather than left to be discovered.

**Backups are yours to arrange, and the phone is not the place to keep them.**
`rsync` to a second disk, or to another machine, is the pattern the assistant's
own skill uses; the same page explains how to do a first run that you can repeat.
A phone's own cloud backup stays where it is: AstraOS neither reads nor writes it.

**The desktop is a mouse-driven desktop.** Gestures do not exist here; a tap is a
click, a long press is a right click, and a swipe does nothing. The assistant's
page is the one place where the phone's keyboard is genuinely useful, because
text entry is the only thing it does.

**What to do first**: pair the phone and try one sentence through it - it is the
feature that surprises people the most positively. Then read *what-the-assistant-
sends-and-what-it-does-not*, so you know exactly what the microphone is for.
