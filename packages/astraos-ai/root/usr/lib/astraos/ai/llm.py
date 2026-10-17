"""One llama.cpp server, started on demand, on 127.0.0.1 only.

Why llama-server over HTTP and not a binding or a library:

    The assistant has to be usable by two callers that never see each other -
    the command line and the web interface - and the machine that runs it is a
    Sandy Bridge desktop where the model takes ten to thirty seconds to load.
    A process that speaks HTTP gives both callers the same object, keeps the
    weights in RAM between questions instead of loading them per question, and
    can be inspected with the tools anyone already has (curl, a browser, ps).
    There is no Python binding to install: the image has no pip, and llama.cpp
    is a C++ program with a server target.

Why the engine starts nothing until it is asked:

    Importing this module must not download, build, spawn or connect to
    anything. A status page that imports it to ask "is the model installed?"
    would otherwise start a server; a test run on a machine with no model
    would fail for no reason. Every effect lives in start(), ask() and stop().

Why the process is not killed when the command exits:

    Loading a 1.5B Q4 model on this hardware costs about as long as the first
    answer does. Leaving the server running is what makes the second question
    fast, and `astra-ai stop` (or the web interface) is the explicit way to
    give the memory back. The engine only ever stops a process it started
    itself: a llama-server started by someone else is not ours to kill.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterator

from . import config as _config

# How long to wait for the model to load before giving up. The reference
# machine needs roughly 10 s for a 1.5B Q4_K_M model and roughly 25 s for a
# 3B one, measured with the CPU otherwise idle; 120 s leaves room for a cold
# page cache and a machine that is doing something else.
START_TIMEOUT_SECONDS = 120

# OpenAI-compatible endpoint. llama.cpp implements this path in every version
# that ships a server, which is why the request bodies below look like the
# ones a hosted API uses.
CHAT_PATH = "/v1/chat/completions"
HEALTH_PATH = "/health"


class EngineUnavailable(RuntimeError):
    """The engine cannot answer, with a one-line reason a user can act on."""


def _log(message: str) -> None:
    """Progress on stderr, never stdout: stdout carries model output only."""
    print(f"astra-ai: {message}", file=sys.stderr)


class Engine:
    """The llama-server process and the HTTP calls that talk to it."""

    def __init__(self, settings: dict):
        # A copy, so that a caller mutating its settings dictionary later does
        # not change the port this engine already decided to use.
        self.settings = dict(settings or {})
        self._process: subprocess.Popen | None = None
        self._logfile = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # What is installed
    # ------------------------------------------------------------------

    def binary(self) -> str | None:
        """The llama-server executable, or None when it is not installed.

        Checked in order: an explicit ASTRAOS_AI_LLAMA_SERVER (a user who
        built it somewhere else), then the assistant's own bin directory,
        then PATH - in case a distribution package provides one.
        """
        override = os.environ.get("ASTRAOS_AI_LLAMA_SERVER")
        if override and Path(override).is_file():
            return override
        for name in ("llama-server", "llama-server.exe"):
            candidate = _config.PATHS.bin_dir / name
            if candidate.is_file():
                return str(candidate)
        return shutil.which("llama-server")

    def model(self) -> Path | None:
        return _config.model_file(self.settings)

    def available(self) -> bool:
        """True when an ask() would have everything it needs.

        A pure check: it looks at the filesystem and PATH and nothing else. It
        does not start the server, and it does not contact a running one.
        """
        return self.binary() is not None and self.model() is not None

    def _unavailable_reason(self) -> str:
        if self.binary() is None:
            return (
                "llama-server is not installed - build it with: "
                "astra-ai setup --build llama"
            )
        if self.model() is None:
            # The same advice tiers.ready_message() gives, built from the
            # ladder instead of typed out: a literal here drifts from the
            # catalogue the moment a model is replaced, and the user is then
            # told to install something `astra-ai setup` no longer sells.
            # tiers imports this module, so the import is local.
            from .tiers import REQUIRED_TIER, TIERS

            return (
                "no model is installed - install one with: "
                f"astra-ai setup --model {TIERS[REQUIRED_TIER]['prefer'][0]}"
            )
        return ""

    # ------------------------------------------------------------------
    # Start / stop
    # ------------------------------------------------------------------

    def _port(self) -> int:
        try:
            return int(self.settings.get("port") or _config.DEFAULTS["port"])
        except (TypeError, ValueError):
            return int(_config.DEFAULTS["port"])

    def _base_url(self) -> str:
        host = str(self.settings.get("host") or _config.DEFAULTS["host"])
        return f"http://{host}:{self._port()}"

    def _argv(self) -> list[str]:
        binary = self.binary()
        if binary is None:
            raise EngineUnavailable(self._unavailable_reason())
        model = self.model()
        if model is None:
            raise EngineUnavailable(self._unavailable_reason())

        argv = [
            binary,
            "-m", str(model),
            "--host", str(self.settings.get("host") or _config.DEFAULTS["host"]),
            "--port", str(self._port()),
            "-c", str(int(self.settings.get("context") or _config.DEFAULTS["context"])),
            "-t", str(int(self.settings.get("threads") or _config.DEFAULTS["threads"])),
            # Kept explicit even though it is the default: on this hardware it
            # is the difference between "CPU only" and a failed start.
            "-ngl", str(int(self.settings.get("gpu_layers") or 0)),
        ]
        return argv

    def _log_path(self) -> Path:
        return _config.PATHS.models_dir.parent / "llama-server.log"

    def start(self) -> None:
        """Start llama-server and wait until it is answering. Idempotent.

        Raises EngineUnavailable with one actionable line when the binary or
        the model is missing, or when the process exits during start-up (the
        reason is in the log file, whose path is printed).
        """
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return
            if self._unavailable_reason():
                raise EngineUnavailable(self._unavailable_reason())

            log_path = self._log_path()
            try:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                self._logfile = open(log_path, "ab")
            except OSError:
                # A missing log must not stop the server from starting.
                self._logfile = subprocess.DEVNULL

            _log(f"starting the model ({self.model().name}) on {self._base_url()}")
            argv = self._argv()
            try:
                self._process = subprocess.Popen(
                    argv,
                    stdin=subprocess.DEVNULL,
                    stdout=self._logfile,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            except OSError as exc:
                self._process = None
                raise EngineUnavailable(f"could not run llama-server: {exc}") from exc

            deadline = time.monotonic() + START_TIMEOUT_SECONDS
            while time.monotonic() < deadline:
                if self._process.poll() is not None:
                    self._close_logfile()
                    raise EngineUnavailable(
                        "llama-server exited while loading the model - see "
                        f"{log_path}"
                    )
                if self._health_ok():
                    _log(f"model ready (pid {self._process.pid})")
                    return
                time.sleep(0.5)

            # NOTE: this must NOT call self.stop(). stop() acquires self._lock, and
            # self._lock is a plain (non-reentrant) threading.Lock that this very
            # `with` block already holds - so the call deadlocked the thread that
            # was waiting for the model, permanently: no EngineUnavailable was ever
            # raised (so no message and no exit), the llama-server child was leaked
            # (it is started in its own session), and Assistant._ask_lock in
            # server.py was never released, which froze every later /api/chat
            # request rather than just this one. Reachable whenever the model takes
            # longer than START_TIMEOUT_SECONDS to load, which is exactly the
            # documented failure mode (see setup.py on the SIGILL-era run).
            self._terminate_locked()
            raise EngineUnavailable(
                f"the model did not load within {START_TIMEOUT_SECONDS}s - see {log_path}"
            )

    def stop(self) -> None:
        """Stop the process this engine started. Does nothing otherwise.

        The check for "did we start it?" is deliberate. `astra-ai stop` in one
        terminal must not kill a llama-server that the web interface started
        in another, and it must not kill an unrelated llama-server the user is
        running by hand.
        """
        with self._lock:
            self._terminate_locked()

    def _terminate_locked(self) -> None:
        """Terminate the child. The caller MUST already hold self._lock.

        Split out of stop() so start()'s timeout path can clean up without
        re-entering the non-reentrant lock it is holding (see the note there).
        """
        process = self._process
        self._process = None
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        self._close_logfile()

    def _close_logfile(self) -> None:
        if self._logfile not in (None, subprocess.DEVNULL):
            try:
                self._logfile.close()
            except OSError:
                pass
        self._logfile = None

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    def _health_ok(self, timeout: float = 2.0) -> bool:
        """True when the server answers /health with 200.

        During loading llama.cpp answers 503 on this path, which is exactly
        the signal start() polls for.
        """
        try:
            with urllib.request.urlopen(
                self._base_url() + HEALTH_PATH, timeout=timeout
            ) as response:
                return 200 <= response.status < 300
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def health(self) -> dict:
        """A description of the engine's state, for `astra-ai status` and the UI.

        Never starts anything and never blocks for longer than a socket
        timeout. The keys are:
            ok          the server answered
            running     this engine has a live process
            port/host   where it would be reached
            model       the model file name, or ""
            model_file  its absolute path, or ""
            binary      the llama-server path, or ""
            pid         the process id, or 0
            message     one line explaining anything that is not ok
        """
        binary = self.binary()
        model = self.model()
        running = self._process is not None and self._process.poll() is None

        info = {
            "ok": False,
            "running": running,
            "host": str(self.settings.get("host") or _config.DEFAULTS["host"]),
            "port": self._port(),
            "model": model.name if model else "",
            "model_file": str(model) if model else "",
            "binary": binary or "",
            "pid": self._process.pid if running else 0,
            "message": "",
        }

        if self._unavailable_reason():
            info["message"] = self._unavailable_reason()
            return info
        if not running:
            info["message"] = "not running (starts on the first question)"
            return info
        if not self._health_ok():
            info["message"] = "the process is alive but /health is not answering yet"
            return info

        info["ok"] = True
        info["message"] = "ready"
        return info

    def _request(self, body: dict, stream: bool) -> urllib.request.Request:
        url = self._base_url() + CHAT_PATH
        payload = json.dumps(body).encode("utf-8")
        return urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "text/event-stream" if stream else "application/json",
            },
            method="POST",
        )

    def ask(self, messages: list[dict], stream: bool = True) -> Iterator[str]:
        """Ask the model and yield the answer in pieces.

        The return value is an iterator of text deltas. With stream=False the
        whole answer arrives as a single piece, which is what the tests and
        any caller that needs the complete text at once should use.

        start() runs before the first piece is produced, so a missing model
        raises EngineUnavailable here rather than half-way through an answer
        the web interface has already begun to send.
        """
        self.start()

        body = self._body(messages, stream)
        return self._stream(body) if stream else self._complete(body)

    def _body(self, messages: list[dict], stream: bool, **extra) -> dict:
        """The chat completion body. Every ask goes through here.

        `extra` carries the caller's additions - response_format for a
        constrained call, chat_template_kwargs for a thinking mode - and it is
        a keyword rather than a positional list because there will be more of
        them, and because a call that needs both must be able to say so in one
        line that reads as one intention.
        """
        body = {
            "messages": messages,
            "stream": bool(stream),
            "temperature": float(
                self.settings.get("temperature") or _config.DEFAULTS["temperature"]
            ),
            "max_tokens": int(
                self.settings.get("max_tokens") or _config.DEFAULTS["max_tokens"]
            ),
        }
        body.update(extra)
        return body

    def ask_json(
        self, messages: list[dict], schema: dict, stream: bool = False
    ) -> Iterator[str]:
        """Ask for one JSON answer the grammar cannot let be malformed.

        WHY THIS EXISTS AT ALL

        A small model asked for JSON produces broken JSON often enough that a
        parser in the loop is a joke: the markdown fence appears, or a quote
        escapes itself, or the object closes two levels down. llama.cpp can
        constrain generation to a JSON schema, which turns the problem from
        "please" into "cannot" - the tokens that would break the schema are not
        generated, so the answer either parses or is empty.

        WHY ENABLE_THINKING IS FORCED OFF

        There is a live llama.cpp defect (issue #20335) in which grammar and
        schema enforcement is silently skipped when a model's thinking mode is
        enabled: the server returns the reasoning text, the constraint is not
        applied to it, and the caller gets a 500 from a token that came out of
        the model's head rather than a malformed answer. Qwen3 and SmolLM3 both
        enable thinking by default in their own chat templates, and the
        ladder's Spark-X2.5 family is a reasoning model as well - so the flag
        is sent for every model rather than for a list, because a catalogue
        that grows must not grow a quiet way to turn the constraint off.

        WHY NOT STREAMING

        A constrained answer is short (a tool call is a few dozen tokens) and it
        is parsed as a whole anyway, so streaming would only add a code path
        that cannot be used. stream=True is accepted for symmetry and ignored.
        """
        self.start()

        body = self._body(
            messages,
            False,
            response_format={"type": "json_object", "schema": schema},
            chat_template_kwargs={"enable_thinking": False},
        )
        return self._complete(body)

    def _complete(self, body: dict) -> Iterator[str]:
        """One non-streaming answer."""
        try:
            with urllib.request.urlopen(self._request(body, False), timeout=300) as response:
                data = json.loads(response.read().decode("utf-8", "replace"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise EngineUnavailable(f"the model server did not answer: {exc}") from exc

        text = _first_content(data)
        if text:
            yield text

    def _stream(self, body: dict) -> Iterator[str]:
        """Server-sent events, one JSON object per line, until [DONE]."""
        try:
            with urllib.request.urlopen(self._request(body, True), timeout=300) as response:
                for raw in response:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[len("data:"):].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        event = json.loads(payload)
                    except ValueError:
                        # A truncated event is a reason to stop, not to crash:
                        # everything before it has already been yielded.
                        break
                    delta = _first_delta(event)
                    if delta:
                        yield delta
        except (urllib.error.URLError, OSError) as exc:
            raise EngineUnavailable(f"the model server did not answer: {exc}") from exc


def _first_choice(data: dict) -> dict:
    """The first choice of a chat completion, or an empty dictionary.

    llama.cpp sends {"choices": []} on some events (usage-only chunks, and the
    final chunk of a stopped generation), so every caller has to tolerate it.
    """
    if not isinstance(data, dict):
        return {}
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return {}
    choice = choices[0]
    return choice if isinstance(choice, dict) else {}


def _first_content(data: dict) -> str:
    choice = _first_choice(data)
    message = choice.get("message")
    if isinstance(message, dict) and isinstance(message.get("content"), str):
        return message["content"]
    # Some versions answer with "text" (the completion endpoint) instead.
    if isinstance(choice.get("text"), str):
        return choice["text"]
    return ""


def _first_delta(data: dict) -> str:
    choice = _first_choice(data)
    delta = choice.get("delta")
    if isinstance(delta, dict) and isinstance(delta.get("content"), str):
        return delta["content"]
    return ""
