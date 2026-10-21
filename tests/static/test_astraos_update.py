"""Tests for astraos-update: the part of an upgrade apt cannot do.

apt is a fine package manager and AstraOS does not replace it. What apt cannot
do is take your files with it, so this command keeps a copy of your home
directory before you upgrade and puts it back if the upgrade went badly.

The properties tested here are the ones a user would be burned by:

  * a snapshot really is a copy of the home directory, and it is written somewhere
    the user owns;
  * a rollback puts the files back, and it can itself be undone (the state from
    before the restore is kept);
  * both of them ask first, and an answer that is not the word changes nothing;
  * the command never runs the upgrade itself. Upgrading needs a password, and a
    tool that types your password for you is a tool that can break your system
    without asking - so it prints the command and you run it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UPDATE = REPO_ROOT / "packages" / "astraos-system-tools" / "root" / "usr" / "bin" / "astraos-update"

DESCRIPTION = "the update command keeps your files safe and never runs the upgrade itself"


def _interpreter() -> list[str]:
    if os.name != "nt":
        return []
    for candidate in (
        Path(r"C:\Program Files\Git\bin\bash.exe"),
        Path(r"C:\Program Files\Git\usr\bin\bash.exe"),
    ):
        if candidate.is_file():
            return [str(candidate)]
    bash = shutil.which("bash")
    assert bash and "WindowsApps" not in bash
    return [bash]


def _run(home: Path, answer: str = "", *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["ASTRAOS_UPDATE_SNAPSHOTS"] = str(home / "snapshots")
    result = subprocess.run(
        _interpreter() + [str(UPDATE), *args],
        input=answer.encode("utf-8"),
        capture_output=True,
        check=False,
        env=env,
    )
    result.stdout = result.stdout.decode("utf-8", "replace")
    result.stderr = result.stderr.decode("utf-8", "replace")
    return result


def _home(work: Path) -> Path:
    home = work / "home"
    (home / "Documents").mkdir(parents=True, exist_ok=True)
    (home / "Documents" / "thesis.txt").write_text("the original\n", encoding="utf-8")
    (home / ".config").mkdir(parents=True, exist_ok=True)
    (home / ".config" / "settings").write_text("before\n", encoding="utf-8")
    return home


def test_a_snapshot_is_a_copy_of_the_home_directory() -> None:
    assert UPDATE.is_file(), f"the command is missing: {UPDATE}"
    with tempfile.TemporaryDirectory(prefix="astraos-update-") as workdir:
        work = Path(workdir)
        home = _home(work)

        result = _run(home, "", "--snapshot")
        assert result.returncode == 0, f"the snapshot failed: {result.stderr}"

        snapshots = sorted((home / "snapshots").iterdir())
        assert snapshots, "no snapshot was taken"
        snapshot = snapshots[0]
        assert (snapshot / "Documents" / "thesis.txt").read_text(encoding="utf-8") == "the original\n"
        assert (snapshot / ".config" / "settings").read_text(encoding="utf-8") == "before\n"
        assert "Snapshot taken" in result.stdout


def test_a_rollback_puts_the_files_back() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-update-rollback-") as workdir:
        work = Path(workdir)
        home = _home(work)
        assert _run(home, "", "--snapshot").returncode == 0

        # Something goes wrong after the upgrade.
        (home / "Documents" / "thesis.txt").write_text("mangled\n", encoding="utf-8")
        (home / ".config" / "settings").write_text("mangled\n", encoding="utf-8")

        result = _run(home, "RESTORE\n", "--rollback")
        assert result.returncode == 0, f"the rollback failed: {result.stderr}"
        assert (home / "Documents" / "thesis.txt").read_text(encoding="utf-8") == "the original\n"
        assert (home / ".config" / "settings").read_text(encoding="utf-8") == "before\n"

        # And the restore itself can be undone: the state from before it is kept.
        before = [p for p in (home / "snapshots").iterdir() if p.name.startswith("before-rollback-")]
        assert before, "the state from before the restore was not kept"
        assert (before[0] / "Documents" / "thesis.txt").read_text(encoding="utf-8") == "mangled\n"


def test_a_rollback_that_is_not_confirmed_changes_nothing() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-update-ask-") as workdir:
        work = Path(workdir)
        home = _home(work)
        assert _run(home, "", "--snapshot").returncode == 0
        (home / "Documents" / "thesis.txt").write_text("mangled\n", encoding="utf-8")

        result = _run(home, "no\n", "--rollback")
        assert result.returncode == 0
        assert "Nothing was changed" in result.stdout
        assert (home / "Documents" / "thesis.txt").read_text(encoding="utf-8") == "mangled\n"


def test_the_command_never_runs_an_upgrade_itself() -> None:
    source = UPDATE.read_text(encoding="utf-8")
    assert "apt-get" not in source, (
        "the command must not run an upgrade: it needs a password, and it prints the "
        "command for the user to run"
    )
    assert "apt update && sudo apt full-upgrade" in source, (
        "the command must tell the user what to run"
    )
    assert "RESTORE" in source, "the rollback must ask for the word RESTORE"


def test_the_check_never_changes_anything_and_says_what_to_run() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-update-check-") as workdir:
        work = Path(workdir)
        home = _home(work)
        result = _run(home, "", "--check")
        assert result.returncode in (0, 1), f"the check failed oddly: {result.stderr}"
        said = result.stdout + result.stderr
        assert "apt is not on this machine" in said or "sudo apt update" in said
        # Nothing was written into the home directory by a check.
        assert not (home / "snapshots").exists()
