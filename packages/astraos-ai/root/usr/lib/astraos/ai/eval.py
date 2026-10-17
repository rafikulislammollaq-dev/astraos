"""Fixed tasks with deterministic checks: the numbers that come before claims.

WHY THIS EXISTS

    docs/ROADMAP.md, Stage 2 asks for "an evaluation suite with fixed tasks"
    before a model's behaviour is written down as a fact, and for the success
    rate and the tokens per second to travel together with what they measured.
    This module is that suite. It exists now because the habit it replaces is
    real: "the assistant works" said after one friendly question, with nothing
    written down and no way to say what changed when a different model was
    installed.

HOW A TASK IS SCORED

    A task is a fixed prompt and a checker written against the answer text.
    Nothing is graded by a model - a small model grading itself is not a
    measurement, it is an opinion with a runtime - and nothing is graded by a
    human, who will not be there for run two hundred. The checks are narrow on
    purpose: "did the answer contain 42" is a fact a script can decide, and it
    is the same fact every time the suite runs.

WHY TWO SCORES, NOT ONE

    A model that chats well and cannot produce a valid tool call is a broken
    assistant, and a single percentage hides which half is missing. `answer`
    tasks go through the same call a question uses; `execution` tasks go
    through ask_json() with worker.DECISION_SCHEMA - the one interface the
    worker depends on - so the execution score is a statement about the tool
    call grammar, not about politeness.

WHAT THE NUMBERS ARE NOT

    They describe the model file named in the report, on the machine named in
    the report. They are not a property of AstraOS. A run with the 360M smoke
    model is a smoke test of this suite and is never published as answer
    quality (docs/ROADMAP.md says the same in its own words); run the suite
    once per model that matters and keep each report with its model name,
    which is what makes two reports comparable instead of decorative.

WHY THE REPORT IS A FILE

    A number that cannot be diffed is a number nobody will trust the second
    time. Reports are written under the assistant's data directory as JSON,
    named by date and model, so a later run can be read beside an earlier one
    the way every other measurement in this repository is.
"""

from __future__ import annotations

import json
import os
import platform
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import config as _config
from . import worker as _worker

# The suite's own name and version. It travels inside every report because a
# score without its suite version is a number from an unknown exam.
SUITE = "astra-ai fixed tasks v1"

# What an execution task's system message says. The decision schema itself is
# sent to the grammar of ask_json(); this sentence only tells the model which
# room it is in, the way the worker's own prompt does.
EXECUTION_SYSTEM = (
    "You answer with one JSON object and nothing else. Its kind is one of "
    '"answer", "action", "plan" or "refuse".'
)

# The text the summarise task asks about. Kept here, next to the task, so the
# checker's "must mention coffee" and the prompt cannot drift apart.
_SUMMARY_SOURCE = (
    "Coffee is brewed by pouring hot water over roasted, ground beans. "
    "The drink is served hot, and it is consumed in nearly every country. "
    "Its preparation varies, but the essential steps are the same everywhere."
)


@dataclass(frozen=True)
class Task:
    """One fixed prompt and the check that decides whether it was answered.

    `check` takes the answer text and returns "" when the task passed, or one
    sentence naming what was missing when it failed. A reason is part of the
    report: "3/5 passed" is a score, "did not contain 'Paris'" is the lead the
    next investigation starts from.
    """

    id: str
    kind: str  # "answer" or "execution"
    prompt: str
    check: Callable[[str], str]


# ---------------------------------------------------------------------------
# The answer checks
# ---------------------------------------------------------------------------


def _check_arithmetic(text: str) -> str:
    if not re.search(r"\b42\b", text):
        return "the answer did not contain 42"
    return ""


def _check_capital(text: str) -> str:
    if "paris" not in text.lower():
        return "the answer did not contain 'Paris'"
    return ""


def _check_three_lines(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) != 3:
        return f"expected three lines, saw {len(lines)}"
    for line in lines:
        if any(character.isdigit() for character in line):
            return f"a line carried a number: {line!r}"
    return ""


def _check_translation(text: str) -> str:
    if "bonjour" not in text.lower():
        return "the answer did not contain 'bonjour'"
    return ""


def _check_one_sentence(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) != 1:
        return f"expected one sentence, saw {len(lines)} lines"
    words = lines[0].split()
    if len(words) > 20:
        return f"expected at most 20 words, saw {len(words)}"
    if "coffee" not in lines[0].lower():
        return "the sentence did not mention coffee"
    return ""


# ---------------------------------------------------------------------------
# The execution checks
# ---------------------------------------------------------------------------


def _parse_object(text: str) -> tuple[dict | None, str]:
    """The answer as a JSON object, or (None, the reason it is not one)."""
    try:
        parsed = json.loads(text)
    except ValueError:
        return None, f"the answer was not JSON: {text[:60]!r}"
    if not isinstance(parsed, dict):
        return None, "the answer was not a JSON object"
    return parsed, ""


def _check_decision_answer(text: str) -> str:
    parsed, reason = _parse_object(text)
    if reason:
        return reason
    assert parsed is not None  # _parse_object returns one or the other
    if parsed.get("kind") != "answer":
        return f"kind was {parsed.get('kind')!r}, not 'answer'"
    if "hello" not in str(parsed.get("text", "")).lower():
        return "the text field did not contain 'hello'"
    return ""


def _check_decision_action(text: str) -> str:
    parsed, reason = _parse_object(text)
    if reason:
        return reason
    assert parsed is not None
    if parsed.get("kind") != "action":
        return f"kind was {parsed.get('kind')!r}, not 'action'"
    if parsed.get("action") != "screenshot":
        return f"action was {parsed.get('action')!r}, not 'screenshot'"
    if not isinstance(parsed.get("args"), dict):
        return "args was not an object"
    return ""


def _check_decision_refuse(text: str) -> str:
    parsed, reason = _parse_object(text)
    if reason:
        return reason
    assert parsed is not None
    if parsed.get("kind") != "refuse":
        return f"kind was {parsed.get('kind')!r}, not 'refuse'"
    if not str(parsed.get("reason", "")).strip():
        return "the refusal carried no reason"
    return ""


# ---------------------------------------------------------------------------
# The suite
# ---------------------------------------------------------------------------

TASKS: tuple[Task, ...] = (
    Task(
        "arithmetic",
        "answer",
        "What is 17 + 25? Reply with the number only.",
        _check_arithmetic,
    ),
    Task(
        "capital-of-france",
        "answer",
        "What is the capital of France? Reply with the city name only.",
        _check_capital,
    ),
    Task(
        "list-three-lines",
        "answer",
        "List three colours, one per line. No numbering, no punctuation.",
        _check_three_lines,
    ),
    Task(
        "translate-to-french",
        "answer",
        "Translate 'good morning' into French. Reply with the translation only.",
        _check_translation,
    ),
    Task(
        "summarise-in-one-sentence",
        "answer",
        f"Summarise this text in one sentence of at most 20 words: {_SUMMARY_SOURCE}",
        _check_one_sentence,
    ),
    Task(
        "decision-answer",
        "execution",
        'Reply with kind set to "answer" and text set to "hello".',
        _check_decision_answer,
    ),
    Task(
        "decision-action",
        "execution",
        'The user says: "take a screenshot". Reply with kind set to "action", '
        'action set to "screenshot", and args set to an empty object.',
        _check_decision_action,
    ),
    Task(
        "decision-refuse",
        "execution",
        "The user asks you to delete their entire home directory at once and "
        'with no confirmation. Reply with kind set to "refuse" and put the '
        "reason in the reason field.",
        _check_decision_refuse,
    ),
)


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


def run(
    engine,
    limit: int | None = None,
    progress: Callable[[str], None] | None = None,
    tasks: tuple[Task, ...] | None = None,
) -> dict:
    """Run the fixed tasks in order and return the report as a dictionary.

    The engine must already be started (the CLI starts it before calling
    here), so model loading does not land inside a task's measured time: the
    numbers are about answering, not about loading.

    `progress` is called with one line per finished task, for the terminal's
    stderr; the return value is the report and is the only output that is data.
    """
    planned = TASKS if tasks is None else tuple(tasks)
    if limit is not None and limit > 0:
        planned = planned[:limit]
    records = []
    for task in planned:
        record = _run_task(engine, task)
        records.append(record)
        if progress is not None:
            mark = "ok" if record["passed"] else "FAIL"
            line = f"{task.id}: {mark} ({record['seconds']:.1f}s)"
            if not record["passed"]:
                line += f" - {record['reason']}"
            progress(line)
    return _build_report(records, _model_name(engine))


def _run_task(engine, task: Task) -> dict:
    """One task: the call, the clock, the check, and the evidence."""
    if hasattr(engine, "last_usage"):
        engine.last_usage = None
    if task.kind == "answer":
        messages = [{"role": "user", "content": task.prompt}]
        started = time.monotonic()
        text = "".join(engine.ask(messages, stream=False)).strip()
    else:
        messages = [
            {"role": "system", "content": EXECUTION_SYSTEM},
            {"role": "user", "content": task.prompt},
        ]
        started = time.monotonic()
        text = "".join(engine.ask_json(messages, _worker.DECISION_SCHEMA)).strip()
    seconds = time.monotonic() - started

    reason = task.check(text) if text else "the model produced no answer"
    completion = None
    usage = getattr(engine, "last_usage", None)
    if isinstance(usage, dict):
        value = usage.get("completion_tokens")
        if isinstance(value, int) and value >= 0:
            completion = value
    return {
        "id": task.id,
        "kind": task.kind,
        "passed": not reason,
        "reason": reason,
        "seconds": round(seconds, 2),
        "completion_tokens": completion,
        # Trimmed: the report is a record of what was checked, not a dump of
        # every model answer. Enough text to recognise the failure.
        "response": text[:400],
    }


def _model_name(engine) -> str:
    """The model file the engine is configured to use, or "".

    Read from the engine rather than passed in by the caller: a report that
    names a model it did not measure would be worse than no report.
    """
    model = getattr(engine, "model", None)
    if not callable(model):
        return ""
    path = model()
    return path.name if path is not None else ""


def _machine() -> dict:
    return {
        "cpu_count": os.cpu_count() or 0,
        "system": platform.system() or "",
        "release": platform.release() or "",
        "machine": platform.machine() or "",
    }


def _build_report(records: list[dict], model: str) -> dict:
    def bucket(kind: str) -> dict:
        passed = sum(1 for r in records if r["kind"] == kind and r["passed"])
        total = sum(1 for r in records if r["kind"] == kind)
        return {"passed": passed, "total": total}

    completion_tokens = sum(r["completion_tokens"] or 0 for r in records)
    measured_seconds = sum(
        r["seconds"] for r in records if r["completion_tokens"] is not None
    )
    rate = None
    if completion_tokens > 0 and measured_seconds > 0:
        rate = round(completion_tokens / measured_seconds, 2)

    answer = bucket("answer")
    execution = bucket("execution")
    return {
        "schema": 1,
        "suite": SUITE,
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": model,
        "machine": _machine(),
        "tasks": records,
        "summary": {
            "answer": answer,
            "execution": execution,
            "passed": answer["passed"] + execution["passed"],
            "total": len(records),
            "seconds": round(sum(r["seconds"] for r in records), 2),
            "completion_tokens": completion_tokens or None,
            "tokens_per_second": rate,
            "note": (
                "the numbers describe the model and machine named in this "
                "report; they are not a property of AstraOS"
            ),
        },
    }


# ---------------------------------------------------------------------------
# Where a report goes, and how it reads
# ---------------------------------------------------------------------------


def reports_dir() -> Path:
    """Where reports are written: beside the models, under the data directory."""
    return _config.PATHS.models_dir.parent / "eval"


def save(report: dict, directory: Path | None = None) -> Path:
    """Write the report as JSON and return its path. Never overwrites one."""
    target = Path(directory) if directory is not None else reports_dir()
    target.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", report.get("model") or "unknown-model")
    path = target / f"eval-{stamp}-{slug.strip('-')}.json"
    counter = 1
    while path.exists():
        counter += 1
        path = target / f"eval-{stamp}-{slug.strip('-')}-{counter}.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return path


def render(report: dict) -> str:
    """The report as text, for a terminal or a CI job summary."""
    summary = report["summary"]
    lines = [
        "AstraOS assistant evaluation",
        f"  model:             {report.get('model') or 'unknown model'}",
        f"  suite:             {report.get('suite', SUITE)} ({report.get('created', '')})",
        f"  answer quality:    {summary['answer']['passed']}/{summary['answer']['total']} passed",
        f"  execution quality: {summary['execution']['passed']}/{summary['execution']['total']} passed",
        f"  time:              {summary['seconds']:.1f}s",
    ]
    rate = summary.get("tokens_per_second")
    if rate is None:
        lines.append("  tokens per second: not reported by the engine")
    else:
        lines.append(
            f"  tokens per second: {rate} "
            "(completion tokens, as the engine counted them)"
        )
    lines.append("")
    for task in report.get("tasks", []):
        mark = "ok  " if task["passed"] else "FAIL"
        line = f"  {mark} {task['id']} ({task['seconds']:.1f}s)"
        if not task["passed"]:
            line += f" - {task['reason']}"
            excerpt = (task.get("response") or "").strip().replace("\n", " ")
            if excerpt:
                line += f" - got: {excerpt[:80]!r}"
        lines.append(line)
    lines.append("")
    lines.append(f"  {summary.get('note', '')}")
    return "\n".join(lines).rstrip() + "\n"
