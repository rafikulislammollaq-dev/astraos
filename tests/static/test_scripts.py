"""Shell script tests.

Syntax validation and a few invariants that matter for a build system: strict mode,
no unquoted variable expansion in destructive commands, and no accidental use of the
development host's devices.

ShellCheck would be better than `bash -n` (it catches real bugs, not just syntax), and
scripts/validate-environment.sh reports whether it is installed. It is not installed on
every host, so it cannot be a hard requirement here; when it is available it is run too.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "lib"))

from astraos_testlib import SkipTest  # noqa: E402

DESCRIPTION = "shell scripts are syntactically valid and follow the project's rules"

SHELL_GLOBS = [
    "scripts/*.sh",
    "config/live-build/auto/*",
    "config/live-build/config/hooks/live/*.hook.chroot",
    "packages/*/root/usr/bin/astraos-*",
    "packages/*/postinst",
    "packages/*/preinst",
    "packages/*/postrm",
    "packages/*/prerm",
]


def _scripts() -> list[Path]:
    found: list[Path] = []
    for pattern in SHELL_GLOBS:
        found.extend(sorted(REPO_ROOT.glob(pattern)))
    return [p for p in found if p.is_file()]


def _shell() -> str | None:
    for candidate in ("bash", "sh"):
        if shutil.which(candidate):
            return candidate
    return None


def test_scripts_were_found() -> None:
    scripts = _scripts()
    assert scripts, "no shell scripts were found; the test globs are wrong"
    assert len(scripts) >= 10, f"only {len(scripts)} shell scripts found; expected more"


def test_shell_syntax() -> None:
    shell = _shell()
    assert shell, "no shell interpreter is available to check syntax"

    failures: list[str] = []
    for path in _scripts():
        result = subprocess.run(
            [shell, "-n", str(path)],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            failures.append(
                f"{path.relative_to(REPO_ROOT)}:\n    "
                + (result.stderr.strip() or "syntax error")
            )
    assert not failures, "shell syntax errors:\n  " + "\n  ".join(failures)


# Scripts whose whole job is to REPORT, not to act. These deliberately avoid `set -e`
# (and some avoid `-u`) so that a missing optional tool prints "unknown" and the rest of
# the report still appears. Aborting would leave the user with no output at all, which
# is worse than an incomplete report (plan §14).
REPORTERS = {
    "astraos-info", "astraos-help", "astraos-release-info",
    "astraos-welcome", "astraos-recovery-guide",
    # Records what it can determine and writes "unknown" for the rest.
    "generate-manifest.sh",
}


def test_scripts_enable_strict_mode_or_aggregate_failures() -> None:
    """Each script must fail loudly, in one of the two documented ways.

    Either it uses `set -e` and aborts on the first error, or it deliberately does not
    use `-e` (because it must run every check before reporting) in which case it must
    track failures and exit non-zero. A script that does neither can report success
    after a failure, which plan §16.2 explicitly forbids.
    """
    offenders: list[str] = []

    for path in _scripts():
        text = path.read_text(encoding="utf-8", errors="replace")
        head = "\n".join(text.splitlines()[:40])

        if path.name in REPORTERS:
            # A reporter must not use `set -e`; it has to survive a missing tool.
            assert not any(
                line.strip().split()[:1] == ["set"] and "e" in line.strip().split()[1].lstrip("-")
                for line in text.splitlines()[:40]
                if line.strip().startswith("set ")
            ), f"{path.name} is a reporter and must not use set -e"
            continue

        uses_e = any(
            line.strip().startswith("set ") and "e" in line.strip().split()[1].lstrip("-")
            for line in head.splitlines()
            if len(line.strip().split()) > 1
        )
        if uses_e:
            continue

        # No -e: it must aggregate failures and exit non-zero explicitly.
        # The counter may be named any of the conventional things; what matters is that
        # a failure is counted and that the script has a non-zero exit path.
        has_counter = re.search(
            r"^\s*(FAIL|FAILED|ERRORS?|failures?|errors?)[A-Za-z_]*=0\s*$", text, re.M
        ) is not None
        exits_nonzero = re.search(r"^\s*exit\s+1\s*$", text, re.M) is not None
        if not (has_counter and exits_nonzero):
            reason = []
            if not has_counter:
                reason.append("no failure counter initialised to 0")
            if not exits_nonzero:
                reason.append("no non-zero exit path")
            offenders.append(f"{path.relative_to(REPO_ROOT)} ({'; '.join(reason)})")

    assert not offenders, (
        "these scripts neither enable `set -e` nor track failures and exit non-zero, so "
        "they could report success after an error:\n  " + "\n  ".join(offenders)
    )


def test_no_hardcoded_device_paths() -> None:
    """Plan §11: do not hardcode device names.

    A script that writes to /dev/sda could destroy a user's disk when it runs.
    """
    offenders: list[str] = []
    for path in _scripts():
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            # Comments and documentation are allowed to mention device names; commands
            # that would act on them are not.
            if stripped.startswith("#"):
                continue
            for device in ("/dev/sda", "/dev/sdb", "/dev/nvme0n1", "/dev/vda"):
                if device in stripped and "mkfs" not in stripped:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {stripped[:80]}")
    assert not offenders, (
        "these lines reference a specific block device, which risks destroying an "
        "unrelated disk:\n  " + "\n  ".join(offenders)
    )


def test_destructive_commands_are_guarded() -> None:
    """No script may format, partition or wipe a device automatically.

    Plan §28 Rule 5 and §10.3: all destructive disk operations happen through the
    installer, in a virtual machine, or after explicit human confirmation.
    """
    # The only permitted mention of these tools is inside documentation strings or in
    # the Calamares configuration, which is not a shell script.
    destructive = ("mkfs.", "wipefs", "sgdisk --zap", "dd if=", "shred ")

    offenders: list[str] = []
    for path in _scripts():
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for pattern in destructive:
                if pattern in stripped:
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT)}:{lineno}: {stripped[:80]}"
                    )
    assert not offenders, (
        "a build script contains a destructive disk command. Disk operations belong to "
        "the installer only:\n  " + "\n  ".join(offenders)
    )


def test_files_with_a_shebang_are_executable_in_git() -> None:
    """Every file with a shebang must be mode 100755 *in git*, not only on disk.

    Windows cannot store the executable bit, so a checkout made there marks every script
    100644 and nothing complains locally: the file still runs in Git Bash. The failure only
    appears on Linux, and it appears twice — `sudo ./scripts/bootstrap-build-environment.sh`
    fails with "command not found", and live-build refuses to execute the hooks inside the
    chroot because they are not executable there either.

    The git index is the only place the bit survives, so it is the only thing worth
    checking.
    """
    if not shutil.which("git"):
        raise SkipTest("git is not available to report index modes")

    result = subprocess.run(
        ["git", "ls-files", "-s"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise SkipTest(f"cannot read git index modes: {result.stderr.strip()}")

    offenders: list[str] = []
    seen = 0
    for line in result.stdout.splitlines():
        parts = line.split(None, 3)
        if len(parts) != 4:
            continue
        mode, _object, _stage, path = parts
        path = path.strip()
        target = REPO_ROOT / path
        if not target.is_file():
            continue
        try:
            if target.open("rb").read(2) != b"#!":
                continue
        except OSError:
            continue
        seen += 1
        if mode != "100755":
            offenders.append(f"{path} is mode {mode}")

    assert seen >= 10, (
        f"only {seen} shebang files were found through git, so this test is not seeing the "
        "repository it thinks it is"
    )
    assert not offenders, (
        "these files have a shebang but are not executable in git, so they will fail to run "
        "on any Linux machine that checks them out. Fix with:\n"
        "  git update-index --chmod=+x <path>\n  " + "\n  ".join(offenders)
    )


def test_shellcheck_when_available() -> None:
    """Run ShellCheck if it is installed, and report a skip if it is not.

    This used to print a note and return, which counted as a PASS. The project's rule is
    that an unperformed check is never a pass (plan §18, §28), and ShellCheck is the check
    that found the real defects in this tree, so claiming it passed while absent is exactly
    the kind of claim that must not appear in a test summary.
    """
    if not shutil.which("shellcheck"):
        raise SkipTest(
            "shellcheck is not installed, so deep linting did not run; install it (see "
            "scripts/bootstrap-build-environment.sh) or CI will be the first to find out"
        )

    failures: list[str] = []
    for path in _scripts():
        result = subprocess.run(
            ["shellcheck", "-S", "warning", "-s", "sh" if path.suffix == ".chroot" else "bash",
             str(path)],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            failures.append(f"{path.relative_to(REPO_ROOT)}:\n{result.stdout.strip()}")
    assert not failures, "shellcheck findings:\n  " + "\n  ".join(failures)
