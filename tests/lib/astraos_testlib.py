"""Shared helpers for the AstraOS test suite.

Kept small and dependency-free so every test can import it on any host: the suite must
run on a Windows development machine as well as in Linux CI, and a test that cannot even
start is not a test.

The important piece here is SkipTest. A test that needs a virtual machine, an ISO or a
Linux-only tool must be able to say "I could not run" out loud. Silently passing would
turn an untested area into a green tick, which is exactly the failure mode plan §18
warns about.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class SkipTest(Exception):
    """Raised by a test that cannot run in this environment.

    The reason is printed by the runner. Use it, do not fake a pass.
    """


def which(tool: str) -> str | None:
    return shutil.which(tool)


def require_tool(tool: str, purpose: str) -> str:
    """Return the path to a tool, or skip the test explaining what is missing."""
    path = which(tool)
    if not path:
        raise SkipTest(f"{tool} is not installed ({purpose})")
    return path


def require_file(path: Path, description: str) -> Path:
    if not path.is_file():
        raise SkipTest(f"{description} not found at {path}")
    return path


def run_command(args: list[str], timeout: int = 60, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run a command, capturing output. Never raises on a non-zero exit."""
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(cwd) if cwd else None,
        errors="replace",
    )


def newest_iso() -> Path | None:
    """The most recently built ISO in dist/, or None."""
    dist = REPO_ROOT / "dist"
    if not dist.is_dir():
        return None
    candidates = sorted(
        dist.glob("*.iso"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def read(relative: str) -> str:
    """Read a repository file as text, tolerating any line endings."""
    return (REPO_ROOT / relative).read_text(encoding="utf-8", errors="replace")


def strip_comments(text: str, marker: str = "#") -> str:
    """Remove comment lines so assertions about content ignore the prose.

    Needed because these files document their own rules: a check for "NOPASSWD" would
    match the comment explaining that NOPASSWD must not be present.
    """
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(marker):
            continue
        lines.append(line)
    return "\n".join(lines)
