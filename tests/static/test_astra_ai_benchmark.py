"""The task benchmark measures the assistant, not the benchmark's own optimism.

Stage 4 asks for representative tasks with published pass rates. The catalogue
here is deliberately small - three tasks the assistant can attempt without a
model download - and the contract is what matters:

  * every task is run through `Worker.handle`, the same entry point a user
    reaches, and an exception is a failed task rather than a crashed suite;
  * a pass means the worker answered or did something, not that it refused or
    crashed; a failure carries the worker's own reason;
  * the report has a pass rate computed from the records, and each record has
    the time that task actually took;
  * `--limit` cuts the suite without changing how a record is judged;
  * the text rendering shows every task and why it failed.

A fake worker is used, so this runs on a machine with no model and no engine.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_LIB = REPO_ROOT / "packages" / "astraos-ai" / "root" / "usr" / "lib"
if str(AI_LIB) not in sys.path:
    sys.path.insert(0, str(AI_LIB))

from astraos.ai import benchmark  # noqa: E402

DESCRIPTION = (
    "The task benchmark runs through Worker.handle, reports a pass rate with reasons, "
    "and treats a crash as a failed task"
)


class _Worker:
    """A worker whose answers are chosen by the test, in call order."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.requests: list[tuple[str, str]] = []

    def handle(self, request: str, context: str = "") -> dict:
        self.requests.append((request, context))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _task(name: str = "one", request: str = "do the thing"):
    return benchmark.BenchmarkTask(name, request, benchmark._check_ok)


def test_a_pass_is_an_answer_or_an_action() -> None:
    for kind in ("answer", "action", "plan"):
        report = benchmark.run(_Worker([{"kind": kind, "text": "done"}]), [_task()])
        assert report["passed"] == 1, kind
        assert report["pass_rate"] == 1.0
        assert report["tasks"][0]["passed"] is True
        assert report["tasks"][0]["seconds"] is not None
        assert report["tasks"][0]["seconds"] >= 0


def test_a_refusal_is_a_failure_with_the_workers_reason() -> None:
    report = benchmark.run(
        _Worker([{"kind": "refuse", "text": "that changes the system"}]), [_task()]
    )
    record = report["tasks"][0]
    assert report["failed"] == 1
    assert record["passed"] is False
    assert "refuse" in record["reason"]
    assert record["kind"] == "refuse"


def test_a_crash_is_one_failed_task_not_a_failed_suite() -> None:
    report = benchmark.run(
        _Worker([RuntimeError("the engine died"), {"kind": "answer", "text": "ok"}]),
        [_task("first"), _task("second")],
    )
    assert report["count"] == 2
    assert report["failed"] == 1
    assert report["passed"] == 1
    assert "engine died" in report["tasks"][0]["reason"]


def test_the_limit_cuts_the_suite_without_changing_a_verdict() -> None:
    worker = _Worker([{"kind": "answer", "text": "ok"}])
    report = benchmark.run(worker, [_task("a"), _task("b"), _task("c")], limit=1)
    assert report["count"] == 1
    assert worker.requests == [("do the thing", "")]
    assert report["pass_rate"] == 1.0


def test_the_catalogue_is_small_but_named_and_unique() -> None:
    ids = [task.id for task in benchmark.BENCHMARK_TASKS]
    assert len(ids) >= 3
    assert len(ids) == len(set(ids))
    assert all(task.request for task in benchmark.BENCHMARK_TASKS)


def test_the_text_report_shows_failures_and_why() -> None:
    report = benchmark.run(
        _Worker([{"kind": "answer", "text": "ok"}, {"kind": "refuse", "text": "no"}]),
        [_task("good"), _task("bad")],
    )
    text = benchmark.render(report)
    assert "1/2 (50%)" in text
    assert "ok   good" in text
    assert "FAIL bad" in text
    assert "no" in text


def test_the_report_is_json_serialisable() -> None:
    report = benchmark.run(_Worker([{"kind": "answer", "text": "ok"}]), [_task()])
    parsed = json.loads(json.dumps(report))
    assert parsed["suite"] == "astra-ai task benchmark v1"
