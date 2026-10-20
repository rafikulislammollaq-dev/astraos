"""The model server can be confined, and the cage is honest about its edges.

`docs/ROADMAP.md`, Stage 3 asks for sandboxing, with llama-server as the first
target: no writes outside the model folder, and a truthful answer when no
sandbox can run. This file proves the command that would be run:

  * with no sandbox binary, the engine's own argv is returned unchanged and the
    info dictionary says `sandboxed: False` - no silent claim of confinement;
  * bubblewrap gets a read-only root, a read-only model directory, private /tmp
    and /dev/shm, and the engine's own argv after `--`;
  * the host network stays shared because the assistant reaches the server over
    127.0.0.1. A private network namespace has its own loopback, so asking for
    one here would produce a server that cannot answer; `confine_llama_server`
    refuses that combination rather than shipping it;
  * `probe()` separates "installed" from "can actually start", which is what a
    kernel without unprivileged user namespaces looks like.

The binary is faked by replacing `sandbox.tool`; nothing here executes bwrap,
so the tests mean the same on a host that has it and one that does not.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_LIB = REPO_ROOT / "packages" / "astraos-ai" / "root" / "usr" / "lib"
if str(AI_LIB) not in sys.path:
    sys.path.insert(0, str(AI_LIB))

from astraos.ai import llm  # noqa: E402
from astraos.ai import sandbox  # noqa: E402

DESCRIPTION = (
    "The model server's sandbox is read-only, keeps the loopback its client needs, "
    "and says when it cannot start"
)

BWRAP = "/usr/bin/bwrap"
FIREJAIL = "/usr/bin/firejail"


class _Tool:
    """Replace sandbox.tool for one test, and restore it however the test ends."""

    def __init__(self, path: str | None):
        self.path = path
        self.previous = sandbox.tool

    def __enter__(self):
        sandbox.tool = lambda: self.path
        return self

    def __exit__(self, *_exc):
        sandbox.tool = self.previous


class _Done:
    def __init__(self, returncode: int, stderr: bytes = b""):
        self.returncode = returncode
        self.stderr = stderr


def test_without_a_tool_argv_is_unchanged_and_info_is_honest() -> None:
    with _Tool(None):
        wrapped, info = sandbox.sandbox_command(["llama-server", "-m", "m.gguf"])

    assert wrapped == ["llama-server", "-m", "m.gguf"]
    assert info["sandboxed"] is False
    assert "no sandbox binary" in info["reason"]
    assert sandbox.available() is False
    assert sandbox.probe()["ok"] is False


def test_bubblewrap_gets_a_read_only_root_and_a_read_only_model() -> None:
    with _Tool(BWRAP):
        wrapped, info = sandbox.confine_llama_server(
            ["llama-server", "-m", "/models/m.gguf"], model_dir="/models"
        )

    assert info["sandboxed"] is True
    assert info["flavour"] == "bwrap"
    assert wrapped[0] == BWRAP
    root = wrapped.index("--ro-bind")
    assert wrapped[root + 1:root + 3] == ["/", "/"], "the whole root must be read-only"
    model = wrapped.index("/models")
    assert wrapped[model - 1] == "--ro-bind", "the model directory must be read-only"
    assert "--tmpfs" in wrapped and "/tmp" in wrapped
    assert "/dev/shm" in wrapped
    assert "--proc" in wrapped and "/proc" in wrapped
    assert "--dev" in wrapped and "/dev" in wrapped
    assert "--die-with-parent" in wrapped
    assert "--new-session" in wrapped
    assert wrapped[wrapped.index("--") + 1:] == ["llama-server", "-m", "/models/m.gguf"]


def test_the_server_keeps_the_loopback_its_client_reaches() -> None:
    with _Tool(BWRAP):
        wrapped, info = sandbox.confine_llama_server(["llama-server"], model_dir="/models")

    assert "--unshare-net" not in wrapped, (
        "a private loopback cannot be reached by the parent that asked the question"
    )
    assert info["network_shared"] is True
    assert info["network_isolated"] is False


def test_a_network_namespace_is_built_only_when_a_caller_asks_for_one() -> None:
    with _Tool(BWRAP):
        wrapped, info = sandbox.sandbox_command(["tool"], network=False)

    assert "--unshare-net" in wrapped
    assert info["network_isolated"] is True
    assert info["network_shared"] is False


def test_confine_llama_server_refuses_a_cage_it_cannot_talk_through() -> None:
    with _Tool(BWRAP):
        try:
            sandbox.confine_llama_server(["llama-server"], model_dir="/models", network=False)
        except ValueError as exc:
            assert "127.0.0.1" in str(exc)
        else:
            raise AssertionError("a network namespace would make the server unreachable")


def test_firejail_is_supported_and_names_the_read_only_paths() -> None:
    with _Tool(FIREJAIL):
        wrapped, info = sandbox.confine_llama_server(["llama-server"], model_dir="/models")

    assert info["flavour"] == "firejail"
    assert wrapped[0] == FIREJAIL
    assert "--read-only=/models" in wrapped
    assert wrapped[wrapped.index("--") + 1:] == ["llama-server"]


def test_probe_reports_a_sandbox_that_cannot_start() -> None:
    original = sandbox.subprocess.run
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        calls.append(argv)
        return _Done(1, b"bwrap: setting up uid map: Permission denied\n")

    try:
        sandbox.subprocess.run = fake_run
        with _Tool(BWRAP):
            result = sandbox.probe()
    finally:
        sandbox.subprocess.run = original

    assert result["ok"] is False
    assert "Permission denied" in result["reason"]
    assert calls and calls[0][0] == BWRAP
    assert "/bin/true" in calls[0]


def test_probe_passes_when_the_sandbox_runs() -> None:
    original = sandbox.subprocess.run

    def fake_run(argv, **_kwargs):
        return _Done(0)

    try:
        sandbox.subprocess.run = fake_run
        with _Tool(BWRAP):
            result = sandbox.probe()
    finally:
        sandbox.subprocess.run = original

    assert result == {"ok": True, "tool": BWRAP, "reason": ""}


def test_is_sandboxed_reads_the_command_not_a_flag() -> None:
    assert sandbox.is_sandboxed([BWRAP, "--", "x"]) is True
    assert sandbox.is_sandboxed([FIREJAIL, "--", "x"]) is True
    assert sandbox.is_sandboxed(["/usr/bin/llama-server", "-m", "m"]) is False
    assert sandbox.is_sandboxed([]) is False


def _engine(sandbox_mode: str) -> llm.Engine:
    engine = llm.Engine({"sandbox": sandbox_mode})
    engine.model = lambda: Path("/models/m.gguf")  # type: ignore[method-assign]
    return engine


def test_the_engine_uses_a_working_sandbox_in_auto_mode() -> None:
    original = sandbox.probe
    sandbox.probe = lambda: {"ok": True, "tool": BWRAP, "reason": ""}
    try:
        with _Tool(BWRAP):
            argv, info = _engine("auto")._sandbox_argv(["llama-server", "-m", "m"])
    finally:
        sandbox.probe = original

    assert argv[0] == BWRAP
    assert info["sandboxed"] is True
    assert any(part == "models" or part.endswith("models") for part in argv), (
        f"the model directory was not bind-mounted: {argv}"
    )
    assert argv[argv.index("--") + 1:] == ["llama-server", "-m", "m"]


def test_the_engine_falls_back_and_says_why_when_no_sandbox_exists() -> None:
    with _Tool(None):
        argv, info = _engine("auto")._sandbox_argv(["llama-server", "-m", "m"])

    assert argv == ["llama-server", "-m", "m"]
    assert info["sandboxed"] is False
    assert "no bubblewrap" in info["reason"]


def test_the_engine_refuses_to_start_when_a_sandbox_is_required() -> None:
    with _Tool(None):
        try:
            _engine("on")._sandbox_argv(["llama-server", "-m", "m"])
        except llm.EngineUnavailable as exc:
            assert "a sandbox was required" in str(exc)
        else:
            raise AssertionError("sandbox=on started without a sandbox")


def test_the_engine_can_be_told_to_run_without_a_sandbox() -> None:
    with _Tool(BWRAP):
        argv, info = _engine("off")._sandbox_argv(["llama-server", "-m", "m"])

    assert argv == ["llama-server", "-m", "m"]
    assert info == {"sandboxed": False, "reason": "disabled in settings"}
