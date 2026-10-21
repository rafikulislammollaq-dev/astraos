"""Tests for the "can I run this app on AstraOS?" answer.

A person arriving from Windows does not ask about packages; they ask about the
application they already use. The answer has to be one they can act on, and it
has to be honest: "it runs under Wine" is a different promise from "it is
native", and "it works in the browser" is a third.

What these tests pin:

  * the skill exists, in the format the assistant reads (keywords, when, steps,
    notes), so the answer is actually reachable by asking;
  * the table it reads exists and uses the four verdicts - native, Wine, browser,
    no - and says "no" where the truth is "no";
  * the applications people ask about most are in the table, each with an honest
    note rather than a promise.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AI = REPO_ROOT / "packages" / "astraos-ai" / "root" / "usr" / "share" / "astraos" / "ai"
SKILL = AI / "skills" / "can-i-run-this-app" / "SKILL.md"
TABLE = AI / "knowledge" / "windows-applications-on-astraos.md"

DESCRIPTION = "the assistant can answer honestly whether an application runs on AstraOS"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_the_skill_is_in_the_format_the_assistant_reads() -> None:
    assert SKILL.is_file(), f"the skill is missing: {SKILL}"
    text = _text(SKILL)
    assert text.startswith("# "), "a skill starts with its title"
    assert "keywords:" in text, "a skill needs its keywords, or it is never matched"
    assert "when:" in text, "a skill needs to say when it applies"
    assert "## Steps" in text and "## Notes" in text
    assert "apt-cache" in text, (
        "the skill must check the archive rather than answer from memory"
    )


def test_the_table_uses_the_four_verdicts_and_says_no_where_it_is_no() -> None:
    assert TABLE.is_file(), f"the table is missing: {TABLE}"
    text = _text(TABLE)
    for verdict in ("native", "Wine", "browser", "no"):
        assert verdict in text, f"the table does not use the {verdict!r} verdict"
    # The applications people ask about most, each with a row.
    for application in ("Microsoft Word", "Excel", "Photoshop", "Teams", "Zoom", "Spotify"):
        assert application in text, f"the table does not answer about {application}"
    # The honest refusals: a line of business tool and a phone game.
    assert "AutoCAD" in text and "no honest substitute" in text
    assert "Candy Crush" in text and "no native way" in text


def test_the_skill_and_the_table_agree_on_the_verdicts() -> None:
    skill = _text(SKILL)
    for verdict in ("native", "Wine", "browser"):
        assert verdict in skill, (
            f"the skill must use the {verdict!r} verdict, so its answer matches the table"
        )
    assert "does not run on AstraOS" in skill, (
        "the skill must have a sentence for the case where the answer is no"
    )
    assert "windows-applications-on-astraos.md" in skill, (
        "the skill must read the table by the name it is shipped under"
    )
