"""The offline help centre, and the promise it makes.

The assistant's corpus - the `knowledge/` pages and the `skills/` - is the answer
to "how do I ...?" written for this distribution. This module pins the help centre
that turns it into something a person can read:

  * the page is generated from the corpus, and regenerating it must produce the
    committed file byte for byte. A page that drifts from the corpus is worse than
    no page: it answers with something the system no longer says;
  * it works with no network at all. Every link in it points at this machine;
  * every topic in the corpus is in the page, and the search box is there to find
    it - a help centre that hides half the answers is not one;
  * it is reachable from the desktop, not only by knowing the file name.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "scripts" / "build-help-center.py"
CORPUS = (
    REPO_ROOT / "packages" / "astraos-ai" / "root" / "usr" / "share" / "astraos" / "ai"
)
HELP_HTML = CORPUS / "web" / "help.html"
DESKTOP_ENTRY = (
    REPO_ROOT / "packages" / "astraos-ai" / "root" / "usr" / "share" / "applications"
    / "astraos-help.desktop"
)

DESCRIPTION = "the offline help centre is generated from the corpus and works without a network"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_the_committed_page_is_what_the_generator_writes() -> None:
    """The page cannot drift from the corpus it is built from."""
    assert GENERATOR.is_file(), f"the generator is missing: {GENERATOR}"
    assert HELP_HTML.is_file(), f"the help page is missing: {HELP_HTML}"

    with tempfile.TemporaryDirectory(prefix="astraos-help-") as workdir:
        rebuilt = Path(workdir) / "help.html"
        result = subprocess.run(
            [sys.executable, str(GENERATOR), "--corpus", str(CORPUS), "--out", str(rebuilt)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"the generator failed: {result.stderr}"
        # Compared with the line endings normalised: what matters is the content,
        # and a checkout on one platform may carry CRLF while the other carries LF.
        rebuilt_text = rebuilt.read_text(encoding="utf-8").replace("\r\n", "\n")
        committed_text = HELP_HTML.read_text(encoding="utf-8").replace("\r\n", "\n")
        assert rebuilt_text == committed_text, (
            "the committed help page is not what the generator produces from the corpus. "
            "Run scripts/build-help-center.py and commit what it writes."
        )


def test_every_topic_in_the_corpus_is_in_the_page() -> None:
    page = _text(HELP_HTML)
    knowledge = sorted((CORPUS / "knowledge").glob("*.md"))
    skills = sorted((CORPUS / "skills").glob("*/SKILL.md"))
    assert knowledge, "the corpus holds no knowledge pages"
    assert skills, "the corpus holds no skills"

    for path in knowledge:
        title = ""
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
        assert title, f"{path.name} has no title"
        assert f"<h1>{title}</h1>" in page, f"the page does not carry {path.name}"
    for path in skills:
        title = path.parent.name.replace("-", " ")
        assert title.split()[0].lower() in page.lower(), (
            f"the page does not carry the skill {path.parent.name}"
        )

    articles = len(re.findall(r"<article id=", page))
    assert articles == len(knowledge) + len(skills), (
        f"the page holds {articles} topic(s) and the corpus holds "
        f"{len(knowledge) + len(skills)}; one of them is missing"
    )


def test_the_page_works_with_no_network() -> None:
    page = _text(HELP_HTML)
    assert 'id="search"' in page, "the page has no search box"
    assert "ASTRAOS_HELP_TOPICS" in page, (
        "the search needs the topics in the page itself, or it would need a server"
    )
    for href in re.findall(r'href="(https?://[^"]+)"', page):
        assert re.match(r"https?://(127\.0\.0\.1|localhost)", href), (
            f"the page links off the machine ({href}); an offline help centre must "
            "not need the network"
        )
    assert not re.search(r"<script[^>]+src=", page), (
        "the page must not load a script from anywhere else"
    )
    assert not re.search(r"<link[^>]+href=\"https?://", page), (
        "the page must not load a stylesheet from anywhere else"
    )
    assert not re.search(r"<img[^>]+src=\"https?://", page), (
        "the page must not load an image from anywhere else"
    )


def test_the_help_centre_is_reachable_from_the_desktop() -> None:
    assert DESKTOP_ENTRY.is_file(), f"the launcher is missing: {DESKTOP_ENTRY}"
    entry = _text(DESKTOP_ENTRY)
    assert "Type=Application" in entry
    assert "Name=AstraOS Help" in entry
    assert "/usr/share/astraos/ai/web/help.html" in entry, (
        "the launcher must open the page the package installs"
    )
    assert "Terminal=false" in entry
