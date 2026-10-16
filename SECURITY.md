# AstraOS security policy

## Reporting a vulnerability

**Do not open a public issue for a security defect.**

Report privately through the project's security contact:

- **Email:** security@astraos.invalid *(placeholder — see "Before this goes public"
  below)*
- **Expected response:** an acknowledgement within 7 days.
- **Disclosure:** please allow 90 days before public disclosure, or less by agreement if
  a fix ships sooner.

### Before this goes public

The contact addresses in this document and throughout the repository use the reserved
`.invalid` domain, which cannot resolve. That is deliberate: inventing a real-looking
address would be worse than an obvious placeholder. **Before any public release, real
contact addresses must be configured**, and this section removed.

## What to include

A useful report contains:

- the AstraOS version (`astraos-info --json` reports it, including the release stage);
- the base release your build came from, if you built it yourself;
- what you did, what happened, and what you expected;
- the smallest reproduction you can manage;
- relevant logs: `sudo journalctl -b -p err`, `systemctl --failed`.

**Never include** passwords, private keys, Wi-Fi configuration files containing network
keys, or screenshots of credential dialogs.

## Scope

In scope:

- the AstraOS packages (`packages/astraos-*`) and the build system (`scripts/`,
  `config/`, `installer/`);
- the AstraOS security configuration: sudo policy, sysctl defaults, APT policy, ufw
  policy, service policy;
- the installer configuration, **especially** anything that could cause data loss on a
  disk the user did not select;
- anything that lets a local user escalate to root without a password prompt.

Out of scope (report these upstream):

- defects in the Linux kernel, Xfce, LightDM, Calamares, GRUB, Firefox or any other
  included component, unless the defect is caused by AstraOS configuration;
- Debian package security, which the Debian Security Team tracks and which AstraOS
  receives through `trixie-security`.

## Security properties AstraOS 0.1.0 actually provides

These are implemented and asserted at build time. They are modest, and that is the
point: it is better to state six things that are true than twenty that are aspirational.

| Property | How it is enforced |
|---|---|
| Root login is locked in the image | `passwd -l root` at build time; asserted by `0500-security.hook.chroot` |
| No passwordless sudo | `/etc/sudoers.d/00-astraos` contains no `NOPASSWD`; the build fails if any appears |
| No shared password | No account in the image has a fixed password; asserted at build time |
| No remote administration daemon | No SSH server is installed; asserted at build time |
| APT signature verification is never disabled | Explicit policy file plus a build-time assertion |
| Kernels/network defaults hardened | `/etc/sysctl.d/60-astraos.conf` |
| No secrets in the repository or the image | Test suite scans the repository; the build scans `/etc` |
| Screen locks by default | Xfce session defaults: blank after 10 minutes, lock after 15 |
| Inbound firewall on by default | ufw with `ENABLED=yes`; only the assistant's page (`8765/tcp`) and mDNS (`5353/udp`) from private ranges; asserted at build time |

## Security limitations — read these

AstraOS 0.1.0 Alpha is **not** a hardened system, and the project makes no claim that it
is. Specifically:

1. **No security audit has been performed.** Not by an external party, not internally.
2. **The firewall's inbound exceptions cover private address ranges only.** The
   firewall itself is on by default (docs/SECURITY.md §3), but the assistant's page and
   mDNS are scoped to `192.168.0.0/16`, `10.0.0.0/8`, `172.16.0.0/12`, `fc00::/7` and
   `fe80::/10`; a network with public IPv6 addresses needs `sudo ufw allow 8765/tcp`
   (docs/KNOWN_LIMITATIONS.md §3.5).
3. **Disk encryption is available through Calamares but has not been tested.** Never
   assume a system is encrypted unless you chose encryption during installation and can
   confirm it with `lsblk` and `cryptsetup status`.
4. **Secure Boot is not supported.** It is disabled in the live image's boot
   configuration, and the boot path has not been verified under Secure Boot.
5. **Updates depend on Debian's security archive.** AstraOS has no independent security
   team. Realistically: AstraOS inherits Debian's response times for components it takes
   from Debian, and the AstraOS-specific packages in this repository are the project's
   own responsibility.
6. **The alpha release has not been fuzzed, and no penetration test has been done.**
7. **`main` is not a stable branch.** Build from a release tag if you need reproducible
   software.

## Update guidance

```bash
sudo apt update
sudo apt full-upgrade
```

Read the output before confirming. AstraOS does not run upgrades for you, and
`unattended-upgrades` is installed but not configured to reboot the system.

For a kernel update, confirm that an initramfs exists for the new kernel before
rebooting (`ls -l /boot/`), and keep the previous kernel until the new one boots
successfully. `docs/RECOVERY.md` covers what to do when it does not.
