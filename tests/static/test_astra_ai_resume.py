"""Resuming a stored task: the journal is the state, and the state is on disk.

What this file is for:

  * A plan that stopped - a crash, a reboot, a terminal closed at the wrong
    moment - continues at the step that did not succeed, not after it. A failed
    third step retried at the fourth is a plan that skipped the broken part.
  * A step that did succeed is not run twice. Running a task twice is one of the
    measured failure modes this journal exists to prevent.
  * The plan's provenance travels with the task. A plan written from a document
    is still a document's plan after a reboot, so the guard refuses it again
    instead of trusting it because a person typed `resume`.
  * A finished task is not reopened, and a task with no stored plan says so
    rather than pretending it has one.
  * A journal written by an earlier version gets the provenance column and reads
    its old tasks as the user's own.

Nothing here needs a model, a server or a desktop: the steps are decided before
they are stored, and actions.execute() is replaced with a recorder, so "the step
ran" is an entry in a list rather than a side effect on the machine.
"""

from __future__ import annotations

import contextlib
import sqlite3
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_LIB = REPO_ROOT / "packages" / "astraos-ai" / "root" / "usr" / "lib"
AI_BIN = REPO_ROOT / "packages" / "astraos-ai" / "root" / "usr" / "bin"
if str(AI_LIB) not in sys.path:
    sys.path.insert(0, str(AI_LIB))

from astraos.ai import actions, journal, tiers, worker  # noqa: E402

DESCRIPTION = (
    "A stopped task resumes at the step that did not succeed, keeps its provenance, "
    "and never reopens a finished one"
)


class _StubPool:
    """No model is installed, so a step that needs new arguments cannot get them.

    That is the state of a fresh machine and the state a resume must survive: the
    plan is already decided, so a step that works runs without borrowing anything,
    and a step that fails ends the attempt instead of hanging on a missing model.
    """

    def __init__(self) -> None:
        self.borrowed: list[str] = []

    def ready(self) -> bool:
        return True

    def asking(self, tier: str):
        self.borrowed.append(tier)
        raise tiers.TierUnavailable(f"the {tier} tier has no model installed")


@contextlib.contextmanager
def _recorder(calls: list, ok: bool = True):
    """actions.execute() replaced with a recorder, as test_astra_ai_brain does."""
    original = actions.execute

    def record(plan, confirmed=False, provenance="user"):  # noqa: ANN001 - mirrors actions.execute
        calls.append({"plan": dict(plan), "confirmed": confirmed, "provenance": provenance})
        return {"ok": ok, "output": "recorded", "error": ""}

    actions.execute = record
    try:
        yield calls
    finally:
        actions.execute = original


def _steps(*names: str) -> list[dict]:
    return [{"action": name, "args": {}} for name in names]


def _book(tmp: str) -> journal.Journal:
    return journal.Journal(Path(tmp) / "journal.sqlite3")


def test_resume_retries_the_step_that_failed_and_runs_the_rest() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-resume-") as tmp:
        book = _book(tmp)
        try:
            task_id = book.add_task(
                "three readings", _steps("tell_time", "tell_battery", "tell_system_info")
            )
            book.set_status(task_id, "running")
            # Step 1 was attempted and failed, then the process stopped.
            book.record_attempt(task_id, 1, {"ok": False, "error": "the clock was unreadable"})
            book.set_step(task_id, 1)

            calls: list[dict] = []
            with _recorder(calls):
                outcome = worker.Worker(_StubPool(), journal=book).resume_task(task_id)

            ran = [call["plan"]["action"] for call in calls]
            assert ran == ["tell_time", "tell_battery", "tell_system_info"], (
                "resume skipped the step that failed: " + ", ".join(ran)
            )
            assert outcome["kind"] == "action"
            assert book.task(task_id)["status"] == "ok"
        finally:
            book.close()


def test_resume_starts_after_a_step_that_succeeded() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-resume-") as tmp:
        book = _book(tmp)
        try:
            task_id = book.add_task(
                "three readings", _steps("tell_time", "tell_battery", "tell_system_info")
            )
            book.set_status(task_id, "running")
            book.record_attempt(task_id, 1, {"ok": True, "output": "12:00"})
            book.set_step(task_id, 1)

            calls: list[dict] = []
            with _recorder(calls):
                outcome = worker.Worker(_StubPool(), journal=book).resume_task(task_id)

            ran = [call["plan"]["action"] for call in calls]
            assert ran == ["tell_battery", "tell_system_info"], (
                "resume ran a step that had already succeeded: " + ", ".join(ran)
            )
            assert outcome["kind"] == "action"
        finally:
            book.close()


def test_a_failed_step_stops_the_resume_and_names_the_failure() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-resume-") as tmp:
        book = _book(tmp)
        try:
            task_id = book.add_task("two readings", _steps("tell_time", "tell_battery"))
            book.set_status(task_id, "running")

            calls: list[dict] = []
            with _recorder(calls, ok=False):
                outcome = worker.Worker(_StubPool(), journal=book).resume_task(task_id)

            assert outcome["kind"] == "failed"
            assert outcome["text"], "a failure with no sentence is a failure nobody can act on"
            assert book.task(task_id)["status"] == "failed"
            assert [call["plan"]["action"] for call in calls] == ["tell_time"], (
                "a failed step must stop the plan, not continue past it"
            )
        finally:
            book.close()


def test_resume_refuses_a_task_that_is_already_done() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-resume-") as tmp:
        book = _book(tmp)
        try:
            task_id = book.add_task("one reading", _steps("tell_time"))
            book.set_status(task_id, "ok")

            calls: list[dict] = []
            with _recorder(calls):
                outcome = worker.Worker(_StubPool(), journal=book).resume_task(task_id)

            assert outcome["kind"] == "refuse"
            assert "already ok" in outcome["text"]
            assert calls == []
        finally:
            book.close()


def test_resume_refuses_a_task_with_no_stored_plan() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-resume-") as tmp:
        book = _book(tmp)
        try:
            task_id = book.add_task("an old single-step task", [])
            calls: list[dict] = []
            with _recorder(calls):
                outcome = worker.Worker(_StubPool(), journal=book).resume_task(task_id)

            assert outcome["kind"] == "refuse"
            assert "no stored plan" in outcome["text"]
            assert calls == []
        finally:
            book.close()


def test_resume_keeps_a_document_plans_provenance() -> None:
    """A resumed plan is not laundered into a trusted one by the act of resuming."""
    with tempfile.TemporaryDirectory(prefix="astraos-resume-") as tmp:
        book = _book(tmp)
        try:
            task_id = book.add_task(
                "read the attachment", _steps("tell_time", "tell_battery"), provenance="document"
            )
            book.set_status(task_id, "running")

            calls: list[dict] = []
            with _recorder(calls):
                worker.Worker(_StubPool(), journal=book).resume_task(task_id)

            assert calls, "nothing ran, so this proves nothing"
            assert all(call["provenance"] == "document" for call in calls), (
                "resume changed where the plan came from: "
                + repr(sorted({call["provenance"] for call in calls}))
            )
        finally:
            book.close()


def test_paused_is_a_real_status_and_a_paused_task_is_open() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-resume-") as tmp:
        book = _book(tmp)
        try:
            task_id = book.add_task("wait a while", _steps("tell_time"))
            book.set_status(task_id, "paused")
            assert [task["id"] for task in book.unfinished()] == [task_id], (
                "a paused task disappeared from the list of tasks that can be resumed"
            )
        finally:
            book.close()


def test_a_journal_written_before_provenance_existed_gains_the_column() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-resume-") as tmp:
        path = Path(tmp) / "journal.sqlite3"
        connection = sqlite3.connect(str(path))
        connection.executescript(
            """
            CREATE TABLE tasks (
                id            TEXT PRIMARY KEY,
                run_id        TEXT NOT NULL,
                goal          TEXT NOT NULL,
                steps         TEXT NOT NULL,
                status        TEXT NOT NULL,
                step_index    INTEGER NOT NULL DEFAULT 0,
                attempts      TEXT NOT NULL DEFAULT '{}',
                result        TEXT,
                error         TEXT,
                needs         TEXT,
                created_ts    TEXT NOT NULL,
                updated_ts    TEXT NOT NULL
            );
            INSERT INTO tasks (id, run_id, goal, steps, status, created_ts, updated_ts)
            VALUES ('old1', 'r1', 'an old task', '[]', 'pending', '2026-01-01', '2026-01-01');
            """
        )
        connection.commit()
        connection.close()

        book = journal.Journal(path)
        try:
            task = book.task("old1")
            assert task is not None
            assert task["provenance"] == "user", (
                "a task recorded before provenance existed was given a different origin"
            )
        finally:
            book.close()


def test_the_command_offers_the_resume_and_asks_the_same_terminal_question() -> None:
    text = (AI_BIN / "astra-ai").read_text(encoding="utf-8")
    assert 'add_parser("resume"' in text
    assert "def cmd_resume" in text
    assert "def _terminal_confirm" in text, (
        "work and resume must ask the same question; two copies drift"
    )
