# AstraOS recovery guide

`astraos-recovery-guide` prints this guidance on a running system. This document is the
fuller version, including the parts that require the installation medium.

**AstraOS makes no claim that every failure is recoverable automatically.**
Some are not, and the sections below say so.

## 0. Start here

Before changing anything, work out *how far* the system got:

| Symptom | Meaning |
|---|---|
| No firmware logo, no power | Hardware, not AstraOS |
| Firmware works, no GRUB | The bootloader stage is broken |
| GRUB appears, kernel messages then stop | Kernel, initramfs or root filesystem |
| Text console works, no desktop | The system booted; the problem is graphical |
| Greeter appears, login returns to the greeter | The session is crashing on start |

Test for a text console with **Ctrl+Alt+F3**. If you can log in there, the system booted
and your data is intact. That single fact changes which of the following applies.

Also: `journalctl -b -1` shows the log of the **previous** boot, which is often the most
useful one when the current boot is broken.

---

## 1. The desktop does not appear

```bash
systemctl --failed
journalctl -b -u lightdm --no-pager | tail -60
less /var/log/Xorg.0.log      # search for lines starting with (EE)
startxfce4                    # start the session by hand and read the error
```

Common causes: a graphics driver failure; a full home directory; a home directory owned by
another user; a corrupted `~/.config/xfce4`.

If `~/.config/xfce4` is suspected, move it aside rather than deleting it — the session
will regenerate defaults and you keep the evidence:

```bash
mv ~/.config/xfce4 ~/.config/xfce4.broken
```

---

## 2. The graphical login fails

```bash
ls /usr/share/xsessions/          # does the xfce session file exist?
systemctl status lightdm
sudo journalctl -b | grep -i xfce
ls -ld "$HOME"                    # ownership of the home directory
```

An empty or unwritable home directory, or one whose ownership changed, will make a session
fail while the text console still works.

If you cannot log in at all, boot the live image and reset the password from there.

---

## 3. The system does not boot

1. Choose the **failsafe** GRUB entry. It disables the splash, kernel modesetting and
   ACPI power management, so failures become visible.
2. If it boots, the fault is in graphics or ACPI — record what the failsafe options
   changed.
3. If it does not boot, use the live image and inspect the installed system.

### Checking the root filesystem

Follow these steps in order. Do not skip the `-n`.

```bash
sudo parted -l                 # identify the partition; do not guess
sudo umount /dev/<root-part>   # it must NOT be mounted
sudo fsck -n /dev/<root-part>  # -n means "report, do not repair"
```

Review the output first. Then, and only if the filesystem is unmounted:

```bash
sudo fsck /dev/<root-part>
```

**Never run fsck on a mounted filesystem.** It can destroy it. If you must repair the
filesystem the live system is running from, mount it read-only elsewhere.

If the filesystem is badly damaged, **copy your data off first** — attach a USB disk and
copy, before attempting any repair.

---

## 4. Package management is broken

```bash
sudo apt update 2>&1 | tail -30         # read the actual error
sudo apt --fix-broken install           # broken dependency chain
sudo dpkg --configure -a                # interrupted dpkg run
```

**Never delete files under `/var/lib/dpkg` by hand.** Doing so corrupts the package
database, and recovering from that is much harder than the original problem.

If you see signature errors, check the clock first — a wrong date breaks TLS and
signature validation, and that looks like a security failure when it is a clock failure.

---

## 5. A kernel update left the system unbootable

```bash
# In GRUB: Advanced options for AstraOS -> choose the previous kernel
dpkg -l 'linux-image-*' | grep ^ii      # which kernels are installed
ls -l /boot/                            # is there an initramfs for each?
sudo update-initramfs -u -k "$(uname -r)"
less /var/log/apt/history.log           # what the update actually did
```

Remove a broken kernel image only after you have confirmed a working one boots.

---

## 6. The bootloader is missing or misconfigured

Repairing GRUB from the live image:

1. Boot the live medium.
2. Identify the root and EFI partitions: `sudo parted -l`, `lsblk -f`. **Do not guess.**
3. Mount the installed root, then the EFI partition at `<root>/boot/efi` on a UEFI system.
4. Bind the system directories before entering the chroot:

   ```bash
   for d in dev proc sys run; do sudo mount --bind /$d <root>/$d; done
   sudo chroot <root> /bin/bash
   ```

5. Inside the chroot:

   ```bash
   grub-install /dev/<disk>     # for UEFI: add --target=x86_64-efi --efi-directory=/boot/efi
   update-grub
   ```

6. Exit, unmount in reverse order, reboot.

Getting the boot mode wrong is the most common reason a "successful" repair still does not
boot. Check it first with `astraos-info | grep -i boot`.

---

## 7. The disk is full

```bash
df -h
sudo du -xh --max-depth=1 / 2>/dev/null | sort -h | tail -20
sudo apt clean                          # safest large win: the package cache
sudo journalctl --vacuum-size=200M      # old journal entries
```

Then look for old kernels you no longer need. If the root filesystem is genuinely too
small, that needs repartitioning, not cleanup — and repartitioning is a data-loss risk of
its own.

---

## 8. Networking does not work

```bash
ip -brief addr                     # does the interface exist and have an address?
ip route show default              # is there a route out?
nmcli device status                # is NetworkManager managing it?
lspci -nnk | grep -A3 -i net       # did the kernel see the hardware?
sudo dmesg | grep -i firmware      # is firmware missing?
systemctl status NetworkManager
```

If firmware is missing, the adapter may not be supported by AstraOS. See
`HARDWARE_COMPATIBILITY.md`. Installing firmware needs a network connection, so use a
wired connection or download it on another machine.

---

## 9. What recovery cannot fix

- **A destroyed partition table.** Rewriting a disk is not reversible. Backups are the
  only protection.
- **Hardware failures.** No amount of software recovery helps a dying disk.
- **Encrypted data without the passphrase.** There is no backdoor.
- **Anything without a backup.** This is why `INSTALLATION_PHYSICAL_PC.md` step 1.3 is the
  step that matters most.

---

## 10. Collecting evidence

```bash
astraos-info --json
systemctl --failed
sudo journalctl -b -p err --no-pager
sudo dmesg | tail -100
df -h
```

Do not send passwords, private keys, or Wi-Fi configuration files containing network keys.
