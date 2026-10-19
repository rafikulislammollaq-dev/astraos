"""Budgets: a plan cannot be unbounded, and a task cannot run forever.

`docs/ROADMAP.md`, Stage 4 asks for time, memory and tool-call limits so a weak
model cannot loop forever. This file proves the two that exist:

  * A plan longer than `MAX_PLAN_STEPS` is refused before it becomes a task, so
    the refusal is visible to the user and leaves no dead row behind.
  * A task that spends `MAX_TASK_SECONDS` stops where it is and is filed as
    `paused`, not `failed`: unfinished work is not wrong work, and `astra-ai
    resume` continues from the next step.
  * The streaming path (the web page) obeys the same limits as the collected
    path (the command line), because a budget that one entry point skips is not
    a budget.

The clock is injected, so no test here waits for real time to pass. The steps
are recorded rather than executed: `tell_time` is in the catalog, and a recorder
in front of `actions.execute` is what turns "the step ran" into a list entry.

Memory is not limited here, and this docstring says so on purpose: a hard RSS cap
needs a cgroup or a setrlimit around the model server, which is a separate
change. Nothing in this file should be read as claiming it.
"""

from __future__ import annotations

import contextlib
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_LIB = REPO_ROOT / "packages" / "astraos-ai" / "root" / "usr" / "lib"
if str(AI_LIB) not in sys.path:
    sys.path.insert(0, str(AI_LIB))

from astraos.ai import actions, journal, tiers, worker  # noqa: E402

DESCRIPTION = (
    "A plan over the step budget is refused before it starts, and a task over the "
    "time budget pauses where it stopped"
)


class _Clock:
    """A clock the test moves, so a nine-hundred-second budget costs no seconds."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class _StubPool:
    def __init__(self) -> None:
        self.borrowed: list[str] = []

    def ready(self) -> bool:
        return True

    def asking(self, tier: str):
        self.borrowed.append(tier)
        raise tiers.TierUnavailable(f"the {tier} tier has no model installed")


@contextlib.contextmanager
def _recorder(calls: list, clock: _Clock | None = None, seconds: float = 0.0):
    """actions.execute() replaced with a recorder that can spend time."""
    original = actions.execute

    def record(plan, confirmed=False, provenance="user"):  # noqa: ANN001 - mirrors actions.execute
        calls.append({"plan": dict(plan), "confirmed": confirmed, "provenance": provenance})
        if clock is not None:
            clock.now += seconds
        return {"ok": True, "output": "recorded", "error": ""}

    actions.execute = record
    try:
        yield calls
    finally:
        actions.execute = original


def _steps(*names: str) -> list[dict]:
    return [{"action": name, "args": {}} for name in names]


def _outcome(text: str = "a task") -> dict:
    return {"kind": "action", "text": text, "plan": [], "evidence": [], "needs": []}


def test_the_defaults_are_small_on_purpose() -> None:
    assert worker.MAX_PLAN_STEPS == 12
    assert worker.MAX_TASK_SECONDS == 900.0


def test_a_plan_longer_than_the_step_budget_is_refused_before_it_starts() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-budget-") as tmp:
        book = journal.Journal(Path(tmp) / "journal.sqlite3")
        try:
            plan = _steps(*(["tell_time"] * (worker.MAX_PLAN_STEPS + 1)))
            calls: list[dict] = []
            with _recorder(calls):
                result = worker.Worker(_StubPool(), journal=book).run_plan(plan, _outcome())

            assert result["kind"] == "refuse"
            assert f"at most {worker.MAX_PLAN_STEPS}" in result["text"]
            assert calls == [], "a refused plan still ran a step"
            assert book.unfinished() == [], "a plan that never started left a task behind"
        finally:
            book.close()


def test_a_plan_at_the_limit_runs_every_step() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-budget-") as tmp:
        book = journal.Journal(Path(tmp) / "journal.sqlite3")
        try:
            plan = _steps(*(["tell_time"] * worker.MAX_PLAN_STEPS))
            calls: list[dict] = []
            with _recorder(calls):
                result = worker.Worker(_StubPool(), journal=book).run_plan(plan, _outcome())

            assert result["kind"] == "action"
            assert len(calls) == worker.MAX_PLAN_STEPS
        finally:
            book.close()


def test_time_running_out_pauses_the_task_where_it_stopped() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-budget-") as tmp:
        book = journal.Journal(Path(tmp) / "journal.sqlite3")
        try:
            clock = _Clock()
            plan = _steps("tell_time", "tell_battery", "tell_system_info")
            calls: list[dict] = []
            with _recorder(calls, clock=clock, seconds=20.0):
                runner = worker.Worker(_StubPool(), journal=book, clock=clock, max_seconds=10.0)
                result = runner.run_plan(plan, _outcome("three readings"))

            assert [call["plan"]["action"] for call in calls] == ["tell_time"], (
                "the budget let the task run past the second step"
            )
            assert result["kind"] == "paused", (
                "unfinished work must be paused, not failed: " + str(result["kind"])
            )
            assert "10-second budget" in result["text"]
            assert "resume" in result["text"]

            open_tasks = book.unfinished()
            assert len(open_tasks) == 1
            assert open_tasks[0]["status"] == "paused"
            assert "resume" in str(open_tasks[0]["error"])
        finally:
            book.close()


def test_a_paused_task_resumes_at_the_next_step_and_finishes() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-budget-") as tmp:
        book = journal.Journal(Path(tmp) / "journal.sqlite3")
        try:
            clock = _Clock()
            plan = _steps("tell_time", "tell_battery", "tell_system_info")
            with _recorder([], clock=clock, seconds=20.0):
                runner = worker.Worker(_StubPool(), journal=book, clock=clock, max_seconds=10.0)
                runner.run_plan(plan, _outcome("three readings"))

            task_id = book.unfinished()[0]["id"]
            resumed: list[dict] = []
            with _recorder(resumed):
                answer = worker.Worker(_StubPool(), journal=book, clock=lambda: 0.0).resume_task(
                    task_id
                )

            assert [call["plan"]["action"] for call in resumed] == [
                "tell_battery",
                "tell_system_info",
            ], "resume repeated the step that had already run"
            assert answer["kind"] == "action"
            assert book.task(task_id)["status"] == "ok"
        finally:
            book.close()


def test_the_streaming_path_obeys_the_same_time_budget() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-budget-") as tmp:
        book = journal.Journal(Path(tmp) / "journal.sqlite3")
        try:
            clock = _Clock()
            plan = _steps("tell_time", "tell_battery")
            with _recorder([], clock=clock, seconds=20.0):
                runner = worker.Worker(_StubPool(), journal=book, clock=clock, max_seconds=10.0)
                events = list(runner._run_plan_events(plan, _outcome("two readings")))

            done = events[-1]
            assert done["type"] == "done"
            assert done["kind"] == "paused"
            assert book.unfinished()[0]["status"] == "paused"
        finally:
            book.close()
