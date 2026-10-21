"""Tests for astraos-reset, the way out of a broken system.

A distribution that cannot be put back to how it shipped is a distribution people
are locked into. This command is that way out, and its two halves are tested
separately because they are different promises:

  * `--settings` restores the shipped desktop and session defaults, keeps every
    file, and backs up what it replaces before it replaces it. It asks first.
  * `--factory` does not erase anything. It says how to reinstall, what to save
    first, and that the installer (which asks for a password and shows the disk)
    is the thing that erases.

The tests run the command against a fixture home and a fixture set of shipped
defaults, so what it does to the home is checked, not read.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RESET = REPO_ROOT / "packages" / "astraos-system-tools" / "root" / "usr" / "bin" / "astraos-reset"

DESCRIPTION = "the reset puts the machine back to how it shipped, and never deletes a file"


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
    assert bash and "WindowsApps" not in bash, (
        "this test needs a POSIX shell to run the command; Git for Windows provides one"
    )
    return [bash]


def _fixture(work: Path) -> tuple[Path, Path]:
    """A home with a broken panel, and the shipped defaults to restore."""
    home = work / "home"
    skel = work / "skel"
    (home / ".config" / "xfce4" / "xfconf" / "xfce-perchannel-xml").mkdir(parents=True)
    (home / ".config" / "xfce4" / "xfconf" / "xfce-perchannel-xml" / "xfce4-panel.xml").write_text(
        "<panel broken='yes'/>", encoding="utf-8"
    )
    (home / "Documents").mkdir(parents=True, exist_ok=True)
    (home / "Documents" / "keepme.txt").write_text("my work\n", encoding="utf-8")

    (skel / ".config" / "xfce4" / "xfconf" / "xfce-perchannel-xml").mkdir(parents=True)
    (skel / ".config" / "xfce4" / "xfconf" / "xfce-perchannel-xml" / "xfce4-panel.xml").write_text(
        "<panel shipped='yes'/>", encoding="utf-8"
    )
    (skel / ".config" / "autostart").mkdir(parents=True)
    (skel / ".config" / "autostart" / "example.desktop").write_text("[Desktop Entry]\n", encoding="utf-8")
    return home, skel


def _run(home: Path, skel: Path, answer: str = "", *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["XDG_STATE_HOME"] = str(home / "state")
    env["ASTRAOS_RESET_SKEL"] = str(skel)
    # The answer goes in as bytes: Python's text mode writes CRLF on Windows, and
    # the shell would then read "RESET\r" and compare it with "RESET".
    result = subprocess.run(
        _interpreter() + [str(RESET), *args],
        input=answer.encode("utf-8"),
        capture_output=True,
        check=False,
        env=env,
    )
    result.stdout = result.stdout.decode("utf-8", "replace")
    result.stderr = result.stderr.decode("utf-8", "replace")
    return result


def test_the_settings_reset_restores_the_defaults_and_keeps_the_files() -> None:
    assert RESET.is_file(), f"the command is missing: {RESET}"
    with tempfile.TemporaryDirectory(prefix="astraos-reset-") as workdir:
        work = Path(workdir)
        home, skel = _fixture(work)

        result = _run(home, skel, "RESET\n", "--settings")
        assert result.returncode == 0, f"the reset failed: {result.stderr}"

        panel = home / ".config" / "xfce4" / "xfconf" / "xfce-perchannel-xml" / "xfce4-panel.xml"
        assert panel.read_text(encoding="utf-8") == "<panel shipped='yes'/>", (
            "the shipped default was not restored"
        )
        assert (home / "Documents" / "keepme.txt").read_text(encoding="utf-8") == "my work\n", (
            "the reset touched a file that is not a setting"
        )
        assert "restored" in result.stdout, "the command did not say what it restored"

        # What it replaced is kept, somewhere the user can find.
        state = home / "state" / "astraos"
        backups = list(state.glob("reset-backup-*"))
        assert backups, "the previous settings were not backed up"
        old = backups[0] / ".config" / "xfce4" / "xfconf" / "xfce-perchannel-xml" / "xfce4-panel.xml"
        assert old.is_file(), "the backup does not hold the file it replaced"
        assert old.read_text(encoding="utf-8") == "<panel broken='yes'/>"


def test_the_reset_asks_before_it_changes_anything() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-reset-ask-") as workdir:
        work = Path(workdir)
        home, skel = _fixture(work)
        panel = home / ".config" / "xfce4" / "xfconf" / "xfce-perchannel-xml" / "xfce4-panel.xml"

        result = _run(home, skel, "no\n", "--settings")
        assert result.returncode == 0, f"the reset failed: {result.stderr}"
        assert "Nothing was changed" in result.stdout
        assert panel.read_text(encoding="utf-8") == "<panel broken='yes'/>", (
            "the reset changed the settings even though the answer was no"
        )


def test_the_factory_mode_explains_and_erases_nothing() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-reset-factory-") as workdir:
        work = Path(workdir)
        home, skel = _fixture(work)

        result = _run(home, skel, "", "--factory")
        assert result.returncode == 0, f"the command failed: {result.stderr}"
        text = result.stdout
        assert "installer" in text.lower(), "the advice must say the installer does the erasing"
        assert "password" in text.lower(), "the advice must say the installer asks for a password"
        assert "WHAT TO SAVE FIRST" in text, "the advice must say what to back up"
        assert "WHAT IT DOES NOT KEEP" in text, "the advice must say what is lost"
        # Nothing was touched.
        assert (home / "Documents" / "keepme.txt").is_file()
        panel = home / ".config" / "xfce4" / "xfconf" / "xfce-perchannel-xml" / "xfce4-panel.xml"
        assert panel.read_text(encoding="utf-8") == "<panel broken='yes'/>"


def test_the_command_never_deletes_a_file() -> None:
    source = RESET.read_text(encoding="utf-8")
    for forbidden in ("rm -rf", "rm -f", "find ... -delete", "shred", "dd if="):
        assert forbidden not in source, (
            f"the reset contains {forbidden!r}: it must not delete a user's files"
        )
    assert "read -r answer" in source, "the reset must ask before it changes anything"
    assert "RESET" in source, "the confirmation word must be in the script"
