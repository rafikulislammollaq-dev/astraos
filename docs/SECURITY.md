# AstraOS security configuration

This document describes the security configuration that ships with AstraOS and
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
lm-sensors, ufw (the inbound firewall itself; on from boot — §3).

**Enabled only where the hypervisor is:** `open-vm-tools.service` — the unit is
conditioned on VMware (`ConditionVirtualization=vmware`) and skips itself on every other
machine. The QEMU and SPICE guest agents need no entry here at all: their packages' udev
rules start them when their virtio ports appear (`60-qemu-guest-agent.rules`,
`70-spice-vdagentd.rules`) and nowhere else. All four packages ship in every image
(`config/package-lists/35-hardware.list.chroot`); `0700-verify` asserts the binaries,
units and rules.

**Deliberately not enabled:** `ssh.service`, `sshd.service`, `cups-browsed.service`.

**Not installed at all:** any SSH server. The build fails if `/usr/sbin/sshd` exists. The
*client* is installed (`openssh-client`, selected in `config/package-lists/50-networking.list.chroot`)
so that a user can reach their own machines; it listens on nothing and runs no service.

Audit the result on an installed system with:

```bash
systemctl list-unit-files --state=enabled
```

---

## 3. Firewall

The host firewall is **on by default** (decided 2026-10-16; `docs/ROADMAP.md`).
`/etc/default/ufw` ships `DEFAULT_INPUT_POLICY="DROP"`, `DEFAULT_OUTPUT_POLICY="ACCEPT"`
and `DEFAULT_FORWARD_POLICY="DROP"`; `/etc/ufw/ufw.conf` sets `ENABLED=yes`; and the
exceptions that exist live in `/etc/ufw/user.rules` and `/etc/ufw/user6.rules`, explained
rule by rule in `/etc/ufw/astraos-policy.conf`:

- **`8765/tcp`, the assistant's page**, from the private ranges (`192.168.0.0/16`,
  `10.0.0.0/8`, `172.16.0.0/12`, and `fc00::/7`, `fe80::/10`). On the machine itself the
  page needs no pairing; from the network it answers `401` until a phone pairs with the
  six-digit code shown on the computer, so what the LAN can reach is an authentication
  surface, not data.
- **`5353/udp`, mDNS**, from the same ranges: the avahi traffic that finds printers. A
  firewall that silently breaks printing is a firewall the user turns off.

Everything else inbound is dropped (and logged, `LOGLEVEL=low`); outbound is allowed;
forwarding is denied. DHCP replies are allowed by ufw's own `before.rules`
(`--sport 67 --dport 68`), so the old concern — an active firewall breaking the network
the live session needs — does not hold; it was the reason earlier releases left it off.

**Where this is proven.** The boot self-test checks that ufw reports active, that the
default incoming policy is deny, and that the page's rule is loaded, and the phone
exercise doubles as the proof that the allowed path works *while* the firewall is up.
The stronger, behavioural half: the guest watches a port that no rule allows while the
caller deliberately probes it from outside — with the firewall on, nothing may arrive,
and the guest fails its own check if anything does (the exercise was added 2026-10-16;
its first CI run was pending at the time of writing). The build's security hook refuses
to build an image where the rule files or `ENABLED=yes` disappear.

Global IPv6 addresses are not covered by the shipped rules. `KNOWN_LIMITATIONS.md` §3.5
records that, and widening is one documented command (`sudo ufw allow 8765/tcp`).

---

## 4. Updates and package authenticity

`/etc/apt/apt.conf.d/60-astraos-security` sets:

```
APT::Get::AllowUnauthenticated "false";
Acquire::AllowInsecureRepositories "false";
Acquire::AllowDowngradeToInsecureRepositories "false";
APT::Sandbox::Seccomp "true";
```

Repositories are the authenticated Debian archives over the official mirror: the pinned
release suite is generated by live-build from the mirror options in
`config/live-build/auto/config`, and `config/live-build/config/archives/astraos.list.chroot`
pins the update and security suites by name. No third-party repository,
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
| Secure Boot | **Boots under enforcing firmware in CI** (run 39028358504, 2026-10-17: OVMF's Secure Boot firmware with the Microsoft keys enrolled verified the chain — Microsoft-signed shim, Debian-signed GRUB and kernel — and the live system reached its login prompt). Physical hardware and the installed system under Secure Boot remain untested. |
| UEFI | Targeted; CI boots the ISO through the GRUB menu under QEMU's firmware (run 38913161772) and under enforcing Secure Boot firmware (run 39028358504); real machines remain untested |
| Legacy BIOS | Targeted; unverified |
| Boot integrity measurement | None |
| Boot splash hiding failures | Mitigated: the failsafe entry drops `quiet splash` and disables modesetting and ACPI power management |

`shim-signed` being installed does **not** by itself mean Secure Boot works — but the
chain is no longer merely carried: CI verified it under enforcement (run 39028358504,
2026-10-17, `scripts/boot-menu-test.sh --medium secure`), with the firmware pair and its
checksums kept beside the serial log. No physical machine has verified it, and the
installed system under Secure Boot is untested; `KNOWN_LIMITATIONS.md` §1.2 says exactly
that.

---

## 7. Secrets

- The repository is scanned for private keys, cloud keys, API tokens and password
  assignments by `tests/static/test_repository.py`. The private-key pattern recognises the
  shape of an armored block (a bare header line followed within a few lines by base64
  payload or by the matching footer) rather than the header text, so documentation, a
  magic(5) entry and a parser constant are not reported as keys.
- The image build runs `astraos-scan-secrets` and refuses to build when it finds an armored
  private key (`0500-security.hook.chroot`, tool shipped in `astraos-base`). It scans
  `/etc`, `/root`, `/home`, `/srv`, `/opt`, `/usr/local`, `/var/lib` and
  `/usr/share/astraos`, and the hook fails if the tool is missing from the image, so a
  scanner that is not there cannot pass as a clean image.
- The scan tests for the *shape* of a key rather than for the armor header text: a line that
  is exactly an armor header, followed before the block ends by the matching footer or by
  base64 payload. Files that merely name the format — a magic(5) entry, a compiled-in parser
  constant, a documentation line — are printed as notes instead of failing the build, and
  every match is printed with its path and its dpkg owner. That distinction has a build
  behind it: the earlier text search failed a real build on a Debian data file and reported
  the pattern it had searched for instead of the file that matched.
- Recognised forms: the PGP armors (including the pre-2.0 `PGP SECRET KEY` spelling),
  PKCS#1, PKCS#8 (`-----BEGIN PRIVATE KEY-----`), encrypted PKCS#8, OpenSSH and SSH2. What
  the scan cannot see is recorded in `KNOWN_LIMITATIONS.md` §3.14.
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
