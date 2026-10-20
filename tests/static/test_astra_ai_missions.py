"""Missions: the journal's open tasks, read as progress a person can check.

Stage 4 asks for the task interface. There is no graphical window yet; what
exists is the read model a window would use, and this file proves it cannot
invent progress:

  * the percentage is the journal's executed step index over the plan length;
    a task with no plan is 0%, not a division by zero;
  * `paused`, `awaiting approval` and `verifying` are open and appear;
    `ok` and `failed` are finished and do not;
  * an approval the journal is waiting on is counted, because that is the thing
    a person must act on;
  * the text rendering marks completed, next and future steps the same way
    plan.md does, and the JSON summary is serialisable.

The journal is a temporary SQLite file; no test reads or writes the real one.
Each one is closed before the temporary directory is removed, because Windows
refuses to delete an open database file and a test failure there would hide the
result that matters.
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_LIB = REPO_ROOT / "packages" / "astraos-ai" / "root" / "usr" / "lib"
if str(AI_LIB) not in sys.path:
    sys.path.insert(0, str(AI_LIB))

CLI = REPO_ROOT / "packages" / "astraos-ai" / "root" / "usr" / "bin" / "astra-ai"

from astraos.ai import journal as journal_module  # noqa: E402
from astraos.ai import missions  # noqa: E402

DESCRIPTION = (
    "Missions reports the journal's real step progress for open tasks, counts "
    "approvals, and invents nothing"
)

PLAN = [
    {"action": "search_files", "why": "find the document"},
    {"action": "read_file", "why": "read it"},
    {"action": "write_file", "why": "save the summary"},
]


@contextlib.contextmanager
def _journal():
    with tempfile.TemporaryDirectory(prefix="astraos-missions-") as tmp:
        active = journal_module.Journal(Path(tmp) / "journal.db")
        try:
            yield active
        finally:
            active.close()


def test_progress_is_the_executed_step_index() -> None:
    with _journal() as active:
        task = active.add_task("summarise the notes", PLAN)
        active.set_status(task, "running")

        assert missions.list_missions(active)[0]["percent"] == 0
        active.set_step(task, 1)
        assert missions.list_missions(active)[0]["percent"] == 33
        active.set_step(task, 3)
        assert missions.list_missions(active)[0]["percent"] == 100


def test_a_task_with_no_plan_is_zero_not_a_crash() -> None:
    with _journal() as active:
        task = active.add_task("something vague", [])

        mission = missions.list_missions(active)[0]
        assert mission["id"] == task
        assert mission["progress"] == 0
        assert mission["total"] == 0
        assert mission["percent"] == 0


def test_open_states_appear_and_finished_ones_do_not() -> None:
    with _journal() as active:
        pending = active.add_task("pending task", PLAN)
        running = active.add_task("running task", PLAN)
        waiting = active.add_task("waiting task", PLAN)
        paused = active.add_task("paused task", PLAN)
        verifying = active.add_task("verifying task", PLAN)
        done = active.add_task("done task", PLAN)
        failed = active.add_task("failed task", PLAN)

        active.set_status(running, "running")
        active.set_status(waiting, "awaiting approval")
        active.set_status(paused, "paused")
        active.set_status(verifying, "verifying")
        active.set_status(done, "ok")
        active.set_status(failed, "failed")

        opened = {mission["id"] for mission in missions.list_missions(active)}
        assert opened == {pending, running, waiting, paused, verifying}
        assert done not in opened and failed not in opened


def test_a_pending_approval_is_part_of_the_summary() -> None:
    with _journal() as active:
        task = active.add_task("change the system", PLAN)
        active.set_status(task, "awaiting approval")
        active.ask("run_command", "run the exact command shown?", task_id=task)

        summary = missions.summary(active)
        assert summary["count"] == 1
        assert summary["pending_approvals"] == 1
        assert summary["missions"][0]["needs"] is None


def test_the_text_marks_completed_next_and_future_steps() -> None:
    with _journal() as active:
        task = active.add_task("summarise the notes", PLAN)
        active.set_status(task, "running")
        active.set_step(task, 1)

        text = missions.render(active)
        assert "summarise the notes" in text
        assert "1/3 (33%)" in text
        assert "- [x] 1. search_files" in text
        assert "- [>] 2. read_file" in text
        assert "- [ ] 3. write_file" in text
        assert task in text


def test_nothing_open_says_so() -> None:
    with _journal() as active:
        assert missions.render(active) == "No open missions.\n"
        assert missions.summary(active)["count"] == 0


def test_the_summary_is_json_serialisable() -> None:
    with _journal() as active:
        active.add_task("one task", PLAN)
        text = json.dumps(missions.summary(active), sort_keys=True)
        assert "one task" in text


def test_the_command_lists_a_mission_from_the_real_journal_path() -> None:
    """`astra-ai missions` is the read path a person actually types."""
    with tempfile.TemporaryDirectory(prefix="astraos-missions-cli-") as tmp:
        models = Path(tmp) / "models"
        models.mkdir()
        active = journal_module.Journal(models.parent / "journal.sqlite3")
        try:
            task = active.add_task("summarise the notes", PLAN)
            active.set_status(task, "running")
            active.set_step(task, 1)
        finally:
            active.close()

        environment = dict(os.environ)
        environment["ASTRAOS_AI_MODELS_DIR"] = str(models)
        done = subprocess.run(
            [sys.executable, str(CLI), "missions", "--json"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            timeout=120,
        )
        assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
        parsed = json.loads(done.stdout.decode("utf-8"))
        assert parsed["count"] == 1
        assert parsed["missions"][0]["goal"] == "summarise the notes"
        assert parsed["missions"][0]["percent"] == 33
