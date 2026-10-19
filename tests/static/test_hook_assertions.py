"""Agreement between the build hooks and what this repository actually ships.

A chroot hook only ever runs on a build host, at the end of the chroot stage, after every
package has been installed. Nothing on a development machine executes one, so a hook
assertion that no longer matches the file it inspects is discovered after a full build
cycle. The checks below were written after exactly that happened:

  * 0300-installer's hook required an unquoted `defaultFileSystemType: ext4`, while the
    shipped Calamares configuration is valid YAML with the value quoted. The image build
    died at the end of the chroot stage with "partition.conf does not select ext4".
  * 0700-verify required `/usr/bin/ssh` to be absent, while 50-networking.list.chroot
    deliberately selects openssh-client. No build satisfying the package selection could
    ever pass that check.
  * 0700-verify required /etc/os-release to declare "0.1.0" as a written-out literal, while
    config/distribution.env had moved to 0.2.0. Every package built and 47 other assertions
    passed; the image was refused because the version had been raised.
  * 0300-installer's password-requirement check used `grep -A4E`; GNU grep reads that as
    `-A 4E` ("invalid context length argument"), the error went to /dev/null, and the
    assertion refused run 38909791960's image, whose packages and other assertions were
    all in place. The check is two plain greps now, and
    test_no_hook_passes_an_attached_flag_after_a_context_flag refuses the shape.

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
# Every entry is a pattern the hook searches FOR in a file it must find it in, so
# `must match` is True for all of them now. The disk-safety assertion used to be the one
# written the other way round - refusing the build when `eraseDisk` was present - and that
# is the shape that let run 39222797247 happen: `eraseDisk` is not a value Calamares has
# (an unknown name falls back to the first entry of Config::installChoiceNames(), which is
# `none`, silently), so the assertion could never fire and the choice it guarded was never
# made. The hook now requires the value to BE `none`.
HOOK_ASSERTIONS: list[tuple[str, str, str, str, bool]] = [
    (
        "0300-installer.hook.chroot",
        r"^initialPartitioningChoice:[[:space:]]*none",
        "installer/calamares/modules/partition.conf",
        "/etc/calamares/modules/partition.conf",
        True,
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
    (
        "0300-installer.hook.chroot",
        r"^setRootPassword:[[:space:]]*false",
        "installer/calamares/modules/users.conf",
        "/etc/calamares/modules/users.conf",
        True,
    ),
    (
        "0300-installer.hook.chroot",
        r"^passwordRequirements:",
        "installer/calamares/modules/users.conf",
        "/etc/calamares/modules/users.conf",
        True,
    ),
    (
        "0300-installer.hook.chroot",
        r"^[[:space:]]+minLength:[[:space:]]*[1-9][0-9]*[[:space:]]*$",
        "installer/calamares/modules/users.conf",
        "/etc/calamares/modules/users.conf",
        True,
    ),
    (
        "0300-installer.hook.chroot",
        r"^componentName:[[:space:]]*astraos[[:space:]]*$",
        "installer/branding/astraos/branding.desc",
        "/usr/share/calamares/branding/astraos/branding.desc",
        True,
    ),
    (
        "0300-installer.hook.chroot",
        r"^slideshow:",
        "installer/branding/astraos/branding.desc",
        "/usr/share/calamares/branding/astraos/branding.desc",
        True,
    ),
    # The module-presence loop above cannot see a search path that finds nothing:
    # the modules were on disk in run 38940011841 and the installer still opened on
    # "Calamares Initialization Failed". This entry pins that the hook reads
    # modules-search from settings.conf and that the shipped file still sets it.
    (
        "0300-installer.hook.chroot",
        r"^modules-search:",
        "installer/calamares/settings.conf",
        "/etc/calamares/settings.conf",
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


def test_no_hook_passes_an_attached_flag_after_a_context_flag() -> None:
    """`grep -A4E` is `grep -A 4E`: "invalid context length argument".

    Run 38909791960 (2026-10-16) died at the end of the chroot stage because of exactly
    this spelling: the context flag and the expression flag had been merged into one
    word, GNU getopt consumed "4E" as the context length, the error was suppressed with
    2>/dev/null, and the empty result refused an image whose packages and other
    assertions were all fine. A flag that takes a numeric argument must stand alone
    (`-A 4 -E`), and this test is what notices before a runner is spent - the pattern
    tables above cannot, because the pattern itself was correct when the build died.
    """
    merged = re.compile(r"-[ABCm]\d+[A-Za-z]")
    offenders: list[str] = []
    for hook_path in sorted(HOOKS_DIR.iterdir()):
        if not hook_path.is_file():
            continue
        for number, line in enumerate(_without_comments(_read(hook_path)).splitlines(), 1):
            if merged.search(line):
                offenders.append(f"{hook_path.name}:{number}: {line.strip()}")
    assert not offenders, (
        "a hook merges a numeric flag with other letters, which grep(1) misreads "
        "(e.g. -A4E becomes -A 4E); write the flags separately:\n  " + "\n  ".join(offenders)
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


def test_no_hook_writes_the_release_version_as_a_literal() -> None:
    """A version literal in a hook turns a release bump into a failed image build.

    This is the case that cost the most, and it is the same shape as the two above: an
    assertion that was true when written and stopped being true for a reason nobody was
    watching. 0700-verify required /etc/os-release to contain 'VERSION_ID="0\\.1\\.0"' while
    config/distribution.env said 0.2.0. Every package built, all 47 other image assertions
    passed, and the build died because the version was raised — the one change that is
    supposed to be routine.

    The hook now reads the version out of the image's own /etc/astraos-release, where it is
    rendered from config/distribution.env, so the assertion checks that the two identity
    files the image ships agree with each other instead of comparing one of them with a
    constant kept in a third place. This test keeps a literal from growing back, for the
    current version and for the next one.

    Commented-out examples are allowed: 0800-disk-info quotes the exact medium string a
    0.1.0 build produced, and that record is worth keeping.
    """
    version = astraos_env.distribution()["ASTRAOS_VERSION"]
    pattern = re.compile(rf"(?<![\d.]){re.escape(version)}(?![\d.])")

    offenders: list[str] = []
    for hook_path in sorted(HOOKS_DIR.iterdir()):
        if not hook_path.is_file():
            continue
        for number, line in enumerate(_without_comments(_read(hook_path)).splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{hook_path.name}:{number}: {line.strip()}")

    assert not offenders, (
        f"a hook writes the release version {version!r} as a literal, so the next version "
        "bump will stop the build instead of changing it. Read the version from the image "
        "(see release_field in 0700-verify.hook.chroot) or from the staged distribution.env:\n  "
        + "\n  ".join(offenders)
    )


def test_disk_info_hook_has_no_identity_defaults() -> None:
    """A default in that hook is a second copy of the release's identity, and it goes stale.

    It is the worst place for one, because it is the copy that actually reaches the medium.
    0800-disk-info reads the identity from the staged configuration, but 0600-cleanup removes
    /usr/share/astraos/staged so that it is not shipped inside the live filesystem, and that
    runs in the chroot stage long before this binary hook. The lookup therefore never
    succeeded, the defaults were used on every build, and the version default sat at 0.1.0
    while the release moved to 0.2.0. Nothing failed; the medium just described itself with a
    version number no release had.

    The hook now searches the trees that can hold the file and refuses the build if none
    does. This keeps a fallback from being reintroduced: the failure it hides is silent, and
    the thing it hides is the image's own name for itself.
    """
    body = _without_comments(_read(HOOKS_DIR / "0800-disk-info.hook.binary"))

    assert "ASTRAOS_VERSION:?" in body, (
        "0800-disk-info no longer requires the version to come from the identity file it "
        "reads, so a stale copy of the version can reach the medium again"
    )

    defaults = sorted(set(re.findall(r"\$\{(ASTRAOS_\w+):[-=]", body)))
    assert not defaults, (
        f"0800-disk-info defaults {', '.join(defaults)}. Every release field has to come from "
        "the identity file, because this hook's defaults are the copy that reaches the ISO: "
        "the staged file it looks for is removed by 0600-cleanup before the binary stage runs, "
        "so a default here is not a fallback, it is the value."
    )
