"""The installer's lock-down step, executed rather than read.

WHY THIS FILE RUNS THE SCRIPT

Every other installer assertion in this suite reads a file and looks for a line in
it. That is the right shape for configuration and the wrong shape for a script. The
shell in shellprocess.conf is the only thing that undoes the live medium's autologin
on the installed system, and a rewritten `sed` expression, a heredoc whose terminator
no longer matches, or a quoting mistake all still contain the lines a grep looks for.

So this test extracts the shell out of the YAML, runs it against a throwaway root that
looks like a live system's /etc, and asserts the state it leaves behind. The absolute
paths are redirected by substituting the temporary root for /etc, which is what makes
the script runnable here without touching the /etc of the machine running the tests.

The last case is the one that matters most: a target that still has an autologin
anywhere must make the installation FAIL. An installer that only warns here produces a
system that logs a user in without a password and never mentions it.

The tests take no arguments and use no framework: the suite's runner loads each module
and calls every test_* function directly (tests/run.py), with no pytest available.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "lib"))

from astraos_testlib import SkipTest  # noqa: E402

DESCRIPTION = "the installer's lock-down step removes the live medium's autologin"

LOCKDOWN = REPO_ROOT / "installer" / "calamares" / "modules" / "shellprocess.conf"

# An autologin key that carries a value. `autologin-user=` with nothing after it is the
# lock-down itself and must not be flagged.
AUTOLOGIN_WITH_VALUE = re.compile(r"^[ \t]*autologin-(user|session|user-timeout)=[^ \t]")


def _require_sh() -> None:
    """The step runs in the target's /bin/sh; without a shell there is nothing to test."""
    if shutil.which("sh") is None:
        raise SkipTest("no POSIX shell on this machine, so the step cannot be run")


def _extract_script() -> str:
    """Pull the block scalar out of the YAML the way YAML would.

    The file is read as text rather than through a YAML parser because the suite has no
    YAML dependency and one script does not justify adding one. The extraction follows
    the rule that matters here: a block's indentation is set by its first non-empty
    line. If the file's shape changes, the assertion below fails rather than the test
    quietly running nothing.
    """
    lines = LOCKDOWN.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.strip() != "- |":
            continue
        body: list[str] = []
        block_indent = None
        for following in lines[index + 1:]:
            if not following.strip():
                body.append("")
                continue
            indent = len(following) - len(following.lstrip(" "))
            if block_indent is None:
                block_indent = indent
            elif indent < block_indent:
                break
            body.append(following[block_indent:])
        script = "\n".join(body).strip("\n")
        assert "autologin-user=" in script, (
            "the block scalar extracted from shellprocess.conf does not contain the "
            "lock-down policy, so this test is not testing the lock-down"
        )
        return script
    raise AssertionError(
        "shellprocess.conf has no `- |` block scalar. The lock-down step would run "
        "nothing, and the installed system would inherit the live medium's autologin."
    )


def _live_root(root: Path) -> Path:
    """A /etc that looks like the live medium's at the moment of installation.

    Calamares unpacks the live filesystem, so the target carries whatever the live boot
    left behind: the main conffile as live-config rewrote it, the image's own drop-in,
    and any live-only drop-in.
    """
    etc = root / "etc" / "lightdm"
    (etc / "lightdm.conf.d").mkdir(parents=True)

    (etc / "lightdm.conf").write_text(
        "[Seat:*]\n"
        "#autologin-user=\n"
        "autologin-user=astra\n"
        "autologin-session=xfce\n"
        "autologin-user-timeout=0\n"
        "#greeter-session=lightdm-gtk-greeter\n",
        encoding="utf-8",
    )
    (etc / "lightdm.conf.d" / "50-astraos.conf").write_text(
        "[Seat:*]\nallow-guest=false\n", encoding="utf-8"
    )
    (etc / "lightdm.conf.d" / "99-astraos-live.conf").write_text(
        "[Seat:*]\nautologin-user=astra\n", encoding="utf-8"
    )
    return root


def _run(script: str, root: Path) -> subprocess.CompletedProcess:
    """Run the script with /etc redirected into the throwaway root."""
    redirected = script.replace("/etc/", f"{root.as_posix()}/etc/")
    return subprocess.run(
        ["sh", "-c", redirected], capture_output=True, text=True
    )


def test_the_lock_down_step_is_valid_posix_shell() -> None:
    """A syntax error here fails an installation halfway through, not at build time."""
    _require_sh()
    check = subprocess.run(
        ["sh", "-n"], input=_extract_script(), capture_output=True, text=True
    )
    assert check.returncode == 0, f"the lock-down script does not parse: {check.stderr}"


def test_the_installed_system_cannot_autologin() -> None:
    """The live autologin is undone on the target and the policy is written there."""
    _require_sh()
    with tempfile.TemporaryDirectory(prefix="astraos-lockdown-") as directory:
        root = _live_root(Path(directory))
        result = _run(_extract_script(), root)
        assert result.returncode == 0, (
            "the lock-down step failed on an ordinary live root, so no installation "
            f"would complete: {result.stdout}{result.stderr}"
        )

        etc = root / "etc" / "lightdm"
        assert not (etc / "lightdm.conf.d" / "99-astraos-live.conf").exists(), (
            "a live-only LightDM drop-in survived into the installed system, so the "
            "disk would autologin like the live medium"
        )

        main = (etc / "lightdm.conf").read_text(encoding="utf-8")
        stray = [line for line in main.splitlines() if AUTOLOGIN_WITH_VALUE.match(line)]
        assert not stray, (
            "the main LightDM configuration still carries a live autologin after the "
            f"lock-down step ran: {stray}. The installer unpacks this file onto the "
            "disk verbatim, so this is what the installed system would log in with."
        )

        policy = (etc / "lightdm.conf.d" / "90-astraos-installed.conf").read_text(encoding="utf-8")
        assert re.search(r"^autologin-user=[ \t]*$", policy, re.M), (
            "the installed system's own drop-in does not clear autologin-user; a stray "
            "key in another file would be able to re-enable it"
        )


def test_an_autologin_that_survives_fails_the_installation() -> None:
    """A check that only warns is a check that gets ignored."""
    _require_sh()
    with tempfile.TemporaryDirectory(prefix="astraos-lockdown-") as directory:
        root = _live_root(Path(directory))
        (root / "etc" / "lightdm" / "lightdm.conf.d" / "40-site.conf").write_text(
            "[Seat:*]\nautologin-user=bob\n", encoding="utf-8"
        )

        result = _run(_extract_script(), root)
        assert result.returncode != 0, (
            "an autologin in a file the lock-down step does not own was left in place "
            "and the installation still reported success. The user would then be "
            "logged in without a password on a system they believe is protected."
        )
        assert "refusing" in result.stderr
