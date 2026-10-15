"""The words the model is given, and the only shape its replies may take.

There are now three voices in this file, and they are deliberately different:

    SYSTEM_PROMPT   the single-action assistant, unchanged since it was written.
                    It is what a person typing one question gets.
    worker_*        the executor's half of a two-tier run.
    planner_*       the middle brain's half. It lives in planner.py because it
                    is about plans, which only the brain writes.

Why the format is a JSON object rather than "tool calling":

    The model is a 1B-3B quantised instruct model on a CPU with AVX but no
    AVX2. Models of that size follow a schema that is written out in plain
    words far more reliably than they follow a protocol whose support depends
    on a chat template, and llama.cpp's native tool-calling support differs by
    version anyway. One object, two keys, no fence - that is a format a small
    model can hold onto, and parse_plan() accepts it with the fences a small
    model adds anyway.

Why the executor's prompt borrows from smolagents:

    HuggingFace's smolagents gives every managed agent a fixed task envelope
    with a mandatory three-part answer and an explicit clause that a failed
    task must still return everything it learned
    (src/smolagents/prompts/code_agent.yaml). That clause is the highest-value
    line in the whole multi-agent prompt literature, because a worker that is
    allowed to fail quietly does: it returns "failed", and the supervisor has
    to guess why. A worker that is required to return a detailed account of
    what happened - including when it did not work - gives the planner and the
    human something to act on.

Why the executor is told how many steps it has:

    The MAST study of 1600+ multi-agent traces (arXiv 2503.13657) found the
    second-largest failure mode is the agent not knowing it is finished
    (FM-1.5, 12.4%), and the largest is repeating a step it already did
    (FM-1.3, 15.7%). Both are fixed by the same thing: the budget and the
    done-set, written down, in the context, on every step.
"""

from __future__ import annotations

from . import actions as _actions
from . import knowledge as _knowledge

# How much of the conversation is kept. See the module docstring.
HISTORY_MESSAGES = 12
MAX_MESSAGE_CHARS = 2000

_INSTRUCTIONS = """You are the AstraOS assistant. AstraOS is a Debian desktop and you are \
running on the user's own computer: the model is a file on this machine and \
nothing is sent anywhere.

You have exactly one way to affect the computer, and it is to reply with a \
single JSON object.

To do something:
{"action": "set_volume", "args": {"percent": 30}}

To answer in words:
{"answer": "The keyboard layout is not something I can change."}

Rules, in order of importance:

1. Use only the action names listed at the end of this message. Never invent
   an action, never write a shell command, never name a program that is not
   in the list. If the user asks for something that is not in the list, use
   "answer" and say plainly that you cannot do it.
2. One action per reply. If two things are needed, do the first and say what
   should happen next.
3. Reply with the JSON object and nothing else: no explanation before it, no
   backticks or code fence, no text after it.
4. The actions marked [asks the user first] are confirmed by the person at
   the screen every single time. You do not have their permission for
   anything, and you must not say you do.
5. Keep "answer" to one or two sentences. This is a desktop, not a document.
6. Paths beginning with ~ are the user's home directory. Anything outside the
   home directory is likely to be refused by the guards, so do not propose it.
7. If the request is ambiguous, ask a question with "answer" instead of
   guessing which action was meant.

The actions, and nothing else:
"""

SYSTEM_PROMPT = _INSTRUCTIONS + _actions.catalog_for_prompt()


def build_messages(user_text: str, history: list[dict]) -> list[dict]:
    """The message list for one question: system prompt, trimmed history, user text.

    `history` is the caller's list of {"role", "content"} dictionaries; it is
    copied, never modified, so the caller can keep using it after the call and
    a second caller cannot corrupt the first one's conversation.
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    kept: list[dict] = []
    for item in history or []:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in ("user", "assistant"):
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        kept.append({"role": role, "content": content[:MAX_MESSAGE_CHARS]})

    messages.extend(kept[-HISTORY_MESSAGES:])
    messages.append({"role": "user", "content": (user_text or "").strip()})
    return messages


# ---------------------------------------------------------------------------
# The executor (worker.py)
# ---------------------------------------------------------------------------

def worker_system() -> str:
    """What the executor is told about its one job.

    The executors's job is not to be clever. It is to look at one request,
    decide whether that is an answer it can give in words, one action from the
    list, or something too big for either - and then do the thing it chose and
    report what actually happened. The "or escalate it upward" branch is the
    part that makes this safe: a small model that cannot escalate has to guess.
    """
    catalog = _actions.catalog_for_prompt()
    return f"""You are the executor of an assistant running on the user's own Linux
machine. You do one thing at a time and you report exactly what happened.

You have five replies, and they are the only ones:

  answer   - you can say this usefully in words. Put it in "text".
  action   - there is one action from the list that does what was asked. Put
             its name in "action" and its arguments in "args".
  plan     - this needs more than one step, or you are not sure which of
             several actions is meant. Put a one-line reason in "text".
             Say this instead of guessing.
  refuse   - you cannot do it and no action in the list applies. Put why in
             "reason".

Rules:

1. Use only names from the list. Never invent an action, never write a command
   line, never name a program that is not in the list.
2. Read the request literally: "turn it down" is volume_down, "make it louder"
   is volume_up, an exact percentage is set_volume.
3. If the request is ambiguous between two actions, say "plan" and name the two
   in "text". Do not pick one.
4. Never claim an action will happen. You report what happened after it ran.
5. Keep "text" to one or two sentences. This is a desktop, not a document.

The actions, and nothing else:

{catalog}
"""


def worker_user(request: str, context: str = "") -> str:
    """The request, plus anything retrieved for it.

    The knowledge comes before the request rather than after, because it is
    background the model should be reading *through* when it decides - and
    because a passage the model has already seen is a fact it can act on, while
    a passage that arrives afterwards is an aside.
    """
    parts = []
    if context.strip():
        parts.append(
            "This is what the machine's own documentation says about the "
            "request. Use it; do not contradict it:\n\n" + context.strip()
        )
    parts.append("The user asks: " + (request or "").strip())
    return "\n\n".join(parts)


def worker_failed() -> str:
    """The stub assistant turn that introduces the retry.

    A retry is only a new question if the model can see what the first answer
    was, and the format is fixed so the transcript reads as one exchange
    rather than as a list of unrelated questions.
    """
    return '{"kind": "refuse", "reason": "not a real answer - recorded so the retry below makes sense"}'


def worker_recovery(failure: str) -> str:
    """The second attempt, with the failure quoted back.

    The failure is the actual output of the action, not a summary of it. A
    model shown "Unknown Desktop Entry Name" fixes the name; a model shown "it
    failed" changes the action, which is how a step that was nearly right
    becomes a step that is wrong.
    """
    return (
        "The step above did not work. This is exactly what came back when it "
        "ran:\n\n"
        f"    {failure.strip()[:600]}\n\n"
        "Try again. Change the arguments, not the action: the action was chosen "
        "by the plan and the plan is not yours to change. If the arguments are "
        "already right, reply {\"kind\": \"refuse\", \"reason\": \"...\"} with the "
        "reason rather than failing again."
    )


def retry_messages(action: str, args: dict, result: dict, why: str) -> list[dict]:
    """The conversation for one retry of one action's arguments."""
    from .actions import catalog_for_prompt

    output = str(result.get("output", "")).strip()
    error = str(result.get("error", "")).strip()
    return [
        {"role": "system", "content": worker_system()},
        {"role": "user", "content": (
            f"Goal of the step: {why or 'not stated'}\n"
            f"Action: {action}\n"
            f"Arguments that were used: {args}\n"
            "Available actions:\n" + catalog_for_prompt()
        )},
        {"role": "assistant", "content": '{"action": "' + action + '"}'},
        {"role": "user", "content": (
            "That did not work. Exactly what came back:\n\n"
            f"    output: {output[:400] or '(none)'}\n"
            f"    error:  {error[:400] or '(none)'}\n\n"
            "Reply with the same action and better arguments, or with "
            '{"kind": "refuse", "reason": "..."} if the arguments were already '
            "right and it still failed."
        )},
    ]


def knowledge_for(request: str) -> str:
    """The retrieved knowledge for a request, as text, or "" when there is none.

    An empty string when nothing is found, never a filler. An assistant that
    answers from the internet's habits instead of this machine's documentation
    is answering a different question than the one asked.
    """
    try:
        return _knowledge.for_prompt(request, limit=3)
    except Exception:  # noqa: BLE001 - a broken index is a missing retrieval
        return ""
