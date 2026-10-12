"""Agreement between the build hooks and what this repository actually ships.

A chroot hook only ever runs on a build host, at the end of the chroot stage, after every
package has been installed. Nothing on a development machine executes one, so a hook
assertion that no longer matches the file it inspects is discovered after a full build
cycle. Both of the checks below were written after exactly that happened:

  * 0300-installer's hook required an unquoted `defaultFileSystemType: ext4`, while the
    shipped Calamares configuration is valid YAML with the value quoted. The image build
    died at the end of the chroot stage with "partition.conf does not select ext4".
  * 0700-verify required `/usr/bin/ssh` to be absent, while 50-networking.list.chroot
    deliberately selects openssh-client. No build satisfying the package selection could
    ever pass that check.

These are pins, not parsers: the pattern has to appear in the hook, and it has to hold for
the file the repository ships. A hook pattern is only as good as the file it is compared
against, and this is where the comparison happens before a runner is spent on it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

import astraos_env  # noqa: E402

DESCRIPTION = "the hooks and the files the repository ships agree with each other"

HOOKS_DIR = REPO_ROOT / "config" / "live-build" / "config" / "hooks" / "live"

# (hook file, pattern the hook must use, repository source, installed path, must match)
#
# `must match` is False for the assertions that refuse the build when the pattern IS found:
# "the default partitioning choice must not be eraseDisk" is written that way.
HOOK_ASSERTIONS: list[tuple[str, str, str, str, bool]] = [
    (
        "0300-installer.hook.chroot",
        r"^initialPartitioningChoice:[[:space:]]*eraseDisk",
        "installer/calamares/modules/partition.conf",
        "/etc/calamares/modules/partition.conf",
        False,
    ),
    (
        "0300-installer.hook.chroot",
        r"^alwaysShowPartitionLabels:[[:space:]]*true",
        "installer/calamares/modules/partition.conf",
        "/etc/calamares/modules/partition.conf",
        True,
    ),
    (
        "0300-installer.hook.chroot",
        r'^defaultFileSystemType:[[:space:]]*"?ext4"?',
        "installer/calamares/modules/partition.conf",
        "/etc/calamares/modules/partition.conf",
        True,
    ),
]

# grep(1) and Python agree on the syntax these patterns use, except for POSIX character
# classes, which are a GNU extension. Each one has to be translated explicitly, and an
# untranslated class fails the test rather than being silently ignored.
POSIX_CLASSES = {
    "[[:space:]]": r"[ \t]",
    "[[:blank:]]": r"[ \t]",
    "[[:alpha:]]": r"[A-Za-z]",
    "[[:digit:]]": r"[0-9]",
    "[[:alnum:]]": r"[A-Za-z0-9]",
}


def _as_python_pattern(pattern: str) -> str:
    for posix, python in POSIX_CLASSES.items():
        pattern = pattern.replace(posix, python)
    assert "[[" not in pattern, (
        f"{pattern!r} still contains a POSIX character class. Add it to POSIX_CLASSES so "
        "this check reads the pattern the way grep does."
    )
    return pattern


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _without_comments(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def test_the_assertions_under_test_are_actually_being_checked() -> None:
    """A table of pins that silently emptied itself would pass this module."""
    assert len(HOOK_ASSERTIONS) >= 3, (
        "fewer assertions are pinned than the installer hook contains, so part of it is "
        "not compared against anything"
    )
    assert HOOKS_DIR.is_dir(), f"the hook directory is missing: {HOOKS_DIR}"


def test_hook_assertions_match_the_files_this_repository_ships() -> None:
    problems: list[str] = []

    for hook_name, pattern, source, installed, must_match in HOOK_ASSERTIONS:
        hook_path = HOOKS_DIR / hook_name
        hook_text = _read(hook_path)
        if pattern not in hook_text:
            problems.append(
                f"{hook_name} no longer contains {pattern!r}, the assertion for {installed}. "
                "If it was reworded, reword it here too — this pin is what compares it with "
                f"the file the repository ships ({source})."
            )
            continue

        shipped = _read(REPO_ROOT / source)
        matched = re.search(_as_python_pattern(pattern), shipped, re.M) is not None
        if matched != must_match:
            expected = "match" if must_match else "not match"
            problems.append(
                f"{hook_name} requires {installed} to {expected} {pattern!r}, but {source} "
                "does not agree. The build would stop at the end of the chroot stage."
            )

    assert not problems, "hook assertions and the shipped files disagree:\n  " + "\n  ".join(
        problems
    )


def test_no_hook_asserts_the_absence_of_something_the_release_ships() -> None:
    """A hook may not forbid a binary that a package list selects on purpose.

    `openssh-client` is selected deliberately, so `/usr/bin/ssh` exists in every image
    AstraOS builds. The property the project documents is that nothing *listens* — no ssh
    server — which is what both hooks now assert. Keeping the two in step is the point of
    this test: dropping the client from the package list is a decision, and it is the only
    thing that would make an assertion about `/usr/bin/ssh` meaningful again.
    """
    packages = astraos_env.all_packages()
    client_is_selected = "openssh-client" in packages

    outdated: list[str] = []
    for hook in sorted(HOOKS_DIR.glob("*.hook.chroot")):
        body = _without_comments(_read(hook))
        if client_is_selected and re.search(r"!\s*test\s+-x\s+/usr/bin/ssh\b", body):
            outdated.append(
                f"{hook.relative_to(REPO_ROOT).as_posix()} requires /usr/bin/ssh to be "
                "absent, but 50-networking.list.chroot selects openssh-client, so no build "
                "can satisfy it"
            )

    assert not outdated, "these assertions cannot hold:\n  " + "\n  ".join(outdated)

    # The property that must stay enforced, in both places that check it.
    for hook_name in ("0500-security.hook.chroot", "0700-verify.hook.chroot"):
        body = _without_comments(_read(HOOKS_DIR / hook_name))
        assert "/usr/sbin/sshd" in body, (
            f"{hook_name} no longer checks for the ssh server. docs/SECURITY.md states that "
            "an image containing /usr/sbin/sshd is refused."
        )


PASSWORDLESS_PATTERN = r'^[[:space:]]*[^#]*NOPASSWD'

SUDO_POLICY = "packages/astraos-base/root/etc/sudoers.d/00-astraos"


def test_the_passwordless_rule_check_reads_rules_and_not_prose() -> None:
    """The policy file explains that no passwordless rule exists, and that is not a rule.

    Both hooks searched /etc/sudoers* for the word and matched the sentence that documents
    its absence, so the build was refused with "a passwordless sudo rule is present in
    /etc/sudoers.d" while the file it complained about grants nothing of the sort. The
    search has to look for a *rule*, which means ignoring anything behind a '#'.

    This pins the pattern in both hooks, checks that it does not match the shipped
    explanation, and checks that it still matches a real rule — so the guard cannot be
    weakened into something that matches nothing at all.
    """
    policy = _read(REPO_ROOT / SUDO_POLICY)
    explanation = [line for line in policy.splitlines() if line.lstrip().startswith("#") and "NOPASSWD" in line]
    assert explanation, (
        f"{SUDO_POLICY} no longer documents the absence of a passwordless rule, so this test "
        "is no longer checking the case it was written for"
    )

    for hook_name in ("0500-security.hook.chroot", "0700-verify.hook.chroot"):
        body = _without_comments(_read(HOOKS_DIR / hook_name))
        assert PASSWORDLESS_PATTERN in body, (
            f"{hook_name} no longer uses the comment-aware passwordless-rule pattern "
            f"{PASSWORDLESS_PATTERN!r}. A plain search for the word matches the explanatory "
            "comment in the shipped policy and refuses a correct image."
        )

    compiled = re.compile(_as_python_pattern(PASSWORDLESS_PATTERN))
    assert not compiled.search("\n".join(explanation)), (
        "the passwordless-rule pattern matches the comment that documents the absence of "
        "such a rule, which would fail the build"
    )
    assert compiled.search("%astra ALL=(ALL:ALL) NOPASSWD: ALL"), (
        "the passwordless-rule pattern does not match a real passwordless rule, so it would "
        "not catch the thing it exists to catch"
    )
