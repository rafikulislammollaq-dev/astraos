"""Blueprint document tests.

docs/blueprints/ holds the designs for the experiences AstraOS promises but has
not built: the first-boot question, profiles, one store, roll-backable updates,
the phone link, the system assistant, privacy, reach, creator packs, the
community rails, and the long-horizon pillars (the mesh, the timeline, the
canvas, the graph). A blueprint is a plan; the risks are that one starts reading
like state, or that a rewrite quietly drops the honest limits each design
records. These checks pin the shape and a few load-bearing sentences, not the
content.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DESCRIPTION = (
    "blueprints stay plans, keep their four sections, and keep their honest limits"
)

BLUEPRINTS = REPO_ROOT / "docs" / "blueprints"
INDEX = BLUEPRINTS / "README.md"
ROADMAP = REPO_ROOT / "docs" / "ROADMAP.md"

NAMES = (
    "FIRST_BOOT",
    "PROFILES",
    "APP_STORE",
    "UNBREAKABLE",
    "PHONE_LINK",
    "OS_AI",
    "PRIVACY",
    "REACH",
    "CREATORS",
    "COMMUNITY",
    "MESH",
    "TIMELINE",
    "CANVAS",
    "GRAPH",
)

SECTIONS = (
    "## The promise",
    "## How it works",
    "## Honest boundaries",
    "## How this gets proven",
)

# One sentence per blueprint that carries its honesty. If a rewrite removes
# one, it must be a deliberate edit with its reason in the commit message.
LOAD_BEARING_LIMITS = {
    "PROFILES": "not separate operating systems",
    "APP_STORE": "origin badge never disappears",
    "UNBREAKABLE": "not image-atomic",
    "PHONE_LINK": "Apple",
    "OS_AI": "No root",
    "PRIVACY": "No telemetry by default",
    "REACH": "aarch64",
    "CREATORS": "Adobe",
    "COMMUNITY": "cannot be designed into existence",
    "MESH": "the data is truly gone",
    "TIMELINE": "The outside world cannot be rewound",
    "CANVAS": "Closed programs stay closed",
    "GRAPH": "never the only copy",
}


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_every_blueprint_exists_and_is_marked_unbuilt() -> None:
    for name in NAMES:
        path = BLUEPRINTS / f"{name}.md"
        assert path.is_file(), f"docs/blueprints/{name}.md is missing"
        text = _text(path)
        assert re.search(r"Nothing (in this document|here) is implemented", text), (
            f"docs/blueprints/{name}.md does not say it is unbuilt; a blueprint "
            "must never read as a feature list"
        )


def test_every_blueprint_keeps_the_four_sections() -> None:
    for name in NAMES:
        text = _text(BLUEPRINTS / f"{name}.md")
        missing = [section for section in SECTIONS if section not in text]
        assert not missing, (
            f"docs/blueprints/{name}.md lost {missing}; every blueprint keeps "
            "the promise, the mechanism, the honest boundaries and the proof plan"
        )


def test_the_index_lists_every_blueprint() -> None:
    text = _text(INDEX)
    missing = [name for name in NAMES if f"{name}.md" not in text]
    assert not missing, f"docs/blueprints/README.md does not link {missing}"


def test_the_blueprints_keep_their_load_bearing_limits() -> None:
    for name, phrase in LOAD_BEARING_LIMITS.items():
        text = _text(BLUEPRINTS / f"{name}.md")
        assert phrase in text, (
            f"docs/blueprints/{name}.md no longer contains {phrase!r}; the honest "
            "limit must stay until the thing behind it is actually proven"
        )


def test_the_roadmap_points_at_the_blueprints() -> None:
    assert "docs/blueprints/" in _text(ROADMAP), (
        "docs/ROADMAP.md no longer links the blueprints; the designs would be "
        "invisible from the plan they belong to"
    )
