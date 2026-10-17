"""The QEMU guest agent client, exercised against a faithful fake agent.

scripts/qga-ping.py is the host half of the boot test's guest-agent exercise: it talks
the qemu-ga protocol (guest-sync-delimited, guest-ping, guest-info) over the virtio
serial socket scripts/smoke-boot.sh attaches to the guest. The real agent only runs
inside a booted guest, so the dialogue is pinned here against a fake agent that speaks
the documented framing - line-framed JSON, messages 0xFF-prefixed in delimited mode -
plus noise a client must skip. The client is what decides whether a booted image's
agent answered, so these tests exist so that a client defect cannot be discovered as a
mysteriously failed ISO run, and cannot pass silently against nothing.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from astraos_testlib import SkipTest  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
CLIENT = REPO_ROOT / "scripts" / "qga-ping.py"

DESCRIPTION = "the QEMU guest agent client speaks the protocol the boot test depends on"


class _FakeAgent:
    """A fake qemu-ga bound to a unix socket in a private temporary directory."""

    def __init__(self, handler) -> None:
        if not hasattr(socket, "AF_UNIX"):
            raise SkipTest("this Python has no AF_UNIX sockets; the client needs a unix socket")
        self._tmp = tempfile.TemporaryDirectory(prefix="astraos-qga-")
        self.dir = Path(self._tmp.name)
        self.sock_path = self.dir / "qga.sock"
        self.log_path = self.dir / "qga-host.log"
        self._handler = handler
        self._ready = threading.Event()
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self._server.bind(str(self.sock_path))
        except OSError as exc:
            self._tmp.cleanup()
            raise SkipTest(f"cannot bind a unix socket on this host: {exc}") from exc
        self._server.listen(1)
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=10):
            raise AssertionError("the fake agent never came up")

    def _serve(self) -> None:
        self._ready.set()
        try:
            conn, _ = self._server.accept()
        except OSError:
            return
        buffer = b""
        try:
            while True:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line.strip():
                        continue
                    self._handler(conn, json.loads(line))
        except (OSError, ValueError):
            pass
        finally:
            conn.close()

    def close(self) -> None:
        self._server.close()
        self._tmp.cleanup()

    def run_client(self, timeout: str = "5") -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(CLIENT), "--timeout", timeout,
             str(self.sock_path), str(self.log_path)],
            capture_output=True,
            text=True,
            timeout=60,
        )

    def transcript(self) -> str:
        return self.log_path.read_text(encoding="utf-8") if self.log_path.is_file() else ""


def test_the_client_gets_through_noise_and_answers() -> None:
    """A real agent's channel is not clean: events and filler are part of the framing.

    The fake agent prefixes every message with 0xFF (delimited mode), emits a
    non-JSON line and an event before the sync echo, and then answers ping and info.
    The client must skip the noise, accept the echo with its own id, and report the
    version - exactly what a PASS is allowed to stand on.
    """

    def handler(conn, request):
        execute = request.get("execute")
        if execute == "guest-sync-delimited":
            # noise first: a stray line and an event, then the echo, all prefixed.
            conn.sendall(b"not json at all\n")
            conn.sendall(b'\xff{"event":"guest-agent-started"}\n')
            reply = {"return": request["arguments"]["id"]}
            conn.sendall(b"\xff" + json.dumps(reply).encode() + b"\n")
        elif execute == "guest-ping":
            conn.sendall(b'\xff{"return":{}}\n')
        elif execute == "guest-info":
            reply = {"return": {"version": "9.9.9-fake"}}
            conn.sendall(b"\xff" + json.dumps(reply).encode() + b"\n")

    agent = _FakeAgent(handler)
    try:
        result = agent.run_client()
    finally:
        transcript = agent.transcript()
        agent.close()

    assert result.returncode == 0, (
        f"the client rejected a faithful agent:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "guest-ping answered" in result.stdout
    assert "guest-sync echoed" in transcript, "the echo is the proof the peer is the agent"
    assert "9.9.9-fake" in transcript, "the agent's version is the evidence the log exists for"


def test_the_client_refuses_a_silent_channel() -> None:
    """A socket that accepts and says nothing is not an agent.

    The guest's service can be "active" while its process is being restarted (the
    package's ExecStart tolerates failure), so the host side must not take the
    connection for an answer. The timeout keeps the failure bounded.
    """

    def handler(conn, request):
        pass  # the silence is the test

    agent = _FakeAgent(handler)
    try:
        started = time.monotonic()
        result = agent.run_client(timeout="2")
        elapsed = time.monotonic() - started
        transcript = agent.transcript()
    finally:
        agent.close()

    assert result.returncode == 1, (
        f"a silent channel must not pass:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert elapsed < 30, "the client must time out, not hang"
    assert "no reply within the timeout" in transcript


def test_the_client_refuses_a_wrong_echo() -> None:
    """Whatever answers must echo the id we sent; anything else is not the agent."""

    def handler(conn, request):
        reply = {"return": 1}  # not the id the client chose
        conn.sendall(b"\xff" + json.dumps(reply).encode() + b"\n")

    agent = _FakeAgent(handler)
    try:
        result = agent.run_client()
    finally:
        agent.close()

    assert result.returncode == 1
    assert "wrong id" in result.stdout


def test_the_message_parser_skips_noise_and_events() -> None:
    """The framing parser, without any real socket - so it runs on every host.

    next_message() is where a 0xFF-prefixed event, a non-JSON line or a line split
    across reads could turn a healthy channel into a false failure; a duck-typed
    socket feeds it the exact bytes a real agent sends, in the ugly shapes a real
    channel arrives in. The AF_UNIX tests above cover the dialogue; this one covers
    the bytes, on platforms (like the maintainer's Windows host) that have no unix
    sockets at all.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location("qga_ping_under_test", CLIENT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class FakeSocket:
        def __init__(self, chunks):
            self.chunks = list(chunks)

        def recv(self, _size):
            if self.chunks:
                return self.chunks.pop(0)
            raise TimeoutError("no more chunks")

        def close(self):
            pass

    chunks = [
        b"not json at all\n",          # channel filler
        b'\xff{"event":"x"}\n',         # an unsolicited event
        b'\xff{"return"',               # a message split across reads...
        b': 7}\n',                      # ...and completed by the next one
    ]
    channel = object.__new__(module.AgentChannel)
    channel.log = lambda _line: None
    channel.buffer = b""
    channel.timeout = 2.0
    channel.sock = FakeSocket(chunks)

    assert channel.next_message() == {"return": 7}

    # An error reply must surface as an error, not be read as a return value.
    channel.buffer = b""
    channel.sock = FakeSocket(
        [b'{"error":{"class":"GenericError","desc":"boom"}}\n']
    )
    try:
        channel.next_message()
    except module.AgentError as exc:
        assert "boom" in str(exc)
    else:
        raise AssertionError("an error reply was accepted as a message")


def test_the_client_reports_a_missing_socket() -> None:
    """With no QEMU socket at all the failure must be reported, not raised."""
    if not hasattr(socket, "AF_UNIX"):
        raise SkipTest("this Python has no AF_UNIX sockets; the client needs a unix socket")
    with tempfile.TemporaryDirectory(prefix="astraos-qga-") as tmp:
        result = subprocess.run(
            [sys.executable, str(CLIENT), "--timeout", "2",
             str(Path(tmp) / "nothing-here.sock"), str(Path(tmp) / "qga-host.log")],
            capture_output=True,
            text=True,
            timeout=60,
        )

    assert result.returncode == 1
    assert "cannot connect" in result.stdout
