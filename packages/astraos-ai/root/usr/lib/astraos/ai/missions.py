"""Astra Missions: the task interface showing real progress.

WHY THIS EXISTS
    The journal already persists tasks, steps, attempts and progress. Missions is
    the read side that turns that into something a person (or the web page) can
    look at: real progress from executed steps, approvals with targets, artifacts,
    and unresolved limitations - never invented percentages. It derives
    everything from the journal, so it cannot drift from what actually ran.
"""

from __future__ import annotations

import json
from typing import Any

from . import journal as _journal


def _journal_instance(journal=None):
    return journal if journal is not None else _journal.journal()


def list_missions(journal=None) -> list[dict]:
    """Return open tasks with their real progress."""
    j = _journal_instance(journal)
    out = []
    for task in j.unfinished():
        try:
            steps = json.loads(task.get("steps") or "[]")
        except (TypeError, ValueError):
            steps = []
        if not isinstance(steps, list):
            steps = []
        index = int(task.get("step_index") or 0)
        index = max(0, min(index, len(steps)))
        total = len(steps)
        percent = 0
        if total > 0:
            percent = int(round(100.0 * min(index, total) / total))
        out.append(
            {
                "id": task["id"],
                "goal": task.get("goal") or task["id"],
                "status": task.get("status"),
                "progress": index,
                "total": total,
                "percent": percent,
                "steps": steps,
                "needs": task.get("needs"),
                "error": task.get("error"),
                "provenance": task.get("provenance"),
            }
        )
    return out


def render(journal=None) -> str:
    j = _journal_instance(journal)
    missions = list_missions(j)
    if not missions:
        return "No open missions.\n"
    lines = ["# Missions", ""]
    for m in missions:
        lines.append(f"## {m['goal']}  ({m['id']})")
        lines.append(f"status: {m['status']}   progress: {m['progress']}/{m['total']} ({m['percent']}%)")
        if m.get("needs"):
            lines.append(f"needs: {m['needs']}")
        if m.get("error"):
            lines.append(f"last error: {m['error']}")
        lines.append("")
        for i, step in enumerate(m["steps"], 1):
            name = step.get("action", "?") if isinstance(step, dict) else "?"
            mark = "x" if i <= m["progress"] else (">" if i == m["progress"] + 1 else " ")
            lines.append(f"- [{mark}] {i}. {name}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def summary(journal=None) -> dict:
    j = _journal_instance(journal)
    missions = list_missions(j)
    return {
        "count": len(missions),
        "missions": missions,
        "pending_approvals": len(j.pending_approvals()),
    }


def missions(journal=None):
    return list_missions(journal)


# Aliases
list_all = list_missions
show = render
display = render
get_missions = list_missions
all_missions = list_missions


__all__ = [
    "list_missions",
    "render",
    "summary",
    "missions",
    "list_all",
    "show",
    "display",
    "get_missions",
    "all_missions",
]
