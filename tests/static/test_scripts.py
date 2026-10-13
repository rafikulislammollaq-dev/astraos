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
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

import astraos_env  # noqa: E402
from astraos_testlib import SkipTest  # noqa: E402

DESCRIPTION = "shell scripts are syntactically valid and follow the project's rules"

SHELL_GLOBS = [
    "scripts/*.sh",
    "config/live-build/auto/*",
    "config/live-build/config/hooks/live/*.hook.chroot",
    "config/live-build/config/hooks/live/*.hook.binary",
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


# The command may be quoted (`sh -c 'ls …'`) and may follow a shell operator, so the
# boundary class includes quotes and the operators that end one command and start the next.
LS_COMMAND = re.compile(r"""(?:^|[\s;&|(='\"])ls\s""")


def _globs_on_ls_command(line: str) -> list[str]:
    """The globs a single `ls` command on this line is given, comments excluded."""
    stripped = line.strip()
    if stripped.startswith("#") or not LS_COMMAND.search(stripped):
        return []
    return re.findall(r"\S*\*\S*", stripped)


def test_no_command_is_given_several_globs() -> None:
    """`ls a-* b-*` fails when only one of the patterns matches, and the shell hands it over.

    With nullglob off — and it is off in dash, which is /bin/sh inside the image — an
    unmatched pattern reaches the command as its own literal text, so `ls` reports
    "cannot access '/boot/initrd-*'" and exits non-zero. That is how the image verification
    hook reported "an initramfs is in /boot" as FAIL for an image that had one: the plymouth
    assertion in the same hook then opened that initramfs and found the AstraOS theme inside
    it. A loop over the patterns — or one command per pattern — has no such failure mode.
    """
    # The detector is checked against the command this rule was written for, so a guard that
    # has stopped recognising it cannot pass quietly, and against its own fix, so the rule
    # cannot start rejecting the shape it recommends.
    historical = (
        'check "an initramfs is in /boot"          '
        "sh -c 'ls /boot/initrd.img-* /boot/initrd-* >/dev/null 2>&1'"
    )
    assert len(_globs_on_ls_command(historical)) >= 2, (
        "the glob detector no longer recognises the command that failed a real build"
    )
    repaired = (
        'check "an initramfs is in /boot" \\\n'
        "    sh -c 'for f in /boot/initrd.img-* /boot/initrd-*; do [ -f \"$f\" ] && exit 0; done; exit 1'"
    )
    assert not _globs_on_ls_command(repaired), (
        "the recommended form is itself reported as a multi-glob command"
    )

    offenders: list[str] = []
    for path in _scripts():
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), 1):
            if len(_globs_on_ls_command(line)) >= 2:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()}")

    assert not offenders, (
        "these commands are given more than one glob, so an unmatched pattern is passed to "
        "the command as literal text and fails it:\n  " + "\n  ".join(offenders)
    )


# A pipeline into `grep -q` in a script that enables `set -o pipefail`. `grep -q` exits as
# soon as it matches, so the command feeding it is killed with SIGPIPE (or fails to write),
# and pipefail then reports the *successful* match as a failed pipeline. The match is real and
# the check says it is not, which is the worst way for a check to be wrong.
#
# The lookarounds exclude `||`, which is a shell operator and not a pipeline. A nested shell
# (`sh -c '... | grep -q ...'`) is excluded separately: it does not inherit pipefail, so its
# pipeline status is grep's and the idiom is safe there.
PIPELINE_INTO_GREP_Q = re.compile(r"(?<!\|)\|(?!\|)\s*grep\s+-[A-Za-z]*q")


def _pipes_into_grep_q(line: str) -> bool:
    stripped = line.strip()
    if stripped.startswith("#"):
        return False
    if "sh -c" in stripped or "bash -c" in stripped:
        return False
    return PIPELINE_INTO_GREP_Q.search(stripped) is not None


def test_no_pipeline_into_grep_q_where_pipefail_is_set() -> None:
    """A `grep -q` at the end of a pipeline must read a file, not a stream.

    This is not hypothetical: `validate-iso.sh` reported a complete live filesystem as
    missing eight of its nine components because of it. The squashfs really held everything
    it looked for — 152556 inodes, `/usr/bin/astraos-info` among them, and the image
    verification hook inside the chroot had found the same paths minutes earlier — but the
    6 MB listing was piped into `grep -q`, every match before the end of that listing killed
    `printf` with SIGPIPE, and pipefail turned each match into exit status 141. Only the one
    pattern that happened to sit near the end survived the race, which is why the check
    looked like it was working and the image looked like it was broken.

    The rule is that the check reads a file. A file cannot race.
    """
    # The detector is checked against the line that failed a real build, so a guard that has
    # stopped recognising it cannot pass quietly, and against the repairs and the false
    # positives that must not be reported.
    historical = '            if printf \'%s\' "$CONTENTS" | grep -q -- "$pattern"; then'
    assert _pipes_into_grep_q(historical), (
        "the detector no longer recognises the pipeline that failed a real ISO build"
    )
    assert not _pipes_into_grep_q('            if grep -q -- "$pattern" "$LIST_FILE"; then'), (
        "the recommended form is itself reported as a pipeline into grep -q"
    )
    assert not _pipes_into_grep_q("    [ -d /lib/live ] || grep -qs overlay /proc/mounts"), (
        "a `||` before grep is a shell operator, not a pipeline, and must not be reported"
    )
    assert not _pipes_into_grep_q(
        "    sh -c 'command -v lsinitramfs >/dev/null 2>&1 && lsinitramfs x | grep -q y'"
    ), "a nested shell does not inherit pipefail, so its pipeline must not be reported"

    offenders: list[str] = []
    for path in _scripts():
        text = path.read_text(encoding="utf-8", errors="replace")
        if "pipefail" not in text:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if _pipes_into_grep_q(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()}")

    assert not offenders, (
        "these scripts enable `set -o pipefail` and pipe into `grep -q`, so a match can be "
        "reported as a failed pipeline. Capture the output and match it from a variable, or "
        "grep a file:\n  " + "\n  ".join(offenders)
    )


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


def _code_head(text: str, lines: int = 40) -> list[str]:
    """The first `lines` lines of *code*, with comment-only lines removed.

    The window is measured over code rather than over the file, because a script whose
    header explains a real failure at length would otherwise fail a check about where its
    strict mode is set. The rule being tested is "strict mode is set before anything runs",
    not "the documentation is short" — and a check that punishes a well-documented script is
    a check that gets a shorter comment rather than a correct script.
    """
    return [line for line in text.splitlines() if not line.lstrip().startswith("#")][:lines]


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
        head = _code_head(text)

        if path.name in REPORTERS:
            # A reporter must not use `set -e`; it has to survive a missing tool.
            assert not any(
                line.strip().split()[:1] == ["set"] and "e" in line.strip().split()[1].lstrip("-")
                for line in head
                if line.strip().startswith("set ")
            ), f"{path.name} is a reporter and must not use set -e"
            continue

        uses_e = any(
            line.strip().startswith("set ") and "e" in line.strip().split()[1].lstrip("-")
            for line in head
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


def test_logging_helpers_use_stderr_where_output_is_captured() -> None:
    """A logging helper that prints on stdout corrupts any function whose value is captured.

    `DEBS+=("$(finish_package astraos-base "$BASE_STAGE")")` takes the function's stdout as
    the path to the .deb, so a progress line printed there becomes part of the filename.
    That is exactly how the first complete package build failed, *after* all five packages
    had been built correctly: the copy failed against a path named after a log line. The
    rule is cheap to state and cheap to check — logs to stderr, data to stdout.
    """
    helpers = ("say", "log", "info", "warn", "note")
    offenders: list[str] = []

    for path in _scripts():
        text = path.read_text(encoding="utf-8", errors="replace")
        functions = set(re.findall(r"^([A-Za-z_][A-Za-z0-9_]*)\(\)", text, re.M))
        captured = {
            name
            for name in functions
            if re.search(rf"\$\(\s*{re.escape(name)}\b", text)
        }
        if not captured:
            continue

        for helper in helpers:
            definition = re.search(rf"^{helper}\(\)", text, re.M)
            if not definition:
                continue

            # Take the definition itself and stop at its closing brace. An earlier
            # version scanned to the next `}` in column 0, which ran past the end of a
            # one-line helper and swallowed the following function — and because that
            # function used stderr, the check could never fire. A guard that cannot fail
            # is worse than none, so the extent of the definition is computed properly.
            lines = text[definition.start():].splitlines()
            body_lines = [lines[0]]
            if not lines[0].rstrip().endswith("}"):
                for line in lines[1:]:
                    body_lines.append(line)
                    if line.rstrip() == "}":
                        break
            body = "\n".join(body_lines)

            if ">&2" not in body:
                offenders.append(
                    f"{path.relative_to(REPO_ROOT)}: {helper}() prints on stdout while the "
                    f"output of {', '.join(sorted(captured))} is captured"
                )

    assert not offenders, (
        "these scripts capture a function's stdout as data while a logging helper writes "
        "to the same stream, so the log line would become part of the value:\n  "
        + "\n  ".join(offenders)
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


def test_live_build_auto_scripts_do_not_recurse() -> None:
    """An auto script must not run the live-build command that runs it.

    live-build executes `auto/<command>` as part of `lb <command>`, so an `auto/build`
    containing `lb build` calls itself. The first build that reached this point recursed
    until it died, which is why there is no `auto/build` in this repository: the logging
    and the image check it used to perform live in `scripts/build-iso.sh`, which is the
    process that invokes live-build and can therefore wrap it without re-entering it.

    `auto/config` is allowed to run `lb config` only because it passes the `noauto`
    positional, which tells live-build not to run the auto script again. That is asserted
    here so the recursion cannot come back in a different command.
    """
    auto_dir = REPO_ROOT / "config" / "live-build" / "auto"
    assert auto_dir.is_dir(), "config/live-build/auto does not exist"

    commands = {"config": "lb config", "build": "lb build", "clean": "lb clean"}
    offenders: list[str] = []

    for path in sorted(auto_dir.iterdir()):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        command = commands.get(path.name)
        if command and command in text and "noauto" not in text:
            offenders.append(
                f"{path.relative_to(REPO_ROOT)} runs {command!r} without the 'noauto' "
                "positional, so live-build will re-run this script and recurse"
            )

    assert not offenders, (
        "these auto scripts would re-enter live-build forever:\n  " + "\n  ".join(offenders)
    )

    assert (auto_dir / "config").is_file(), (
        "config/live-build/auto/config is missing, so `lb build` would run with no "
        "AstraOS configuration at all"
    )


def test_build_paths_do_not_repeat_the_live_build_segment() -> None:
    """The build root is the live-build working directory; it must not appear twice.

    `config/packages.chroot` only means something directly under that directory: the .deb
    files are installed from there. One level deeper lives a directory live-build never
    reads, so the packages are built successfully and then quietly left out of the image.
    That is what happened once — the first symptom was the identity hook failing because
    /usr/bin/astraos-info was not in the chroot, which is a long way from the typo.
    """
    document = astraos_env.distribution()
    build_dir = document["ASTRAOS_BUILD_DIR"]
    offenders: list[str] = []

    for path in _scripts():
        # Comments are stripped: the scripts legitimately explain this trap in prose, and
        # the explanation has to name the path it is warning about.
        text = "\n".join(
            line
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
            if not line.lstrip().startswith("#")
        )
        for needle in (f"{build_dir}/live-build", "live-build/live-build"):
            if needle in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: contains {needle!r}")

    assert not offenders, (
        f"{build_dir} is the live-build working directory, so appending another live-build "
        "segment stages files where live-build will never look:\n  " + "\n  ".join(offenders)
    )


def test_live_build_firmware_sweep_is_disabled() -> None:
    """The image must only contain the firmware this repository chose.

    live-build installs every package whose name starts with firmware- unless told not to,
    which both defeats config/package-lists/20-firmware.list.chroot and pulls in contrib
    installers that download firmware at install time. The build failed on one of those, so
    the option is asserted here rather than left to the list to compensate for.
    """
    text = (REPO_ROOT / "config" / "live-build" / "auto" / "config").read_text(
        encoding="utf-8"
    )
    assert '--firmware-chroot false' in text, (
        "auto/config does not pass --firmware-chroot false, so live-build will add every "
        "firmware-* package in the archive to the image"
    )
    assert 'supports --firmware-chroot' in text, (
        "the firmware option is passed without a probe, so a live-build that lacks it would "
        "fail the build instead of recording the setting as skipped"
    )


def test_every_optional_live_build_flag_is_probed() -> None:
    """A flag passed to `lb config` without a probe is a flag that fails on some release.

    live-build renames and removes options between releases: --binary-images became
    --binary-image, --binary-compression became --chroot-squashfs-compression-type, and
    --tasks and --syslinux-timeout are gone in the pinned release. A removed flag that is
    passed unguarded stops the build; a removed optional one is silently dropped, which is
    worse because nothing reports it.

    The flags in ALWAYS are the ones every supported live-build accepts and the build cannot
    proceed without, so they are asserted individually in the script instead.
    """
    ALWAYS = {
        "mode", "system", "distribution", "architecture", "archive-areas", "initsystem",
        "mirror-bootstrap", "mirror-chroot", "mirror-binary",
    }

    text = (REPO_ROOT / "config" / "live-build" / "auto" / "config").read_text(
        encoding="utf-8"
    )
    code = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )

    unguarded: list[str] = []
    for flag in sorted(set(re.findall(r'set -- "\$@" --([a-z0-9-]+)', code))):
        if flag in ALWAYS:
            continue
        if f"supports --{flag}" not in code:
            unguarded.append(flag)

    assert not unguarded, (
        "these live-build options are passed without a `supports` probe, so a release that "
        "renamed or removed them would fail the build or silently ignore the setting:\n  "
        + "\n  ".join(f"--{flag}" for flag in unguarded)
    )

    for flag in sorted(ALWAYS):
        assert f'--{flag}' in code, (
            f"the build no longer sets --{flag}, which every supported live-build accepts"
        )


def _shellcheck_dialect(path: Path) -> str:
    """Which shell dialect this file is actually run by.

    Getting this wrong is not cosmetic. live-build executes the auto scripts with sh,
    whatever their shebang says, and it runs every hook — `.hook.chroot` in the chroot stage
    and `.hook.binary` in the binary stage — through its own `#!/bin/sh`, which is dash on the
    build host. Linting one as bash once hid a `${PIPESTATUS[0]}` that made every image build
    die with "Bad substitution" under dash.
    """
    relative = path.relative_to(REPO_ROOT).as_posix()
    if (
        relative.startswith("config/live-build/auto/")
        or relative.startswith("config/live-build/config/hooks/")
    ):
        return "sh"
    return "bash"


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
            ["shellcheck", "-S", "warning", "-s", _shellcheck_dialect(path), str(path)],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            failures.append(f"{path.relative_to(REPO_ROOT)}:\n{result.stdout.strip()}")
    assert not failures, "shellcheck findings:\n  " + "\n  ".join(failures)
