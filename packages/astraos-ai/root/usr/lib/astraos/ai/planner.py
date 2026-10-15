"""The middle brain: it reads the whole request and writes the plan.

WHY PLANNING IS A SEPARATE TIER

The measured finding this file is built on (arXiv 2601.11327v2, v2 2026-04-13) is
that multi-agent systems with small models are planner-limited, not
executor-limited: an 8B orchestrator scores flat across 1.7B/8B/32B sub-agents
on GAIA (23.0 / 23.0 / 23.6), and giving the orchestrator thinking while the
workers stay cheap is worth +18.2 GAIA and +36.7 AIME, where giving the workers
thinking is worth marginal or negative amounts. ProST (arXiv 2509.04508v2) found
the same shape from the other side: 14-7-7 (strong planner, weak executor)
beats 7-14-14 on the Pareto front at equal total parameters.

So the parameter budget goes here, and the worker gets the smallest model that
can follow one instruction. The consequence for this machine is the swap the
pool already performs: the brain's weights come in, the plan is written, and
they go out again before the worker's come in.

WHY THE PLAN IS CONSTRAINED JSON AND NOT PROSE

A plan written as prose is advice: the user reads it and does the work. A plan
written as a typed list of actions is something the worker can execute and
something the user can veto line by line. The schema below is the whole
vocabulary of a plan - every step must name an action that exists in
actions.ACTIONS and arguments that are an object - which is what makes "run
these five steps" safe to do without reading the model's mind.

WHY THE PLAN IS SHORT BY CONSTRUCTION

Seven steps, three by default. The two largest failure modes measured for
small-agent systems are step repetition (FM-1.3, 15.7%) and being unaware of the
termination condition (FM-1.5, 12.4%) - MAST, arXiv 2503.13657. A plan the
model has to fit into a short list is a plan that has to decide what it is for,
and the budget that produced it is stated to the worker so it knows when it is
done.

WHY THE PLAN CARRIES ITS OWN EVIDENCE REQUIREMENT

Every step names what must be true afterwards. It is a field the model fills in
and the worker reads, not a field anyone parses: it exists so that the model
that is about to run step four knows what step three was supposed to leave
behind, and so that the human reading the plan can see that the assistant meant
to end up somewhere in particular.
"""

from __future__ import annotations

import json
import re
from typing import Callable

from . import actions as _actions
from . import skills as _skills

# How many steps a plan may have. Not a soft target: the grammar refuses a
# longer list, so the model has to prioritise rather than enumerate.
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "goal": {"type": "string"},
        "steps": {
            "type": "array",
            "maxItems": 7,
            "items": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": sorted(_actions.ACTIONS),
                    },
                    "args": {"type": "object"},
                    "why": {"type": "string"},
                    "expect": {"type": "string"},
                    "skill": {"type": "string"},
                },
                "required": ["action", "args", "why"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string"},
        "needs": {"type": "string"},
    },
    "required": ["goal", "steps"],
    "additionalProperties": False,
}

# The catalogue of actions as one line each, for the planner's prompt. Cached
# because the planner is asked once per request and the catalogue is 30 lines.
_CATALOG: list[str] = []


def action_catalog() -> list[str]:
    """The action names and their argument names, as the prompt shows them."""
    global _CATALOG
    if not _CATALOG:
        lines = []
        for action in _actions.ACTIONS.values():
            arguments = ", ".join(action.args.keys())
            confirm = " [asks first]" if action.needs_confirm else ""
            lines.append(f"- {action.name}({arguments}): {action.summary}{confirm}")
        _CATALOG = lines
    return _CATALOG


def plan(engine, request: str, context: str = "",
         on_event: Callable[[dict], None] | None = None) -> list[dict]:
    """Ask the middle brain for a plan, and return it as a list of steps.

    The steps come back in the shape worker.run_plan() expects, which is the
    shape the schema enforces: each one has an action from the catalogue, an
    arguments object, and a line saying why it is there.

    Failure modes, all of which return [] rather than raising:

      * no brain installed - the caller falls back to one step and says so;
      * the brain returns nothing the grammar would allow - an empty plan,
        reported as one rather than as a crash;
      * every step the brain produced is not usable - a plan with one bad step
        in it is not a plan with a hole in it, it is a plan that does not run,
        so it is rejected whole rather than partially applied.

    The last case is the one worth being strict about. A plan whose step three
    names an action that does not exist has already lost the thread, and the
    half that is valid is not what the brain decided.
    """
    emit = on_event or (lambda event: None)
    messages = [
        {"role": "system", "content": system_prompt()},
        {"role": "user", "content": user_prompt(request, context)},
    ]

    emit({"type": "thinking", "text": "the middle brain is reading the request"})
    raw = "".join(engine.ask_json(messages, PLAN_SCHEMA))
    candidate = _parse(raw)

    steps = candidate.get("steps") if isinstance(candidate, dict) else None
    if not isinstance(steps, list):
        emit({"type": "thinking", "text": "no plan came back"})
        return []

    usable = []
    for index, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            continue
        action = str(step.get("action", "")).strip()
        if action not in _actions.ACTIONS:
            emit({"type": "thinking",
                  "text": f"step {index} named {action!r}, which is not in the catalogue"})
            continue
        args = step.get("args")
        if not isinstance(args, dict):
            args = {}
        usable.append(
            {
                "action": action,
                "args": _prune_args(action, args),
                "why": str(step.get("why", "")).strip(),
                "expect": str(step.get("expect", "")).strip(),
                "skill": str(step.get("skill", "")).strip(),
            }
        )

    goal = str(candidate.get("goal", "")).strip() if isinstance(candidate, dict) else ""
    emit({"type": "plan", "goal": goal, "steps": usable})
    return usable


def _prune_args(action: str, args: dict) -> dict:
    """Keep only the arguments the action actually takes.

    The schema cannot express this - an object with arbitrary keys is the only
    way to describe thirty actions with different arguments in one grammar -
    so it is enforced here instead. A hallucinated "verbose: true" passed to
    open_app would reach the function as **kwargs and be a TypeError in the
    middle of a task.
    """
    spec = _actions.ACTIONS[action]
    pruned = {}
    for key, value in args.items():
        if key not in spec.args:
            continue
        expected = str(spec.args[key].get("type", "string"))
        if expected == "integer":
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue
        else:
            value = str(value)
        pruned[key] = value
    return pruned


# ---------------------------------------------------------------------------
# The prompts
# ---------------------------------------------------------------------------

def system_prompt() -> str:
    """What the middle brain is told about itself and about the catalogue.

    Written as instructions, not as a personality. The brain is the one part of
    this system that is asked to think, so it is told what a plan is for, what
    the vocabulary is, and what it is allowed to do when the request cannot be
    planned - which is to say so in `needs` and stop.
    """
    catalog = "\n".join(action_catalog())
    return f"""You are the planning half of an assistant running on the user's own
machine. You write plans; a smaller, faster model executes them.

You may use only these actions:

{catalog}

Rules for a plan:

1. Every step is one action from that list. You may not invent an action, and
   you may not use an argument the action does not take.
2. Seven steps at most, and three is usual. A plan longer than that is a
   request nobody made.
3. `why` says what the step is for, in one line a person can check.
4. `expect` says what must be true after the step. This is how the executor
   knows the step worked; if you cannot say it, do not plan the step.
5. Read the user's request literally. "turn it down" is volume_down, not
   set_volume.
6. If the request needs a program this machine does not have, say so in `needs`
   and plan the steps that can still be done.
7. If nothing can be planned, return an empty steps list and say why in
   `notes`. An empty plan is an answer; a made-up plan is not.
8. Prefer the smallest number of steps that finishes the request. Steps are not
   free: each one is a model call on a slow CPU.
"""


def user_prompt(request: str, context: str = "") -> str:
    """The request, the skills that exist, and anything retrieved for it."""
    parts = [f"The user asks: {request.strip()}"]
    catalogue = _skills.catalogue()
    if catalogue:
        parts.append(
            "These skills are installed and may be named in a step's `skill` "
            "field when one of them applies:\n" + catalogue
        )
    if context.strip():
        parts.append("Background:\n" + context.strip())
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _parse(raw: str) -> dict:
    """The object the grammar produced, or {} when there was none."""
    text = (raw or "").strip()
    if not text:
        return {}
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
