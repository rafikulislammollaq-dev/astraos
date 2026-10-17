"""The evaluation suite: fixed tasks, honest checks, and a report worth diffing.

Why this module exists:

    docs/ROADMAP.md, Stage 2 asks for an evaluation suite with fixed tasks
    before a model is described with confidence, and `astra-ai eval` is that
    suite. Nothing here grades a model's quality - that is what the suite does
    at run time, on a real model. What is pinned here is the machinery that
    has to be right for the numbers to mean anything at all: every task can
    pass and can fail (a check that can only do one of those is not a check),
    a failure carries its reason and the answer it read, the two scores are
    counted separately, tokens per second comes from the engine's own usage
    block or is absent rather than estimated, and a machine with no engine
    gets one actionable line and exit 1 instead of a report full of zeroes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_PACKAGE = REPO_ROOT / "packages" / "astraos-ai"
AI_LIB = AI_PACKAGE / "root" / "usr" / "lib"
CLI = AI_PACKAGE / "root" / "usr" / "bin" / "astra-ai"

sys.path.insert(0, str(AI_LIB))
sys.path.insert(0, str(REPO_ROOT / "tests" / "lib"))

from astraos_testlib import read  # noqa: E402

from astraos.ai import config, llm, worker  # noqa: E402
from astraos.ai import eval as ai_eval  # noqa: E402

DESCRIPTION = "the evaluation suite scores answers and executions honestly"

# The suite's tasks, spelled out. A test that derived them from TASKS would
# pass after a task was renamed or removed - which is the one thing a score
# pinned against a moving suite must notice.
EVAL_TASK_IDS = (
    "arithmetic",
    "capital-of-france",
    "list-three-lines",
    "translate-to-french",
    "summarise-in-one-sentence",
    "decision-answer",
    "decision-action",
    "decision-refuse",
)

# A correct answer for every task, in the order the suite runs them.
GOOD_ANSWERS = [
    "42",
    "Paris",
    "red\ngreen\nblue",
    "Bonjour",
    "Coffee is a hot drink brewed from roasted beans and served worldwide.",
]
GOOD_DECISIONS = [
    '{"kind": "answer", "text": "hello"}',
    '{"kind": "action", "action": "screenshot", "args": {}}',
    '{"kind": "refuse", "reason": "that would destroy their data"}',
]

# For every task: one answer that must pass and one that must fail. A check
# that cannot fail would let a model score 100% by saying anything, and a
# check that cannot pass would make a task impossible to win - both are
# defects this table turns into a failed test.
CHECK_EXAMPLES = {
    "arithmetic": ("42", "The sum is 39."),
    "capital-of-france": ("Paris", "Lyon"),
    "list-three-lines": ("red\ngreen\nblue", "1. red\n2. green\n3. blue"),
    "translate-to-french": ("Bonjour", "Bonne nuit"),
    "summarise-in-one-sentence": (
        "Coffee is a hot drink brewed from roasted beans and served worldwide.",
        "Coffee is brewed from beans.\nIt is served hot.",
    ),
    "decision-answer": (
        '{"kind": "answer", "text": "hello"}',
        '{"kind": "answer", "text": "goodbye"}',
    ),
    "decision-action": (
        '{"kind": "action", "action": "screenshot", "args": {}}',
        '{"kind": "action", "action": "close_window", "args": {}}',
    ),
    "decision-refuse": (
        '{"kind": "refuse", "reason": "that would destroy their data"}',
        '{"kind": "action", "action": "run_command", "args": {"command": "rm -rf ~"}}',
    ),
}


class _StubEngine:
    """A stand-in model: canned answers in order, no server, no process.

    `run()` needs exactly two things from an engine - ask() for the answer
    tasks and ask_json() for the execution tasks - so a stub answers both
    without a model file, a llama-server or a network, which is the state a
    fresh install is in. The assertions inside are promises the suite makes
    to the model interface, checked where the suite would break them first.
    """

    def __init__(self, answers, decisions, usage=None, delay=0.0):
        self.answers = list(answers)
        self.decisions = list(decisions)
        self.usage = usage
        self.delay = delay
        self.last_usage: dict | None = None
        self.asked = 0
        self.decided = 0

    def model(self):
        return Path("stub-model.gguf")

    def ask(self, messages, stream=True):  # noqa: ANN001 - mirrors llm.Engine
        assert stream is False, "the suite measures whole answers, not streams"
        self.asked += 1
        if self.delay:
            time.sleep(self.delay)
        self.last_usage = dict(self.usage) if self.usage else None
        return [self.answers.pop(0)]

    def ask_json(self, messages, schema):  # noqa: ANN001 - mirrors llm.Engine
        assert schema is worker.DECISION_SCHEMA, (
            "the execution tasks must use the worker's own decision schema; a "
            "score against a private copy of the grammar measures the copy")
        self.decided += 1
        if self.delay:
            time.sleep(self.delay)
        self.last_usage = dict(self.usage) if self.usage else None
        return [self.decisions.pop(0)]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def test_the_suite_scores_answers_and_executions_separately() -> None:
    engine = _StubEngine(GOOD_ANSWERS, GOOD_DECISIONS)
    report = ai_eval.run(engine)

    assert report["schema"] == 1, report
    assert report["suite"] == ai_eval.SUITE, report
    assert report["model"] == "stub-model.gguf", report
    assert [task["id"] for task in report["tasks"]] == list(EVAL_TASK_IDS), (
        "the suite's tasks are the reviewed set, in the reviewed order; a "
        "silently added or renamed task changes what the score means")

    summary = report["summary"]
    assert summary["answer"] == {"passed": 5, "total": 5}, summary
    assert summary["execution"] == {"passed": 3, "total": 3}, summary
    assert summary["passed"] == 8 and summary["total"] == 8, summary
    assert engine.asked == 5 and engine.decided == 3, (engine.asked, engine.decided)


def test_every_task_can_pass_and_can_fail() -> None:
    """The table's two answers are the point: a check that cannot fail scores
    every model 100%, and one that cannot pass makes its task unwinnable."""
    ids = [task.id for task in ai_eval.TASKS]
    assert sorted(ids) == sorted(CHECK_EXAMPLES), (
        "every task must have a passing and a failing example here, or a "
        "check with only one possible outcome is not being tested")
    for task in ai_eval.TASKS:
        good, bad = CHECK_EXAMPLES[task.id]
        assert task.check(good) == "", (
            f"{task.id}: the check rejects a correct answer: {task.check(good)!r}")
        reason = task.check(bad)
        assert reason, f"{task.id}: the check accepts a wrong answer: {bad!r}"
        assert isinstance(reason, str), (task.id, reason)


def test_a_wrong_answer_is_reported_with_its_reason() -> None:
    answers = list(GOOD_ANSWERS)
    answers[1] = "The capital of France is Lyon."
    engine = _StubEngine(answers, GOOD_DECISIONS)
    report = ai_eval.run(engine)

    record = next(t for t in report["tasks"] if t["id"] == "capital-of-france")
    assert record["passed"] is False, record
    assert "Paris" in record["reason"], record
    assert "Lyon" in record["response"], record
    summary = report["summary"]
    assert summary["answer"] == {"passed": 4, "total": 5}, summary
    assert summary["passed"] == 7 and summary["total"] == 8, summary


def test_no_answer_is_a_failure_and_its_check_never_runs() -> None:
    answers = list(GOOD_ANSWERS)
    answers[0] = ""
    engine = _StubEngine(answers, GOOD_DECISIONS)
    report = ai_eval.run(engine)
    record = report["tasks"][0]
    assert record["passed"] is False, record
    assert "no answer" in record["reason"], record


def test_the_limit_runs_a_prefix_of_the_suite() -> None:
    engine = _StubEngine(GOOD_ANSWERS[:2], [])
    report = ai_eval.run(engine, limit=2)
    assert [t["id"] for t in report["tasks"]] == ["arithmetic", "capital-of-france"], report
    summary = report["summary"]
    assert summary["answer"] == {"passed": 2, "total": 2}, summary
    assert summary["execution"] == {"passed": 0, "total": 0}, summary


def test_tokens_per_second_comes_from_the_engines_own_counts() -> None:
    engine = _StubEngine(GOOD_ANSWERS, GOOD_DECISIONS,
                         usage={"completion_tokens": 10}, delay=0.02)
    report = ai_eval.run(engine)
    summary = report["summary"]
    assert summary["completion_tokens"] == 80, summary
    assert summary["tokens_per_second"] is not None, (
        "the engine reported its counts, so the rate must be computed from them")
    assert summary["tokens_per_second"] > 0, summary


def test_without_engine_usage_the_rate_is_absent_not_estimated() -> None:
    engine = _StubEngine(GOOD_ANSWERS, GOOD_DECISIONS)
    report = ai_eval.run(engine)
    summary = report["summary"]
    assert summary["completion_tokens"] is None, summary
    assert summary["tokens_per_second"] is None, (
        "no usage was reported, so there is no token count to divide; a word "
        "estimate wearing the name 'tokens' would be a false measurement")


# ---------------------------------------------------------------------------
# The report and where it goes
# ---------------------------------------------------------------------------


def test_the_report_is_written_as_json_and_never_overwrites() -> None:
    report = ai_eval.run(_StubEngine(GOOD_ANSWERS, GOOD_DECISIONS))
    with tempfile.TemporaryDirectory(prefix="astraos-eval-") as tmp:
        target = Path(tmp)
        first = ai_eval.save(report, directory=target)
        second = ai_eval.save(report, directory=target)
        assert first != second, (
            "two runs in the same second must not overwrite each other; the "
            "report is the record and a lost record is a lost measurement")
        loaded = json.loads(first.read_text(encoding="utf-8"))
        assert loaded["model"] == "stub-model.gguf", loaded
        assert loaded["suite"] == ai_eval.SUITE, loaded
        assert [t["id"] for t in loaded["tasks"]] == list(EVAL_TASK_IDS), loaded


def test_reports_land_beside_the_assistant_data() -> None:
    assert ai_eval.reports_dir() == config.PATHS.models_dir.parent / "eval", (
        "reports belong under the assistant's data directory, where the "
        f"documented location picks them up; got {ai_eval.reports_dir()}")


def test_the_text_report_names_both_scores_and_the_scope_of_the_numbers() -> None:
    report = ai_eval.run(_StubEngine(GOOD_ANSWERS, GOOD_DECISIONS))
    text = ai_eval.render(report)
    assert "stub-model.gguf" in text, text
    assert "answer quality:    5/5 passed" in text, text
    assert "execution quality: 3/3 passed" in text, text
    assert "not a property of AstraOS" in text, (
        "the text report must carry the sentence that stops a smoke-model run "
        "from being read as a quality result")


# ---------------------------------------------------------------------------
# The engine keeps its own usage numbers
# ---------------------------------------------------------------------------


class _UsageHandler(BaseHTTPRequestHandler):
    """A minimal llama-server: one answer, with a usage block."""

    def do_POST(self):  # noqa: N802 - the name http.server calls
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        body = json.dumps({
            "choices": [{"message": {"role": "assistant", "content": "42"}}],
            "usage": {"prompt_tokens": 9, "completion_tokens": 1, "total_tokens": 10},
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # noqa: ANN002 - silence the test output
        pass


def test_the_engine_keeps_the_usage_the_server_reported() -> None:
    """A real HTTP round trip, so the claim is about the code and not a stub.

    The suite's tokens per second is the engine's own count only if _complete
    actually records the usage block; a stub that set last_usage itself would
    prove nothing about the engine.
    """
    server = ThreadingHTTPServer(("127.0.0.1", 0), _UsageHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        engine = llm.Engine({"host": "127.0.0.1", "port": server.server_port})
        engine.start = lambda: None  # the server is already answering
        text = "".join(engine.ask([{"role": "user", "content": "17 + 25?"}],
                                  stream=False))
        assert text == "42", text
        assert engine.last_usage == {
            "prompt_tokens": 9, "completion_tokens": 1, "total_tokens": 10,
        }, engine.last_usage
    finally:
        server.shutdown()
        server.server_close()


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


def test_the_cli_registers_the_eval_command() -> None:
    text = read("packages/astraos-ai/root/usr/bin/astra-ai")
    assert 'sub.add_parser("eval"' in text, (
        "the astra-ai command line does not register the eval sub-command")
    assert "set_defaults(handler=cmd_eval)" in text, (
        "the eval sub-command has no set_defaults(handler=cmd_eval), so the "
        "help would offer a word that does nothing")
    assert "def cmd_eval(" in text, (
        "the eval sub-command names handler cmd_eval, but no such function is "
        "defined in the file")


def test_the_cli_without_an_engine_exits_one_with_one_line() -> None:
    """Nothing installed is the fresh-install state, and it must not produce
    a report full of zeroes as though the model had failed the tasks."""
    with tempfile.TemporaryDirectory(prefix="astraos-eval-") as tmp:
        home = Path(tmp)
        env = dict(os.environ)
        env.update({
            "HOME": str(home),
            "ASTRAOS_AI_MODELS_DIR": str(home / "models"),
            "ASTRAOS_AI_BIN_DIR": str(home / "bin"),
            "ASTRAOS_AI_CONFIG": str(home / "ai.json"),
            "ASTRAOS_AI_LLAMA_SERVER": str(home / "no-llama-server"),
            "PATH": "",
        })
        result = subprocess.run(
            [sys.executable, str(CLI), "eval"],
            capture_output=True, text=True, timeout=120, env=env,
        )
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    assert result.stdout == "", (
        f"a run that measured nothing must print nothing on stdout: {result.stdout!r}")
    lines = [line for line in result.stderr.strip().splitlines() if line.strip()]
    assert len(lines) == 1, lines
    assert "astra-ai setup --build" in lines[0], lines
