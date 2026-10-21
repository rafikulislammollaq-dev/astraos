# Testing AstraOS on your own machine

You do not need a spare computer. The machine you are reading this on - the one
running Ubuntu or Linux Mint - is enough, in either of two ways, and this page
gives the exact steps for both.

**Do not install AstraOS over your daily system.** Not because it is dangerous,
but because you would be debugging your own machine instead of AstraOS. Use one of
the two routes below.

## Route A: a virtual machine on this machine (no risk, and it is the honest first test)

This is what the project recommends first, and it is a real test: a real
VirtualBox window, a real Calamares installer, a real AstraOS desktop you can
click in. The difference from CI is that *you* see it.

1. Download the ISO from the build you want to test. Every build publishes it as
   the `astraos-iso` artifact of the "Build ISO" run; the release notes list the
   run id and the image's SHA-256.
2. Check the download before you use it:

       sha256sum astraos-0.2.0-alpha-amd64.iso

   (on Windows: `certutil -hashfile astraos-0.2.0-alpha-amd64.iso SHA256`)
   The expected value is in the run's proof page. A hash that does not match is
   a download that did not finish - do not install it.
3. Install VirtualBox if it is not there (`sudo apt install virtualbox`), or use
   the procedure in `docs/INSTALLATION_VIRTUALBOX.md` for the details.
4. Create a machine: **Linux / Other (Unknown/64-bit)**, 4096 MB of memory
   (2048 works, but the assistant wants more), 40 GB of disk, and enable the
   EFI boot mode. Turn on 3D acceleration if your machine has it; if the
   installer freezes, turn it off and try again.
5. Attach the ISO to the optical drive and boot it. Sign in as `astra` (the
   live account) and start the installer from the desktop.
6. Let it install to the virtual disk, restart, and let it boot from the disk
   alone. Create your own account when the installer asks.
7. Now do the things that matter, in this order:
   - `astraos-doctor` - the health report, and `--share` for a version you can
     paste anywhere;
   - open the help centre ("AstraOS Help Centre" in the menu) and search for
     something you would actually look up;
   - `astra ai` and ask it something ordinary;
   - pair your phone (`astra ai start --lan`) and try one sentence through it;
   - `astraos-update --check` - what is on offer;
   - take a screenshot of the desktop and of the help centre.
8. Write down what surprised you - the good and the bad. That is the report.

## Route B: a spare disk in this machine (the closest thing to physical hardware)

If you have a disk that holds nothing you need (an old drive, a USB drive of
32 GB or more), AstraOS can be installed to it and you keep your daily system
intact:

1. Write the ISO to a USB stick: `dd if=astraos-0.2.0-alpha-amd64.iso of=/dev/sdX bs=4M status=progress`
   (find the right device with `lsblk` first - and double-check, because `dd`
   writes to whatever you name).
2. Boot from the stick, install to the spare disk, and choose the disk
   explicitly in the partitioner. The installer shows which disk it will erase
   and asks for your password; read it before you confirm.
3. When it is done, remove the stick and reboot: the machine should boot into
   AstraOS from the spare disk.

## What to send back

The project keeps a compatibility table, and it is empty because nobody has run
this yet. Your run is the first row. What is useful:

| What | Where to get it |
|---|---|
| CPU, RAM, graphics | `lscpu \| head -20` and `free -h` on the AstraOS machine |
| The image you used | its file name and SHA-256 |
| Did the installer finish? | yes / no, and the last line of the installer's output |
| Did it boot from the disk alone? | yes / no |
| What did the help centre and the assistant do? | a sentence each |
| What broke, or surprised you? | in your words, not a bug report |

`astraos-doctor --share` produces most of that, already redacted.

## One more thing this machine can be

AstraOS's first run wants to import the things you already have - your files,
your settings, your dotfiles. Your home directory is exactly the kind of source
the import is written for, so this machine is a real test of that path too: the
procedure is in the roadmap, and this is the machine where it can be tried
without risk.

And if anything goes wrong that the doctor does not explain, `astraos-recovery-guide`
prints the recovery procedure, including how to use the live image to inspect the
installed system without erasing anything.
