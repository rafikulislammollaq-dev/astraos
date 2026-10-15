"""Static tests for the AstraOS AI assistant server and its page.

The points these tests pin down, and why each one has a test rather than a
comment:

  * Event framing. The page parses newline-delimited JSON from a chunked
    response, so "one JSON object per line, ending in done" is a contract
    between two files that are written separately. A stray print() in the
    server, or an event that is not JSON, breaks the page silently.

  * The not-ready path. The server must start with no model installed, serve
    the page, report ready=false, and answer a chat with a single explainable
    error event instead of a traceback or a hang. That is the state every fresh
    install is in.

  * The confirmation gate. /api/confirm must refuse any plan whose action is
    not in actions.ACTIONS, before execute() is called. This is the whitelist
    the whole safety model rests on, and it is the one check that must hold
    even when the client is edited by hand.

  * The page makes no external requests. "No tracking, no external fonts, no
    network calls other than the local API" is a product promise; a single
    copied font link would break it invisibly, so it is asserted by scanning
    the file.

The sibling package modules (config, llm, prompt, actions, voice) belong to the
package and are stubbed here on purpose: these tests must run with no model, no
llama.cpp binary, no whisper and no network, on any host, and they must not
depend on the internals of the modules they stand in for. The HTTP server
itself is real, on 127.0.0.1 and an ephemeral port, because that is the thing
under test.
"""

from __future__ import annotations

import http.client
import importlib.util
import inspect
import contextlib
import functools
import json
import re
import sys
import tempfile
import threading
import types
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = REPO_ROOT / "packages" / "astraos-ai"
SERVER_PY = PACKAGE / "root" / "usr" / "lib" / "astraos" / "ai" / "server.py"
INDEX_HTML = PACKAGE / "root" / "usr" / "share" / "astraos" / "ai" / "web" / "index.html"

DESCRIPTION = "the AI server frames events, refuses unknown plans, and stays local"


# ---------------------------------------------------------------------------
# Stub siblings for astraos.ai.*
#
# They record what the server asked them to do, so a test can assert not just
# the response but the call behind it (execute() was not reached, ask() was
# never called, and so on).
# ---------------------------------------------------------------------------


class _StubEngine:
    instances: list["_StubEngine"] = []

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self.available_flag = True
        self.chunks = ["Hello ", "world."]
        self.error_after: int | None = None
        self.started = False
        self.stopped = False
        self.asked: list[list[dict]] = []
        _StubEngine.instances.append(self)

    def available(self) -> bool:
        return self.available_flag

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def ask(self, messages, stream=True):
        self.asked.append(messages)
        for index, chunk in enumerate(self.chunks):
            if self.error_after is not None and index == self.error_after:
                raise RuntimeError("engine exploded")
            yield chunk

    def health(self) -> dict:
        return {"available": self.available_flag}


class _StubAction:
    def __init__(self, name: str, summary: str, dangerous: bool = False) -> None:
        self.name = name
        self.summary = summary
        self.args: dict = {}
        self.dangerous = dangerous
        self.needs_confirm = dangerous
        self.func = None


def _make_stubs() -> dict[str, types.ModuleType]:
    scratch = Path(tempfile.gettempdir()) / "astraos-ai-test"

    config = types.ModuleType("astraos.ai.config")
    config.PATHS = types.SimpleNamespace(
        share_dir=INDEX_HTML.parent.parent,
        models_dir=scratch / "models",
        bin_dir=scratch / "bin",
        config_file=scratch / "settings.json",
    )
    config.load_settings = lambda: {}
    config.save_settings = lambda settings: None
    config.LAN_DEFAULT = False

    llm = types.ModuleType("astraos.ai.llm")
    llm.Engine = _StubEngine

    prompt = types.ModuleType("astraos.ai.prompt")
    prompt.SYSTEM_PROMPT = "stub system prompt"
    prompt.built: list[tuple[str, list[dict]]] = []

    def build_messages(user_text, history):
        prompt.built.append((user_text, list(history)))
        return ([{"role": "system", "content": prompt.SYSTEM_PROMPT}]
                + list(history)
                + [{"role": "user", "content": user_text}])

    prompt.build_messages = build_messages

    actions = types.ModuleType("astraos.ai.actions")
    actions.ACTIONS = {
        "open_app": _StubAction("open_app", "Open an application"),
        "mix_volume": _StubAction("mix_volume", "Change the volume"),
        "delete_file": _StubAction("delete_file", "Delete a file", dangerous=True),
    }
    actions.plan: dict | None = None
    actions.executed: list[dict] = []

    def parse_plan(text):
        return actions.plan

    def execute(plan, confirmed=False):
        actions.executed.append({"plan": plan, "confirmed": confirmed})
        return {"ok": True, "detail": "stub executed " + str(plan.get("action", "?"))}

    actions.parse_plan = parse_plan
    actions.execute = execute
    actions.list_actions = lambda: [
        {"name": action.name, "summary": action.summary,
         "dangerous": action.dangerous, "needs_confirm": action.needs_confirm}
        for action in actions.ACTIONS.values()
    ]
    actions.catalog_for_prompt = lambda: "stub catalogue"

    voice = types.ModuleType("astraos.ai.voice")
    voice.tts_flag = False
    voice.stt_flag = False
    voice.spoken: list[str] = []
    voice.transcribed: list[bytes] = []
    voice.tts_available = lambda: voice.tts_flag
    voice.stt_available = lambda: voice.stt_flag

    def speak(text):
        voice.spoken.append(text)
        return True

    def transcribe(wav_bytes):
        voice.transcribed.append(wav_bytes)
        return "stub transcript"

    voice.speak = speak
    voice.transcribe = transcribe

    ai_pkg = types.ModuleType("astraos.ai")
    ai_pkg.__path__ = []
    ai_pkg.config = config
    ai_pkg.llm = llm
    ai_pkg.prompt = prompt
    ai_pkg.actions = actions
    ai_pkg.voice = voice

    root_pkg = types.ModuleType("astraos")
    root_pkg.__path__ = []
    root_pkg.ai = ai_pkg

    return {
        "astraos": root_pkg,
        "astraos.ai": ai_pkg,
        "astraos.ai.config": config,
        "astraos.ai.llm": llm,
        "astraos.ai.prompt": prompt,
        "astraos.ai.actions": actions,
        "astraos.ai.voice": voice,
    }


_MISSING = object()
_LOADED: dict[str, Any] = {}


def _load_server() -> tuple[types.ModuleType, dict[str, types.ModuleType]]:
    """Import server.py once, against the stubs, without touching sys.modules for good."""
    if "module" in _LOADED:
        return _LOADED["module"], _LOADED["stubs"]

    assert SERVER_PY.is_file(), f"the server is missing: {SERVER_PY}"
    assert INDEX_HTML.is_file(), f"the page is missing: {INDEX_HTML}"

    stubs = _make_stubs()
    saved: dict[str, Any] = {}
    for name, module in stubs.items():
        saved[name] = sys.modules.get(name, _MISSING)
        sys.modules[name] = module
    try:
        spec = importlib.util.spec_from_file_location("astraos_ai_server_under_test", SERVER_PY)
        assert spec is not None and spec.loader is not None, f"cannot load {SERVER_PY}"
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for name, previous in saved.items():
            if previous is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous

    _LOADED["module"] = module
    _LOADED["stubs"] = stubs
    return module, stubs


def _reset_stubs(stubs: dict[str, types.ModuleType]) -> None:
    _StubEngine.instances.clear()
    actions = stubs["astraos.ai.actions"]
    actions.plan = None
    actions.executed.clear()
    stubs["astraos.ai.prompt"].built.clear()
    voice = stubs["astraos.ai.voice"]
    voice.tts_flag = False
    voice.stt_flag = False
    voice.spoken.clear()
    voice.transcribed.clear()


class _Running:
    """A real HTTP server on loopback, plus the two calls a test needs."""

    def __init__(self, module, stubs, assistant, engine, httpd):
        self.module = module
        self.stubs = stubs
        self.assistant = assistant
        self.engine: _StubEngine = engine
        self.actions = stubs["astraos.ai.actions"]
        self.prompt = stubs["astraos.ai.prompt"]
        self.voice = stubs["astraos.ai.voice"]
        self._httpd = httpd
        self.port = httpd.server_address[1]

    def request(self, method: str, path: str, body: bytes | None = None,
                headers: dict | None = None) -> tuple[int, str, bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return (response.status,
                    response.getheader("Content-Type") or "",
                    response.read())
        finally:
            connection.close()

    def get_json(self, path: str) -> tuple[int, dict]:
        status, _content_type, body = self.request("GET", path)
        return status, json.loads(body.decode("utf-8"))

    def post_json(self, path: str, payload: dict) -> tuple[int, dict]:
        body = json.dumps(payload).encode("utf-8")
        status, _content_type, raw = self.request(
            "POST", path, body=body, headers={"Content-Type": "application/json"})
        return status, json.loads(raw.decode("utf-8"))

    def post_raw(self, path: str, payload: bytes, content_type: str) -> tuple[int, str, bytes]:
        return self.request("POST", path, body=payload,
                            headers={"Content-Type": content_type})

    def chat(self, text: str, history: list | None = None) -> list[dict]:
        body = json.dumps({"text": text, "history": history or []}).encode("utf-8")
        status, content_type, raw = self.request(
            "POST", "/api/chat", body=body,
            headers={"Content-Type": "application/json"})
        assert status == 200, f"chat answered {status}: {raw!r}"
        assert "application/x-ndjson" in content_type, (
            f"chat must be an ndjson stream, not {content_type!r}")
        events = []
        for line in raw.decode("utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
        return events


@contextlib.contextmanager
def running_app():
    """A live server on a loopback port, torn down however the test ends."""
    module, stubs = _load_server()
    _reset_stubs(stubs)
    assistant = module.Assistant()
    engine = _StubEngine.instances[-1]
    httpd = module.AIServer(("127.0.0.1", 0), assistant, module.locate_web_index())
    thread = threading.Thread(target=httpd.serve_forever,
                              kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield _Running(module, stubs, assistant, engine, httpd)
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def needs_a_server(func):
    """Run a test with a live server.

    tests/run.py calls every test_* function with no arguments and pytest is not
    installed on the CI machine, so a test that needs a server asks for one here
    rather than through a fixture. One line per test, and the test body keeps the
    plain `app` argument it reads well with.

    The wrapper itself takes no arguments, but functools.wraps copies the
    wrapped function's __wrapped__ attribute and pytest inspects through it:
    it would read the signature `(app)` and look for an `app` fixture that does
    not exist. An empty __signature__ stops that, so one definition serves both
    pytest and tests/run.py.
    """
    @functools.wraps(func)
    def run() -> None:
        with running_app() as app:
            func(app)
    run.__signature__ = inspect.Signature()
    return run


# ---------------------------------------------------------------------------
# The not-ready path: this is the state of every fresh install.
# ---------------------------------------------------------------------------


@needs_a_server
def test_health_reports_not_ready_and_the_page_explains_setup(app) -> None:
    app.engine.available_flag = False

    status, health = app.get_json("/api/health")
    assert status == 200
    assert health["ready"] is False
    assert "astra ai setup" in health["setup_hint"]
    assert health["voice"] == {"tts": False, "stt": False}

    status, content_type, body = app.request("GET", "/")
    assert status == 200
    assert "text/html" in content_type
    text = body.decode("utf-8")
    assert "astra ai setup" in text, (
        "the page served without a model must still explain how to finish setup")


@needs_a_server
def test_chat_without_a_model_is_one_error_event_then_done(app) -> None:
    app.engine.available_flag = False
    events = app.chat("hello")
    assert [event["type"] for event in events] == ["error", "done"], (
        "the not-ready path must be a normal stream, so the page has one code path")
    assert "astra ai setup" in events[0]["text"]
    assert app.engine.asked == [], "the engine must not be asked with no model installed"


@needs_a_server
def test_health_survives_a_probing_engine_that_raises(app) -> None:
    class ExplodingEngine(_StubEngine):
        def available(self):
            raise OSError("no binary")

        def health(self):
            raise OSError("no binary")

    app.assistant.engine = ExplodingEngine(app.assistant.settings)
    status, health = app.get_json("/api/health")
    assert status == 200
    assert health["ready"] is False
    assert "engine_error" in health


# ---------------------------------------------------------------------------
# Event framing: one JSON object per line, in order, ending in done.
# ---------------------------------------------------------------------------


@needs_a_server
def test_chat_streams_delta_events_in_order(app) -> None:
    app.engine.chunks = ["Hello ", "world."]
    events = app.chat("hi", history=[{"role": "user", "content": "earlier"}])
    assert [event["type"] for event in events] == ["delta", "delta", "done"]
    assert events[0]["text"] == "Hello "
    assert events[1]["text"] == "world."
    assert app.prompt.built[-1][0] == "hi"
    assert app.prompt.built[-1][1] == [{"role": "user", "content": "earlier"}]


@needs_a_server
def test_chat_emits_a_plan_event_with_the_catalogue(app) -> None:
    app.engine.chunks = ["I can do that."]
    plan = {"action": "open_app", "args": {"app": "firefox"}}
    app.actions.plan = plan

    events = app.chat("open firefox")
    assert [event["type"] for event in events] == ["delta", "plan", "done"]
    plan_event = events[1]
    assert plan_event["plan"] == plan, "the plan must survive the JSON round trip intact"
    names = [entry["name"] for entry in plan_event["catalog"]]
    assert "open_app" in names


@needs_a_server
def test_chat_reports_an_engine_failure_as_an_error_event(app) -> None:
    app.engine.chunks = ["partial ", "never sent"]
    app.engine.error_after = 1
    events = app.chat("hello")
    assert [event["type"] for event in events] == ["delta", "error", "done"]
    assert events[0]["text"] == "partial "
    assert "engine exploded" in events[1]["text"]


@needs_a_server
def test_history_from_the_page_is_filtered_before_the_model_sees_it(app) -> None:
    junk = [
        {"role": "robot", "content": "not a role"},
        {"role": "user", "content": "kept"},
        {"role": "user", "content": 5},
        {"role": "assistant", "content": "kept too"},
        "not a dict",
        42,
    ]
    app.chat("hi", history=junk)
    assert app.prompt.built[-1][1] == [
        {"role": "user", "content": "kept"},
        {"role": "assistant", "content": "kept too"},
    ]


# ---------------------------------------------------------------------------
# The confirmation gate: the whitelist that the safety model rests on.
# ---------------------------------------------------------------------------


@needs_a_server
def test_confirm_refuses_a_plan_outside_the_repertoire(app) -> None:
    status, payload = app.post_json(
        "/api/confirm", {"plan": {"action": "format_disk", "args": {}}})
    assert status == 400, "a plan that is not in ACTIONS must be refused, not executed"
    assert payload["ok"] is False
    assert "format_disk" in payload["detail"]
    assert app.actions.executed == [], "execute() must not be reached for an unknown action"


@needs_a_server
def test_confirm_refuses_a_plan_that_names_no_action(app) -> None:
    for plan in ({"args": {"x": 1}}, {}, "open_app", ["open_app"]):
        status, payload = app.post_json("/api/confirm", {"plan": plan})
        assert status == 400, f"plan {plan!r} must be refused"
        assert payload["ok"] is False
    assert app.actions.executed == []


@needs_a_server
def test_confirm_executes_a_known_plan_with_confirmed_true(app) -> None:
    plan = {"action": "open_app", "args": {"app": "firefox"}}
    status, payload = app.post_json("/api/confirm", {"plan": plan})
    assert status == 200
    assert payload["ok"] is True
    assert app.actions.executed == [{"plan": plan, "confirmed": True}], (
        "the server must execute the exact plan with confirmed=True, and only after "
        "the client asked /api/confirm")


@needs_a_server
def test_confirm_reads_the_name_from_the_usual_keys(app) -> None:
    for plan in ({"name": "mix_volume"}, {"tool": "mix_volume"}, {"id": "mix_volume"}):
        status, payload = app.post_json("/api/confirm", {"plan": plan})
        assert status == 200 and payload["ok"] is True, f"{plan!r} was refused"
    assert len(app.actions.executed) == 3


@needs_a_server
def test_plan_helpers_pin_the_gate(app) -> None:
    module = app.module
    assert module.plan_action_name({"action": "open_app"}) == "open_app"
    assert module.plan_action_name({"name": "mix_volume"}) == "mix_volume"
    # No recognised key, but a value that is a real action: found anyway.
    assert module.plan_action_name({"tool": {"x": 1}, "target": "mix_volume"}) == "mix_volume"
    assert module.plan_action_name({"args": {"x": 1}}) is None
    assert module.plan_action_name("open_app") is None
    assert module.plan_refusal({"action": "open_app"}) is None
    assert module.plan_refusal({"action": "rm_rf_slash"}) is not None


# ---------------------------------------------------------------------------
# Voice endpoints.
# ---------------------------------------------------------------------------


@needs_a_server
def test_transcribe_is_503_without_whisper_and_posts_bytes_with_it(app) -> None:
    wav = b"RIFF\x24\x00\x00\x00WAVEfmt "
    status, content_type, raw = app.post_raw("/api/transcribe", wav, "audio/wav")
    assert status == 503
    payload = json.loads(raw.decode("utf-8"))
    assert payload["ok"] is False
    assert "astra ai setup" in payload["detail"]

    app.voice.stt_flag = True
    status, content_type, raw = app.post_raw("/api/transcribe", wav, "audio/wav")
    assert status == 200
    assert json.loads(raw.decode("utf-8")) == {"text": "stub transcript"}
    assert app.voice.transcribed == [wav], "the raw WAV bytes must be handed over unchanged"


@needs_a_server
def test_speak_is_503_without_tts_and_speaks_with_it(app) -> None:
    status, payload = app.post_json("/api/speak", {"text": "hello there"})
    assert status == 503
    assert payload["ok"] is False

    app.voice.tts_flag = True
    status, payload = app.post_json("/api/speak", {"text": "hello there"})
    assert status == 200 and payload["ok"] is True
    assert app.voice.spoken == ["hello there"]


# ---------------------------------------------------------------------------
# Request parsing and routing.
# ---------------------------------------------------------------------------


@needs_a_server
def test_bad_requests_get_json_errors(app) -> None:
    status, _content_type, raw = app.post_raw("/api/chat", b"{not json", "application/json")
    assert status == 400
    assert json.loads(raw.decode("utf-8"))["ok"] is False

    status, payload = app.post_json("/api/chat", {"history": []})
    assert status == 400, "a chat without text must be refused"

    status, payload = app.get_json("/api/nope")
    assert status == 404
    assert payload["ok"] is False


@needs_a_server
def test_actions_endpoint_lists_the_repertoire(app) -> None:
    status, payload = app.get_json("/api/actions")
    assert status == 200
    names = [entry["name"] for entry in payload["actions"]]
    assert names == ["open_app", "mix_volume", "delete_file"]


# ---------------------------------------------------------------------------
# The page itself.
# ---------------------------------------------------------------------------


def test_index_html_makes_no_external_requests() -> None:
    assert INDEX_HTML.is_file(), f"the page is missing: {INDEX_HTML}"
    text = INDEX_HTML.read_text(encoding="utf-8")
    lowered = text.lower()

    assert "http://" not in lowered, "the page must contain no external address"
    assert "https://" not in lowered, "the page must contain no external address"
    assert "@import" not in lowered, "CSS must not import anything, not even a font"
    assert "<link" not in lowered, "the page must load no external resource"
    assert "<script src" not in lowered, "the script must be inline"

    targets = re.findall(r"""fetch\(\s*["']([^"']+)["']""", text)
    assert targets, "the page is expected to call its own API"
    for target in targets:
        assert target.startswith("/api/"), (
            f"the page calls {target!r}; every request must stay on the local server")


def test_index_html_is_the_finished_product_shape() -> None:
    text = INDEX_HTML.read_text(encoding="utf-8")
    for needle, why in (
        ('id="orb"', "the state ring"),
        ('id="state-caption"', "the idle/listening/thinking/speaking caption"),
        ('id="transcript"', "the scrolling transcript"),
        ('id="mic-btn"', "the microphone button"),
        ('id="send-btn"', "the send button"),
        ('id="speak-seg"', "the voice-output toggle"),
        ('id="setup-banner"', "the astra ai setup explanation"),
        ("MediaRecorder", "recorded-audio fallback"),
        ("speechSynthesis", "speaking replies in the browser"),
        ("SpeechRecognition", "browser speech recognition"),
        ("/api/confirm", "the confirmation request"),
        ("/api/transcribe", "the whisper upload"),
        ("/api/speak", "speaking through the PC"),
        ("astra ai setup", "the setup instruction"),
    ):
        assert needle in text, f"the page is missing {needle!r} ({why})"


@needs_a_server
def test_server_refuses_to_say_it_is_ready_without_the_engine(app) -> None:
    # Belt and braces for the not-ready path: an engine object that failed to
    # construct must not stop the server from answering.
    app.assistant.engine = None
    app.assistant.engine_error = "ImportError: no engine"
    status, health = app.get_json("/api/health")
    assert status == 200 and health["ready"] is False
    events = app.chat("hello")
    assert events[0]["type"] == "error"
    assert "no engine" in events[0]["text"]
