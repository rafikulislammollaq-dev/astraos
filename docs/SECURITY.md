# AstraOS security configuration

This document describes the security configuration that ships with AstraOS 0.1.0 and
where it is enforced. The reporting policy and the summary of claims live in
[`../SECURITY.md`](../SECURITY.md); this file is the implementation detail.

**Nothing here has been verified by a security audit.** It is a configuration baseline,
not a hardened profile.

---

## 1. Accounts and privilege

| Property | Implementation | Enforced at |
|---|---|---|
| Root login is locked | `passwd -l root`; asserted with `passwd -S root` | `0500-security.hook.chroot` |
| No passwordless sudo | `%sudo ALL=(ALL:ALL) ALL` with no `NOPASSWD` | `packages/astraos-base/root/etc/sudoers.d/00-astraos`, asserted at build time |
| Sudo is validated before it is trusted | `visudo -cf` | package postinst and the build hook |
| Sudo sessions are logged | `log_input, log_output`, `logfile=/var/log/sudo.log` | sudoers drop-in |
| No shared password | No account in the image has a fixed password | asserted at build time |
| The live user does not survive installation | `removeuser.conf`, `removeHome: true` | Calamares |
| Normal user, not root, runs the desktop | Calamares creates a normal account in the `sudo` group | `users.conf` |

The live session's user has administrative rights through sudo. That is necessary for the
installer, and it is the reason the account is removed from the installed system.

---

## 2. Services

Rationale for every service is written into the image at
`/usr/share/astraos/SERVICE-POLICY.txt` by `0400-services.hook.chroot`, in the format
`unit|intent|result|reason`, where `result` records what actually happened (including
`NOT-ENABLED` when a unit was missing — a failed enable is never recorded as a success).

**Enabled because the desktop needs them:** NetworkManager, lightdm, bluetooth, cups,
thermald, systemd-timesyncd, udisks2, upower, accounts-daemon, rsyslog, cron, avahi,
lm-sensors, ufw (policy engine only, firewall not active).

**Deliberately not enabled:** `ssh.service`, `sshd.service`, `cups-browsed.service`.

**Not installed at all:** any SSH server. The build fails if `/usr/sbin/sshd` exists.

Audit the result on an installed system with:

```bash
systemctl list-unit-files --state=enabled
```

---

## 3. Firewall

`/etc/default/ufw` ships with `DEFAULT_INPUT_POLICY="DROP"`,
`DEFAULT_OUTPUT_POLICY="ACCEPT"` and `DEFAULT_FORWARD_POLICY="DROP"`.
`/etc/ufw/astraos-policy.conf` documents the exact rules to apply.

**The firewall is not enabled by default.** Reasons:

1. Nothing listens: no SSH server, no web server, no remote administration daemon.
2. Enabling it during the live session can break the network the user needs in order to
   install.

To enable it:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow out 67,68/udp    # DHCP
sudo ufw allow out 53           # DNS
sudo ufw allow out 5353/udp     # mDNS
sudo ufw enable
sudo ufw status verbose
```

Those outbound allowances exist because a default-deny *outbound* policy breaks DHCP, DNS
and local discovery — the failure mode plan §13.4 warns about.

---

## 4. Updates and package authenticity

`/etc/apt/apt.conf.d/60-astraos-security` sets:

```
APT::Get::AllowUnauthenticated "false";
Acquire::AllowInsecureRepositories "false";
Acquire::AllowDowngradeToInsecureRepositories "false";
APT::Sandbox::Seccomp "true";
```

Repositories are the authenticated Debian archives over the official mirror
(`config/live-build/config/archives/astraos.list.chroot`). No third-party repository,
PPA, or unsigned source is added, and backports are excluded so a released image cannot
silently pick up a newer ABI from an unrelated suite.

The live-build stage passes `APT::Get::AllowUnauthenticated=false` on the command line, and
a build-time assertion fails if any file under `/etc/apt/` sets it to `true`.

**Note:** AstraOS's own five packages are local `.deb` files with no repository and no
signature. This is acceptable for an alpha, and it is recorded in
`KNOWN_LIMITATIONS.md` §3.7 — it must change before a stable release.

---

## 5. Kernel and network defaults

`/etc/sysctl.d/60-astraos.conf`, installed by `astraos-base`:

- kernel information exposure restricted (`dmesg_restrict`, `kptr_restrict`,
  `perf_event_paranoid=2`, `unprivileged_bpf_disabled`);
- ptrace restricted to direct descendants;
- core dumps disabled (`kernel.core_pattern=|/bin/false`, `fs.suid_dumpable=0`);
- address space randomisation at the upstream default;
- IPv4/IPv6 spoofing and redirect protection;
- `fs.protected_hardlinks` and `fs.protected_symlinks`;
- `fs.inotify.max_user_watches` raised for editors and indexers.

These are conservative, long-standing desktop defaults. None is a security boundary on
its own, and `ptrace_scope=1` can interfere with some debuggers.

---

## 6. Boot path

| Property | Status |
|---|---|
| Secure Boot | **Not supported and not claimed.** Disabled in the live boot configuration. |
| UEFI | Targeted; `shim` and signed GRUB are installed, but the path is unverified |
| Legacy BIOS | Targeted; unverified |
| Boot integrity measurement | None |
| Boot splash hiding failures | Mitigated: the failsafe entry drops `quiet splash` and disables modesetting and ACPI power management |

`shim-signed` being installed does **not** mean Secure Boot works. It has not been tested
on any machine, and `KNOWN_LIMITATIONS.md` §1.2 says so explicitly.

---

## 7. Secrets

- The repository is scanned for private keys, cloud keys, API tokens and password
  assignments by `tests/static/test_repository.py`.
- The image build scans `/etc` for private keys and fails if one is found
  (`0500-security.hook.chroot`).
- No credentials, keys or tokens are committed, embedded in the ISO, or passed to CI.
- `astraos-info` and the other utilities deliberately do not read `/etc/shadow`,
  NetworkManager connection profiles, keyrings, or environment variables that commonly
  hold tokens.
- Passwords are handled only by sudo, LightDM and Calamares; AstraOS tooling never reads
  or writes one.

---

## 8. What is not done

- No audit, no penetration test, no fuzzing.
- No integrity measurement or verified boot.
- No mandatory access control (no AppArmor or SELinux profile set beyond Debian's defaults).
- No AstraOS package signing.
- No independent security team and no stated response time beyond the 7-day
  acknowledgement in `../SECURITY.md`.
- Disk encryption is available through Calamares but **has not been tested**.
