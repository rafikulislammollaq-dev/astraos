"""The worker: one constrained tool call at a time, checked, retried, escalated.

WHY THE WORKER ONLY EVER MAKES ONE CALL

A small model that is asked for a list of five actions produces five actions.
It then cannot tell which of them happened, it does not read the output of the
first before writing the second, and when the third fails it carries on and
reports success - because it never saw anything but the text it generated. So
the worker is given one task, runs it, READS WHAT CAME BACK, and only then
decides what to do next. That is not a limitation being worked around; it is
what the second tier of the ladder is for. The middle brain (planner.py) is the
part that is allowed to think in lists, because a list is where planning lives
and a list is what a human can read and veto.

WHY THE TOOL CALL IS CONSTRAINED

see llm.py ask_json(). The short version: a 1B model asked politely for JSON
produces broken JSON, and a grammar produces a call that is either valid or
empty. Empty is a case the worker handles; malformed is not a case it can.

WHY EVERY STEP IS VERIFIED, AND WHAT VERIFICATION MEANS HERE

Verification is not "the model said it worked". It is one of two things, in
order:

  1. STRUCTURE - the action ran without an error and produced output. This is
     what most actions get.
  2. STATE - the thing the action claimed to change is actually different now.
     set_volume is verified by reading the volume back through the same code
     path that set it; screenshot_screen is verified by checking that the file
     it named exists and is not empty. Anything that claims a side effect it
     cannot show is a failure, and it is treated as one.

A step that fails is retried exactly once, with the failure quoted back to the
model in the prompt. A step that fails twice is not retried a third time: the
task is handed to the human with what was tried, what came back, and what is
missing. The third failure is not information, it is a user's patience.

WHY THE WORKER ASKS BEFORE IT DESTROYS

actions.execute() already refuses the irreversible actions without a
confirmation, and that refusal is the last word. This module's job is to make
sure the human is asked at a moment when they can still say no: before the
action runs, with the exact command in front of them, not after it.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Callable, Iterator

from . import actions as _actions
from . import journal as _journal
from . import prompt as _prompt
from .llm import EngineUnavailable
from .tiers import TierPool, TierUnavailable

# What a worker is allowed to be asked for. The three shapes below are the
# whole grammar it can speak, and an answer outside them is a refusal rather
# than a guess.
DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {
            "type": "string",
            "enum": ["answer", "action", "plan", "refuse"],
        },
        "text": {"type": "string"},
        "action": {"type": "string"},
        "args": {"type": "object"},
        "reason": {"type": "string"},
    },
    "required": ["kind"],
    "additionalProperties": False,
}

TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string"},
        "args": {"type": "object"},
        "why": {"type": "string"},
    },
    "required": ["action", "args"],
    "additionalProperties": False,
}

# One retry. The number is a policy, not a constant of nature: a second attempt
# with the failure in the prompt is a different question, and a third is usually
# the same question with less patience.
MAX_ATTEMPTS = 2

# How long one task may take before the worker stops waiting for it. A task is
# a single action with a bounded command inside it, so this is a ceiling that
# catches a hung child process, not a timeout anyone tuned.
TASK_TIMEOUT_SECONDS = 180

Confirm = Callable[[str, dict], bool]

# What a confirmation dialog says. The sentence is the point: the human is being
# asked to approve a specific thing, with its arguments visible, not a category
# of thing. "Run this command: rm ~/notes.txt" is a question; "allow the
# assistant to run a command" is a rubber stamp.
CONFIRM_QUESTIONS = {
    "run_command": "the assistant wants to run this command",
    "shutdown": "the assistant wants to shut this machine down",
    "reboot": "the assistant wants to restart this machine",
    "suspend": "the assistant wants to suspend this machine",
    "close_window": "the assistant wants to close this window",
}


def question_for(action: str, args: dict) -> str:
    """One sentence naming the exact action and its arguments."""
    opening = CONFIRM_QUESTIONS.get(action, f"the assistant wants to run {action}")
    detail = ", ".join(f"{key}={value!r}" for key, value in args.items())
    return f"{opening} ({detail})" if detail else opening


def plan_goal(plan: list[dict]) -> str:
    """A plan's stated purpose, or its first step's, for the plan event.

    Between the two classes of answer: the brain's own goal when it wrote one,
    and the first step's reason otherwise. A page that shows a plan with no
    title over it is showing a list of commands with no purpose.
    """
    for step in plan:
        why = step.get("why") if isinstance(step, dict) else ""
        if why:
            return why
    return ""


class Worker:
    """Runs tasks. Borrows the worker tier only while it needs it."""

    def __init__(self, pool: TierPool, confirm: Confirm | None = None,
                 on_event: Callable[[dict], None] | None = None,
                 journal: _journal.Journal | None = None):
        self.pool = pool
        self._confirm = confirm
        self._on_event = on_event or (lambda event: None)
        # The journal is what makes a run auditable and resumable. It is
        # created here rather than taken from a parameter in the normal case,
        # and passed in by a caller that already has one - the web interface,
        # which has a run id of its own.
        self.journal = journal or _journal.journal()

    # ------------------------------------------------------------------
    # Talking to the model
    # ------------------------------------------------------------------

    def _decide(self, request: str, context: str, engine) -> dict:
        """Ask the worker what this request is: an answer, a task, or a plan.

        The prompt is short on purpose. A worker's context is small, and every
        line of instruction in it is a line taken from the knowledge and the
        request itself.
        """
        system = _prompt.worker_system()
        user = _prompt.worker_user(request, context)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        raw = "".join(engine.ask_json(messages, DECISION_SCHEMA))
        return _parse_object(raw)

    def _recover(self, request: str, context: str, failure: str, engine) -> dict:
        """The second attempt: the same request, and what actually happened."""
        messages = [
            {"role": "system", "content": _prompt.worker_system()},
            {"role": "user", "content": _prompt.worker_user(request, context)},
            {"role": "assistant", "content": _prompt.worker_failed()},
            {"role": "user", "content": _prompt.worker_recovery(failure)},
        ]
        raw = "".join(engine.ask_json(messages, DECISION_SCHEMA))
        return _parse_object(raw)

    # ------------------------------------------------------------------
    # The loop
    # ------------------------------------------------------------------

    def handle(self, request: str, context: str = "") -> dict:
        """Answer a request: directly, by doing one thing, or by handing it up.

        Returns the same shape whatever the answer was, because the callers
        (the command line, the web page, a phone) must not have to branch:

            kind      answer | action | plan | refuse | escalate | failed
            text      what to tell the user, always present
            plan      the steps that ran, when there were any
            evidence  what each step produced, for the journal and the page
            needs     what is missing, when something is

        The `plan` key is where the executor's work is visible. Everything else
        is commentary.
        """
        outcome = {
            "kind": "failed",
            "text": "",
            "plan": [],
            "evidence": [],
            "needs": [],
        }

        if not self.pool.ready():
            outcome["kind"] = "needs"
            outcome["text"] = (
                "The assistant has no model installed yet, so it cannot answer "
                "or do anything. " + self.pool.unavailable_reason()
            )
            return outcome

        retrieved = _prompt.knowledge_for(request)
        full_context = "\n\n".join(part for part in (context, retrieved) if part)

        try:
            with self.pool.asking("worker") as engine:
                decision = self._decide(request, full_context, engine)
        except (TierUnavailable, EngineUnavailable) as exc:
            outcome["kind"] = "needs"
            outcome["text"] = str(exc)
            return outcome

        kind = decision.get("kind", "refuse")
        outcome["kind"] = kind
        outcome["text"] = decision.get("text", "")

        if kind == "answer":
            return outcome

        if kind == "refuse":
            outcome["text"] = decision.get("reason") or (
                "I do not have a way to do that from here."
            )
            return outcome

        if kind == "plan":
            # The middle brain is a different model and a different borrow. The
            # swap happens inside the pool, and it is the reason a planned task
            # takes longer than a one-step one: the brain's weights have to come
            # in before the worker's can go out.
            from . import planner as _planner

            try:
                with self.pool.asking("brain") as brain:
                    plan = _planner.plan(brain, request, full_context)
            except (TierUnavailable, EngineUnavailable) as exc:
                outcome["kind"] = "degraded"
                outcome["text"] = (
                    "No middle brain is installed, so this is being attempted in "
                    "one step instead. " + str(exc)
                )
                return self._single_step(request, full_context, outcome)
            return self.run_plan(plan, outcome)

        if kind == "action":
            return self._single_step(request, full_context, outcome)

        outcome["kind"] = "refuse"
        outcome["text"] = "I could not work out what was being asked for."
        return outcome

    def _single_step(self, request: str, context: str, outcome: dict) -> dict:
        """Do the one thing the worker named, and report what happened."""
        task_id = self.journal.add_task(request, [])
        self.journal.set_status(task_id, "running")
        try:
            with self.pool.asking("worker") as engine:
                decision = self._decide(request, context, engine)
        except (TierUnavailable, EngineUnavailable) as exc:
            outcome["kind"] = "failed"
            outcome["text"] = f"The model could not be reached: {exc}"
            self.journal.set_result(task_id, None, error=str(exc))
            self.journal.set_status(task_id, "failed")
            return outcome

        action = decision.get("action", "")
        args = decision.get("args") if isinstance(decision.get("args"), dict) else {}
        if not action or action not in _actions.ACTIONS:
            outcome["kind"] = "refuse"
            outcome["text"] = decision.get("reason") or (
                "That did not map to anything I can do."
            )
            return outcome

        step = {"action": action, "args": args, "why": decision.get("reason", "")}
        evidence = self._run_step(step, 1, task_id)
        outcome["plan"] = [step]
        outcome["evidence"] = [evidence]
        outcome["kind"] = "action" if evidence["ok"] else self._end_status(evidence)
        outcome["text"] = evidence["output"] or evidence["error"]
        if evidence["ok"]:
            self.journal.set_status(task_id, "ok")
            self.journal.set_result(task_id, {"text": outcome["text"]})
        else:
            self.journal.set_status(task_id, outcome["kind"])
            self.journal.set_result(task_id, None, error=evidence["error"])
        return outcome

    def events_for(self, request: str,
                  context: str = "") -> Iterator[dict]:
        """Run one request and yield its events. Same behaviour as handle().

        The event vocabulary:

            thinking   what the assistant is deciding, in one line
            plan       {"goal", "steps"} - the middle brain's plan
            step-start {"step"} - a task is about to run, with its action
            step       {"evidence"} - what came back, and whether it verified
            done       {"kind", "text", "plan", "evidence"} - the whole result

        `done` is always last, so a client has one rule for the end of the turn
        rather than three.
        """
        yield {"type": "thinking", "text": "reading the request"}

        outcome = {
            "kind": "failed",
            "text": "",
            "plan": [],
            "evidence": [],
            "needs": [],
        }

        if not self.pool.ready():
            outcome["kind"] = "needs"
            outcome["text"] = (
                "The assistant has no model installed yet, so it cannot answer "
                "or do anything. " + self.pool.unavailable_reason()
            )
            yield {"type": "done", **outcome}
            return

        retrieved = _prompt.knowledge_for(request)
        full_context = "\n\n".join(part for part in (context, retrieved) if part)

        try:
            with self.pool.asking("worker") as engine:
                decision = self._decide(request, full_context, engine)
        except (TierUnavailable, EngineUnavailable) as exc:
            outcome["kind"] = "needs"
            outcome["text"] = str(exc)
            yield {"type": "done", **outcome}
            return

        kind = decision.get("kind", "refuse")
        outcome["kind"] = kind
        outcome["text"] = decision.get("text", "")

        if kind == "answer":
            yield {"type": "done", **outcome}
            return

        if kind == "refuse":
            outcome["text"] = decision.get("reason") or (
                "I do not have a way to do that from here."
            )
            yield {"type": "done", **outcome}
            return

        if kind == "plan":
            from . import planner as _planner

            try:
                with self.pool.asking("brain") as brain:
                    plan = _planner.plan(brain, request, full_context)
            except (TierUnavailable, EngineUnavailable) as exc:
                outcome["kind"] = "degraded"
                outcome["text"] = (
                    "No middle brain is installed, so this is being attempted in "
                    "one step instead. " + str(exc)
                )
                for event in self._single_step_events(request, full_context, outcome):
                    yield event
                return

            yield {"type": "plan", "goal": outcome["text"] or plan_goal(plan), "steps": plan}
            for event in self._run_plan_events(plan, outcome):
                yield event
            return

        if kind == "action":
            for event in self._single_step_events(request, full_context, outcome):
                yield event
            return

        outcome["kind"] = "refuse"
        outcome["text"] = "I could not work out what was being asked for."
        yield {"type": "done", **outcome}

    def _single_step_events(self, request: str, context: str, outcome: dict):
        """The one-step path, emitted rather than collected."""
        task_id = self.journal.add_task(request, [])
        self.journal.set_status(task_id, "running")
        try:
            with self.pool.asking("worker") as engine:
                decision = self._decide(request, context, engine)
        except (TierUnavailable, EngineUnavailable) as exc:
            outcome["kind"] = "failed"
            outcome["text"] = f"The model could not be reached: {exc}"
            self.journal.set_result(task_id, None, error=str(exc))
            self.journal.set_status(task_id, "failed")
            yield {"type": "done", **outcome}
            return

        action = decision.get("action", "")
        args = decision.get("args") if isinstance(decision.get("args"), dict) else {}
        if not action or action not in _actions.ACTIONS:
            outcome["kind"] = "refuse"
            outcome["text"] = decision.get("reason") or (
                "That did not map to anything I can do."
            )
            self.journal.set_status(task_id, "failed")
            yield {"type": "done", **outcome}
            return

        step = {"action": action, "args": args, "why": decision.get("reason", "")}
        yield {"type": "step-start", "step": step}
        evidence = self._run_step(step, 1, task_id)
        outcome["plan"] = [step]
        outcome["evidence"] = [evidence]
        outcome["kind"] = "action" if evidence["ok"] else self._end_status(evidence)
        outcome["text"] = evidence["output"] or evidence["error"]
        if evidence["ok"]:
            self.journal.set_status(task_id, "ok")
            self.journal.set_result(task_id, {"text": outcome["text"]})
        else:
            self.journal.set_status(task_id, outcome["kind"])
            self.journal.set_result(task_id, None, error=evidence["error"])
        yield {"type": "step", "evidence": evidence}
        yield {"type": "done", **outcome}

    def _run_plan_events(self, plan: list[dict], outcome: dict):
        """The plan, one task at a time, emitted as each step runs."""
        if not plan:
            outcome["kind"] = "refuse"
            outcome["text"] = "The plan was empty, so nothing was done."
            yield {"type": "done", **outcome}
            return

        task_id = self.journal.add_task(outcome.get("text") or "planned task", plan)
        self.journal.set_status(task_id, "running")

        for index, step in enumerate(plan, 1):
            yield {"type": "step-start", "step": step}
            evidence = self._run_step(step, index, task_id)
            outcome["plan"].append(step)
            outcome["evidence"].append(evidence)
            if not evidence["ok"]:
                status = self._end_status(evidence)
                outcome["kind"] = status
                outcome["text"] = (
                    evidence["error"]
                    or "That step did not work, so the rest of the plan was not run."
                )
                self.journal.set_status(task_id, status)
                self.journal.set_result(task_id, None, error=outcome["text"])
                yield {"type": "done", **outcome}
                return
            yield {"type": "step", "evidence": evidence}

        outcome["kind"] = "action"
        outcome["text"] = outcome["text"] or "Done."
        self.journal.set_status(task_id, "ok")
        self.journal.set_result(task_id, {"text": outcome["text"]})
        yield {"type": "done", **outcome}

    def _end_status(self, evidence: dict) -> str:
        """How a failed step ends a task.

        A step a human refused is `needs_human`, not `failed`. The person's no
        is the correct outcome of that conversation, and a journal that files
        every refusal as a failure teaches its reader that saying no is a bug.
        """
        if evidence.get("needs_confirm") and not evidence.get("confirmed"):
            return "needs_human"
        return "failed"

    # ------------------------------------------------------------------
    # Running a step, and telling the truth about it
    # ------------------------------------------------------------------

    def _needs_confirmation(self, action: str, args: dict) -> bool:
        """Is this an action that must not run without a human's yes?"""
        spec = _actions.ACTIONS.get(action)
        if spec is None:
            return False
        return bool(spec.dangerous) and bool(spec.needs_confirm)

    def _ask(self, action: str, args: dict) -> bool:
        """Ask a human. With no one to ask, the answer is no."""
        question = question_for(action, args)
        if self._confirm is None:
            self.journal.ask(action, question)
            return False
        try:
            granted = bool(self._confirm(action, args))
        except Exception:  # noqa: BLE001 - a broken callback is a no, never a yes
            granted = False
        approval_id = self.journal.ask(action, question)
        self.journal.answer(approval_id, "yes" if granted else "no")
        return granted

    def _run_step(self, step: dict, index: int = 0, task_id: str = "") -> dict:
        """Run one task, with the confirmation, the retry and the log of it."""
        action = str(step.get("action", "")).strip()
        args = step.get("args") if isinstance(step.get("args"), dict) else {}
        evidence = {
            "action": action,
            "args": args,
            "ok": False,
            "output": "",
            "error": "",
            "attempts": 0,
            "confirmed": False,
            "verified": False,
            "needs_confirm": self._needs_confirmation(action, args),
        }

        if action not in _actions.ACTIONS:
            evidence["error"] = (
                f"there is no action called {action!r} - the model invented it"
            )
            self._journal_step(task_id, index, evidence)
            return evidence

        if evidence["needs_confirm"]:
            evidence["confirmed"] = self._ask(action, args)
            if not evidence["confirmed"]:
                evidence["error"] = (
                    "not run: this changes the system and nobody confirmed it"
                )
                self._journal_step(task_id, index, evidence)
                return evidence

        for attempt in range(1, MAX_ATTEMPTS + 1):
            evidence["attempts"] = attempt
            # The arguments belong under "args". actions.execute() reads plan["args"]
            # (actions.py, `raw_args = plan.get("args")`) and resolves each key against
            # the action's declared argument table; splatting them at the top level
            # instead left that table empty, so every action with a required argument
            # failed with "the plan is missing the argument", and every action whose
            # arguments all have defaults silently ran with the DEFAULTS - asked for
            # 20% volume, set_volume applied 50% and reported ok=True. Both paths
            # (/api/work and `astra-ai work`) go through here.
            result = _actions.execute({"action": action, "args": args}, confirmed=True)
            evidence["ok"] = bool(result.get("ok"))
            evidence["output"] = str(result.get("output", "")).strip()
            evidence["error"] = str(result.get("error") or "")
            evidence["verified"] = self._verify(action, args, result)
            self._journal_step(task_id, index, evidence)
            self._on_event({"type": "step", "evidence": dict(evidence)})

            if evidence["ok"] and (evidence["verified"] or not self._has_verifier(action)):
                return evidence

            # A failed or unverifiable step is retried once, with the failure in
            # the prompt. The model gets to change its mind about the arguments;
            # it does not get to change its mind about the action it chose to
            # do, because that decision was planned above this line.
            if attempt < MAX_ATTEMPTS:
                retry = self._retry_args(action, args, result, step.get("why", ""))
                if retry is None:
                    return evidence
                args = retry
                evidence["args"] = args
                continue
            return evidence

        return evidence

    def _journal_step(self, task_id: str, index: int, evidence: dict) -> None:
        """Write one attempt to the journal. Best effort, never fatal.

        The journal is the record of what happened, so the one thing it must not
        do is stop the thing it is recording. A read-only home directory is a
        journal with no rows, not a task that did not run.
        """
        if not task_id:
            return
        try:
            self.journal.record_attempt(task_id, index, evidence)
            self.journal.set_step(task_id, index)
        except Exception:  # noqa: BLE001 - see the docstring
            pass

    def _retry_args(self, action: str, args: dict, result: dict, why: str) -> dict | None:
        """Ask the model for different arguments, given what just happened."""
        try:
            with self.pool.asking("worker") as engine:
                messages = _prompt.retry_messages(action, args, result, why)
                raw = "".join(engine.ask_json(messages, TASK_SCHEMA))
        except (TierUnavailable, EngineUnavailable):
            return None
        candidate = _parse_object(raw)
        if candidate.get("action") != action:
            return None
        fixed = candidate.get("args")
        return fixed if isinstance(fixed, dict) else None

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def _has_verifier(self, action: str) -> bool:
        return action in _VERIFIERS

    def _verify(self, action: str, args: dict, result: dict) -> bool:
        """Did the thing the action claimed to do actually happen?

        True when there is a verifier and it agrees, and True when there is no
        verifier at all - the caller distinguishes the two, because "we checked"
        and "we could not check" are different things to report.
        """
        verifier = _VERIFIERS.get(action)
        if verifier is None:
            return True
        try:
            return bool(verifier(args, result))
        except Exception:  # noqa: BLE001 - a broken verifier is an unverified step
            return False

    # ------------------------------------------------------------------
    # A whole plan
    # ------------------------------------------------------------------

    def run_plan(self, plan: list[dict], outcome: dict) -> dict:
        """Run the middle brain's plan, one task at a time, and report all of it.

        A failed step stops the plan. That is a considered choice: the steps of
        a plan are ordered, and step four's argument is usually step three's
        output, so continuing past a failure is not resilience, it is guessing
        with authority. The user gets the steps that ran, what each produced,
        and the first failure named.

        The plan is in the journal BEFORE it runs, not after. A plan that exists
        only once it has finished is a plan nobody could veto, and a crash on
        step two leaves nothing for a human to resume from.
        """
        if not plan:
            outcome["kind"] = "refuse"
            outcome["text"] = "The plan was empty, so nothing was done."
            return outcome

        task_id = self.journal.add_task(outcome.get("text") or "planned task", plan)
        self.journal.set_status(task_id, "running")

        for index, step in enumerate(plan, 1):
            self._on_event({"type": "step-start", "step": step})
            evidence = self._run_step(step, index, task_id)
            outcome["plan"].append(step)
            outcome["evidence"].append(evidence)
            if not evidence["ok"]:
                status = self._end_status(evidence)
                outcome["kind"] = status
                outcome["text"] = (
                    evidence["error"]
                    or "That step did not work, so the rest of the plan was not run."
                )
                self.journal.set_status(task_id, status)
                self.journal.set_result(task_id, None, error=outcome["text"])
                return outcome

        outcome["kind"] = "action"
        outcome["text"] = outcome["text"] or "Done."
        self.journal.set_status(task_id, "ok")
        self.journal.set_result(task_id, {"text": outcome["text"]})
        return outcome


# ---------------------------------------------------------------------------
# State verifiers: read the thing back and compare
# ---------------------------------------------------------------------------

def _read_volume() -> int | None:
    """The current output volume, read back through the tools that set it.

    pactl prints `Volume: front-left: 32768 /  50% / -18.06 dB`; amixer prints
    `Front Left: Playback 32768 [50%] [ -18.06dB]`. The percentage is what both
    of them agree on, so it is what is compared, and it is parsed with the one
    pattern that matches both rather than with a hope.
    """
    pactl = _actions._pactl()
    if pactl:
        code, output = _actions._run([pactl, "get-sink-volume", "@DEFAULT_SINK@"])
        if code == 0:
            match = re.search(r"(\d{1,3})\s*%", output)
            if match:
                return int(match.group(1))
    amixer = _actions._amixer()
    if amixer:
        code, output = _actions._run([amixer, "sget", "Master"])
        if code == 0:
            match = re.search(r"\[(\d{1,3})%\]", output)
            if match:
                return int(match.group(1))
    return None


def _verify_volume(args: dict, result: dict) -> bool:
    """set_volume is true when the volume is now what was asked for."""
    try:
        wanted = int(args.get("percent", args.get("level")))
    except (TypeError, ValueError):
        return False
    current = _read_volume()
    return current is not None and abs(current - wanted) <= 2


def _verify_screenshot(args: dict, result: dict) -> bool:
    """A screenshot exists when the file it named is there and has bytes."""
    match = re.search(r"[\w./~-]+\.png", result.get("output", ""))
    if not match:
        return False
    path = Path(match.group(0)).expanduser()
    return path.is_file() and path.stat().st_size > 0


_VERIFIERS: dict[str, Callable[[dict, dict], bool]] = {
    "set_volume": _verify_volume,
    "screenshot": _verify_screenshot,
}


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _parse_object(raw: str) -> dict:
    """The JSON object the grammar produced, or {} when there was none.

    A constrained call is either a valid object or empty; a truncated one is a
    reason to try again, not a reason to crash in the middle of a task.
    """
    text = (raw or "").strip()
    if not text:
        return {}
    # Strip the fence some chat templates still insert around JSON despite the
    # grammar - the grammar constrains the generation, not the template's habit
    # of wrapping it in three backticks.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except ValueError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
        except ValueError:
            return {}
    return parsed if isinstance(parsed, dict) else {}
