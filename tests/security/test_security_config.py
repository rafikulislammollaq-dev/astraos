"""Security configuration assertions.

These check the *source* of the security baseline, so a weakening change fails here in
seconds rather than requiring a Linux build. The build hooks assert the same properties
inside the image; the duplication is deliberate. The hooks prove what shipped; these prove
what the repository says, and either alone leaves a gap.

Assertions ignore comment lines. Several of these files legitimately document the rule
they are enforcing (for example "no NOPASSWD rule is present"), and a naive grep would
match the explanation.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "lib"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

import astraos_env  # noqa: E402
from astraos_testlib import read, strip_comments  # noqa: E402

DESCRIPTION = "the security baseline is enforced in the shipped configuration"

SUDOERS = "packages/astraos-base/root/etc/sudoers.d/00-astraos"
APT_POLICY = "packages/astraos-base/root/etc/apt/apt.conf.d/60-astraos-security"
UFW_DEFAULTS = "system/security/astraos-firewall.default"
UFW_CONF = "system/security/astraos-ufw.conf"
UFW_RULES = "system/security/astraos-ufw-user.rules"
UFW_RULES6 = "system/security/astraos-ufw-user6.rules"
SYSCTL = "system/sysctl/60-astraos.conf"
SECURITY_HOOK = "config/live-build/config/hooks/live/0500-security.hook.chroot"
CLEANUP_HOOK = "config/live-build/config/hooks/live/0600-cleanup.hook.chroot"
IDENTITY_HOOK = "config/live-build/config/hooks/live/0100-identity.hook.chroot"
REMOVEUSER = "installer/calamares/modules/removeuser.conf"
USERS_CONF = "installer/calamares/modules/users.conf"
GREETER_DROPIN = "branding/lightdm/lightdm.conf.d/50-astraos.conf"
LOCKDOWN = "installer/calamares/modules/shellprocess.conf"
ASTRAOS_INFO = "packages/astraos-base/root/usr/bin/astraos-info"
ASTRA_DOCTOR = "packages/astraos-winbridge/root/usr/bin/astra"
SCAN_SECRETS = "packages/astraos-base/root/usr/bin/astraos-scan-secrets"


def test_sudo_policy_has_no_passwordless_rule() -> None:
    """No NOPASSWD. This is the single most important line in the file."""
    active = strip_comments(read(SUDOERS))
    assert "NOPASSWD" not in active, (
        "the shipped sudo policy contains a passwordless rule. AstraOS must never ship "
        "passwordless privilege escalation (plan §10.4, §13.1)."
    )
    assert "%sudo ALL=(ALL:ALL) ALL" in active, (
        "the sudoers file does not grant the sudo group the normal password-prompting "
        "grant, so administrators would have no privilege escalation at all"
    )


def test_sudo_policy_enables_logging() -> None:
    """Administrative actions must be auditable."""
    active = strip_comments(read(SUDOERS))
    assert "log_input" in active and "log_output" in active, (
        "sudo command logging is not enabled, so administrative actions leave no record"
    )


def test_apt_signature_verification_is_never_disabled() -> None:
    """No setting may enable unauthenticated packages."""
    policy = read(APT_POLICY)
    assert 'AllowUnauthenticated "false"' in policy, (
        "the APT policy does not explicitly disable unauthenticated packages"
    )

    offenders = [
        line for line in strip_comments(policy).splitlines()
        if re.search(r'AllowUnauthenticated\s+"true"', line)
        or re.search(r'AllowInsecureRepositories\s+"true"', line)
    ]
    assert not offenders, (
        "the APT policy enables insecure packages:\n  " + "\n  ".join(offenders)
    )


def test_no_package_list_selects_a_remote_access_daemon() -> None:
    """AstraOS ships no remote administration daemon, and documents that as a property."""
    packages = astraos_env.all_packages()
    for forbidden in ("openssh-server", "openssh-sftp-server", "dropbear", "dropbear-initramfs",
                      "tigervnc-standalone-server", "x11vnc", "vino", "xrdp"):
        assert forbidden not in packages, (
            f"{forbidden} is selected. docs/SECURITY.md states that AstraOS 0.1.0 installs "
            "no listening remote-access service; adding one contradicts that claim."
        )


def test_firewall_defaults_deny_inbound() -> None:
    """The shipped ufw defaults must deny inbound and forward."""
    defaults = read(UFW_DEFAULTS)
    assert re.search(r'^DEFAULT_INPUT_POLICY="DROP"', defaults, re.M), (
        "the firewall defaults do not deny inbound connections"
    )
    assert re.search(r'^DEFAULT_OUTPUT_POLICY="ACCEPT"', defaults, re.M), (
        "the firewall defaults do not allow outbound connections, which would break "
        "browsing and updates"
    )
    assert re.search(r'^DEFAULT_FORWARD_POLICY="DROP"', defaults, re.M), (
        "the firewall defaults do not deny forwarding"
    )


def test_firewall_state_is_documented_where_it_is_configured() -> None:
    """The firewall is on by default (2026-10-16); the files must say so together.

    The defaults file explains why, ufw.conf carries the switch and the rule files
    carry the exceptions. A reader of any one of them must be able to find the others.
    """
    defaults = read(UFW_DEFAULTS)
    assert "enabled by default" in defaults, (
        "the ufw defaults do not state that the firewall is enabled by default, so a "
        "reader could reasonably assume nothing was decided"
    )
    assert "/etc/ufw/ufw.conf" in defaults and "user.rules" in defaults, (
        "the defaults file no longer points at the state file and the rules, so the "
        "explanation and the implementation can drift apart unnoticed"
    )
    enabled = read(UFW_CONF)
    assert re.search(r"^ENABLED=yes$", enabled, re.M), (
        "the shipped ufw.conf does not start the firewall on boot; the default-on "
        "decision would exist in the documentation and nowhere else"
    )
    for path in (UFW_RULES, UFW_RULES6):
        rules = read(path)
        assert "--dport 8765" in rules, (
            f"{path} lost the assistant's page rule, so a phone on the local network "
            "would be refused by the firewall the release itself ships"
        )


def test_firewall_rules_accept_only_the_documented_exceptions() -> None:
    """The two exceptions are the whole inbound story; nothing else may be ACCEPTed.

    The rules the release ships are the strongest part of the decision, so they are
    pinned from the source: port, protocol and source range of every ACCEPT line, and
    a matching `### tuple ###` for each rule - that is the form `ufw` itself reads and
    rewrites, so a hand-edit that breaks it would silently lose the rule the next time
    `ufw` touches the file.
    """
    expected = {
        ("tcp", "8765"): {"192.168.0.0/16", "10.0.0.0/8", "172.16.0.0/12"},
        ("udp", "5353"): {"192.168.0.0/16", "10.0.0.0/8", "172.16.0.0/12"},
    }
    expected6 = {
        ("tcp", "8765"): {"fc00::/7", "fe80::/10"},
        ("udp", "5353"): {"fc00::/7", "fe80::/10"},
    }
    for path, wanted, chain in (
        (UFW_RULES, expected, "ufw-user-input"),
        (UFW_RULES6, expected6, "ufw6-user-input"),
    ):
        rules = read(path)
        accepted = [
            line for line in rules.splitlines()
            if line.startswith(f"-A {chain} ") and "-j ACCEPT" in line
        ]
        assert accepted, f"{path} has no ACCEPT rules at all"
        found: dict[tuple[str, str], set[str]] = {}
        for line in accepted:
            port = re.search(r"--dport ([0-9]+)", line)
            proto = re.search(r"-p (tcp|udp)", line)
            source = re.search(r"-s (\S+)", line)
            assert port and proto and source, f"{path}: unparsable ACCEPT line {line!r}"
            key = (proto.group(1), port.group(1))
            assert key in wanted, (
                f"{path} accepts {key} - only the assistant's page (8765/tcp) and "
                "mDNS (5353/udp) are the documented exceptions"
            )
            found.setdefault(key, set()).add(source.group(1))
            assert f"### tuple ### allow {key[0]} {key[1]} " in rules, (
                f"{path}: {line!r} has no matching ufw tuple comment; ufw's own parser "
                "reads the tuples, and a rule without one would be lost the first time "
                "`ufw` rewrites the file"
            )
        assert found == wanted, (
            f"{path} exceptions are {sorted(found)}, expected {sorted(wanted)}; the "
            "documented policy and the shipped rules have drifted apart"
        )


def test_kernel_hardening_settings_are_present() -> None:
    """The documented sysctl hardening must actually be configured."""
    sysctl = read(SYSCTL)
    required = {
        "kernel.dmesg_restrict": "restricts kernel log access",
        "kernel.kptr_restrict": "restricts kernel address exposure",
        "kernel.unprivileged_bpf_disabled": "blocks unprivileged eBPF",
        "kernel.perf_event_paranoid": "restricts the performance events interface",
        "kernel.yama.ptrace_scope": "restricts ptrace",
        "fs.suid_dumpable": "prevents setuid core dumps",
        "net.ipv4.tcp_syncookies": "enables SYN cookie protection",
        "fs.protected_hardlinks": "blocks hardlink attacks",
        "fs.protected_symlinks": "blocks symlink attacks",
    }
    missing = [f"{key} ({why})" for key, why in required.items() if key not in sysctl]
    assert not missing, (
        "the sysctl file is missing settings the documentation claims:\n  "
        + "\n  ".join(missing)
    )


def test_build_locks_the_root_account() -> None:
    """The build must disable root login, and must verify that it did."""
    hook = read(SECURITY_HOOK)
    assert "passwd -l root" in hook, "the build does not lock the root account"
    assert re.search(r"passwd -S root", hook), (
        "the build locks root but never verifies it, so a failure would be silent"
    )


def test_build_fails_on_embedded_credentials() -> None:
    """The image build must refuse to ship a private key, and must be able to say why.

    The check lives in a shipped tool (`test_secret_scan.py` runs it against fixture trees)
    rather than in this hook, because the version that lived here failed a real build on a
    file that merely names the armor format and printed the pattern instead of the path.
    What this hook has to do is fail when the tool fails, and refuse to run at all when the
    tool is not in the image.
    """
    hook = read(SECURITY_HOOK)
    assert "/usr/bin/astraos-scan-secrets" in hook, (
        "the build does not scan the image for private keys"
    )
    assert re.search(r"^\s*if !\s+\S*astraos-scan-secrets", hook, re.M), (
        "the build runs the credential scan but does not fail when it finds something, so "
        "an embedded key would only appear in the log"
    )
    assert re.search(r"^\s*if \[ ! -x \S*astraos-scan-secrets \]", hook, re.M), (
        "the hook does not check that the scanner is present. If astraos-base were replaced "
        "by a version without the tool, a missing scanner would look like a clean image."
    )

    tool = read(SCAN_SECRETS)
    for kind in ("PRIVATE", "SECRET"):
        assert kind in tool, (
            f"the scanner's key patterns do not mention {kind}, so a whole family of keys "
            "would be invisible"
        )


def test_machine_identity_is_reset_for_each_installation() -> None:
    """A cloned machine-id is a real defect: DHCP identity and systemd services break."""
    hook = read(CLEANUP_HOOK)
    assert "/etc/machine-id" in hook, (
        "the cleanup hook does not clear /etc/machine-id, so every installation from this "
        "image would share one machine identity"
    )
    assert "ssh_host_" in hook, (
        "the cleanup hook does not remove pre-generated SSH host keys"
    )


def test_live_account_is_removed_from_installed_systems() -> None:
    """The live account must not survive installation, and its name must match."""
    config = astraos_env.distribution()
    live_user = config["ASTRAOS_LIVE_USER"]
    removeuser = read(REMOVEUSER)

    assert f"username: {live_user}" in removeuser, (
        f"removeuser.conf does not remove the live account {live_user!r}. An account with "
        "sudo rights and no password must not exist on an installed system."
    )
    assert "removeHome: true" in removeuser, (
        "removeuser.conf leaves the live user's home directory behind"
    )


def test_installer_never_enables_autologin() -> None:
    """AstraOS must not log a user in without authentication."""
    users_conf = read(USERS_CONF)
    assert re.search(r"^doAutologin:\s*false", users_conf, re.M), (
        "users.conf does not disable autologin"
    )
    assert "doAutologin: true" not in strip_comments(users_conf), (
        "users.conf enables autologin, which would bypass authentication at the greeter"
    )

    greeter = read(GREETER_DROPIN)
    # 0.2.1 moved the lock-down out of this file and into the installer. The drop-in
    # ships inside the live image as well, and live-config arranges the live medium's
    # autologin by editing the commented autologin keys in /etc/lightdm/lightdm.conf
    # while the medium boots; a drop-in that cleared autologin-user cancelled that, so
    # a 0.2.0 live boot could stop at the greeter and ask for a password the user had
    # never been given. The rule this test exists for is asserted where it now lives.
    assert not re.search(r"^autologin-user=", strip_comments(greeter), re.M), (
        "the greeter drop-in sets autologin-user again. The same file is copied into "
        "the live image, where that key cancels the autologin live-config arranges, so "
        "a live boot would stop at a password prompt."
    )
    assert "allow-guest=false" in greeter, "the greeter drop-in does not disable guest sessions"

    # The half of the policy that survives onto the disk is the installer's job: it
    # runs on the target after unpackfs, where the live autologin can be undone.
    lockdown = read(LOCKDOWN)
    assert re.search(r"^[ \t]*autologin-user=[ \t]*$", lockdown, re.M), (
        "the installer's lock-down step does not clear autologin-user, so the live "
        "session's autologin would follow the installation onto the disk"
    )
    assert re.search(r"^[ \t]*autologin-session=[ \t]*$", lockdown, re.M), (
        "the installer's lock-down step does not clear autologin-session"
    )
    assert re.search(r"^[ \t]*autologin-user-timeout=0[ \t]*$", lockdown, re.M), (
        "the installer's lock-down step does not set autologin-user-timeout to 0"
    )
    assert "#autologin-user=" in lockdown, (
        "the installer's lock-down step does not neutralise the autologin that "
        "live-config wrote into /etc/lightdm/lightdm.conf; the installer copies that "
        "file onto the disk verbatim"
    )
    assert "*live*.conf" in lockdown, (
        "the installer's lock-down step does not remove live-only LightDM drop-ins "
        "from the target"
    )


def test_installer_ships_no_fixed_credentials() -> None:
    """No pre-filled username, name, email or password in the installer config.

    The value is matched with [^\s] after a horizontal-only gap on purpose. Using `\s*`
    would let the pattern step over a newline, so a YAML block header such as
    `username:` followed by an indented `maxLength:` on the next line would look like
    `username: maxLength:` and read as a preset value. That is a false positive, and a
    false positive in a security check trains people to ignore it.
    """
    active = strip_comments(read(USERS_CONF))
    for key in ("password", "username", "fullName", "email"):
        match = re.search(rf"^{key}:[ \t]*(\S+)", active, re.M)
        if match:
            raise AssertionError(
                f"users.conf sets {key} to {match.group(1)!r}. AstraOS must not ship fixed "
                "or pre-filled credentials (plan §10.4)."
            )

    # The block-header forms must still be present, so this test cannot pass merely
    # because the whole section was deleted.
    assert re.search(r"^username:[ \t]*$", active, re.M), (
        "users.conf has no username validation block, so the check above proves nothing"
    )


def test_hooks_do_not_install_package_owned_paths() -> None:
    """Architectural invariant: files a package can own must not be written by a hook.

    The identity hook exists for paths owned by other Debian packages as conffiles. If a
    future hook starts writing something astraos-base already owns, packaging and the
    hook would fight each other, and dpkg would report local modifications.
    """
    # Comments are stripped first. The hook's own header legitimately names the package
    # owned paths (to explain why it does not write them), and matching prose would make
    # this test fail for the wrong reason.
    active = strip_comments(read(IDENTITY_HOOK))

    package_owned = [
        "/etc/astraos-release",
        "/etc/sysctl.d/60-astraos.conf",
        "/etc/sudoers.d/00-astraos",
        "/etc/apt/apt.conf.d/60-astraos-security",
    ]

    conflicts = []
    for line in active.splitlines():
        stripped = line.strip()
        if not stripped.startswith("install_file"):
            continue
        for path in package_owned:
            if stripped.endswith(path) or f"{path} " in stripped:
                conflicts.append(f"{path} written by: {stripped}")

    assert not conflicts, (
        "the identity hook installs files the astraos-base package owns, so packaging and "
        "the hook would fight each other:\n  " + "\n  ".join(conflicts)
    )


def _reported_firewall_state(ufw_first_line: str) -> str:
    """Run the real astraos-info with a stub ufw on PATH; return its firewall line.

    The tool is executed rather than read because the defect this guards against was a
    pattern-order bug in a shell `case`: the source looks correct to a reviewer, and only
    running it showed that "Status: inactive" was reported as active.
    """
    shell = shutil.which("bash") or shutil.which("sh")
    assert shell, "no shell interpreter is available to run astraos-info"

    with tempfile.TemporaryDirectory() as temporary:
        stub_dir = Path(temporary)
        ufw = stub_dir / "ufw"
        ufw.write_text(f'#!/bin/sh\nprintf \'%s\\n\' "{ufw_first_line}"\n', encoding="utf-8")
        ufw.chmod(0o755)

        environment = dict(os.environ)
        environment["PATH"] = f"{stub_dir}{os.pathsep}{environment.get('PATH', '')}"

        completed = subprocess.run(
            [shell, str(REPO_ROOT / ASTRAOS_INFO)],
            capture_output=True, text=True, env=environment, timeout=120,
        )

    assert completed.returncode == 0, (
        f"astraos-info failed with a stub ufw on PATH:\n{completed.stderr.strip()}"
    )

    match = re.search(r"^[ \t]*firewall[ \t]+(\S.*)$", completed.stdout, re.M)
    assert match, (
        "astraos-info printed no firewall line, so this test cannot tell what it claims:\n"
        + completed.stdout
    )
    return match.group(1).strip()


def test_reported_firewall_state_is_never_overclaimed() -> None:
    """`astraos-info` must not report an inactive firewall as active.

    This is not hypothetical. The patterns were `*active*` and `*inactive*`, and a bare
    `*active*` also matches "Status: inactive"; because case takes the first match, an
    install of the release before 2026-10-16 — when ufw was shipped disabled by design —
    reported `firewall active`. That is a false security claim shown to the user, and a
    security review would have to trust it.
    """
    inactive = _reported_firewall_state("Status: inactive")
    active = _reported_firewall_state("Status: active")
    unprivileged = _reported_firewall_state("ERROR: You need to be root to run this script")

    assert inactive.startswith("inactive"), (
        f"astraos-info reports {inactive!r} for an inactive firewall; a user would be told "
        "the firewall is protecting them when it is not"
    )
    assert "sudo ufw enable" in inactive, (
        "the inactive message no longer says how to turn the firewall back on. The "
        "firewall is on by default since 2026-10-16, so an inactive one means someone "
        "turned it off; the report has to hand the user the way back."
    )
    assert "default" not in inactive, (
        f"astraos-info reports {inactive!r} for an inactive firewall, which still reads "
        "as if being off were what the release ships; it was the default only until "
        "2026-10-16, and the report is now false"
    )
    assert active == "active", f"astraos-info reports {active!r} for an active firewall"
    assert unprivileged.startswith("unknown"), (
        f"astraos-info reports {unprivileged!r} when ufw cannot be queried, so the "
        "fallback branch is unreachable or misordered"
    )


def test_astra_doctor_anchors_the_firewall_state_like_astraos_info() -> None:
    """`astra doctor` carried the same unanchored `*active*` pattern.

    "Status: inactive" contains "active"; reporting a firewall that is off as
    protection is a false claim whether it is the shipped default or a state the user
    chose. The two tools must read the state the same anchored way, and this test keeps
    them from drifting apart again.
    """
    text = read(ASTRA_DOCTOR)
    assert '"Status: active"*' in text, (
        "astra doctor no longer anchors its active pattern, so an inactive firewall "
        "would be reported as active"
    )
    assert '*"active"*' not in text, (
        'astra doctor is back to the unanchored *"active"* pattern, which also matches '
        '"Status: inactive"'
    )
    assert "sudo ufw enable" in text, (
        "astra doctor no longer tells the user how to bring the firewall back when it "
        "is not active; the release starts it on, so the way back is the whole message"
    )
