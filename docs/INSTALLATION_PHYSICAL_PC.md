# Installing AstraOS on physical hardware

> ## Do not do this yet
>
> AstraOS 0.2.0 Alpha has **never been booted on physical hardware**, the installer has **never been run**, and
> **no hardware has been tested** (`KNOWN_LIMITATIONS.md` §2). Physical installation is a
> later milestone and is gated on the VirtualBox acceptance procedure in
> [`INSTALLATION_VIRTUALBOX.md`](INSTALLATION_VIRTUALBOX.md) passing first (plan §20).
>
> Installing an untested alpha on a computer you rely on can destroy your data and your
> existing operating system. If you want to try AstraOS today, do it in a virtual machine.

This document exists so that the procedure is written and reviewed *before* anyone runs
it, not improvised afterwards.

---

## 1. Before installation

Work through every item. If you cannot answer one, stop and answer it.

| # | Check | Why it matters |
|---|---|---|
| 1 | Verify the ISO checksum: `sha256sum -c astraos-0.2.0-alpha-amd64.iso.sha256` | A corrupt image can fail in confusing ways, and a CDN error should not be your problem |
| 2 | The machine supports x86_64 | This release ships amd64 only |
| 3 | **Back up everything you cannot lose** to a device that will not be attached during installation | This is the only step that protects you |
| 4 | List the disks and partitions (`sudo parted -l`, `lsblk`) and write down what you see | You must be able to recognise the target disk in the installer |
| 5 | Confirm enough free space (8 GB minimum, 20 GB realistic) | The installer refuses below 8 GB |
| 6 | Research your Wi-Fi chipset and GPU | See `HARDWARE_COMPATIBILITY.md`; an unsupported Wi-Fi card means no internet |
| 7 | Know whether the machine boots in UEFI or legacy BIOS mode | Getting this wrong produces an installation that does not boot |
| 8 | Check for existing disk encryption (BitLocker, FileVault-style, LUKS) | An encrypted volume cannot simply be resized or shared |
| 9 | Decide: replace, dual-boot, or a separate disk? | These are different procedures with different risks |

### The safest first physical test

Use a **spare computer** or a **separate physical SSD** that contains nothing you need.
Then the worst case is a wasted afternoon rather than lost files.

Do not assume anything about the drive layout. AstraOS cannot know whether
`/dev/nvme0n1` is your Windows drive or an empty SSD. Neither can this document.

---

## 2. Create the installation USB

Writing an ISO to a USB drive **erases that drive entirely**.

1. Identify the drive by **size and model**, and confirm with `lsblk` that it is the one
   you think it is. Unplug other USB storage first; this removes the possibility of
   picking the wrong device.
2. Write the image:

   ```bash
   # /dev/sdX must be the USB drive you identified above. NOT a partition: no trailing "1".
   sudo dd if=astraos-0.2.0-alpha-amd64.iso of=/dev/sdX bs=4M status=progress oflag=sync
   sync
   ```

   There is deliberately no script in this repository that does this for you. A command
   that guesses which disk to overwrite is how people lose their data (plan §20).

3. On Windows, use a maintained tool such as balenaEtcher or Rufus in DD mode. Do not use
   a tool that extracts the ISO to a FAT partition; AstraOS needs a hybrid image written
   raw so that it boots in both modes.

---

## 3. Boot from the USB

1. Enter the firmware boot menu. Common keys: **F12** (Dell, Lenovo), **F10** (HP),
   **Esc** (Asus), **Option/Alt** (Apple).
2. Choose the USB device. It may appear twice, once as UEFI and once as legacy BIOS.
   Choose the one matching how you intend to install.
3. If the USB is not listed, check the firmware settings: USB boot may be disabled, or
   "Fast Boot" may be skipping external devices.
4. **Secure Boot:** the medium carries Debian's signed chain and boots under
   Secure Boot-enforcing firmware in CI (run 39028358504, 2026-10-17), but **no
   physical machine has been tried**: if the machine refuses to boot the medium, turn
   Secure Boot off. Disabling it reduces your machine's boot protection, so
   understand what you are turning off, and re-enable it if you abandon the
   installation. There is no other supported path in this release — key enrollment
   is the machine's own firmware setup's business, not a procedure this project
   documents.
5. At the GRUB menu, choose the normal entry. Use the **failsafe** entry if the screen
   stays black.

---

## 4. Installation

1. Verify you are in the **live** session: `astraos-info` reports `environment: live`.
   The desktop message of the day says the session is not persistent.
2. Start the installer.
3. **Partitioning.** This is the step that can destroy data.
   - The installer does not pre-select a disk or a scheme.
   - "Erase disk" destroys **everything** on the selected disk, including other operating
     systems and all partitions.
   - If you intend to keep an existing operating system, do **not** choose "Erase disk".
     Free space yourself beforehand, or use manual partitioning and select only the
     partitions you created.
   - Read the device name, size and model on screen and match them against the list you
     wrote down in step 1.4. Sizes match surprisingly often; **models and sizes together**
     are much harder to confuse.
4. **Users.** Choose your own password. Do not use a password you already use elsewhere.
5. **Summary.** Read the disk and filesystem one final time. This is the last point at
   which nothing has been written.
6. Only then confirm.
7. When it finishes, choose **Restart now**.

---

## 5. After installation

1. **Remove the USB drive**, or change the firmware boot order back to the internal disk.
2. Log in with the account you created.
3. Verify the system:
   - `astraos-info` reports `environment: installed`;
   - `systemctl --failed` shows no failures;
   - `sudo apt update && sudo apt full-upgrade` is needed and succeeds;
   - the display resolution and audio are correct;
   - networking works after a reboot, not just immediately after installation.
4. Confirm the disk layout is what you intended: `lsblk`, `sudo parted -l`.
5. Make a recovery backup of anything important **now**, before you have had a chance to
   break it.

---

## 6. If something goes wrong

### The machine no longer boots anything

You have almost certainly overwritten the bootloader of the other operating system.

- Boot the AstraOS medium and use `astraos-recovery-guide bootloader` for the procedure.
- To restore another operating system's bootloader, you need *its* recovery media, not
  AstraOS's. Have it ready before you start, or accept this risk.

### Wi-Fi does not work

Check `sudo dmesg | grep -i firmware` for a missing firmware file, then read
`HARDWARE_COMPATIBILITY.md`. Note that if Wi-Fi was the only network connection, you
cannot install the missing firmware without a wired connection or another machine.

### The screen is black or the wrong resolution, or the desktop did not start

Boot the failsafe entry from GRUB, then follow `TROUBLESHOOTING.md`.

### You want to go back

Reinstall your previous operating system from its own media and restore your backups. A
partition table that has been rewritten cannot be "undone" — which is why step 3.3 exists
and why the backup in step 1.3 is not optional.
