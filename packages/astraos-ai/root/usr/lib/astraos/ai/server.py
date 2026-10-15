#!/usr/bin/env python3
"""The AstraOS assistant's local web server.

Why this exists and why it is written this way:

  * The assistant is a local page, not a cloud service. The server binds 127.0.0.1
    by default and the page makes no request of any kind except to this server.

  * --lan opens the page to the local network so a phone can act as the microphone
    for a PC that has none. That is the whole feature and the whole risk: there is
    no authentication. The one-line warning printed at startup says so, and every
    action still needs an explicit confirmation in the page before it runs.

  * Streaming is newline-delimited JSON over a chunked response: one JSON object
    per line, flushed as it happens, so the reply appears as the model produces it.
    Events: delta, plan, done, error. The browser keeps one code path for every
    outcome because even the not-ready case is a (single) error event.

  * It must start and keep working with nothing installed: no model, no llama.cpp
    binary, no whisper, no text-to-speech. /api/health then reports ready=false and
    the page explains "astra ai setup". A missing tool is a state, not a crash.

  * Standard library only (http.server, json, threading, socket). This computer may
    have no network at all, so it cannot depend on pip-installed packages.

The safety model, in the order the checks run:

  1. /api/chat streams the model's text and, when the model proposed one, a "plan"
     event carrying the action catalogue. Nothing has run yet.
  2. The page renders an action card and waits. A plan is not executed because it
     was proposed; it is executed because a human pressed Confirm.
  3. /api/confirm re-checks the plan itself -- plan_refusal() below -- and refuses
     any plan that does not name an action in actions.ACTIONS, before calling
     execute(plan, confirmed=True). The client cannot widen the repertoire by
     editing the JSON, and the tests pin that down.

Limits, stated honestly: no authentication on --lan, no TLS, no per-action
sandbox -- actions run as the logged-in user with the same rights as the terminal
they would otherwise be typed into. See docs/AI.md in the source tree.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit

try:
    # The installed layout: /usr/lib/astraos/ai/*.py, imported as astraos.ai.*
    from astraos.ai import actions, config, llm, prompt, tiers, voice
    from astraos.ai import journal as _journal
    from astraos.ai import worker as _worker
except ImportError:
    # Running this file by path puts its own directory on sys.path, not /usr/lib,
    # so the astraos package is not importable. Add the tree root and retry once.
    _TREE_ROOT = str(Path(__file__).resolve().parents[2])
    if _TREE_ROOT not in sys.path:
        sys.path.insert(0, _TREE_ROOT)
    from astraos.ai import actions, config, llm, prompt, tiers, voice
    from astraos.ai import journal as _journal
    from astraos.ai import worker as _worker

DEFAULT_HOST = "127.0.0.1"
LAN_HOST = "0.0.0.0"
DEFAULT_PORT = 8765

MAX_CHAT_BYTES = 256 * 1024
MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_HISTORY = 40

SETUP_HINT = "The assistant has no local model yet. In a terminal run: astra ai setup"

# Printed once by every --lan start. One line, and it has to say both things:
# the page is reachable by the whole network, and execution still needs a human.
LAN_WARNING = (
    "warning: this page is open to every device on the local network; "
    "actions still require confirmation in the page"
)

JSON_TYPE = "application/json; charset=utf-8"
NDJSON_TYPE = "application/x-ndjson; charset=utf-8"

# Keys that commonly carry an action name in a plan. The value is what matters,
# not the key: see plan_action_name().
_NAME_KEYS = ("action", "name", "tool", "id")


def normalize_history(value: Any) -> list[dict[str, str]]:
    """Keep only well-formed {role, content} entries; the model sees nothing else.

    History arrives from the browser, which means it is untrusted input. Anything
    that is not a plain string pair from a real role is dropped rather than passed
    through: build_messages() must never receive a dict with extra keys or a
    non-string content, whatever the page sent.
    """
    if not isinstance(value, list):
        return []
    cleaned: list[dict[str, str]] = []
    for item in value[-MAX_HISTORY:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role in ("user", "assistant", "system") and isinstance(content, str) and content:
            cleaned.append({"role": role, "content": content})
    return cleaned


def plan_action_name(plan: Any) -> str | None:
    """The action a plan claims to be, or None when the plan does not say.

    The plan's exact shape belongs to actions.parse_plan(), not to this file, so
    the name is read from the usual keys first and then from any top-level string
    value that matches a real action. That keeps the server working if the plan
    format is renamed without weakening the gate: a refused plan is one whose
    claimed action is not in the repertoire, in whatever field it is written.
    """
    if not isinstance(plan, dict):
        return None
    for key in _NAME_KEYS:
        value = plan.get(key)
        if isinstance(value, str) and value:
            return value
    known = getattr(actions, "ACTIONS", {})
    for value in plan.values():
        if isinstance(value, str) and value in known:
            return value
    return None


def plan_refusal(plan: Any) -> str | None:
    """The reason to refuse a plan, or None when it may be executed.

    This is the whole whitelist: a plan executes only if it names an action that
    exists in actions.ACTIONS. Everything else -- unknown names, missing names,
    non-dicts -- is refused here, before execute() is reached.
    """
    name = plan_action_name(plan)
    if name is None:
        return ("Refused: the plan does not name an action from the AstraOS "
                "repertoire; nothing was executed.")
    known = getattr(actions, "ACTIONS", {})
    if name not in known:
        return (f"Refused: '{name}' is not an AstraOS action; nothing was "
                "executed.")
    return None


def locate_web_index() -> Path | None:
    """Where the single HTML page lives, installed or running from the source tree.

    /usr/lib/astraos/ai/server.py and packages/astraos-ai/root/usr/lib/astraos/ai/server.py
    have the same shape, so parents[3] plus the share path covers both. PATHS is
    tried first because config.py owns the installed locations.
    """
    candidates: list[Path] = []
    try:
        share_dir = Path(config.PATHS.share_dir)
        candidates.append(share_dir / "web" / "index.html")
        candidates.append(share_dir / "index.html")
    except Exception:
        pass
    here = Path(__file__).resolve()
    candidates.append(here.parents[3] / "share" / "astraos" / "ai" / "web" / "index.html")
    candidates.append(here.parent / "index.html")
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


class Assistant:
    """The state every request shares: the engine, lazy startup, and the gate.

    All engine access goes through this object so that the HTTP layer can stay
    thin, and so that "no engine" is a representable state instead of an
    exception that takes the server down with it.
    """

    def __init__(self, settings: dict | None = None) -> None:
        try:
            self.settings = settings if settings is not None else config.load_settings()
        except Exception:
            # A broken settings file must not stop the page from loading.
            self.settings = {}
        self.engine: Any = None
        self.engine_error = ""
        try:
            self.engine = llm.Engine(self.settings)
        except Exception as exc:
            self.engine_error = f"{type(exc).__name__}: {exc}"
        self._start_lock = threading.Lock()
        # One generation at a time: llama.cpp servers do not enjoy concurrent
        # streams, and this is a single-user desktop tool anyway.
        self._ask_lock = threading.Lock()
        self._started = False

    def ready(self) -> bool:
        """True only when a model is installed and the engine says so. Never raises."""
        if self.engine is None:
            return False
        try:
            return bool(self.engine.available())
        except Exception:
            return False

    def health(self) -> dict:
        """A JSON-safe status report. Every probe is wrapped: health is a report,
        not a test that may fail."""
        report: dict[str, Any] = {
            "ready": self.ready(),
            "engine": {},
            "voice": {"tts": False, "stt": False},
            "setup_hint": SETUP_HINT,
        }
        if self.engine is not None:
            try:
                raw = self.engine.health()
                report["engine"] = raw if isinstance(raw, dict) else {"value": raw}
            except Exception as exc:
                report["engine_error"] = f"{type(exc).__name__}: {exc}"
        elif self.engine_error:
            report["engine_error"] = self.engine_error
        for key, probe in (("tts", voice.tts_available), ("stt", voice.stt_available)):
            try:
                report["voice"][key] = bool(probe())
            except Exception as exc:
                report["voice"][key + "_error"] = f"{type(exc).__name__}: {exc}"
        return report

    def chat(self, user_text: str, history: list[dict[str, str]]) -> Iterator[dict]:
        """Yield the events of one conversation turn, in order.

        The event stream always ends with "done", even after an error, so the
        page can finish the turn with one rule instead of three.
        """
        if self.engine is None:
            yield {"type": "error",
                   "text": "The assistant engine could not start: " + self.engine_error}
            yield {"type": "done"}
            return
        if not self.ready():
            yield {"type": "error", "text": SETUP_HINT}
            yield {"type": "done"}
            return
        try:
            messages = prompt.build_messages(user_text, history)
        except Exception as exc:
            yield {"type": "error",
                   "text": f"Could not prepare the request: {type(exc).__name__}: {exc}"}
            yield {"type": "done"}
            return

        chunks: list[str] = []
        try:
            with self._ask_lock:
                if not self._started:
                    self.engine.start()
                    self._started = True
                for chunk in self.engine.ask(messages, stream=True):
                    if not isinstance(chunk, str):
                        chunk = str(chunk)
                    if not chunk:
                        continue
                    chunks.append(chunk)
                    yield {"type": "delta", "text": chunk}
        except Exception as exc:
            yield {"type": "error", "text": f"The model failed: {type(exc).__name__}: {exc}"}
            yield {"type": "done"}
            return

        answer = "".join(chunks)
        try:
            plan = actions.parse_plan(answer)
        except Exception:
            # A parser crash is not a reason to lose the answer that streamed.
            plan = None
        if isinstance(plan, dict) and plan:
            try:
                catalog = actions.list_actions()
            except Exception:
                catalog = []
            if not isinstance(catalog, list):
                catalog = []
            yield {"type": "plan", "plan": plan, "catalog": catalog}
        yield {"type": "done"}

    def confirm(self, plan: dict) -> dict:
        """Execute a confirmed plan, after the whitelist check. Never raises."""
        refusal = plan_refusal(plan)
        if refusal:
            return {"ok": False, "detail": refusal}
        try:
            result = actions.execute(plan, confirmed=True)
        except Exception as exc:
            return {"ok": False,
                    "detail": (f"The action failed before it could run: "
                               f"{type(exc).__name__}: {exc}")}
        if isinstance(result, dict):
            return {"ok": bool(result.get("ok")), "detail": str(result.get("detail", ""))}
        return {"ok": False,
                "detail": f"The action returned {type(result).__name__} instead of a result."}

    def transcribe(self, wav: bytes) -> tuple[int, dict]:
        """(status, body) for a WAV upload. 503 means: install whisper first."""
        if not wav:
            return 400, {"ok": False, "detail": "Empty body: expected raw WAV audio."}
        available = False
        try:
            available = bool(voice.stt_available())
        except Exception:
            available = False
        if not available:
            return 503, {"ok": False, "detail": (
                "Speech recognition is not installed on this computer, so recorded "
                "audio cannot be transcribed. Install it with 'astra ai setup', or "
                "use a browser whose own speech recognition works.")}
        try:
            text = voice.transcribe(wav)
        except Exception as exc:
            return 500, {"ok": False,
                         "detail": f"Transcription failed: {type(exc).__name__}: {exc}"}
        return 200, {"text": text if isinstance(text, str) else str(text)}

    def speak(self, text: str) -> tuple[int, dict]:
        """(status, body) for a request to speak through the PC's own speakers."""
        if not text.strip():
            return 400, {"ok": False, "detail": "Nothing to say."}
        available = False
        try:
            available = bool(voice.tts_available())
        except Exception:
            available = False
        if not available:
            return 503, {"ok": False, "detail": (
                "Text-to-speech is not installed on this computer. Run "
                "'astra ai setup' to add a speech tool, or use 'This device' "
                "in the page.")}
        try:
            spoke = bool(voice.speak(text))
        except Exception as exc:
            return 500, {"ok": False,
                         "detail": f"Speaking failed: {type(exc).__name__}: {exc}"}
        if spoke:
            return 200, {"ok": True, "detail": ""}
        return 200, {"ok": False, "detail": "The speech tool was not able to speak the text."}


class RequestHandler(BaseHTTPRequestHandler):
    """HTTP surface. Thin: parse, delegate to Assistant, frame the answer."""

    protocol_version = "HTTP/1.1"
    server_version = "AstraOS-AI/0.1"
    timeout = 60

    # -- plumbing -----------------------------------------------------------

    def log_message(self, fmt: str, *args: Any) -> None:
        # Quiet by default: this is a desktop tool, not a web log. --verbose for
        # the cases where someone needs to see requests.
        if getattr(self.server, "verbose", False):
            super().log_message(fmt, *args)

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", JSON_TYPE)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _body_bytes(self, limit: int) -> tuple[bytes | None, tuple[int, str] | None]:
        raw = self.headers.get("Content-Length")
        try:
            length = int(raw) if raw is not None else 0
        except ValueError:
            return None, (400, "Content-Length is not a number.")
        if length < 0:
            return None, (400, "Content-Length is negative.")
        if length > limit:
            return None, (413, f"Request body too large ({length} bytes; limit {limit}).")
        if length == 0:
            return b"", None
        return self.rfile.read(length), None

    def _read_json(self, limit: int) -> dict | None:
        data, error = self._body_bytes(limit)
        if error is not None:
            self._json(error[0], {"ok": False, "detail": error[1]})
            return None
        try:
            payload = json.loads(data.decode("utf-8")) if data else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._json(400, {"ok": False, "detail": f"Invalid JSON body: {exc}"})
            return None
        if not isinstance(payload, dict):
            self._json(400, {"ok": False, "detail": "Expected a JSON object."})
            return None
        return payload

    def _begin_stream(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", NDJSON_TYPE)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

    def _send_event(self, event: dict) -> None:
        line = json.dumps(event, ensure_ascii=False,
                          separators=(",", ":")).encode("utf-8") + b"\n"
        self.wfile.write(b"%x\r\n" % len(line))
        self.wfile.write(line)
        self.wfile.write(b"\r\n")
        self.wfile.flush()

    def _end_stream(self) -> None:
        try:
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except OSError:
            self.close_connection = True

    def _no_content(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _fail_safely(self, exc: Exception) -> None:
        try:
            self._json(500, {"ok": False,
                             "detail": f"Internal error: {type(exc).__name__}: {exc}"})
        except Exception:
            # Headers already went out (mid-stream) or the socket is gone; there
            # is nothing left that this server can say.
            self.close_connection = True

    # -- routing ------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802 - name fixed by BaseHTTPRequestHandler
        try:
            path = urlsplit(self.path).path
            if path in ("/", "/index.html"):
                self._serve_index()
            elif path == "/api/health":
                self._json(200, self.server.assistant.health())
            elif path == "/api/actions":
                try:
                    items = actions.list_actions()
                except Exception as exc:
                    self._json(500, {"ok": False,
                                     "detail": f"Could not list actions: {exc}"})
                    return
                self._json(200, {"actions": items if isinstance(items, list) else []})
            elif path == "/api/journal":
                try:
                    report = _journal.journal().summary()
                except Exception as exc:
                    self._json(500, {"ok": False,
                                     "detail": f"Could not read the journal: {exc}"})
                    return
                self._json(200, {"journal": report})
            elif path == "/favicon.ico":
                self._no_content()
            else:
                self._json(404, {"ok": False, "detail": f"No such path: {path}"})
        except Exception as exc:
            self._fail_safely(exc)

    def do_POST(self) -> None:  # noqa: N802 - name fixed by BaseHTTPRequestHandler
        try:
            path = urlsplit(self.path).path
            if path == "/api/chat":
                self._chat()
            elif path == "/api/confirm":
                self._confirm()
            elif path == "/api/transcribe":
                self._transcribe()
            elif path == "/api/speak":
                self._speak()
            elif path == "/api/work":
                self._work()
            else:
                self._json(404, {"ok": False, "detail": f"No such path: {path}"})
        except Exception as exc:
            self._fail_safely(exc)

    # -- endpoints ----------------------------------------------------------

    def _serve_index(self) -> None:
        index = getattr(self.server, "web_index", None)
        if index is None or not Path(index).is_file():
            self._json(500, {"ok": False, "detail": (
                "The assistant page is missing from this installation; "
                "reinstall the astraos-ai package.")})
            return
        body = Path(index).read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _chat(self) -> None:
        payload = self._read_json(MAX_CHAT_BYTES)
        if payload is None:
            return
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            self._json(400, {"ok": False, "detail": 'Expected a non-empty "text" string.'})
            return
        history = normalize_history(payload.get("history"))
        self._begin_stream()
        try:
            for event in self.server.assistant.chat(text.strip(), history):
                self._send_event(event)
        except (BrokenPipeError, ConnectionResetError):
            # The page went away mid-reply. Nothing to report to anyone.
            self.close_connection = True
            return
        except Exception as exc:
            try:
                self._send_event({"type": "error",
                                  "text": f"Internal error: {type(exc).__name__}: {exc}"})
                self._send_event({"type": "done"})
            except OSError:
                self.close_connection = True
        finally:
            self._end_stream()

    def _work(self) -> None:
        """One request through the ladder, with every step visible.

        The stream carries the plan and each step's evidence rather than only the
        model's prose, which is the whole difference between an assistant and a
        chat box: what it decided to do, and what happened when it did.

        Confirmation happens the way it already does - in the page, through
        /api/confirm - so a phone taps Confirm rather than being asked to type.
        The callback below is only reached by a caller that wired one without a
        human behind it, and it refuses.
        """
        payload = self._read_json(MAX_CHAT_BYTES)
        if payload is None:
            return
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            self._json(400, {"ok": False,
                             "detail": 'Expected a non-empty "text" string.'})
            return

        pool = tiers.TierPool(self.server.assistant.settings)
        agent = _worker.Worker(pool, confirm=self._confirm_action)

        self._begin_stream()
        try:
            for event in agent.events_for(text.strip()):
                self._send_event(event)
        except (BrokenPipeError, ConnectionResetError):
            # The page went away mid-task. Nothing to report to anyone.
            self.close_connection = True
            return
        except Exception as exc:  # noqa: BLE001 - the page must not die here
            try:
                self._send_event({"type": "error",
                                  "text": f"{type(exc).__name__}: {exc}"})
                self._send_event({"type": "done"})
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True

    def _confirm_action(self, action: str, args: dict) -> bool:
        """Refuse, and say why. The page's Confirm is not this callback.

        The page asks the human and posts their answer back to /api/confirm;
        this path is reached only by a caller that wired a callback without a
        human behind it. Refusing is the only safe default, and the event says
        so in the words the journal uses for the same question.
        """
        self._send_event({"type": "needs",
                          "text": _worker.question_for(action, args)})
        return False

    def _confirm(self) -> None:
        payload = self._read_json(MAX_CHAT_BYTES)
        if payload is None:
            return
        plan = payload.get("plan")
        if not isinstance(plan, dict):
            self._json(400, {"ok": False, "detail": 'Expected a "plan" object.'})
            return
        refusal = plan_refusal(plan)
        if refusal is not None:
            # Refused before execute() is reached. The status is 400 because the
            # page sent something that is not a permitted plan, and the detail
            # says exactly what was checked.
            self._json(400, {"ok": False, "detail": refusal})
            return
        self._json(200, self.server.assistant.confirm(plan))

    def _transcribe(self) -> None:
        data, error = self._body_bytes(MAX_AUDIO_BYTES)
        if error is not None:
            self._json(error[0], {"ok": False, "detail": error[1]})
            return
        status, payload = self.server.assistant.transcribe(data or b"")
        self._json(status, payload)

    def _speak(self) -> None:
        payload = self._read_json(MAX_CHAT_BYTES)
        if payload is None:
            return
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            self._json(400, {"ok": False, "detail": 'Expected a non-empty "text" string.'})
            return
        status, body = self.server.assistant.speak(text.strip())
        self._json(status, body)


class AIServer(ThreadingHTTPServer):
    """ThreadingHTTPServer plus the shared Assistant and the page path."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], assistant: Assistant,
                 web_index: Path | None, verbose: bool = False) -> None:
        super().__init__(address, RequestHandler)
        self.assistant = assistant
        self.web_index = web_index
        self.verbose = verbose


def local_ip() -> str | None:
    """This machine's address on the local network, or None.

    A UDP connect() sends nothing; it only asks the kernel which local address
    would be used for an outside route. The target is TEST-NET-3, which is never
    reachable, and the socket is closed immediately.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("203.0.113.1", 9))
        return sock.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return None
    finally:
        sock.close()


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="astra ai",
        description="AstraOS local assistant server (no account, no cloud).",
    )
    parser.add_argument("--lan", action="store_true",
                        help="bind 0.0.0.0 so a phone on the same network can use "
                             "the page as a microphone; there is no authentication")
    parser.add_argument("--host", default=None,
                        help=f"bind address (default {DEFAULT_HOST}, or 0.0.0.0 with --lan)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"TCP port (default {DEFAULT_PORT})")
    parser.add_argument("--verbose", action="store_true",
                        help="log every request to stderr")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    host = args.host or (LAN_HOST if args.lan else DEFAULT_HOST)

    try:
        assistant = Assistant()
    except Exception as exc:
        print(f"astra ai: cannot start: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    try:
        server = AIServer((host, args.port), assistant, locate_web_index(),
                          verbose=args.verbose)
    except OSError as exc:
        print(f"astra ai: cannot bind {host}:{args.port}: {exc}", file=sys.stderr)
        return 1

    print(f"AstraOS assistant listening on http://127.0.0.1:{args.port}/", flush=True)
    if args.lan:
        print(LAN_WARNING, flush=True)
        address = local_ip()
        if address:
            print(f"phone or another computer on the network: http://{address}:{args.port}/",
                  flush=True)
        else:
            print(f"phone or another computer: http://<this machine's address>:{args.port}/",
                  flush=True)
    if not assistant.ready():
        print(f"note: {SETUP_HINT}", flush=True)

    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nastra ai: stopping", flush=True)
    finally:
        server.server_close()
        try:
            if assistant.engine is not None:
                assistant.engine.stop()
        except Exception:
            # Stopping a tool that never started is not an error worth a line.
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
