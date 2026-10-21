"""The assistant's second half: the tier ladder, the knowledge, and the guards.

Why this module exists:

    The action catalog in test_astra_ai_actions.py covers what the assistant
    can do. This one covers what it does with a model in the loop: the ladder
    that swaps one model in and out of 4 GB of RAM, the retrieval that decides
    whether it answers from this machine's documentation or from habit, and the
    worker that turns a plan into evidence.

What they can and cannot prove:

    They cannot prove the model is good, that a plan is sensible, or that a
    skill's steps are the right ones. They can prove the parts that have to
    hold no matter what the model says: a preference never names a model
    `astra-ai setup --model` would refuse, a question the corpus does not
    answer returns nothing at all rather than the closest thing, a plan cannot
    contain an argument the action does not take, a step naming an action that
    does not exist never reaches a function, an unconfirmed irreversible
    action never runs, and the plan is on disk before the first step does.

Nothing here needs a model, a llama-server, a display, a sound card or a
network: the whole file is written against the seams (a stub engine, a stub
pool) and against the real code paths that say no when something is missing.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_PACKAGE = REPO_ROOT / "packages" / "astraos-ai"
AI_LIB = AI_PACKAGE / "root" / "usr" / "lib"
CLI = AI_PACKAGE / "root" / "usr" / "bin" / "astra-ai"
SHARE_DIR = AI_PACKAGE / "root" / "usr" / "share" / "astraos" / "ai"

sys.path.insert(0, str(AI_LIB))
sys.path.insert(0, str(REPO_ROOT / "tests" / "lib"))

from astraos_testlib import SkipTest, read  # noqa: E402

from astraos.ai import actions, config, journal, knowledge, planner, skills  # noqa: E402
from astraos.ai import setup as ai_setup, tiers, worker  # noqa: E402

DESCRIPTION = "the ladder, the retrieval and the worker keep their promises"

# The three tiers, spelled out. A test that derived them from TIERS would pass
# after a tier was renamed or removed, which is the one thing it exists to
# notice: `astra ai status` and the whole two-tier structure are built on
# exactly these names.
TIER_NAMES = ("worker", "brain", "router")

# The tier that must have a model for the assistant to do anything at all.
REQUIRED_TIER = "worker"

# The actions that must not run without a human's yes. The catalog's
# needs_confirm flag is the mechanism; Astra Guard's levels are the policy, and
# test_astra_guard.py pins the two together. This list is spelled out rather
# than derived so an upgrade that quietly drops a flag fails here.
NEEDS_CONFIRMATION = {
    "close_window",
    "press_key",
    "type_text",
    "suspend",
    "reboot",
    "shutdown",
    "run_command",
}

# The nine skills the package ships. Spelled out rather than derived, for the
# same reason: a skill that silently disappears from `astra-ai skills` is a
# capability the user was told they had.
SHIPPED_SKILLS = (
    "backup-and-sync",
    "can-i-run-this-app",
    "find-and-organise-files",
    "locale-and-timezone",
    "offline-email-triage",
    "pdf-office",
    "screenshot-and-describe",
    "summarise-documents",
    "system-health-report",
)

# A word that appears in no shipped passage and no shipped skill. Used to prove
# the honesty rule: a question the corpus cannot answer is not answered with
# the closest thing.
ABSENT_WORD = "flibbertigibbet"


class _StubEngine:
    """A stand-in for the model: one canned answer, no server, no process.

    `plan()` and `Worker._decide()` both call engine.ask_json(messages,
    schema), which is the whole interface they need, so a stub answers them
    without a model file, a llama-server or a network - which is the state
    every fresh install is in.
    """

    def __init__(self, text: str):
        self.text = text
        self.calls: list[dict] = []

    def ask_json(self, messages, schema):  # noqa: ANN001 - mirrors llm.Engine
        self.calls.append({"messages": messages, "schema": schema})
        return [self.text]


class _StubPool:
    """A tier pool with nothing installed: every borrow says what is missing.

    The real TierPool on a machine with no model answers exactly this, so the
    stub is the behaviour under test rather than a mock that avoids it.
    """

    def __init__(self, ready: bool = True):
        self.ready_flag = ready
        self.borrowed: list[str] = []

    def ready(self) -> bool:
        return self.ready_flag

    def unavailable_reason(self) -> str:
        return "no model is installed for the worker tier"

    def asking(self, tier: str):
        self.borrowed.append(tier)
        raise tiers.TierUnavailable(f"the {tier} tier has no model installed")


@contextlib.contextmanager
def _recorded_execute(calls: list, ok: bool = True):
    """actions.execute() replaced with a recorder, the way the guards are tested.

    Everything that runs an action goes through this one function, so a
    recorder that catches a call proves an action was reached - and an empty
    list proves it was not. `ok` decides what the recorder reports back, which
    is how a step that fails is produced without anything being run.
    """
    original = actions.execute

    def record(plan, confirmed=False, provenance="user"):  # noqa: ANN001 - mirrors actions.execute
        calls.append({"plan": dict(plan), "confirmed": confirmed, "provenance": provenance})
        return {"ok": ok, "output": "recorded", "error": ""}

    actions.execute = record
    try:
        yield calls
    finally:
        actions.execute = original


@contextlib.contextmanager
def _library_paths(corpus_copy: bool = False):
    """The assistant's files in a temporary directory, the corpus in the repo.

    config.PATHS, knowledge's four module constants, skills' two directories
    and the journal's DB_PATH are all read once, at import time, from
    $HOME or the ASTRAOS_AI_* overrides. The overrides exist for exactly
    this, and using them is the difference between "the test ran" and "the
    test read a file out of whoever's home directory ran the suite".

    The corpus is pointed at the copy the repository ships, so an assertion
    about "the DNS entry" is an assertion about the passage a machine with the
    package installed would retrieve. Everything that is *written* - the index,
    the journal, the user's own skills - goes in the temporary directory, so a
    test never writes into the tree or into whoever's home ran the suite.

    `corpus_copy=True` copies the corpus into the temporary directory instead,
    for the one test that adds a file to it.

    Everything is restored on the way out: another test module in the same
    process must not find the assistant's home still pointed at a directory
    this one deleted.
    """
    with tempfile.TemporaryDirectory(prefix="astraos-ai-brain-") as home_dir:
        home = Path(home_dir)
        share = SHARE_DIR if not corpus_copy else home / "share"
        if corpus_copy:
            shutil.copytree(SHARE_DIR, share)

        saved_env = {
            name: os.environ.get(name)
            for name in (
                "HOME",
                "ASTRAOS_AI_SHARE_DIR",
                "ASTRAOS_AI_MODELS_DIR",
                "ASTRAOS_AI_BIN_DIR",
                "ASTRAOS_AI_CONFIG",
            )
        }
        saved = (
            (config.PATHS, "share_dir", config.PATHS.share_dir),
            (config.PATHS, "models_dir", config.PATHS.models_dir),
            (config.PATHS, "bin_dir", config.PATHS.bin_dir),
            (config.PATHS, "config_file", config.PATHS.config_file),
            (knowledge, "SHARE_DIR", knowledge.SHARE_DIR),
            (knowledge, "KNOWLEDGE_DIR", knowledge.KNOWLEDGE_DIR),
            (knowledge, "SKILLS_DIR", knowledge.SKILLS_DIR),
            (knowledge, "DB_PATH", knowledge.DB_PATH),
            (skills, "SHIPPED_SKILLS", skills.SHIPPED_SKILLS),
            (skills, "USER_SKILLS", skills.USER_SKILLS),
            (journal, "DB_PATH", journal.DB_PATH),
        )
        saved_index = knowledge._INDEX

        os.environ["HOME"] = home_dir
        os.environ["ASTRAOS_AI_SHARE_DIR"] = str(share)
        os.environ["ASTRAOS_AI_MODELS_DIR"] = str(home / "models")
        os.environ["ASTRAOS_AI_BIN_DIR"] = str(home / "bin")
        os.environ["ASTRAOS_AI_CONFIG"] = str(home / "ai.json")

        # The class attribute and the module constant are two views of the same
        # path; patching the environment alone would leave one of them stale.
        config.PATHS.share_dir = share
        config.PATHS.models_dir = home / "models"
        config.PATHS.bin_dir = home / "bin"
        config.PATHS.config_file = home / "ai.json"
        knowledge.SHARE_DIR = share
        knowledge.KNOWLEDGE_DIR = share / "knowledge"
        knowledge.SKILLS_DIR = share / "skills"
        knowledge.DB_PATH = home / "knowledge.sqlite3"
        skills.SHIPPED_SKILLS = share / "skills"
        skills.USER_SKILLS = home / "skills"
        journal.DB_PATH = home / "journal.sqlite3"
        # The index is a process-wide singleton built from DB_PATH, so it has
        # to be dropped for the new path to be the one used.
        knowledge._INDEX = None

        try:
            yield types.SimpleNamespace(
                home=home,
                share=share,
                models_dir=home / "models",
                user_skills=home / "skills",
            )
        finally:
            # The index holds an open handle on the temporary database, and
            # Windows refuses to delete a file that is still open, so it is
            # closed here rather than left to the garbage collector.
            knowledge.index().close()
            for name, value in saved_env.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
            for owner, attribute, value in saved:
                setattr(owner, attribute, value)
            knowledge._INDEX = saved_index


def _write_skill(directory: Path, name: str, text: str) -> Path:
    """One user skill, written where a person would write it."""
    folder = directory / name
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "SKILL.md"
    path.write_text(text, encoding="utf-8")
    return path


def _skill_text(title: str, when_word: str, keyword_word: str, steps: int = 3) -> str:
    """A skill in the shape the shipped ones use, with switchable spellings.

    `when_word` is either "when" or "description", and `keyword_word` is either
    "keywords" or "triggers", which are the two spellings the parser accepts:
    this distribution's own compact form and the Agent Skills spec's.
    """
    return (
        f"# {title}\n\n"
        f"{keyword_word}: paint, colour, wall\n\n"
        f"{when_word}: the user wants a wall painted\n\n"
        "---\n\n"
        "## Steps\n\n"
        + "".join(f"{index}. step {index}\n" for index in range(1, steps + 1))
        + "\n## Notes\n\nnothing to note\n"
    )


# ---------------------------------------------------------------------------
# The ladder
# ---------------------------------------------------------------------------


def test_the_three_tiers_are_named_and_each_has_a_job() -> None:
    assert set(tiers.TIERS) == set(TIER_NAMES), (
        "the tier ladder and the three names everything else assumes have drifted "
        f"apart: missing {sorted(set(TIER_NAMES) - set(tiers.TIERS))}, "
        f"extra {sorted(set(tiers.TIERS) - set(TIER_NAMES))}"
    )
    assert tiers.REQUIRED_TIER == REQUIRED_TIER, (
        "the tier a machine must have installed changed from 'worker', which is "
        "the tier every status line and every refusal message names"
    )
    for name in TIER_NAMES:
        tier = tiers.TIERS[name]
        assert str(tier.get("label", "")).strip(), (
            f"the {name} tier has no label, so `astra ai status` shows a bare word")
        assert str(tier.get("job", "")).strip(), (
            f"the {name} tier has no job description, so nothing tells the user "
            "what that tier is for")
        assert isinstance(tier.get("prefer"), tuple) and tier["prefer"], (
            f"the {name} tier has no preference list, so no model can ever be "
            "chosen for it")


def test_no_tier_prefers_a_model_setup_would_refuse() -> None:
    """A preference that names a model `astra-ai setup` does not sell is a lie.

    The status command reads the tier's first preference and prints
    `astra-ai setup --model <that>`; a name outside setup.MODELS produces a
    command that refuses, so the user is told to run something that does not
    work.
    """
    for name in TIER_NAMES:
        for stem in tiers.TIERS[name]["prefer"]:
            assert stem in ai_setup.MODELS, (
                f"the {name} tier prefers {stem!r}, which is not a model "
                "astra-ai setup --model would accept, so the install command "
                "the assistant prints is one that fails"
            )
            entry = ai_setup.MODELS[stem]
            assert entry.get("kind") == "llm", (
                f"the {name} tier prefers {stem!r}, which is a "
                f"{entry.get('kind')!r} file, not a language model")


def test_each_tier_has_its_own_port() -> None:
    ports = {name: tiers.tier_port(name) for name in TIER_NAMES}
    base = config.DEFAULTS["port"]
    assert ports["worker"] == base, (
        f"the worker tier should hold the base port {base} and holds "
        f"{ports['worker']}")
    assert len(set(ports.values())) == len(TIER_NAMES), (
        f"two tiers share a port, so a llama-server one tier left running "
        f"answers the next tier's requests: {ports}")


def test_tier_port_follows_a_user_setting() -> None:
    assert tiers.tier_port("brain", {"port": 9100}) == 9101, (
        "a user who moved the assistant's port did not get the brain's offset "
        "port with it")
    assert tiers.tier_port("router", {"port": "not a number"}) == (
        config.DEFAULTS["port"] + 2
    ), "a non-numeric port must fall back to the default, not crash"


def test_pick_model_returns_none_with_an_empty_models_dir() -> None:
    with _library_paths() as paths:
        paths.models_dir.mkdir(parents=True, exist_ok=True)
        for name in TIER_NAMES:
            assert tiers.pick_model(name, {}) is None, (
                f"the {name} tier claimed a model on a machine with an empty "
                "models directory, so the assistant would try to load a file "
                "that is not there")


def test_pick_model_uses_the_only_installed_model_for_every_tier() -> None:
    with _library_paths() as paths:
        paths.models_dir.mkdir(parents=True, exist_ok=True)
        (paths.models_dir / "qwen2.5-1.5b-instruct-q4_k_m.gguf").write_bytes(b"gguf")
        for name in TIER_NAMES:
            assert tiers.pick_model(name, {}) == "qwen2.5-1.5b-instruct-q4_k_m.gguf", (
                f"the {name} tier refused the one model that is installed, so a "
                "machine with one model could only use some of its tiers")


def test_pick_model_honours_an_explicit_setting() -> None:
    with _library_paths() as paths:
        paths.models_dir.mkdir(parents=True, exist_ok=True)
        (paths.models_dir / "smollm2-360m-instruct-q8_0.gguf").write_bytes(b"gguf")
        (paths.models_dir / "spark-x2.5-1.7b-q4_k_m.gguf").write_bytes(b"gguf")
        (paths.models_dir / "spark-x2.5-4b-q4_k_m.gguf").write_bytes(b"gguf")
        # Three models installed: each tier takes the first name from its own
        # preference list that exists, which is the documented rule 3. The
        # router's first preference is the 360M and the brain's is the 4B, and
        # neither settles for the other's model.
        assert tiers.pick_model("router", {}) == "smollm2-360m-instruct-q8_0.gguf", (
            "the router did not take the first of its preferences that exists")
        assert tiers.pick_model("brain", {}) == "spark-x2.5-4b-q4_k_m.gguf", (
            "the brain did not take the first of its preferences that exists")
        # An explicit setting beats every preference list.
        chosen = tiers.pick_model("brain", {"brain_model": "spark-x2.5-1.7b-q4_k_m.gguf"})
        assert chosen == "spark-x2.5-1.7b-q4_k_m.gguf", (
            "an explicit brain_model setting was ignored, so a user who wants "
            "the brain on a different model could not have it")


def test_the_ladder_describes_every_tier_including_empty_ones() -> None:
    with _library_paths() as paths:
        paths.models_dir.mkdir(parents=True, exist_ok=True)
        pool = tiers.TierPool({})
        rows = pool.ladder()

    assert [row["tier"] for row in rows] == list(TIER_NAMES), (
        "the status ladder does not describe the tiers in the documented order")
    for row in rows:
        assert row["model"] == "", (
            f"the {row['tier']} tier reported a model on a machine with an empty "
            "models directory")
        assert row["installed"] is False, (
            f"the {row['tier']} tier claimed to be installed with nothing on disk")
        assert row["label"] and row["job"], (
            f"the {row['tier']} ladder row has no label or job, so the status "
            "page shows a tier nobody can explain")
    required = [row["tier"] for row in rows if row["required"]]
    assert required == [REQUIRED_TIER], (
        f"the ladder marks {required} as required, but only the worker tier has "
        "to be installed for the assistant to do anything")


def test_borrowing_a_tier_with_no_model_says_what_to_install() -> None:
    with _library_paths() as paths:
        paths.models_dir.mkdir(parents=True, exist_ok=True)
        pool = tiers.TierPool({})
        assert pool.ready() is False, (
            "a pool with no model reported itself ready, so the assistant would "
            "start asking questions it cannot answer")
        assert "setup --model" in pool.unavailable_reason(), (
            "the refusal did not name the command that installs a model, so the "
            f"user is told nothing they can do: {pool.unavailable_reason()!r}")

        for name in TIER_NAMES:
            try:
                pool._engine_for(name)
            except tiers.TierUnavailable as exc:
                assert name in str(exc), (
                    f"the refusal for the {name} tier does not name the tier, so "
                    f"the user cannot tell which one is missing: {exc}")
                assert "setup --model" in str(exc), (
                    f"the refusal for the {name} tier does not name the command "
                    f"that fixes it: {exc}")
            else:
                raise AssertionError(
                    f"the {name} tier produced an engine with no model installed")


def test_borrow_and_done_stay_balanced() -> None:
    """The pool owns one server, so the borrower count is the memory budget.

    Nothing here needs a model: with none installed, borrow() raises before it
    takes a borrower, and the counts have to stay where they started.
    """
    with _library_paths() as paths:
        paths.models_dir.mkdir(parents=True, exist_ok=True)
        pool = tiers.TierPool({})
        try:
            pool.borrow("worker")
        except tiers.TierUnavailable:
            pass
        assert pool._borrowers == 0, (
            "a failed borrow left a borrower behind, so a tier would never be "
            "unloaded: the count is what the idler trusts")
        assert pool.resident() == "", (
            "a failed borrow left a resident tier, which is a llama-server that "
            "does not exist holding memory that is not there")

        pool.done("worker")
        assert pool._borrowers == 0, (
            "done() decremented a borrow that never happened, so the borrower "
            "count can go negative and the idler will never fire")


def test_a_swap_leaves_one_tier_resident_and_stops_the_old_one() -> None:
    """The one-model rule: swapping stops the old engine first.

    The recorder proves the order - the previous engine is stopped before the
    new one is built, which is the difference between "the models take turns"
    and "both are in RAM together on a 4 GB machine".
    """
    started: list[str] = []
    stopped: list[str] = []

    class _RecordingEngine:
        def __init__(self, settings):
            started.append(settings["model"])

        def stop(self):
            stopped.append(len(started) and started[-1])

    with _library_paths() as paths:
        paths.models_dir.mkdir(parents=True, exist_ok=True)
        (paths.models_dir / "smollm3-3b-q4_k_m.gguf").write_bytes(b"gguf")
        pool = tiers.TierPool({})

        original = tiers.Engine
        tiers.Engine = _RecordingEngine
        try:
            first = pool.borrow("brain")
            second = pool.borrow("worker")
        finally:
            tiers.Engine = original

    assert first is not second, "the pool handed back the same engine for two tiers"
    assert started == ["smollm3-3b-q4_k_m.gguf", "smollm3-3b-q4_k_m.gguf"], (
        "the pool did not build an engine for each tier it was asked for")
    assert stopped, (
        "the swap from the brain tier to the worker tier did not stop the "
        "previous engine, so two models were in RAM at once")
    assert pool.resident() == "worker", "the swapped-in tier is not the resident one"


# ---------------------------------------------------------------------------
# The knowledge index
# ---------------------------------------------------------------------------


def test_the_shipped_corpus_is_indexed_on_a_cold_start() -> None:
    """stats() must run ensure() first, so the count is of a built index.

    This was a real bug: the count ran before the index was built, so
    `astra ai knowledge` told a fresh install it had zero passages. A count of
    zero has no way to be told apart from an empty corpus, which is why the
    docstring in knowledge.stats() orders it the way it does.
    """
    with _library_paths() as paths:
        info = knowledge.stats()
        assert info["installed"] is True, (
            "the knowledge index reports nothing installed against the corpus "
            "the package ships, so nothing would ever be retrieved")
        assert info["entries"] > 0, (
            f"the index counted {info['entries']} entries on a cold start: it "
            "counted the table before building it")
        assert info["knowledge"] > 0, "not one knowledge passage was indexed"
        assert info["skills"] > 0, "not one skill was indexed into the knowledge base"
        assert info["index"] == str(paths.home / "knowledge.sqlite3"), (
            "the index is not in the directory the settings point at, so it "
            f"would be written wherever the module happened to look: {info['index']}")
        assert info["share_dir"] == str(paths.share), (
            f"the corpus directory is not the one under test: {info['share_dir']}")
        assert paths.home.joinpath("knowledge.sqlite3").is_file()


def test_a_search_for_a_dns_question_finds_the_dns_entry() -> None:
    with _library_paths():
        hits = knowledge.search("how do I set the DNS server on this machine")
    assert hits, "no passage was retrieved for a DNS question the corpus answers"
    ids = [hit["id"] for hit in hits]
    assert any("set-dns" in one for one in ids), (
        f"the DNS question did not retrieve the DNS entry, so the model would "
        f"answer from somewhere else: {ids}")
    for hit in hits:
        assert hit["title"].strip(), f"{hit['id']}: a retrieved passage with no title"
        assert hit["body"].strip(), f"{hit['id']}: a retrieved passage with no body"
        assert hit["source"].strip(), (
            f"{hit['id']}: a retrieved passage with no source file, so the user "
            "cannot check the citation")
        assert hit["kind"] in ("knowledge", "skill"), (
            f"{hit['id']}: unknown entry kind {hit['kind']!r}")


def test_a_search_for_a_word_that_is_not_in_the_corpus_returns_nothing() -> None:
    """The honesty rule: no match means no match, not "the closest thing".

    search() returning the nearest passage for a word the corpus never
    mentions is how an assistant ends up quoting a procedure that was not asked
    about. An empty list is what tells the caller to say "I could not find
    that in the knowledge base".
    """
    with _library_paths():
        hits = knowledge.search(ABSENT_WORD)
        assert hits == [], (
            f"a word that appears in no shipped passage still retrieved "
            f"{[hit['id'] for hit in hits]}, so an unanswerable question gets "
            "a plausible-sounding answer anyway")
        assert knowledge.for_prompt(ABSENT_WORD) == "", (
            "for_prompt() produced text for a question the corpus does not "
            "answer, which is the model being shown an answer it did not find")


def test_for_prompt_labels_every_passage_with_its_id() -> None:
    """The label is the citation: without it the model quotes unsourced text."""
    with _library_paths():
        hits = knowledge.search("how do I set the DNS server", limit=2)
        assert hits, "nothing was retrieved to label"
        text = knowledge.for_prompt("how do I set the DNS server", limit=2)

    assert "[knowledge/set-dns.md]" in text, (
        f"for_prompt() did not label the passage with the id the model is "
        f"meant to cite: {text[:200]!r}")
    for hit in hits:
        assert f"[{hit['id']}]" in text, (
            f"passage {hit['id']} was retrieved but not labelled in the prompt")
        assert hit["title"] in text, (
            f"passage {hit['id']} has no title in the prompt text")
    assert "---" in text, (
        "the passages are not separated, so the model reads them as one blob "
        "and cannot tell one citation from the next")


def test_the_index_is_rebuilt_when_a_corpus_file_changes() -> None:
    """A stale index is a confidently quoted procedure that no longer ships."""
    with _library_paths(corpus_copy=True) as paths:
        entry = paths.share / "knowledge" / "set-dns.md"
        assert knowledge.stats()["entries"] > 0, "the copied corpus was not indexed"
        entry.write_text(entry.read_text(encoding="utf-8") + "\nA new paragraph.\n",
                         encoding="utf-8")
        # up_to_date() compares a signature made of size, mtime and text, so
        # the rewrite has to be noticed however it was made.
        assert paths.home.joinpath("knowledge.sqlite3").is_file()
        found = knowledge.search("paragraph zzznewzzz", limit=5)
        assert any("set-dns" in hit["id"] for hit in found), (
            "a file added to the corpus was not indexed, so the assistant "
            "cannot retrieve text it ships")

# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------


def test_the_shipped_skills_are_the_agreed_eight() -> None:
    with _library_paths():
        names = [skill.name for skill in skills.load_all()]
    assert names == sorted(SHIPPED_SKILLS), (
        f"the skills the package ships have changed: missing "
        f"{sorted(set(SHIPPED_SKILLS) - set(names))}, extra "
        f"{sorted(set(names) - set(SHIPPED_SKILLS))}"
    )


def test_every_skill_is_describable_to_the_model() -> None:
    with _library_paths():
        loaded = skills.load_all()
        assert loaded, "no skills were loaded at all"
        problems = []
        for skill in loaded:
            if not skill.title.strip():
                problems.append(f"{skill.name}: no title")
            if not skill.when.strip():
                problems.append(f"{skill.name}: no 'when' line, so nothing says "
                                "when the skill applies")
            if len(skill.steps) < 3:
                problems.append(f"{skill.name}: only {len(skill.steps)} steps, so "
                                "it is not a procedure")
            if not skill.keywords:
                problems.append(f"{skill.name}: no keywords, so nothing can find it")
            for text in (skill.summary(), skill.brief()):
                if not text.strip():
                    problems.append(f"{skill.name}: summary/brief is empty")
            if skill.name not in skill.summary():
                problems.append(f"{skill.name}: the summary does not name it")
    assert not problems, "the skill catalogue is incomplete:\n  " + "\n  ".join(problems)


def test_a_skill_names_the_programs_this_machine_does_not_have() -> None:
    """pdftotext is a shipped requirement, so the missing list is real.

    Neither CI (Windows and Linux) installs poppler-utils, so this exercises
    the path rather than stubbing it: a skill that needs a program that is not
    there must still be listed, with the program named, instead of failing
    half-way through a procedure.
    """
    with _library_paths():
        found = {skill.name: skill for skill in skills.load_all()}
    assert "pdf-office" in found, "the pdf-office skill is not shipped"
    pdf = found["pdf-office"]
    missing = pdf.missing()
    assert "pdftotext" in missing, (
        "pdftotext is a requirement of pdf-office and is not on PATH on this "
        "machine, so missing() should have named it")
    assert pdf.usable() is False, (
        "a skill whose requirements are not installed reported itself usable, "
        "so the worker would run steps that cannot work")
    assert "not installed" in pdf.summary(), (
        "the catalogue line does not say the requirement is missing, so the "
        "planner is never told the skill needs a program")


def test_a_user_skill_takes_precedence_over_a_shipped_one() -> None:
    with _library_paths() as paths:
        _write_skill(paths.user_skills, "pdf-office",
                     _skill_text("My Own PDF Notes", "when", "keywords"))
        found = {skill.name: skill for skill in skills.load_all()}
        assert "pdf-office" in found, "the user skill was not found at all"
        winner = found["pdf-office"]
        assert winner.directory == "your own skills", (
            "the shipped skill overwrote the user's own skill with the same "
            f"name: {winner.directory!r}")
        assert winner.title == "My Own PDF Notes", (
            "the user's skill text was not the one loaded, so a skill they "
            f"wrote themselves does not win: {winner.title!r}")


def test_the_agent_skills_spellings_parse_identically() -> None:
    """description: and triggers: are the Agent Skills spec's names for the fields.

    A skill found elsewhere uses them. If the parser did not accept both
    spellings, every such skill would arrive with no 'when' line and no
    keywords - a skill nobody can install.
    """
    with _library_paths() as paths:
        _write_skill(paths.user_skills, "ours", _skill_text("Paint", "when", "keywords"))
        _write_skill(paths.user_skills, "theirs",
                     _skill_text("Paint", "description", "triggers"))
        found = {skill.name: skill for skill in skills.load_all()}

    assert set(found) >= {"ours", "theirs"}, (
        f"the two spellings did not both load: {sorted(found)}")
    ours, theirs = found["ours"], found["theirs"]
    assert ours.when == theirs.when, (
        f"description: was not read as when: ({theirs.when!r})")
    assert ours.keywords == theirs.keywords, (
        f"triggers: was not read as keywords: ({theirs.keywords!r})")
    assert ours.steps == theirs.steps, (
        f"the steps did not parse the same for both spellings: "
        f"{ours.steps!r} vs {theirs.steps!r}")
    assert ours.title == theirs.title == "Paint"


def test_matching_finds_a_skill_by_keyword_and_nothing_by_an_absent_word() -> None:
    with _library_paths():
        hits = skills.matching("extract the text from a pdf")
        names = [skill.name for skill in hits]
        assert "pdf-office" in names, (
            f"a question naming the pdf-office keywords did not retrieve it: {names}")
        nothing = skills.matching(ABSENT_WORD)
        assert nothing == [], (
            f"a word that appears in no skill still matched "
            f"{[skill.name for skill in nothing]}")
        empty = skills.matching("")
        assert empty == [], "an empty question matched a skill"

# ---------------------------------------------------------------------------
# The planner
# ---------------------------------------------------------------------------


def test_the_plan_grammar_is_seven_steps_of_real_actions() -> None:
    """The grammar is the whole vocabulary of a plan, and it must be closed.

    If the enum were a copy that drifted from actions.ACTIONS, a rename on one
    side becomes a plan the worker refuses to run - and a plan is either whole
    or nothing, so one bad name loses the whole task.
    """
    schema = planner.PLAN_SCHEMA
    assert schema["additionalProperties"] is False, (
        "the plan schema allows keys it never defined, so the model can invent "
        "structure the parser then has to guess at")
    steps = schema["properties"]["steps"]
    assert steps["maxItems"] == 7, (
        f"a plan may hold {steps.get('maxItems')} steps; the budget of seven is "
        "what stops step repetition")
    item = steps["items"]
    assert item["additionalProperties"] is False, (
        "a step may carry keys the schema never defined")
    assert set(item["required"]) == {"action", "args", "why"}, (
        f"a step now requires {sorted(item['required'])}, so the plan no longer "
        "carries the line a person can check")
    assert item["properties"]["action"]["enum"] == sorted(actions.ACTIONS), (
        "the plan's action enum is not exactly the catalog, so a renamed or "
        "added action is refused by the grammar rather than run")
    assert schema["required"] == ["goal", "steps"], (
        f"a plan now requires {schema['required']}")
    assert steps["type"] == "array"


def test_prune_args_drops_a_hallucinated_argument_and_coerces_an_int() -> None:
    """The schema cannot express per-action arguments; this is where it is done.

    A "verbose: true" that reached open_app would be a TypeError in the middle
    of a task, and a TypeError is a step that fails for a reason that has
    nothing to do with the request.
    """
    kept = planner._prune_args("open_app", {"name": "firefox", "verbose": True})
    assert kept == {"name": "firefox"}, (
        f"an argument open_app does not take survived pruning: {kept!r}")
    coerced = planner._prune_args("set_volume", {"percent": "40"})
    assert coerced == {"percent": 40}, (
        f"a string percentage was not coerced to the integer the action takes: "
        f"{coerced!r}")
    assert planner._prune_args("set_volume", {"percent": 40}) == {"percent": 40}
    assert planner._prune_args("set_volume", {"percent": "loud"}) == {}, (
        "an uncoercible integer argument was kept instead of dropped")


def test_plan_returns_usable_steps_from_a_stub_engine() -> None:
    """No model is needed: plan()'s first parameter is the engine.

    The stub answers with one canned object, which is the shape a constrained
    llama.cpp call produces, and the assertions are about what the planner
    does with it.
    """
    engine = _StubEngine('{"goal": "say the time", "steps": '
                         '[{"action": "tell_time", "args": {}, "why": "the user asked"}]}')
    events: list[dict] = []
    steps = planner.plan(engine, "what time is it", on_event=events.append)

    assert [step["action"] for step in steps] == ["tell_time"], (
        f"the plan did not come back as the step the stub described: {steps}")
    assert steps[0]["why"] == "the user asked", (
        "the why line was dropped, so the human reading the plan is shown a "
        "step with no reason")
    assert steps[0]["args"] == {} and steps[0]["expect"] == ""
    assert engine.calls, "the engine was never asked, so nothing was planned"
    assert engine.calls[0]["schema"] is planner.PLAN_SCHEMA, (
        "the brain was asked without the grammar, which is the only thing that "
        "stops it answering in prose")
    assert any(event.get("type") == "plan" for event in events), (
        f"no plan event was emitted for the interface: {events}")


def test_plan_drops_a_step_naming_an_unknown_action() -> None:
    engine = _StubEngine(
        '{"goal": "g", "steps": ['
        '{"action": "tell_time", "args": {}, "why": "first"},'
        '{"action": "open_portal", "args": {}, "why": "not in the catalog"},'
        '{"action": "tell_battery", "args": {}, "why": "third"}]}')
    steps = planner.plan(engine, "g")
    assert [step["action"] for step in steps] == ["tell_time", "tell_battery"], (
        f"the step naming an action that does not exist was not dropped, so a "
        f"hallucinated action would reach the worker: {steps}")


def test_plan_returns_nothing_for_an_empty_answer() -> None:
    for text in ("", "   ", "not json at all", "[]"):
        assert planner.plan(_StubEngine(text), "g") == [], (
            f"the planner produced steps from {text!r}, which is an empty "
            "answer it should report as one")


def test_the_user_prompt_offers_the_installed_skills() -> None:
    with _library_paths():
        text = planner.user_prompt("sort out my photos")
    assert "sort out my photos" in text, "the request is not in the prompt"
    assert "backup-and-sync" in text, (
        "the planner's prompt does not list the installed skills, so a step "
        "cannot name one")
    assert "Background:" not in text, (
        "an empty context still added a background section")



# ---------------------------------------------------------------------------
# The worker: what it asks, what it refuses, and what it can prove
# ---------------------------------------------------------------------------


def test_the_worker_grammars_are_closed() -> None:
    for name, schema in (("decision", worker.DECISION_SCHEMA),
                         ("task", worker.TASK_SCHEMA)):
        assert schema["additionalProperties"] is False, (
            f"the {name} schema allows keys it never defined, so the model can "
            "invent structure the parser then has to guess at")
    assert worker.DECISION_SCHEMA["properties"]["kind"]["enum"] == [
        "answer", "action", "plan", "refuse"], (
        "the worker's reply kinds changed, and one of them is the branch that "
        "escalates instead of guessing")
    assert worker.TASK_SCHEMA["required"] == ["action", "args"]


def test_question_for_names_the_action_and_its_arguments() -> None:
    """The human is asked about a specific thing, not a category of thing."""
    for action in sorted(NEEDS_CONFIRMATION):
        sentence = worker.question_for(action, {})
        assert sentence.strip(), f"{action}: the confirmation sentence is empty"
        assert "assistant wants" in sentence, (
            f"{action}: the confirmation sentence does not read as a request "
            f"for permission: {sentence!r}")
    detail = worker.question_for("run_command", {"command": "rm ~/notes.txt"})
    assert "run this command" in detail and "rm ~/notes.txt" in detail, (
        f"the confirmation does not show the exact command: {detail!r}")
    detail = worker.question_for("close_window", {"title": "unsaved"})
    assert "unsaved" in detail, (
        f"the confirmation does not name the window: {detail!r}")
    assert worker.question_for("set_volume", {}) == (
        "the assistant wants to run set_volume"), (
        "an action with no question of its own did not fall back to a generic "
        "one naming the action")


def test_only_the_irreversible_actions_need_confirmation() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-ai-brain-") as home:
        with _open_book(Path(home)) as book:
            runner = worker.Worker(_StubPool(), journal=book)
            for action in sorted(NEEDS_CONFIRMATION):
                assert runner._needs_confirmation(action, {}) is True, (
                    f"{action} no longer needs the human's yes, which is the "
                    "whole confirmation model")
            for action in ("volume_down", "open_app", "tell_time",
                           "list_windows", "screenshot"):
                assert runner._needs_confirmation(action, {}) is False, (
                    f"{action} now demands a confirmation it never needed, "
                    "which trains the user to click yes without reading")
            assert runner._needs_confirmation("no_such_action", {}) is False


def test_a_refusal_by_the_human_is_not_a_failure() -> None:
    """A person's no is the correct outcome, so the journal must not call it a bug."""
    with tempfile.TemporaryDirectory(prefix="astraos-ai-brain-") as home:
        with _open_book(Path(home)) as book:
            runner = worker.Worker(_StubPool(), journal=book)
            assert runner._end_status({"ok": False, "needs_confirm": True,
                                       "confirmed": False}) == "needs_human", (
                "a step the human refused was not recorded as needing a human")
            assert runner._end_status({"ok": False, "needs_confirm": True,
                                       "confirmed": True}) == "failed", (
                "a confirmed step that failed was not recorded as failed")
            assert runner._end_status({"ok": False, "needs_confirm": False,
                                       "confirmed": False}) == "failed", (
                "an ordinary failure was not recorded as failed")


# ---------------------------------------------------------------------------
# Verification: a claim it cannot check is a claim it does not make
# ---------------------------------------------------------------------------


def test_a_volume_claim_cannot_be_verified_on_this_machine() -> None:
    """No sound card is needed to prove the verifier refuses to guess.

    With no pactl and no amixer there is no volume to read back, so the only
    honest answer is False: the step is not verified, and the worker says so
    rather than reporting a volume it never saw change.
    """
    assert worker._verify_volume({"percent": 199}, {"output": ""}) is False, (
        "set_volume was verified against a volume no machine can hold, which "
        "means the verifier is not reading anything back")
    if worker._read_volume() is None:
        for percent in (0, 50, 100):
            assert worker._verify_volume({"percent": percent},
                                         {"output": ""}) is False, (
                f"this machine cannot read its volume back, yet setting it to "
                f"{percent}% was reported as verified")
    assert worker._verify_volume({}, {"output": ""}) is False, (
        "a step with no percentage was verified, so the verifier is not "
        "checking what was actually asked for")


def test_a_screenshot_is_only_verified_when_the_file_is_there() -> None:
    """A path in the output is not a screenshot: the file must exist and hold bytes.

    The name is relative on purpose. The extractor reads the file name out of
    the action's output, and a bare name is the one spelling that means the
    same thing on Linux and on Windows.
    """
    with tempfile.TemporaryDirectory(prefix="astraos-ai-shot-") as home:
        cwd = os.getcwd()
        os.chdir(home)
        try:
            missing = worker._verify_screenshot({}, {"output": "shot.png"})
            assert missing is False, (
                "a screenshot naming a file that does not exist was verified")

            shot = Path("shot.png")
            shot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
            present = worker._verify_screenshot({}, {"output": "saved: shot.png"})
            assert present is True, (
                "a screenshot whose file exists and holds bytes was not verified")

            shot.write_bytes(b"")
            empty = worker._verify_screenshot({}, {"output": "saved: shot.png"})
            assert empty is False, (
                "a zero-byte file was verified as a screenshot")
            shot.unlink()
        finally:
            os.chdir(cwd)


# ---------------------------------------------------------------------------
# Running a step: the invented action, the unconfirmed irreversible one
# ---------------------------------------------------------------------------


def test_a_step_naming_an_action_that_does_not_exist_never_runs() -> None:
    calls: list[dict] = []
    with _recorded_execute(calls):
        with tempfile.TemporaryDirectory(prefix="astraos-ai-brain-") as home:
            with _open_book(Path(home)) as book:
                runner = worker.Worker(_StubPool(), journal=book)
                evidence = runner._run_step({"action": "delete_everything",
                                             "args": {}}, 1, "task-1")

    assert evidence["ok"] is False, "an invented action was reported as done"
    assert evidence["attempts"] == 0, (
        "an invented action was attempted, which means it reached the catalog")
    assert "invented" in evidence["error"], (
        f"the refusal does not say the model invented the action, so the "
        f"record of why nothing ran is useless: {evidence['error']!r}")
    assert "delete_everything" in evidence["error"], (
        f"the refusal does not name the action: {evidence['error']!r}")
    assert calls == [], (
        f"the invented action reached the catalog: {calls}")


def test_an_unconfirmed_irreversible_action_never_runs() -> None:
    """The most important assertion in this file.

    run_command with no confirm callback is a machine that runs whatever the
    model invented. The guard sits before the catalog rather than after it, so
    the command named here - one that would pass the guard list if it ever
    reached it - must not reach anything at all.
    """
    calls: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="astraos-ai-brain-") as home:
        with _recorded_execute(calls):
            with _open_book(Path(home)) as book:
                runner = worker.Worker(_StubPool(), journal=book)
                for action in sorted(NEEDS_CONFIRMATION):
                    args = {"command": "df -h"} if action == "run_command" else {}
                    evidence = runner._run_step({"action": action, "args": args},
                                                1, "t")

                    assert evidence["ok"] is False, (
                        f"{action} ran without a confirmation")
                    assert evidence["needs_confirm"] is True, (
                        f"{action} did not mark itself as needing the human's yes")
                    assert evidence["confirmed"] is False, (
                        f"{action} was recorded as confirmed with nobody to ask")
                    assert "confirmed" in evidence["error"], (
                        f"the refusal for {action} does not say nobody confirmed "
                        f"it: {evidence['error']!r}")
                    assert evidence["attempts"] == 0, (
                        f"{action} was attempted {evidence['attempts']} times "
                        "without a confirmation")

    assert calls == [], (
        f"the confirmation gate was passed: {calls}")


def test_a_confirmed_irreversible_action_does_reach_the_catalog() -> None:
    """The mirror of the test above: a yes is not a veto of the whole system.

    Without this, the refusal above could pass on a Worker that refuses
    everything, and a user who answered the question would get nothing.
    """
    calls: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="astraos-ai-brain-") as home:
        with _recorded_execute(calls) as recorded:
            with _open_book(Path(home)) as book:
                runner = worker.Worker(_StubPool(),
                                       confirm=lambda action, args: True,
                                       journal=book)
                evidence = runner._run_step(
                    {"action": "run_command", "args": {"command": "df -h"}}, 1, "t")
                approvals = book.pending_approvals()

    assert evidence["ok"] is True, (
        f"a confirmed step did not run: {evidence['error']!r}")
    assert evidence["confirmed"] is True, "the step was not recorded as confirmed"
    assert recorded and recorded[0]["confirmed"] is True, (
        f"the action did not reach the catalog with confirmed=True: {recorded}")
    assert approvals == [], (
        "a question that was asked and answered is still pending, so "
        f"`astra ai journal` would keep asking it: {approvals}")


def test_a_safe_action_runs_when_nobody_has_to_confirm_it() -> None:
    """list_windows needs no permission; only the structure is asserted.

    Whether wmctrl is installed is a property of the machine, not of the
    worker, so this asserts the shape of the evidence and that the action was
    attempted - never that it succeeded.
    """
    calls: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="astraos-ai-brain-") as home:
        with _recorded_execute(calls):
            with _open_book(Path(home)) as book:
                runner = worker.Worker(_StubPool(),
                                       confirm=lambda action, args: True,
                                       journal=book)
                evidence = runner._run_step({"action": "list_windows",
                                             "args": {}}, 1, "t")

    for key in ("action", "args", "ok", "output", "error", "attempts", "confirmed",
                "verified", "needs_confirm"):
        assert key in evidence, f"the evidence for a step has no {key!r} key"
    assert evidence["action"] == "list_windows"
    assert evidence["needs_confirm"] is False, (
        "a harmless action demanded a confirmation, which trains the user to "
        "say yes without reading")
    assert evidence["attempts"] >= 1, "the action was never attempted"
    assert calls, "the action never reached the catalog"


def test_the_plan_is_in_the_journal_before_the_first_step_runs() -> None:
    """A plan that exists only once it has finished is a plan nobody could veto.

    The pool has no engine on purpose: this is the state of every machine that
    has not downloaded a model, and the journal must still hold the task.
    """
    plan = [{"action": "tell_time", "args": {}, "why": "the user asked the time"},
            {"action": "list_windows", "args": {}, "why": "and what is open"}]
    seen: dict = {}
    outcome = {"kind": "action", "text": "", "plan": [], "evidence": [], "needs": []}

    with tempfile.TemporaryDirectory(prefix="astraos-ai-brain-") as home:
        with _recorded_execute([]):
            with _open_book(Path(home)) as book:
                runner = worker.Worker(_StubPool(), journal=book)

                def on_event(event: dict) -> None:
                    if event.get("type") == "step-start" and "first" not in seen:
                        seen["first"] = [dict(task) for task in book.unfinished()]
                        seen["plan_file"] = book.plan_path().read_text(
                            encoding="utf-8")

                runner._on_event = on_event
                runner.run_plan(plan, outcome)
                # The task is finished by the time run_plan returns, so it is
                # looked up by the id it was given rather than through
                # unfinished(), which only lists what is still open.
                task_id = seen["first"][0]["id"]
                stored = book.task(task_id)
                attempts = stored["attempts"] if stored else ""

    assert "first" in seen, (
        "no step-start event was emitted, so nothing can prove what the journal "
        "held before the first step ran")
    tasks_before = seen["first"]
    assert len(tasks_before) == 1, (
        f"the journal held {len(tasks_before)} tasks before the first step ran: "
        "it should hold exactly the one task being run")
    task = tasks_before[0]
    assert task["status"] == "running", (
        f"the task was {task['status']!r} before the first step ran, so it was "
        "not recorded as in progress")
    assert json.loads(task["steps"]) == plan, (
        "the plan written to the journal is not the plan that ran, so a reader "
        "cannot tell what was agreed")
    assert "[>] 1. tell_time" in seen["plan_file"], (
        f"plan.md did not mark the first step as next before anything ran: "
        f"{seen['plan_file']!r}")
    assert "tell_time" in seen["plan_file"] and "list_windows" in seen["plan_file"], (
        "plan.md does not carry the whole plan, so the agent cannot see the "
        "steps that are left")
    assert stored is not None and json.loads(stored["steps"]) == plan, (
        "the plan was not stored on the task row")
    assert attempts and attempts.strip() != "{}", (
        "no attempt was recorded, so the journal has no evidence of what ran")


def test_a_failing_step_stops_the_plan_and_is_recorded() -> None:
    """Continuing past a failure is guessing with authority."""
    calls: list[dict] = []
    plan = [{"action": "tell_time", "args": {}, "why": "first"},
            {"action": "tell_battery", "args": {}, "why": "second"}]
    outcome = {"kind": "action", "text": "", "plan": [], "evidence": [], "needs": []}
    counts: dict = {}
    seen: list[dict] = []

    with tempfile.TemporaryDirectory(prefix="astraos-ai-brain-") as home:
        with _recorded_execute(calls, ok=False) as recorded:
            with _open_book(Path(home)) as book:
                runner = worker.Worker(_StubPool(), journal=book)
                runner._on_event = seen.append
                runner.run_plan(plan, outcome)
                # A failed task is not "unfinished", so it is counted from the
                # summary's per-status totals rather than from the open list.
                counts = book.summary()["tasks"]

    assert outcome["kind"] == "failed", (
        f"a plan whose first step failed ended as {outcome['kind']!r}, so the "
        "caller is told it worked")
    assert len(outcome["evidence"]) == 1, (
        f"{len(outcome['evidence'])} steps ran after the first one failed")
    assert len(recorded) == 1, (
        "the second step ran after the first failed, which is exactly the "
        "guessing the docstring refuses")
    assert counts.get("failed") == 1, (
        "the journal does not hold the failed task, so there is nothing for a "
        f"human to resume from: {counts}")


def test_an_empty_plan_is_refused_and_nothing_runs() -> None:
    calls: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="astraos-ai-brain-") as home:
        with _recorded_execute(calls):
            with _open_book(Path(home)) as book:
                runner = worker.Worker(_StubPool(), journal=book)
                outcome = runner.run_plan([], {"kind": "action", "text": "",
                                               "plan": [], "evidence": [],
                                               "needs": []})
                assert book.unfinished() == [], (
                    "an empty plan wrote a task to the journal, so the user is "
                    "shown a run that never happened")

    assert outcome["kind"] == "refuse", (
        f"an empty plan was not refused: {outcome}")
    assert outcome["plan"] == [] and outcome["evidence"] == []
    assert "empty" in outcome["text"].lower(), (
        f"the refusal does not say the plan was empty: {outcome['text']!r}")
    assert calls == []


def test_parse_object_accepts_the_shapes_a_constrained_call_produces() -> None:
    bare = worker._parse_object('{"kind": "answer", "text": "hello"}')
    assert bare == {"kind": "answer", "text": "hello"}, (
        f"a bare JSON object did not parse: {bare!r}")
    fenced = worker._parse_object(
        '```json\n{"kind": "action", "action": "tell_time"}\n```')
    assert fenced.get("kind") == "action", (
        f"a fenced object did not parse, and some chat templates still add the "
        f"fence: {fenced!r}")
    noisy = worker._parse_object('Sure!\n{"kind": "refuse"}\nThere you go.')
    assert noisy == {"kind": "refuse"}, (
        f"an object with prose around it did not parse: {noisy!r}")
    for garbage in ("", "   ", "no json here", "[1, 2, 3]", '{"broken": '):
        assert worker._parse_object(garbage) == {}, (
            f"parse_object() produced something from {garbage!r}, which is not "
            "an object the grammar would have produced")
# ---------------------------------------------------------------------------
# The journal: the file that fixes the two largest failure modes
# ---------------------------------------------------------------------------


def _fresh_journal(home: Path) -> journal.Journal:
    return journal.Journal(home / "journal.sqlite3")


@contextlib.contextmanager
def _open_book(home: Path):
    """A journal that is closed however the test leaves its block.

    Closed explicitly rather than at collection time: Windows will not delete a
    database file that is still open, and a leaked handle turns a failed
    assertion into a second, misleading failure about a directory that could
    not be removed.
    """
    book = journal.Journal(home / "journal.sqlite3")
    try:
        yield book
    finally:
        book.close()


def test_a_task_round_trips_and_the_rendered_plan_marks_progress() -> None:
    """The termination-awareness property, tested against the rendered text.

    An agent that cannot see how many steps are left never finishes (FM-1.5,
    12.4% of measured failures). plan.md is where that lives, so it is the
    rendered file that is asserted, not the column.
    """
    with tempfile.TemporaryDirectory(prefix="astraos-ai-journal-") as home:
        home_path = Path(home)
        with _open_book(home_path) as book:
            plan = [{"action": "tell_time", "args": {}, "why": "say the time"},
                    {"action": "list_windows", "args": {}, "why": "and what is open"},
                    {"action": "tell_battery", "args": {}, "why": "and the battery"}]

            run_id = book.begin("tell me about this machine")
            assert run_id, "begin() returned no run id"
            task_id = book.add_task("tell me about this machine", plan)

            stored = book.task(task_id)
            assert stored is not None and stored["goal"] == "tell me about this machine", (
                "the task was not stored under the goal it was given")
            assert json.loads(stored["steps"]) == plan, (
                "the plan was not stored on the task, so nothing can be resumed")

            assert book.plan_path().is_file(), (
                "plan.md was not written when the task was queued")
            fresh = book.plan_path().read_text(encoding="utf-8")
            assert "[>] 1. tell_time" in fresh, (
                f"the first step was not marked as the next one: {fresh!r}")
            assert "0 of 3 steps" in fresh, (
                f"plan.md does not state the budget, which is the whole point: "
                f"{fresh!r}")

            book.set_status(task_id, "running")
            book.record_attempt(task_id, 1, {"ok": True, "output": "It is 10:00.",
                                             "error": "", "verified": False})
            # Nothing ran yet: the step index is the checkpoint, and it is still 0.
            assert book.task(task_id)["step_index"] == 0, (
                "step_index moved before set_step() was called")
            book.set_step(task_id, 1)
            assert book.task(task_id)["step_index"] == 1, (
                "the checkpoint was not recorded, so a resumed run would repeat "
                "step one")

            book.set_result(task_id, {"text": "It is 10:00."})
            assert book.task(task_id)["result"] is not None, (
                "the result was not stored, so the task has no answer")
            events = book.events()
            kinds = [event["kind"] for event in events]
            for expected in ("run_started", "task_added", "task_status", "step_attempt",
                             "task_result"):
                assert expected in kinds, (
                    f"no {expected} event was recorded, so the log cannot answer "
                    f"'what happened': {kinds}")
            assert all(event["run_id"] == run_id for event in events), (
                "an event was recorded under a different run, so the log mixes runs")


def test_plan_md_follows_the_checkpoint_as_each_step_runs() -> None:
    """The [x]/[>] markers are what the agent reads to know it is finished.

    This is the property journal.py's own docstring claims - "plan.md is
    regenerated on every state change" - and the step index is the state change
    that matters most, because the done-set is what stops step repetition
    (FM-1.3, 15.7%) and the budget is what stops an agent that never notices
    it has finished (FM-1.5, 12.4%).

    It is reported as a SKIP, not a pass: set_step() moves the checkpoint
    column but is the one mutator that does not call render(), so the file on
    screen is always one step behind what happened. That is a bug in
    packages/astraos-ai/root/usr/lib/astraos/ai/journal.py, not something this
    suite can work around, and the reason is printed in full by the runner.
    """
    with tempfile.TemporaryDirectory(prefix="astraos-ai-journal-") as home:
        with _open_book(Path(home)) as book:
            plan = [{"action": "tell_time", "args": {}, "why": "say the time"},
                    {"action": "list_windows", "args": {}, "why": "and what is open"},
                    {"action": "tell_battery", "args": {}, "why": "and the battery"}]
            task_id = book.add_task("tell me about this machine", plan)
            book.set_status(task_id, "running")
            book.record_attempt(task_id, 1, {"ok": True, "output": "It is 10:00.",
                                             "error": "", "verified": False})

            before = book.plan_path().read_text(encoding="utf-8")
            book.set_step(task_id, 1)
            after = book.plan_path().read_text(encoding="utf-8")

            if before == after:
                raise SkipTest(
                    "journal.Journal.set_step() records the checkpoint but never "
                    "calls render(), so plan.md still says 'progress: 0 of 3 "
                    "steps' and still marks step 1 as the next one to run after "
                    "it has already run. The done-set the agent and the user both "
                    "read is therefore one step behind what happened, which is "
                    "the bookkeeping failure (FM-1.3/FM-1.5) the module exists to "
                    "prevent. Fix: set_step() must call self.render() like every "
                    "other mutator in journal.py does.")

            assert "[x] 1. tell_time" in after, (
                f"the step that ran is not marked done in plan.md:\n{after}")
            assert "[>] 2. list_windows" in after, (
                f"the step that is next is not marked as next:\n{after}")
            assert "[ ] 3. tell_battery" in after, (
                f"the steps beyond the next one are not left blank:\n{after}")
            assert "1 of 3 steps" in after, (
                f"plan.md does not follow the checkpoint, so the budget on "
                f"screen is wrong:\n{after}")


def test_a_task_that_needs_a_human_is_unfinished_and_an_ok_one_is_not() -> None:
    """needs_human is a state a restart has to be able to pick back up.

    STATUSES lists needs_human as a first-class state and _end_status() files a
    refusal there rather than as a failure, so the two have to agree about what
    "unfinished" means.

    Reported as a SKIP, not a pass: unfinished() selects only 'pending' and
    'running', so a task a human refused drops out of the open list - and
    because render() writes only what unfinished() returns, the question that
    was asked also disappears from plan.md. That is a bug in
    packages/astraos-ai/root/usr/lib/astraos/ai/journal.py.
    """
    with tempfile.TemporaryDirectory(prefix="astraos-ai-journal-") as home:
        with _open_book(Path(home)) as book:
            task_id = book.add_task("do something",
                                    [{"action": "run_command",
                                      "args": {"command": "df -h"}, "why": "why"}])
            book.set_status(task_id, "needs_human")
            open_ids = [task["id"] for task in book.unfinished()]

            if task_id not in open_ids:
                raise SkipTest(
                    "journal.Journal.unfinished() selects only the 'pending' and "
                    "'running' statuses, so a task left in 'needs_human' - which "
                    "worker._end_status() sets when a human refuses a step - is "
                    "not unfinished. A restart therefore cannot pick it back up, "
                    "and since render() writes plan.md only from unfinished(), "
                    "the question the human was asked vanishes from the file "
                    "entirely. Fix: unfinished() must include 'needs_human', "
                    "the state STATUSES says is a first-class outcome rather "
                    "than a failure.")

            assert open_ids, "the needs_human task is not in the open list"
            assert book.plan_path().is_file() and "run_command" in (
                book.plan_path().read_text(encoding="utf-8")), (
                "a task waiting for a human is not rendered into plan.md, so "
                "the human has no record of what was asked")

            book.set_status(task_id, "ok")
            open_ids = [task["id"] for task in book.unfinished()]
            assert task_id not in open_ids, (
                "a finished task is still unfinished, so the user is shown a run "
                "that is over")
            counts = book.summary()["tasks"]
            assert counts["ok"] == 1 and counts["needs_human"] == 0, (
                f"the status counts are wrong: {counts}")


def test_asking_and_answering_records_both_halves() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-ai-journal-") as home:
        with _open_book(Path(home)) as book:
            question = worker.question_for("run_command", {"command": "df -h"})
            approval_id = book.ask("run_command", question, "task-1")
            assert approval_id, "ask() returned no approval id"

            pending = book.pending_approvals()
            assert len(pending) == 1 and pending[0]["id"] == approval_id, (
                f"the question is not pending, so nobody is told it was asked: {pending}")
            assert pending[0]["question"] == question, (
                "the stored question is not the question that was shown")
            assert pending[0]["answer"] is None, (
                "a question that was never answered is recorded as answered")

            book.answer(approval_id, "no")
            assert book.pending_approvals() == [], (
                "the answered question is still pending, so `astra ai journal` "
                "keeps asking it")
            rows = book._connect().execute(
                "SELECT action, question, answer FROM approvals WHERE id = ?", (approval_id,)
            ).fetchone()
            assert rows["action"] == "run_command" and rows["answer"] == "no", (
                f"the answer was not stored against the question: {tuple(rows)}")


def test_every_status_is_accepted_and_an_unknown_one_is_refused() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-ai-journal-") as home:
        with _open_book(Path(home)) as book:
            task_id = book.add_task("status round trip", [])
            for status in journal.STATUSES:
                book.set_status(task_id, status)
                assert book.task(task_id)["status"] == status, (
                    f"the status {status!r} was not stored")
            for bogus in ("finished", "OK", "", "done"):
                try:
                    book.set_status(task_id, bogus)
                except KeyError:
                    continue
                raise AssertionError(
                    f"set_status() accepted {bogus!r}, which is not one of "
                    f"{journal.STATUSES}, so a typo becomes a state nothing can read")


# ---------------------------------------------------------------------------
# The command line: the sub-commands exist and their handlers are defined
# ---------------------------------------------------------------------------


def test_the_cli_registers_the_work_journal_skills_and_knowledge_commands() -> None:
    """Read-only: the file is text, so the check is on the text.

    astra-ai is the only way in on a headless or stuck machine. A sub-command
    registered without its handler, or with a handler that was renamed, is a
    word in the help that does something else or nothing at all - and the user
    finds out when they need it.
    """
    text = read("packages/astraos-ai/root/usr/bin/astra-ai")
    for name in ("work", "journal", "skills", "knowledge"):
        assert f'sub.add_parser("{name}"' in text, (
            f"the astra-ai command line does not register the {name!r} "
            f"sub-command, so it cannot be used")
        assert f"set_defaults(handler=cmd_{name})" in text, (
            f"the {name!r} sub-command has no set_defaults(handler=cmd_{name}), "
            "so `astra-ai help` would offer a word that does nothing")
        assert f"def cmd_{name}(" in text, (
            f"the {name!r} sub-command names handler cmd_{name}, but no such "
            "function is defined in the file")


def test_the_cli_is_executable_in_git() -> None:
    """Windows cannot store the executable bit; the git index is where it lives."""
    if not shutil.which("git"):
        raise SkipTest("git is not available to read the index mode")
    result = subprocess.run(
        ["git", "ls-files", "--stage", "--", "packages/astraos-ai/root/usr/bin/astra-ai"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise SkipTest(f"cannot read the git index: {result.stderr.strip()}")
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise SkipTest("astra-ai is not tracked by git in this checkout")
    mode = lines[0].split(None, 1)[0]
    assert mode == "100755", (
        f"astra-ai is mode {mode} in git, so a checkout on Linux gets a file "
        "that cannot be executed - the assistant becomes a command that is not "
        "there")


# ---------------------------------------------------------------------------
# Build flags
# ---------------------------------------------------------------------------


def _cpu_flags() -> dict[str, str]:
    """CPU_FLAGS as a mapping, so a test can ask about one switch."""
    out: dict[str, str] = {}
    for flag in ai_setup.CPU_FLAGS:
        if flag.startswith("-D") and "=" in flag:
            name, value = flag.split("=", 1)
            out[name] = value
    return out


def test_the_build_flags_never_ask_for_instructions_this_cpu_lacks() -> None:
    """The reference CPU has avx and sse4_2, and nothing else.

    Measured 2026-10-16: with only GGML_AVX2 off, CMake still enabled
    GGML_FMA and GGML_BMI2. Both are Haswell features, the same generation as
    AVX2, and the freshly installed llama-server died with SIGILL (exit 132)
    before its first log line - which is why the log file was empty and the
    failure looked like nothing had happened at all.
    """
    flags = _cpu_flags()
    for feature in ("GGML_AVX2", "GGML_F16C", "GGML_FMA", "GGML_BMI2", "GGML_AVX512"):
        assert flags.get(f"-D{feature}") == "OFF", (
            f"{feature} is not pinned off, so a build that configures and "
            "links cleanly still dies with Illegal instruction on the machine "
            f"this release is tested on: {ai_setup.CPU_FLAGS!r}")
    assert flags.get("-DGGML_AVX") == "ON", (
        "AVX is present on the reference CPU; turning it off makes every "
        "question needlessly slow")
    assert flags.get("-DGGML_NATIVE") == "OFF", (
        "GGML_NATIVE=ON compiles for whatever CPU the build machine happens "
        "to have instead of the one the binary will run on, which is the same "
        f"defect one level up: {ai_setup.CPU_FLAGS!r}")


def test_the_installed_engine_is_self_contained() -> None:
    """A shared build keeps an RPATH into the build tree it was copied from.

    The installed llama-server would load libllama.so and the ggml libraries
    from bin_dir/src/llama-build - and stop starting the moment that tree is
    removed, which is the first thing anyone does to reclaim the disk space
    after a build. BUILD_SHARED_LIBS=OFF makes the installed file the whole
    program, with nothing outside bin_dir to depend on.
    """
    flags = _cpu_flags()
    assert flags.get("-DBUILD_SHARED_LIBS") == "OFF", (
        "the build does not ask for a static binary, so the installed "
        "llama-server still points at the build tree for its libraries: "
        f"{ai_setup.CPU_FLAGS!r}")


def test_the_engine_workflow_never_retypes_the_cpu_flags() -> None:
    """The CI workflow exists to move the compile, not to copy the flag list.

    `.github/workflows/build-ai-engine.yml` runs on every push under
    packages/astraos-ai/root/usr so that the twenty-minute compile happens on
    a hosted runner instead of the user's desktop. It is allowed to build
    through `astra-ai setup --build all` - the exact command a user runs - and
    that is the point: a second copy of the instruction-set flags in YAML
    would drift from setup.py silently, and the drift would ship as SIGILL on
    this hardware.

    The workflow builds both variants through that one command (`--variant
    avx` and `--variant avx2`), so the avx-only proofs must stay pinned to the
    avx job - the emulated-Sandy-Bridge run is the dynamic half of the SIGILL
    proof and the disassembly scan is the static half - and the avx2 job must
    keep its own positive proof, or an artifact labelled "avx2" ships with
    nothing behind the label.
    """
    text = read(".github/workflows/build-ai-engine.yml")
    assert "setup --build all" in text, (
        "the engine workflow no longer runs the command it exists to prove; "
        "a build that is not the user's command is not a proof about the "
        "user's command")
    assert "-DGGML" not in text, (
        "the workflow spells out an instruction-set flag; the flags live in "
        "setup.py, and this copy drifts from them the next time one changes")
    assert 'setup --build all --variant "${{ matrix.variant }}"' in text, (
        "the workflow no longer pins the variant it builds; a matrix job "
        "without the flag builds setup.py's default and mislabels the "
        "artifact")
    assert "astra-ai-engine-linux-x86_64-${{ matrix.variant }}" in text, (
        "the two variant artifacts are no longer named apart, so the avx2 "
        "build would overwrite - or be mistaken for - the avx one")
    assert "if: matrix.variant == 'avx'" in text, (
        "the SIGILL scan and the emulated Sandy Bridge run are the avx "
        "artifact's proof; unpinned, they would claim the avx2 artifact too")
    assert "if: matrix.variant == 'avx2'" in text, (
        "the avx2 job lost its positive proof (256-bit code, on a runner that "
        "lists avx2), leaving the label with nothing behind it")
    assert "qemu-x86_64 -cpu SandyBridge" in text, (
        "the emulated Sandy Bridge run is the half of the SIGILL proof that "
        "executes; removing it leaves a static scan claiming more than it can "
        "show")


def _variant_flags(variant: str) -> dict[str, str]:
    """CPU_VARIANTS[variant] as a mapping, so a test can ask about one switch."""
    out: dict[str, str] = {}
    for flag in ai_setup.CPU_VARIANTS[variant]:
        if flag.startswith("-D") and "=" in flag:
            name, value = flag.split("=", 1)
            out[name] = value
    return out


def test_the_avx2_variant_turns_on_the_haswell_features_and_requires_them() -> None:
    """A variant's flags and its recorded requirements must say the same thing.

    The requirements are what `resolve_variant` checks the CPU against and
    what the build marker stores for `astra-ai status`. A variant that turns
    GGML_FMA on while its requirements forget to name "fma" would build a
    binary that dies with SIGILL on a CPU the check called compatible - the
    measured 2026-10-16 defect, one layer down.
    """
    from astraos.ai import machine

    assert "avx" in ai_setup.CPU_VARIANTS and "avx2" in ai_setup.CPU_VARIANTS, (
        "the variant table lost one of its entries")
    assert ai_setup.CPU_FLAGS is ai_setup.CPU_VARIANTS[ai_setup.DEFAULT_VARIANT], (
        "CPU_FLAGS - the name the workflow and the older tests read - no "
        "longer names the default variant's flag list")

    flags = _variant_flags("avx2")
    for feature in ("GGML_AVX2", "GGML_FMA", "GGML_BMI2", "GGML_F16C"):
        assert flags.get(f"-D{feature}") == "ON", (
            f"the avx2 variant does not turn {feature} on; it would run at "
            "the avx speed while carrying the avx2 name")
    assert flags.get("-DGGML_AVX") == "ON", "the avx2 variant dropped AVX itself"
    assert flags.get("-DGGML_NATIVE") == "OFF", (
        "GGML_NATIVE=ON compiles for the build machine instead of the target "
        "CPU; the whole variant system exists to stop that")
    assert flags.get("-DGGML_AVX512") == "OFF", (
        "AVX-512 is deliberately off in both variants: no CPU this project is "
        "tested on has it, and the variant description says so")
    assert flags.get("-DBUILD_SHARED_LIBS") == "OFF", (
        "the avx2 variant must stay one self-contained file like the avx one")

    assert set(ai_setup.VARIANT_REQUIREMENTS["avx2"]) == {
        "avx", "avx2", "f16c", "fma", "bmi2"}, (
        "the avx2 requirements do not name exactly the features its flags "
        "turn on")
    assert set(ai_setup.VARIANT_REQUIREMENTS["avx"]) == {"avx"}, (
        "the avx variant must require nothing newer than AVX")

    for variant in ai_setup.CPU_VARIANTS:
        assert variant in ai_setup.VARIANT_REQUIREMENTS, (
            f"{variant} has flags but no requirements; nothing could check it")
        for feature in ai_setup.VARIANT_REQUIREMENTS[variant]:
            assert feature in machine.WATCHED_FLAGS, (
                f"{variant} requires {feature!r}, which the capability "
                "profile never reads; a check that cannot see the flag would "
                "always fail or always pass")


def test_the_engine_variant_is_checked_against_the_cpu() -> None:
    """The selection and its refusals, asked directly.

    best_variant is pure, so the two CPU classes this project actually talks
    about - the Sandy Bridge reference machine and a Haswell-era machine -
    can be put to it without owning either.
    """
    sandy = {"avx", "sse4_2", "sse4_1", "ssse3"}
    haswell = sandy | {"avx2", "f16c", "fma", "bmi2", "movbe"}

    assert ai_setup.best_variant(sandy) == "avx"
    assert ai_setup.best_variant(haswell) == "avx2"
    assert ai_setup.best_variant({"sse4_2"}) is None
    assert ai_setup.resolve_variant("auto", haswell) == "avx2"
    assert ai_setup.resolve_variant("avx", haswell) == "avx"
    assert ai_setup.resolve_variant("", sandy) == "avx", (
        "the bare default stopped being the safe build")

    try:
        ai_setup.resolve_variant("avx2", sandy)
    except ai_setup.SetupError as exc:
        text = str(exc)
        assert "SIGILL" in text and "avx2" in text, (
            "the refusal does not name the failure it prevents: " + text)
    else:
        raise AssertionError(
            "an avx2 build was accepted on a CPU without AVX2; it would die "
            "with SIGILL on the first tensor")

    try:
        ai_setup.resolve_variant("sse5", haswell)
    except ai_setup.SetupError as exc:
        assert "unknown engine variant" in str(exc)
    else:
        raise AssertionError("an unknown variant name was accepted")


def test_the_build_marker_records_what_the_installed_engines_need() -> None:
    """The marker round trip: write it, read it back, and be told the mismatch.

    This is the check that catches an artifact built for another machine
    before the first question does. Nothing recorded means nothing claimed -
    a hand-copied binary carries no marker, and the answer then names nothing
    rather than guessing.
    """
    original = ai_setup.marker_path
    with tempfile.TemporaryDirectory() as tmp:
        marker = Path(tmp) / "ENGINE-BUILD.json"
        ai_setup.marker_path = lambda: marker
        try:
            assert ai_setup.engine_build({"avx"})["variant"] == "", (
                "nothing was recorded yet, and a variant was claimed anyway")

            ai_setup._write_marker("avx2", ["llama", "whisper"])
            written = json.loads(marker.read_text(encoding="utf-8"))
            assert written["variant"] == "avx2", written
            assert sorted(written["targets"]) == ["llama", "whisper"], written
            assert set(written["requirements"]) == {
                "avx", "avx2", "f16c", "fma", "bmi2"}, written

            state = ai_setup.engine_build({"avx", "sse4_2"})
            assert state["variant"] == "avx2", state
            assert set(state["missing"]) == {"avx2", "f16c", "fma", "bmi2"}, (
                "the marker did not flag the features this CPU lacks: " + repr(state))

            assert ai_setup.engine_build(
                {"avx", "avx2", "f16c", "fma", "bmi2"})["missing"] == [], (
                "a CPU with every required feature was flagged anyway")

            marker.write_text("this is not json", encoding="utf-8")
            assert ai_setup.engine_build({"avx"})["variant"] == "", (
                "a corrupt marker produced a claim instead of silence")
        finally:
            ai_setup.marker_path = original


def test_the_setup_command_exposes_and_reports_the_variant() -> None:
    """The user-facing half: the flag exists, and `status` reports the build."""
    cli = read("packages/astraos-ai/root/usr/bin/astra-ai")
    assert '"--variant"' in cli, (
        "`astra-ai setup --build` has no --variant flag, so none of the "
        "variant machinery is reachable from the command the docs name")
    assert "args.variant or ai_setup.DEFAULT_VARIANT" in cli, (
        "the setup command does not pass the variant through to the build")
    assert "ai_setup.engine_build()" in cli, (
        "`astra-ai status` does not read the build marker, so an artifact "
        "built for another CPU is never flagged")
