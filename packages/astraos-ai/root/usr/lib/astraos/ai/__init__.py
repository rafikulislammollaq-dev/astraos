"""The AstraOS assistant: a local model wired to the desktop's own tools.

This package is deliberately thin and deliberately boring. It has six parts:

    config   paths and settings
    llm      one llama-server process, started on demand
    prompt   the words the model is given, and the only JSON it may answer with
    actions  the complete list of things the model may ask for, and the guards
    voice    speaking and listening, with what Debian already has
    setup    explicit, user-run downloads and builds

Three rules shaped the design, and every file below states how it keeps them:

    * Nothing happens at import time. The package can be imported by a shell
      completion, a status page or a test run without a model, a network or a
      display, and without starting a process or opening a socket.
    * The model is not an authority. actions.py owns the repertoire and
      parse_plan() rejects anything outside it; the four irreversible actions
      are refused unless the human confirmed them.
    * No root, ever. No systemd unit, nothing installed outside $HOME, no
      sudo in any code path. If a thing needs root, the assistant does not do
      it and says so in one line.

This module intentionally imports nothing. `import astraos.ai` must stay free
of side effects, so the submodules are imported by whoever needs them.
"""

from __future__ import annotations

__all__ = ["actions", "config", "llm", "prompt", "setup", "voice"]
