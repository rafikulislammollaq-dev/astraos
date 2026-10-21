"""Tests for the first-run welcome.

A new account's first login is the one moment the system can explain itself.
Three things have to hold, and each of them is a way the welcome could be
useless:

  * the page exists, says what the machine is, and is honest about what has not
    been proven - a welcome that oversells is worse than none;
  * it opens once. The marker file is what makes it a first-run thing; without it
    the page would open at every login, which is how a welcome becomes noise;
  * it never fails a login. A missing page, a missing browser or a read-only home
    has to end in silence, not in an error on a fresh desktop.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AI = REPO_ROOT / "packages" / "astraos-ai" / "root" / "usr"
WELCOME_HTML = AI / "share" / "astraos" / "ai" / "web" / "welcome.html"
WELCOME_COMMAND = AI / "bin" / "astraos-welcome"
AUTOSTART = (
    REPO_ROOT / "desktop" / "skel" / ".config" / "autostart" / "astraos-welcome.desktop"
)
SMOKE = (
    REPO_ROOT / "config" / "live-build" / "config" / "includes.chroot"
    / "usr" / "local" / "sbin" / "astraos-smoke"
)

DESCRIPTION = "the first-run welcome opens once, says the truth, and never breaks a login"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_the_page_says_what_the_machine_is_and_what_is_not_proven() -> None:
    assert WELCOME_HTML.is_file(), f"the welcome page is missing: {WELCOME_HTML}"
    page = _text(WELCOME_HTML)
    assert "Welcome to AstraOS" in page
    assert "Debian 13" in page, "the page must say what the system is"
    assert "not signed" in page, "the page must say the image is not signed"
    assert "physical hardware" in page, (
        "the page must say that no install has been run on physical hardware"
    )
    assert 'href="help.html"' in page, "the page must link to the help centre"
    assert "http://" not in page.replace("http://127.0.0.1", ""), (
        "the page must not need the network"
    )


def test_the_launcher_opens_it_once_and_never_fails() -> None:
    assert WELCOME_COMMAND.is_file(), f"the launcher is missing: {WELCOME_COMMAND}"
    script = _text(WELCOME_COMMAND)
    assert "welcome-seen" in script, (
        "the launcher must remember that the page has been shown, or it opens at every "
        "login"
    )
    assert "xdg-open" in script
    assert "--reset" in script, "there must be a way to see it again"
    # It ends in silence, whatever happens.
    for line in script.splitlines():
        stripped = line.strip()
        if stripped.startswith("exit "):
            assert stripped == "exit 0", "the launcher must never fail a login"


def test_the_autostart_entry_is_wired_to_the_launcher() -> None:
    assert AUTOSTART.is_file(), f"the autostart entry is missing: {AUTOSTART}"
    entry = _text(AUTOSTART)
    assert "Type=Application" in entry
    assert "astraos-welcome" in entry
    assert "NoDisplay=true" in entry, (
        "an autostart entry that shows in the menu is not an autostart entry"
    )


def test_the_image_is_checked_for_the_welcome() -> None:
    smoke = _text(SMOKE)
    assert 'ok "welcome-page"' in smoke and 'bad "welcome-page"' in smoke
    assert "/usr/share/astraos/ai/web/welcome.html" in smoke
    assert "/etc/skel/.config/autostart/astraos-welcome.desktop" in smoke


def test_the_launcher_says_nothing_when_the_page_is_not_there() -> None:
    """With no page installed, the launcher must exit quietly and change nothing."""
    if sys.platform == "win32":
        return  # the launcher is a POSIX script; CI and Linux hosts cover it
    with tempfile.TemporaryDirectory(prefix="astraos-welcome-") as workdir:
        home = Path(workdir)
        env = {
            "HOME": str(home),
            "PATH": "/usr/bin:/bin",
            "XDG_STATE_HOME": str(home / "state"),
        }
        result = subprocess.run(
            [str(WELCOME_COMMAND)],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        assert result.returncode == 0, (
            f"the launcher failed a login: {result.stderr}"
        )
        assert result.stdout == "" and result.stderr == "", (
            "the launcher must say nothing when there is no page to show"
        )
