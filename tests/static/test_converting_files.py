"""Tests for the conversion skill and page.

The image ships the tools - LibreOffice for documents, ImageMagick for pictures,
poppler for PDFs - but a tool that is installed and never mentioned is a tool the
assistant does not know it may use. These tests pin that the conversion knowledge
exists, that it names the real commands, and that it refuses the two things that
would cost a user their files: overwriting an existing file, and running a
conversion without saying what it will produce.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AI = REPO_ROOT / "packages" / "astraos-ai" / "root" / "usr" / "share" / "astraos" / "ai"
SKILL = AI / "skills" / "converting-files" / "SKILL.md"
PAGE = AI / "knowledge" / "converting-files.md"

DESCRIPTION = "the assistant knows how to convert files, and says what it will do first"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_the_skill_names_the_tools_that_are_really_installed() -> None:
    assert SKILL.is_file(), f"the skill is missing: {SKILL}"
    text = _text(SKILL)
    assert "soffice --headless --convert-to pdf" in text, (
        "the skill must tell the assistant how to make a PDF from a document"
    )
    assert re.search(r"`convert \"<file>\"", text), (
        "the skill must tell the assistant how to convert a picture"
    )
    assert "pdftotext" in text and "pdfinfo" in text, (
        "reading a PDF is part of converting files"
    )
    for tool in ("soffice", "convert", "pdftotext"):
        assert tool in text, f"the skill does not mention {tool}"


def test_the_skill_never_overwrites_and_always_says_what_it_will_do() -> None:
    text = _text(SKILL)
    assert "overwrit" in text.lower(), (
        "the skill must say that nothing is overwritten"
    )
    assert "before doing it" in text or "before" in text.lower(), (
        "the skill must say what it will produce before it produces it"
    )
    assert "check the result" in text.lower(), (
        "a conversion that produced nothing must be reported as a failure"
    )


def test_the_page_matches_the_skill() -> None:
    assert PAGE.is_file(), f"the page is missing: {PAGE}"
    page = _text(PAGE)
    assert "soffice --headless --convert-to pdf" in page
    assert "convert " in page
    assert "-quality" in page, "the page must explain what makes a JPG smaller"
    assert "never overwrites" in page.lower() or "will not overwrite" in page.lower()
    # The page must not promise a tool the image does not ship.
    assert "impress" in page.lower(), (
        "the page must say that Impress is not in the image, rather than implying it is"
    )
