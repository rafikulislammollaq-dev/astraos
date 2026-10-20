"""Task benchmark: representative research-assistant tasks with pass rates.

WHY THIS EXISTS
    Stage 4 asks for a benchmark of representative tasks with published pass
    rates, starting smaller than the review's suggested one hundred cases and
    growing. This module defines the tasks and runs them through the worker,
    reporting what passed and what did not. Success targets are set from
    measured results, not aspiration.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Iterable

from . import worker as _worker


@dataclass
class BenchmarkTask:
    id: str
    request: str
    check: Callable[[dict], str]  # returns "" on pass, reason on fail
    context: str = ""


def _check_ok(outcome: dict) -> str:
    """A task passed when something was answered or done, not refused or crashed."""
    if outcome.get("kind") in ("action", "answer", "plan"):
        return ""
    return f"outcome was {outcome.get('kind')!r}, not action/answer/plan"


BENCHMARK_TASKS: tuple[BenchmarkTask, ...] = (
    BenchmarkTask("tell-time", "what time is it", _check_ok),
    BenchmarkTask("tell-battery", "what is the battery level", _check_ok),
    BenchmarkTask("find-document", "find the documents about AstraOS", _check_ok),
)


def run(worker, tasks: Iterable[BenchmarkTask] | None = None, limit: int | None = None) -> dict:
    planned = list(BENCHMARK_TASKS if tasks is None else tasks)
    if limit is not None and limit > 0:
        planned = planned[:limit]
    records = []
    started = time.monotonic()
    for task in planned:
        task_started = time.monotonic()
        try:
            outcome = worker.handle(task.request, task.context)
        except Exception as exc:  # noqa: BLE001 - a crashed task is a failure, not a crash
            outcome = {"kind": "failed", "text": str(exc)}
        reason = task.check(outcome) if callable(task.check) else ""
        if outcome.get("kind") == "failed":
            # The worker's own sentence is more useful than "the kind was
            # failed", so a crash keeps its cause in the report.
            reason = outcome.get("text") or reason or "failed"
        records.append(
            {
                "id": task.id,
                "request": task.request,
                "passed": not reason,
                "reason": reason,
                "kind": outcome.get("kind"),
                "seconds": round(time.monotonic() - task_started, 2),
            }
        )
    total = len(records)
    passed = sum(1 for r in records if r["passed"])
    return {
        "suite": "astra-ai task benchmark v1",
        "count": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": (passed / total) if total else 0.0,
        "seconds": round(time.monotonic() - started, 2),
        "tasks": records,
    }


def render(report: dict) -> str:
    lines = [
        "AstraOS task benchmark",
        f"  passed: {report['passed']}/{report['count']} ({report['pass_rate']:.0%})",
    ]
    for t in report.get("tasks", []):
        mark = "ok  " if t["passed"] else "FAIL"
        lines.append(f"  {mark} {t['id']}" + (f" - {t['reason']}" if not t["passed"] else ""))
    return "\n".join(lines).rstrip() + "\n"


# Aliases
task_benchmark = run
run_benchmark = run
benchmark = run


__all__ = [
    "BenchmarkTask",
    "BENCHMARK_TASKS",
    "run",
    "render",
    "task_benchmark",
    "run_benchmark",
    "benchmark",
]
