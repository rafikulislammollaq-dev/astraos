"""Skills: procedures the assistant can read, follow, and that a user can write.

WHAT A SKILL IS

A skill is one markdown file. It has a title, a line of keywords, a line saying
what it requires, a line saying when it applies, and a numbered list of steps.
That is the whole format, and it is deliberately that small: a skill nobody can
read is a skill nobody can fix, and a skill that needs a framework is a skill
that cannot ship in a distribution package with no pip.

    # Summarise a PDF

    keywords: pdf, extract, text, document, summarise, summary
    requires: pdftotext
    when: the user wants the contents of a PDF as text or as a summary
    ---

    ## Steps

    1. Find the file. Use open_file with the path the user gave.
    2. Extract the text with run_command: pdftotext "<file>" -
    3. Say in three bullets what the document is about, and name the file.

    ## Notes

    Extraction is read-only. If a step appears to need a writable copy of the
    PDF, the step is wrong.

The steps are not a program. They are a playbook the worker model follows, one
step at a time, with the real tools in actions.py underneath it. That is the
difference between a skill and a script: a script is right until the input
changes, and a playbook has a model reading it and noticing that the file was
called something else today.

WHY SKILLS LIVE IN TWO PLACES

`/usr/share/astraos/ai/skills` ships with the package, and
`~/.local/share/astraos/ai/skills` is the user's. The user's wins on a name
collision, because a person who wrote their own skill for their own machine
meant it. Nothing is ever read from root-owned paths by the assistant at run
time: the whole point is that adding a skill is editing a text file in your own
home directory, not a package operation.

WHY EVERYTHING IS PARSED FROM TEXT AND NOT IMPORTED

There is no registry, no JSON manifest and no code to load. `astra-ai skills`
lists what the directory holds, the search index indexes it like any other
passage, and the catalogue the planner sees is the same text a human reads. A
skill that the assistant cannot see in the catalogue does not exist, and one
that the human cannot read cannot be diagnosed.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from . import config as _config

# Shipped by the package, and the user's own. Searched in that order, with the
# user's taking precedence on a name collision.
SHIPPED_SKILLS = _config.PATHS.share_dir / "skills"
USER_SKILLS = _config.PATHS.models_dir.parent / "skills"

# A skill whose requirements are missing is still listed - it says which - but
# it is marked unusable, so the assistant can answer "I can do that once you
# install poppler-utils" instead of failing half-way through a procedure.
REQUIRES_SEPARATOR = re.compile(r"[,;/]")


class Skill:
    """One skill: what it is for, what it needs, and what it tells the worker."""

    def __init__(self, path: Path, directory_label: str):
        self.path = path
        self.name = path.parent.name if path.parent != path else path.stem
        self.title = path.stem.replace("-", " ").replace("_", " ").strip()
        self.keywords: list[str] = []
        self.requires: list[str] = []
        self.when = ""
        self.notes = ""
        self.steps: list[str] = []
        self.directory = directory_label
        self._parse()

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse(self) -> None:
        """Read the markdown. A malformed skill is a skill with no body.

        The failure mode matters more than the parser: a skill that cannot be
        parsed still appears in the catalogue with a reason, because the
        alternative - silently leaving it out - means a user who writes a skill
        and sees nothing happen has no way to find out why.
        """
        try:
            text = self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self.notes = f"could not be read: {exc}"
            return

        lines = text.splitlines()
        header: list[str] = []
        body_start = 0
        for index, line in enumerate(lines):
            if line.strip() in ("---", "***"):
                body_start = index + 1
                break
            header.append(line)
        else:
            header = []
            body_start = 0

        for line in header:
            stripped = line.strip()
            if stripped.startswith("# ") and self.title == self.path.stem:
                self.title = stripped[2:].strip()
                continue
            # Three spellings of the same fields are accepted, because a skill
            # is written by whoever wrote it: this distribution's compact form,
            # and the Agent Skills spec (anthropic.com/engineering/
            # equipping-agents-for-the-real-world-with-agent-skills,
            # agentskills.io) which is what a skill found elsewhere will use. A
            # skill that has to be rewritten before it works is a skill nobody
            # installs, so `description` is read as `when` and `triggers` is
            # read as `keywords`.
            if stripped.lower().startswith("description:") and not self.when:
                self.when = stripped.split(":", 1)[1].strip().strip("`").strip()
                continue
            for field in ("keywords", "triggers", "requires", "when"):
                if stripped.lower().startswith(field + ":"):
                    value = stripped.split(":", 1)[1].strip().strip("`").strip()
                    if field in ("keywords", "triggers"):
                        self.keywords = [
                            word.strip().lower()
                            for word in REQUIRES_SEPARATOR.split(value)
                            if word.strip()
                        ]
                    elif field == "requires":
                        self.requires = [
                            word.strip()
                            for word in REQUIRES_SEPARATOR.split(value)
                            if word.strip()
                        ]
                    else:
                        self.when = value
                    break

        if not self.keywords:
            # Fall back to the words of the title, so a skill with no keyword
            # line is still findable by what it is called.
            self.keywords = [
                word.lower()
                for word in re.findall(r"[a-z]{4,}", self.title.lower())
            ]

        self._parse_steps("\n".join(lines[body_start:]))

    def _parse_steps(self, body: str) -> None:
        """The numbered list after "## Steps", and everything after it as notes."""
        in_steps = False
        notes: list[str] = []
        for line in body.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("## steps"):
                in_steps = True
                continue
            if stripped.startswith("## "):
                in_steps = False
                continue
            if in_steps:
                match = re.match(r"^(\d+)[.)]\s+(.*)$", stripped)
                if match:
                    self.steps.append(match.group(2).strip())
                    continue
                if self.steps and stripped:
                    # A continuation line belongs to the step above it: the
                    # numbered form is what a person reads and what a parser
                    # must not lose half of.
                    self.steps[-1] = f"{self.steps[-1]} {stripped}"
                    continue
                if not stripped:
                    continue
            notes.append(line)
        self.notes = "\n".join(notes).strip()

    # ------------------------------------------------------------------
    # What can be said about it
    # ------------------------------------------------------------------

    def missing(self) -> list[str]:
        """The requirements this machine does not have, as command names."""
        return [name for name in self.requires if shutil.which(name) is None]

    def usable(self) -> bool:
        return not self.missing()

    def score(self, query: str) -> int:
        """How well a question matches this skill.

        Deliberately simple and deterministic. Synonym-aware retrieval is the
        index's job (knowledge.py indexes the keywords and the body together);
        this is the part that must be explainable, because a user who asks "why
        did it pick that skill?" gets an answer made of words they can check:
        the title, a keyword, or a phrase from the requirements.
        """
        words = re.findall(r"[a-z0-9_.-]+", (query or "").lower())
        if not words:
            return 0
        score = 0
        title_words = set(re.findall(r"[a-z0-9_.-]+", self.title.lower()))
        for word in words:
            if word in title_words:
                score += 3
            if word in self.keywords:
                score += 2
            if word in [need.lower() for need in self.requires]:
                score += 1
        for phrase in (self.when, self.notes):
            lowered = phrase.lower()
            for word in words:
                if word and word in lowered:
                    score += 1
        return score

    # ------------------------------------------------------------------
    # The text the model is given
    # ------------------------------------------------------------------

    def summary(self) -> str:
        """One entry for the planner's catalogue: name, when, and what it needs."""
        lines = [f"{self.name}: {self.title}"]
        if self.when:
            lines.append(f"  when: {self.when}")
        if self.keywords:
            lines.append(f"  keywords: {', '.join(self.keywords)}")
        missing = self.missing()
        if missing:
            lines.append(f"  needs: {', '.join(missing)} (not installed)")
        return "\n".join(lines)

    def brief(self) -> str:
        """Everything about the skill, for the worker that is about to run it."""
        lines = [
            f"# Skill: {self.title} ({self.name})",
            f"when: {self.when or 'any time the user asks for this'}",
            "",
            "## Steps",
        ]
        lines.extend(f"{index}. {step}" for index, step in enumerate(self.steps, 1))
        if self.notes:
            lines.extend(["", "## Notes", self.notes])
        return "\n".join(lines)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Skill {self.name} steps={len(self.steps)}>"


def directories() -> list[tuple[Path, str]]:
    """The skill directories to read, user's first."""
    found = [(USER_SKILLS, "your own skills")]
    if SHIPPED_SKILLS.is_dir():
        found.append((SHIPPED_SKILLS, "AstraOS skills"))
    return [(path, label) for path, label in found if path.is_dir()]


def load_all() -> list[Skill]:
    """Every installed skill. A skill is a SKILL.md inside a named directory."""
    skills: dict[str, Skill] = {}
    for directory, label in directories():
        for path in sorted(directory.glob("*/SKILL.md")):
            skill = Skill(path, label)
            if not skill.name:
                continue
            # The user's directory is read first, so it overwrites.
            skills.setdefault(skill.name, skill)
    return [skills[name] for name in sorted(skills)]


def by_name(name: str) -> Skill | None:
    """One skill by its directory name, case-insensitively."""
    wanted = (name or "").strip().lower()
    for skill in load_all():
        if skill.name.lower() == wanted:
            return skill
    return None


def matching(query: str, limit: int = 5) -> list[Skill]:
    """The skills a question is about, best first, lowest score 1."""
    scored = [(skill.score(query), skill) for skill in load_all()]
    scored = [(score, skill) for score, skill in scored if score > 0]
    scored.sort(key=lambda pair: (-pair[0], pair[1].name))
    return [skill for _score, skill in scored[: max(0, int(limit))]]


def catalogue(limit: int = 40) -> str:
    """Every skill as the planner sees it.

    The planner is given the whole catalogue rather than the retrieved top two,
    because picking the wrong skill costs one step while failing to mention a
    skill that existed costs the whole task - and because the catalogue is small
    enough (a few hundred lines at the shipped count) to fit beside a question.
    """
    skills = load_all()[: max(0, int(limit))]
    if not skills:
        return "(no skills are installed)"
    return "\n".join(skill.summary() for skill in skills)


def stats() -> dict:
    skills = load_all()
    return {
        "count": len(skills),
        "usable": sum(1 for skill in skills if skill.usable()),
        "shipped": SHIPPED_SKILLS.is_dir(),
        "user_dir": str(USER_SKILLS),
    }
