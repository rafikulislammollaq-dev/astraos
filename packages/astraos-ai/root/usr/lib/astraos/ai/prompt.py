"""The words the model is given, and the only shape its replies may take.

Why the format is a JSON object rather than "tool calling":

    The model is a 1B-3B quantised instruct model on a CPU with AVX but no
    AVX2. Models of that size follow a schema that is written out in plain
    words far more reliably than they follow a protocol whose support depends
    on a chat template, and llama.cpp's native tool-calling support differs by
    version anyway. One object, two keys, no fence - that is a format a small
    model can hold onto, and parse_plan() accepts it with the fences a small
    model adds anyway.

Why the catalog is in the prompt at all:

    The prompt is where the model is told the rules; actions.py is where the
    rules are enforced. Listing the actions here is what makes the refusal
    ("that is not in the list of things I can do") the model's natural answer
    instead of an invented action name that parse_plan() then has to throw
    away. The list is generated from ACTIONS, so it cannot drift from what is
    actually implemented.

Why history is trimmed twice:

    Every token in the prompt costs time on this hardware, and a desktop
    assistant's third question does not need the first one. The last twelve
    messages, each capped at two thousand characters, is roughly a screenful
    of conversation - enough for "do that again but louder" to make sense, not
    enough for a pasted book to push the actual question out of the context
    window. Only the user and assistant roles survive the trim: a "system"
    entry arriving from the web interface is dropped rather than passed on,
    because the only system prompt the model gets is the one below.
"""

from __future__ import annotations

from . import actions as _actions

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
