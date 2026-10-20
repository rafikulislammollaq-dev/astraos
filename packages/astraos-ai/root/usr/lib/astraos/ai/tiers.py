"""The model ladder: three tiers, one GPU-free machine, one process at a time.

WHY A LADDER AND NOT ONE MODEL

A single small model has to be three things at once - good enough to plan, cheap
enough to call a hundred times, and smart enough to know when it is out of its
depth - and it is none of them. The fix is the shape a small company uses: a
planner that thinks, a worker that does, and a router that sorts what arrives
into one of the two. Three small models beat one small model for the same reason
three specialists beat one generalist, and all three of them still fit in the
machine this distribution is tested on.

WHY ONLY ONE MODEL IS IN MEMORY AT A TIME

The reference machine has 4 GB of RAM and no swap to speak of. A 1.5B Q4_K_M
model is about 1 GB resident, a 4B about 2.4 GB, and the KV cache adds a slice
on top of each. Loading both halves of the ladder at once is the difference
between an assistant and a machine that swaps the desktop out. So the pool below
owns at most ONE llama-server at a time and swaps the model when the tier
changes, which costs a reload (ten to thirty seconds on this hardware) and buys
a machine that still works while the assistant is running. Everything else in
this package goes through acquire(), so that constraint is enforced in one place
rather than trusted of every caller.

WHY THE TIERS ARE NAMED, NOT NUMBERED

"worker" and "brain" are what the two ends of the ladder are for, and the code
reads better for it. "router" is a third tier that is deliberately optional:
classifying a request is one short constrained call, so it reuses the worker's
engine on a small model rather than occupying memory of its own.
"""

from __future__ import annotations

import shutil
import threading
import time

from . import config as _config
from .llm import Engine, EngineUnavailable

# How long a tier stays resident after its last use. The reload is what makes
# this number a trade-off: loading a 1.5B model takes about as long as the first
# answer, so the idler is set long enough that a conversation does not pay for
# it and short enough that memory comes back when the user walks away.
IDLE_UNLOAD_SECONDS = 180

# The three tiers, in the order they are described in docs/AI.md. The ladder is
# a dictionary rather than a list because everything that needs a tier looks it
# up by name, and because a missing tier has to be a lookup failure the caller
# can explain rather than an IndexError.
TIERS: dict[str, dict] = {
    "worker": {
        "label": "the executor",
        "job": "does one task at a time: reads the request, makes one chosen "
               "tool call, reports what happened, tries again or escalates",
        "prefer": ("spark-x2.5-1.7b-q4_k_m", "smollm3-3b-q4_k_m",
                   "qwen2.5-3b-instruct-q4_k_m"),
        "context": 4096,
        "temperature": 0.1,
        "max_tokens": 256,
    },
    "brain": {
        "label": "the middle brain",
        "job": "reads the whole request and the retrieved knowledge, writes the "
               "plan as a list of typed tasks, and decides what the worker is "
               "allowed to be asked",
        "prefer": ("spark-x2.5-4b-q4_k_m", "smollm3-3b-q4_k_m",
                   "qwen2.5-3b-instruct-q4_k_m"),
        "context": 8192,
        "temperature": 0.2,
        "max_tokens": 768,
    },
    "router": {
        "label": "the router",
        "job": "sorts a request into worker, brain, or a plain answer, in one "
               "short constrained call",
        "prefer": ("smollm2-360m-instruct-q8_0", "spark-x2.5-1.7b-q4_k_m",
                   "qwen2.5-1.5b-instruct-q4_k_m"),
        "context": 2048,
        "temperature": 0.0,
        "max_tokens": 96,
    },
}

# The tier that must be installed for an assistant to do anything at all. The
# other two upgrade it.
REQUIRED_TIER = "worker"


class TierUnavailable(RuntimeError):
    """No model is installed that can fill a tier, with the reason and the fix."""


def _installed_models() -> list[str]:
    """Every .gguf file name visible, the user's directory and the image's.

    The image ships the executor and the user may download a second model; the
    same name in both places is one model, which is what config.installed_models()
    guarantees.
    """
    return sorted(
        name for name in _config.installed_models() if name.lower().endswith(".gguf")
    )


def pick_model(tier: str, settings: dict | None = None) -> str | None:
    """The model file name to use for a tier, or None when there is none.

    Resolution, in order:

      1. an explicit setting: settings["<tier>_model"] - a user who wants the
         brain to be a different model from the worker, or who fine-tuned their
         own and wants it in a specific place;
      2. the only model installed at all, whatever it is. One model means the
         machine is doing its best with what it has, and refusing to work
         because it is not in the *right* tier would be a policy nobody asked
         for;
      3. the first file name from the tier's preference list that exists.

    A tier that resolves to None is not an error by itself: the caller decides
    whether it can carry on with a different tier (the router and the brain
    both can), and the message that results names the tier and the command that
    installs a model for it.
    """
    settings = dict(settings or _config.load_settings())
    explicit = str(settings.get(f"{tier}_model") or "").strip()
    if explicit:
        return explicit

    installed = _installed_models()
    if len(installed) == 1:
        return installed[0]

    wanted = TIERS.get(tier, {}).get("prefer", ())
    for stem in wanted:
        for name in installed:
            if name.lower().startswith(stem.lower()):
                return name
    return None


def tier_settings(tier: str, settings: dict | None = None) -> dict:
    """The settings for one tier: the global file, then this tier's overrides.

    The tier's own temperature, context and max_tokens win over the user's,
    because a router that wants 0.0 determinism must not be talked out of it by
    a chat setting, and a worker that needs a 256-token ceiling must not be
    opened up to a 512-token one. Everything the user set that a tier does not
    care about - host, port, threads - is left exactly as they left it.
    """
    merged = dict(settings or _config.load_settings())
    tier_config = TIERS.get(tier)
    if tier_config is None:
        raise KeyError(f"unknown tier: {tier}")
    for key in ("context", "temperature", "max_tokens"):
        if key in tier_config:
            merged[key] = tier_config[key]

    chosen = pick_model(tier, merged)
    if not chosen:
        return merged
    merged["model"] = chosen
    return merged


def tier_port(tier: str, settings: dict | None = None) -> int:
    """The llama.cpp port a tier's server listens on.

    Only one tier is resident at a time, so the ports could all be the same
    one. They are not, for a reason that costs nothing: a user who starts a
    llama-server by hand on the assistant's port, and a stub in a test that
    remembered one, both behave predictably instead of colliding in a way that
    depends on which tier happened to be loaded.
    """
    base = _config.DEFAULTS["port"]
    try:
        base = int((settings or _config.load_settings()).get("port") or base)
    except (TypeError, ValueError):
        base = _config.DEFAULTS["port"]
    offset = {"worker": 0, "brain": 1, "router": 2}.get(tier, 0)
    return base + offset


class TierPool:
    """At most one llama-server, shared by every tier, reloaded on swap.

    The pool is the only thing in the package that starts a model server. That
    is a deliberate single choke point: the memory constraint is not a setting
    or a convention, it is the machine, and it is enforced once instead of being
    remembered by every caller.

        pool = TierPool(settings)
        with pool.borrow("brain") as brain_engine:
            plan = plan_with(brain_engine, ...)
        with pool.borrow("worker") as worker_engine:
            done = work_with(worker_engine, ...)

    Both halves of that sequence run ONE server at a time. The reload between
    them is visible in the log line the pool prints, because a user watching an
    assistant think for thirty seconds deserves to know the model is being
    swapped and not stuck.
    """

    def __init__(self, settings: dict | None = None):
        self.settings = dict(settings or _config.load_settings())
        self._engine: Engine | None = None
        self._engine_tier = ""
        self._borrowers = 0
        self._last_used = 0.0
        self._lock = threading.Lock()
        self._idler: threading.Thread | None = None

    # ------------------------------------------------------------------
    # What is available
    # ------------------------------------------------------------------

    def ladder(self) -> list[dict]:
        """Each tier with the model it would use, for `astra ai status`.

        The result is a description, not a promise: a tier whose model is not
        installed still appears, with `model` empty and a message saying what
        to install. A status command that hides a tier the user has not set up
        is a status command that cannot tell them how to set it up.
        """
        rows = []
        for name, tier_config in TIERS.items():
            chosen = pick_model(name, self.settings)
            rows.append(
                {
                    "tier": name,
                    "label": tier_config["label"],
                    "job": tier_config["job"],
                    "model": chosen or "",
                    "port": tier_port(name, self.settings),
                    "installed": bool(chosen),
                    "required": name == REQUIRED_TIER,
                }
            )
        return rows

    def ready(self) -> bool:
        """True when at least the required tier can be served."""
        return bool(pick_model(REQUIRED_TIER, self.settings))

    def unavailable_reason(self) -> str:
        if self.ready():
            return ""
        # The model name comes from the tier's own preference list, the same
        # rule pick_model applies. Advice that names a model has to be built
        # from that list rather than typed out: the string this replaced was a
        # hardcoded model name, and it went stale exactly as fast as a
        # hardcoded model name does.
        return (
            f"no model is installed for the {REQUIRED_TIER} tier - install one "
            f"with: astra-ai setup --model {TIERS[REQUIRED_TIER]['prefer'][0]}"
        )

    # ------------------------------------------------------------------
    # Borrowing
    # ------------------------------------------------------------------

    def _engine_for(self, tier: str) -> Engine:
        chosen = pick_model(tier, self.settings)
        if not chosen:
            raise TierUnavailable(
                f"the {tier} tier has no model installed - install one with: "
                f"astra-ai setup --model {TIERS[tier]['prefer'][0]}"
            )
        settings = tier_settings(tier, self.settings)
        settings["port"] = tier_port(tier, self.settings)
        return Engine(settings)

    def borrow(self, tier: str) -> Engine:
        """Get the engine for a tier, swapping the resident model if needed.

        Raises TierUnavailable when the tier has no model. Swapping stops the
        current engine first, so the two models are never in RAM together - the
        reload is the price of the machine we have.
        """
        with self._lock:
            if self._engine is None or self._engine_tier != tier:
                if self._engine is not None:
                    current = self._engine_tier
                    self._engine.stop()
                    self._engine = None
                    _log(f"the {current} model made room for the {tier} model")
                self._engine = self._engine_for(tier)
                self._engine_tier = tier
            self._borrowers += 1
            self._last_used = time.monotonic()
            return self._engine

    def done(self, tier: str) -> None:
        """Give a borrowed tier back. The process keeps running for now.

        Not unloading here is the whole point: a plan is one borrow and a task
        is another, and a reload between them would double the wall-clock cost
        of every step. The idler unloads once the tier has actually been idle
        for IDLE_UNLOAD_SECONDS.
        """
        with self._lock:
            if self._borrowers > 0:
                self._borrowers -= 1
            self._last_used = time.monotonic()

    def unload(self) -> None:
        """Stop the resident model and give the RAM back."""
        with self._lock:
            engine, self._engine = self._engine, None
            self._engine_tier = ""
            self._borrowers = 0
        if engine is not None:
            engine.stop()

    def resident(self) -> str:
        """The tier currently holding memory, or "" when nothing is loaded."""
        with self._lock:
            return self._engine_tier if self._engine is not None else ""

    def start_idler(self) -> None:
        """Spawn the thread that unloads an idle tier. Idempotent."""
        with self._lock:
            if self._idler is not None and self._idler.is_alive():
                return
            self._idler = threading.Thread(target=self._idle_loop, daemon=True)
            self._idler.start()

    def _idle_loop(self) -> None:
        while True:
            time.sleep(5)
            with self._lock:
                engine = self._engine
                idle_for = time.monotonic() - self._last_used if engine else 0.0
                should_unload = (
                    engine is not None
                    and self._borrowers == 0
                    and idle_for >= IDLE_UNLOAD_SECONDS
                )
            if should_unload:
                self.unload()

    # ------------------------------------------------------------------
    # Convenience: a borrowed engine that is given back by itself
    # ------------------------------------------------------------------

    def asking(self, tier: str) -> "Borrowed":
        """A context manager, so a caller cannot forget to give the tier back."""
        return Borrowed(self, tier)


class Borrowed:
    """The engine for a tier, for as long as the `with` block lives."""

    def __init__(self, pool: TierPool, tier: str):
        self._pool = pool
        self._tier = tier
        self.engine: Engine | None = None

    def __enter__(self) -> Engine:
        self.engine = self._pool.borrow(self._tier)
        return self.engine

    def __exit__(self, *_exc) -> None:
        self._pool.done(self._tier)
        self.engine = None


def _log(message: str) -> None:
    """Progress on stderr: stdout carries the answer only."""
    import sys

    print(f"astra-ai: {message}", file=sys.stderr)


def ready_message() -> str:
    """What to tell a user whose machine has no model installed yet."""
    if shutil.which("llama-server") is None:
        return (
            "llama-server is not installed - build it with: "
            "astra-ai setup --build llama"
        )
    return (
        "no model is installed - install one with: "
        f"astra-ai setup --model {TIERS[REQUIRED_TIER]['prefer'][0]}"
    )
