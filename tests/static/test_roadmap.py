"""Roadmap document tests.

docs/ROADMAP.md is a plan. A plan drifts in two ways: it can describe unbuilt
things as if they existed, and a rewrite can quietly drop the commitments the rest
of the repository is built around. These checks pin the frame, not the content:

  * a reader must be told the document is a plan and not a description of the
    system, or the component table reads as a feature list;
  * the security invariants (policy decisions outside the model, untrusted
    retrieved content, an audit trail, no self-granted permissions) must survive
    every roadmap edit, because they are the project's stated reason to exist;
  * model independence and the no-telemetry-by-default promise must survive too:
    they are what makes this different from the cloud agent products the document
    contrasts itself with;
  * and the plan must not drift into phrases that would read as though the
    platform already shipped.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DESCRIPTION = (
    "the roadmap says it is a plan, keeps its security invariants, and does not read "
    "as though the platform shipped"
)

ROADMAP = REPO_ROOT / "docs" / "ROADMAP.md"
README = REPO_ROOT / "README.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_the_roadmap_exists_and_says_it_is_a_plan() -> None:
    assert ROADMAP.is_file(), "docs/ROADMAP.md is missing"
    text = _text(ROADMAP)
    assert re.search(r"plan, not the current system", text, re.IGNORECASE), (
        "docs/ROADMAP.md does not say it is a plan; a future reader could mistake it "
        "for a description of the current system"
    )
    assert "does not exist" in text or "not started" in text, (
        "the roadmap marks nothing as unbuilt; unbuilt components must say so"
    )


def test_the_readme_links_the_roadmap() -> None:
    assert "docs/ROADMAP.md" in _text(README), (
        "README.md does not link docs/ROADMAP.md, so the planned direction is "
        "invisible from the project's front page"
    )


def test_the_roadmap_keeps_all_six_stages() -> None:
    text = _text(ROADMAP)
    missing = [n for n in range(1, 7) if not re.search(rf"^## Stage {n}\b", text, re.M)]
    assert not missing, f"the roadmap lost the heading for Stage {missing}"


def test_the_roadmap_keeps_the_security_invariants() -> None:
    text = _text(ROADMAP)
    for phrase in (
        "must never grant itself permission",
        "untrusted input",
        "policy engine",
        "audit",
    ):
        assert phrase in text, (
            f"docs/ROADMAP.md no longer contains {phrase!r}; the security "
            "invariants must survive roadmap edits"
        )


def test_the_roadmap_keeps_model_independence() -> None:
    text = _text(ROADMAP)
    assert "no model installed" in text, (
        "the roadmap no longer says the system works with no model installed"
    )
    assert "no telemetry by default" in text, (
        "the roadmap no longer promises no telemetry by default"
    )


def test_the_roadmap_does_not_describe_unbuilt_things_as_working() -> None:
    text = _text(ROADMAP).lower()
    forbidden = ("is implemented", "already works", "works today", "production-ready")
    hits = [phrase for phrase in forbidden if phrase in text]
    assert not hits, (
        f"docs/ROADMAP.md uses {hits}; a plan must not read as though these things "
        "already work"
    )
