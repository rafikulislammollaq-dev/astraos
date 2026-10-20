"""The journal: what the assistant did, what it is doing, and what it needs.

WHY THIS EXISTS

The two largest measured failure modes of small-model agent systems are not bad
reasoning, they are bookkeeping: step repetition (FM-1.3, 15.7% of failures) and
being unaware of the termination condition (FM-1.5, 12.4%) - MAST, arXiv
2503.13657, 1600+ annotated traces across seven frameworks, κ=0.88 agreement. An
agent that cannot see what it has already done repeats it; an agent that cannot
see how many steps are left never finishes.

The journal is the fix, and it is deliberately visible rather than internal. It
is four tables and one plaintext file:

    events     every step that ran, what it did, what came back, in order
    tasks      the queue: what was asked, what is allowed, where it got to
    approvals  the questions that were asked of a human, and what was answered
    plan.md    the same task, rendered as something a person can read in a shell

plan.md is regenerated on every state change because it is the part that
actually fixes FM-1.5: the budget and the done-set are on screen, in the agent's
working directory, where the user and a second process can both see them.

WHY SQLITE AND NOT A LOG FILE

The journal is read, not just written: `astra ai journal` shows the run, the web
page polls it, and a step that has to be resumed after a crash has to be found.
A text log can only be tailed. SQLite also gives the one-writer rule for free
(the assistant is a single-writer system by design - see _WRITER below), which
means "database is locked" cannot happen to a caller that does everything
through here.

WHY IT SURVIVES A RESTART, AND WHY THAT MATTERS

The engine is stopped and started between questions; the machine is rebooted by
the assistant itself; the process is killed by a user who changed their mind. A
run that only exists in memory is a run that cannot be resumed, and resuming is
the difference between "the assistant is doing step 4 of 5" and "the assistant
did nothing".
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from . import config as _config

DB_PATH = _config.PATHS.models_dir.parent / "journal.sqlite3"

# One process writes at a time. The assistant is single-writer by construction -
# one CLI invocation, one server, one tier pool - and pretending otherwise with
# retries would only turn a clear failure into a slow one.
_WRITER = "astra-ai"

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts       TEXT NOT NULL,
    run_id   TEXT NOT NULL,
    actor    TEXT NOT NULL,
    kind     TEXT NOT NULL,
    payload  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_run ON events(run_id, id);

CREATE TABLE IF NOT EXISTS tasks (
    id            TEXT PRIMARY KEY,
    run_id        TEXT NOT NULL,
    goal          TEXT NOT NULL,
    steps         TEXT NOT NULL,
    status        TEXT NOT NULL,
    provenance    TEXT NOT NULL DEFAULT 'user',
    step_index    INTEGER NOT NULL DEFAULT 0,
    attempts      TEXT NOT NULL DEFAULT '{}',
    result        TEXT,
    error         TEXT,
    needs         TEXT,
    created_ts    TEXT NOT NULL,
    updated_ts    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS tasks_status ON tasks(status, id);

CREATE TABLE IF NOT EXISTS approvals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    run_id       TEXT NOT NULL,
    task_id      TEXT,
    action       TEXT NOT NULL,
    question     TEXT NOT NULL,
    answer       TEXT,
    answered_ts  TEXT
);
"""

# The states a task can be in. `needs_human` is not a failure: smolagents makes
# it a first-class return (see research 0.2), because a worker that is told to
# return "I need to ask something, specifically this" as a success returns it,
# whereas one that treats asking as failing guesses instead.
STATUSES = (
    "pending",
    "planning",
    "awaiting approval",
    "running",
    "verifying",
    "paused",
    "ok",
    "failed",
    "needs_human",
    "cancelled",
)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Journal:
    """One run at a time, or a whole history when asked for it."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path or DB_PATH)
        self.run_id = ""
        # One connection per THREAD, not one per process.
        #
        # The server is a ThreadingHTTPServer: a request handler reads the
        # journal while the worker thread is writing to it, and sqlite3 refuses
        # any use of a connection from a thread other than the one that made it
        # ("ProgrammingError: SQLite objects created in a thread can only be
        # used in that same thread"). A single cached connection therefore
        # failed on whichever thread touched it second, reproducibly, for every
        # /api/work run and every poll of /api/journal from another connection.
        #
        # check_same_thread=False is not the fix either: two threads
        # interleaving execute()/commit() on one handle do not get two
        # transactions, they get one mixed transaction, and a rollback by
        # either undoes the other's committed work.
        #
        # _connection stays a property, so every existing self._connection use
        # in this file keeps working unchanged while each thread transparently
        # gets its own handle. The schema is CREATE TABLE IF NOT EXISTS, so
        # creating it once per thread is a no-op after the first. A thread's
        # connection is released when the thread's locals are.
        self._local = threading.local()

    @property
    def _connection(self) -> sqlite3.Connection | None:
        return getattr(self._local, "connection", None)

    @_connection.setter
    def _connection(self, value: sqlite3.Connection | None) -> None:
        self._local.connection = value

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        if self._connection is not None:
            return self._connection
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(self.path), timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(SCHEMA)
        connection.commit()
        # A database written by an earlier version has no provenance column, and
        # SQLite's CREATE TABLE IF NOT EXISTS will not add one. The migration is
        # here rather than behind a schema version because ALTER TABLE ADD COLUMN
        # is cheap and the default is the honest reading: a task recorded before
        # provenance existed came from the user.
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(tasks)")}
        if "provenance" not in columns:
            connection.execute(
                "ALTER TABLE tasks ADD COLUMN provenance TEXT NOT NULL DEFAULT 'user'"
            )
            connection.commit()
        self._connection = connection
        return connection

    def close(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
            finally:
                self._connection = None

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    def begin(self, goal: str) -> str:
        """Start a run and return its id. Every task is attached to one."""
        if not self.run_id:
            self.run_id = uuid.uuid4().hex[:12]
        self._connect().execute(
            "INSERT INTO events (ts, run_id, actor, kind, payload) VALUES (?,?,?,?,?)",
            (_now(), self.run_id, _WRITER, "run_started",
             json.dumps({"goal": goal})),
        )
        self._connection.commit()
        return self.run_id

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    def add_task(self, goal: str, steps: list[dict], provenance: str = "user") -> str:
        """Queue a task. The id is returned so the caller can follow it.

        provenance travels with the task because a resumed task must be judged by
        where its plan came from, not by who ran the resume command: a plan written
        from a document stays a document's plan across a reboot.
        """
        self._connect()
        task_id = uuid.uuid4().hex[:12]
        now = _now()
        self._connection.execute(
            "INSERT INTO tasks (id, run_id, goal, steps, status, provenance,"
            " created_ts, updated_ts) VALUES (?,?,?,?, 'pending', ?, ?, ?)",
            (task_id, self.run_id, goal, json.dumps(steps), provenance, now, now),
        )
        self._event("task_added", task_id, {"goal": goal, "steps": len(steps)})
        self._connection.commit()
        self.render()
        return task_id

    def task(self, task_id: str) -> dict | None:
        """One task as a dictionary, or None when the id is unknown."""
        row = self._connect().execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        return dict(row) if row else None

    def set_steps(self, task_id: str, steps: list[dict]) -> None:
        """Record the steps a task turned out to have.

        A task is queued before its plan exists - the request is known, the
        steps are not - so the plan arrives as an update. Until it does, the
        journal holds the request and a step count of zero, which is the honest
        description of what is happening: something was asked, nothing has been
        decided yet.
        """
        self._connect().execute(
            "UPDATE tasks SET steps = ?, updated_ts = ? WHERE id = ?",
            (json.dumps(steps or []), _now(), task_id),
        )
        self._connection.commit()
        self.render()

    def set_status(self, task_id: str, status: str) -> None:
        """Move a task to a new state, and say so in the log."""
        if status not in STATUSES:
            raise KeyError(f"unknown task status: {status}")
        self._connect().execute(
            "UPDATE tasks SET status = ?, updated_ts = ? WHERE id = ?",
            (status, _now(), task_id),
        )
        self._event("task_status", task_id, {"status": status})
        self._connection.commit()
        self.render()

    def set_step(self, task_id: str, index: int) -> None:
        """Record progress through the plan.

        This is the checkpoint. A crash between step two and step three leaves
        the index at two, and a resumed run starts at three - which is the whole
        reason the number is a column rather than a variable in a loop.
        """
        self._connect().execute(
            "UPDATE tasks SET step_index = ?, updated_ts = ? WHERE id = ?",
            (int(index), _now(), task_id),
        )
        self._connection.commit()
        # Re-rendered here, and this is the mutator that matters most: the step
        # index is what moves the [>] marker along the list. Without this, the
        # file said "0 of 3 steps" with step 1 still next for the whole run -
        # a done-set that never advances is worse than no file at all, because
        # it is the thing the reader trusts.
        self.render()

    def set_result(self, task_id: str, result: dict | None = None,
                   error: str = "", needs: str = "") -> None:
        """Store how a task ended. `result` is the structured finish."""
        self._connect().execute(
            "UPDATE tasks SET result = ?, error = ?, needs = ?, updated_ts = ?"
            " WHERE id = ?",
            (json.dumps(result) if result is not None else None,
             error or None, needs or None, _now(), task_id),
        )
        if result is not None:
            self._event("task_result", task_id, result)
        if error:
            self._event("task_error", task_id, {"error": error})
        if needs:
            self._event("task_needs", task_id, {"needs": needs})
        self._connection.commit()
        self.render()

    def record_attempt(self, task_id: str, step_index: int, evidence: dict) -> None:
        """What one attempt at a step produced.

        Every attempt is kept, not just the last. A user asking "why did it do
        that twice" is asking about the first attempt, and the answer is the
        reason the second one was needed.
        """
        self._connect()
        row = self._connect().execute(
            "SELECT attempts FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return
        attempts = json.loads(row["attempts"] or "{}")
        attempts.setdefault(str(step_index), []).append(
            {
                "at": _now(),
                "ok": bool(evidence.get("ok")),
                "output": str(evidence.get("output", ""))[:400],
                "error": str(evidence.get("error", ""))[:400],
                "verified": bool(evidence.get("verified")),
            }
        )
        self._connect().execute(
            "UPDATE tasks SET attempts = ?, updated_ts = ? WHERE id = ?",
            (json.dumps(attempts), _now(), task_id),
        )
        self._event("step_attempt", task_id, {"step": step_index, **evidence})
        self._connection.commit()
        self.render()

    def unfinished(self) -> list[dict]:
        """Tasks that a restart could pick up."""
        # needs_human is in this list on purpose. A step the user declined is
        # recorded as needs_human rather than failed - the no is the right
        # outcome - and a task in that state is exactly what a human opening
        # plan.md needs to see. Excluding it hid the question that was asked
        # and the answer that was given.
        rows = self._connect().execute(
            "SELECT * FROM tasks"
            " WHERE status IN ('pending','planning','awaiting approval',"
            " 'running','verifying','paused','needs_human')"
            " ORDER BY created_ts"
        ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Approvals
    # ------------------------------------------------------------------

    def ask(self, action: str, question: str, task_id: str = "") -> int:
        """Record that a human was asked. Returns the approval row's id."""
        cursor = self._connect().execute(
            "INSERT INTO approvals (ts, run_id, task_id, action, question)"
            " VALUES (?,?,?,?,?)",
            (_now(), self.run_id, task_id, action, question),
        )
        # Read the row id before _event() inserts into events: last_insert_rowid()
        # is per connection, so asking after the event would return the event's id
        # and answer() would update no approval at all.
        approval_id = int(cursor.lastrowid)
        self._connection.commit()
        self._event("approval_asked", task_id, {"action": action, "question": question})
        return approval_id

    def answer(self, approval_id: int, answer: str) -> None:
        """Record what the human said."""
        self._connect().execute(
            "UPDATE approvals SET answer = ?, answered_ts = ? WHERE id = ?",
            (answer, _now(), int(approval_id)),
        )
        self._connection.commit()
        self._event("approval_answered", "", {"id": approval_id, "answer": answer})

    def pending_approvals(self) -> list[dict]:
        rows = self._connect().execute(
            "SELECT * FROM approvals WHERE answer IS NULL ORDER BY id"
        ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def _event(self, kind: str, task_id: str = "", payload: dict | None = None) -> None:
        self._connect().execute(
            "INSERT INTO events (ts, run_id, actor, kind, payload) VALUES (?,?,?,?,?)",
            (_now(), self.run_id, _WRITER, kind,
             json.dumps({"task": task_id, **(payload or {})})),
        )

    def events(self, limit: int = 200) -> list[dict]:
        """The log, newest last."""
        rows = self._connect().execute(
            "SELECT * FROM events ORDER BY id DESC LIMIT ?", (int(limit),)
        ).fetchall()
        return [dict(row) for row in reversed(rows)]

    # ------------------------------------------------------------------
    # plan.md
    # ------------------------------------------------------------------

    def plan_path(self) -> Path:
        return self.path.parent / "plan.md"

    def render(self) -> None:
        """Write plan.md from the database.

        Rendered rather than maintained. A file that is both written by the
        agent and meant to describe the agent has a way of drifting; a file
        regenerated from the same rows the agent commits cannot disagree with
        itself, and it is always safe to open in an editor for reading.
        """
        tasks = self.unfinished()
        if not tasks:
            return
        lines = [f"# plan.md - task journal, written {_now()}", ""]
        for task in tasks:
            steps = _loads(task["steps"], [])
            lines.append(f"## {task['goal'] or task['id']}")
            lines.append(f"status: {task['status']}   task: {task['id']}")
            lines.append(f"progress: {task['step_index']} of {len(steps)} steps")
            if task.get("error"):
                lines.append(f"last error: {task['error']}")
            if task.get("needs"):
                lines.append(f"needs: {task['needs']}")
            lines.append("")
            for index, step in enumerate(steps, 1):
                if index <= task["step_index"]:
                    mark = "x"
                elif index == task["step_index"] + 1:
                    mark = ">"
                else:
                    mark = " "
                name = step.get("action", "?") if isinstance(step, dict) else "?"
                why = step.get("why", "") if isinstance(step, dict) else ""
                lines.append(f"- [{mark}] {index}. {name} - {why}".rstrip())
            lines.append("")
        text = "\n".join(lines).rstrip() + "\n"
        try:
            self.plan_path().write_text(text, encoding="utf-8")
        except OSError:
            # A read-only home is a state to report, not a reason to stop a run
            # that is already in the database.
            pass

    def summary(self) -> dict:
        """What `astra ai journal` prints."""
        connection = self._connect()
        counts = {}
        for status in STATUSES:
            counts[status] = connection.execute(
                "SELECT count(*) FROM tasks WHERE status = ?", (status,)
            ).fetchone()[0]
        return {
            "path": str(self.path),
            "plan": str(self.plan_path()),
            "tasks": counts,
            "pending_approvals": len(self.pending_approvals()),
            "open": self.unfinished(),
        }


def _loads(text, default):
    try:
        value = json.loads(text or "")
    except (TypeError, ValueError):
        return default
    return value if isinstance(value, list) else default


# One journal per process. The database is the shared state; this is the handle.
_JOURNAL: Journal | None = None


def journal() -> Journal:
    global _JOURNAL
    if _JOURNAL is None:
        _JOURNAL = Journal()
    return _JOURNAL
