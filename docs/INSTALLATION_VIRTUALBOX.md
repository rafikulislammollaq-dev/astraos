# Testing AstraOS in VirtualBox

This is the acceptance procedure for AstraOS 0.1.0 Alpha. Its purpose is to establish
whether the release is usable **before** anyone considers installing it on a real
computer (plan §19).

Nothing in this document has been performed yet. See `KNOWN_LIMITATIONS.md` §2.

---

## 0. Before you begin

You need:

- the `astraos-0.1.0-alpha-amd64.iso` file and its `.sha256` file;
- Oracle VirtualBox 7.x;
- roughly 35 GB of free disk space;
- 4 GB of RAM you can give the virtual machine.

**Nothing in this procedure touches your host operating system.** The virtual machine
uses a virtual disk, and the installer cannot see your real drives.

---

## 1. Verify the download

```bash
sha256sum -c astraos-0.1.0-alpha-amd64.iso.sha256
```

Expected: `astraos-0.1.0-alpha-amd64.iso: OK`

If it does not say OK, **stop**. Do not boot an image that failed its checksum. Download
it again; if it fails twice, report it, because the published checksum may be wrong.

---

## 2. Create the virtual machine

**Machine → New:**

| Setting | Value | Why |
|---|---|---|
| Name | `AstraOS 0.1.0 Alpha` | — |
| ISO Image | the `.iso` you verified | VirtualBox may offer unattended installation. **Decline it** — you must run the AstraOS installer, not VirtualBox's. |
| Type | Linux | — |
| Version | Debian (64-bit) | AstraOS is Debian-based |
| Memory | 4096 MB | 2048 MB works if your host is short on RAM. The installer's minimum is 2048 MB. |
| Processors | 2 | 1 works but makes the install slow |
| Disk | 30 GB, VDI, dynamically allocated | The installer's minimum is 8 GB |

**On a resource-constrained host:** reduce memory to 2048 MB and disk to 20 GB. Do not
reduce below those values; the installer will refuse to continue, which is the correct
behaviour rather than failing halfway through.

**Verify the virtual disk was created.** Continue only when the disk appears under the
VM's Storage settings.

---

## 3. Configure the firmware mode

AstraOS ships a hybrid image, so both modes should be tested. Test them **separately**,
in separate VMs:

- **UEFI:** Settings → System → Motherboard → tick **Enable EFI**.
- **Legacy BIOS:** leave **Enable EFI** unticked.

Secure Boot is not supported. If your VirtualBox build offers it, it must be off.
Requiring Secure Boot is expected to fail, and that is a documented limitation, not a
defect to report.

---

## 4. Boot

1. Start the VM.
2. Wait for the **GRUB menu**. It should show AstraOS, a failsafe entry, and — if the VM
   has no other OS — nothing else.
3. Choose the normal entry.
4. The Plymouth splash should show the AstraOS ring, then LightDM should appear with the
   AstraOS login background.

**If GRUB never appears:** the image did not boot. Note the firmware mode, capture the
screen, and report it. Do not proceed.

**If the screen stays black after GRUB:** reboot and choose the **failsafe** entry. It
disables kernel modesetting and ACPI power management, so boot messages are visible.
Report what appears.

---

## 5. The live session

The live user is `astra` with **no password**. Select the user and press Enter.

Check, and record the result of each:

| # | Check | Expected |
|---|---|---|
| 1 | Desktop appears | Xfce with the AstraOS wallpaper |
| 2 | Panel | Top: menu, windows, tray, clock. Bottom: launcher dock and workspace pills |
| 3 | Clock shows the correct time | May be UTC; the installer sets the real timezone |
| 4 | `Ctrl+Alt+T` opens a terminal | `xfce4-terminal` |
| 5 | `astraos-info` runs | Prints the release, kernel, hardware and network summary |
| 6 | File manager opens | Thunar, with removable media visible |
| 7 | Screen resolution | 1024x768 or better; change it in Settings → Display if not |
| 8 | Mouse and keyboard | Both work, including copy and paste in the terminal |
| 9 | Network is detected | The network icon in the panel shows a connection |
| 10 | The browser opens a page | Firefox ESR loads a site (proves DNS and TLS) |
| 11 | Wallpaper and theme | The AstraOS ring wallpaper is set; window titles are readable |
| 12 | Screen lock | `Ctrl+Alt+L` locks the screen |
| 13 | The desktop's own documentation | `astraos-help` lists the offline docs |

**The live session is not persistent.** Nothing you do here survives a reboot, and the
message of the day says so.

---

## 6. Install

1. Launch **Install AstraOS** from the menu or the dock. Authenticate through the polkit
   prompt — the live user has sudo rights.
2. **Welcome:** read the storage requirement. Continue.
3. **Location and keyboard:** set both. They apply to the installed system.
4. **Partitioning — read this carefully.**
   - No disk and no scheme are pre-selected. Nothing has been written yet.
   - For a fresh VM, choose **Erase disk**. Because the disk is virtual, this is safe.
   - Confirm the disk shown is the **virtual** disk and not a host drive. If you see a
     device size that matches a real disk in your computer, **stop**.
5. **Users:** enter your own name, username and password. Do not skip the password, and
   do not reuse a password you use elsewhere.
6. **Summary:** this is the last chance to check the target disk and the filesystem.
   Confirm only when the disk is the one you intend.
7. Wait for the installation to complete. It takes a few minutes.
8. Choose **Restart now**.

---

## 7. Boot the installed system

1. **Power off the VM** if it restarted into the live session again.
2. Settings → Storage → remove the ISO from the optical drive. **This is the step people
   skip**, and then conclude the installer failed because the live session came back.
3. Start the VM.
4. GRUB should appear, then LightDM, then your account.
5. Log in with the password you chose.

Then check:

| # | Check | Expected |
|---|---|---|
| 1 | `astraos-info` | `environment` reports **installed**, not live |
| 2 | `hostname` | the name you chose during installation |
| 3 | `systemctl --failed` | no failed units |
| 4 | Your account is an administrator | `sudo -v` succeeds |
| 5 | The live account is gone | `getent passwd astra` returns nothing |
| 6 | Network works | `ip -brief addr` shows an address |
| 7 | Updates can be fetched | `sudo apt update` succeeds |
| 8 | Restart | Reboots cleanly |
| 9 | Shut down | Powers off cleanly |
| 10 | Boot again | Returns to the login screen |

---

## 8. Recording the result

Report for each check: **pass**, **fail**, or **not tested**. A "not tested" is a useful
result; an invented "pass" is not, and plan §18.3 forbids it.

Include:

- the VirtualBox version, the firmware mode (UEFI or BIOS), and the memory/CPU allocation;
- the exact step where a failure occurred;
- a screenshot if the failure is visual;
- the logs (`sudo journalctl -b -p err`, `systemctl --failed`).

Then update `docs/KNOWN_LIMITATIONS.md` §2 with the results and the date.

---

## 9. Cleaning up

Delete the VM and choose **Delete all files** so the virtual disk is removed. Nothing was
installed on your host, so there is nothing else to undo.
