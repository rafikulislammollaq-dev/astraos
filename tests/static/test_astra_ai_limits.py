"""The model server's memory cap is a number, and it is applied to the child.

`docs/ROADMAP.md`, Stage 4 asks for a memory cap so a weak model that loops
cannot take the machine with it. The cap is `memory_cap_mb` in the settings and
is applied with `RLIMIT_AS` in the model server child, never to the assistant or
the desktop.

What this file proves:

  * 0 (the default) means no cap, and a cap in the settings is converted to the
    bytes the kernel wants;
  * the environment is honoured when the settings do not name a cap, and a
    malformed value is treated as "no cap" rather than a crash;
  * `preexec(0)` returns None so no `preexec_fn` is passed, and a positive cap
    returns a callable - the shape `llm.Engine.start()` relies on;
  * on a platform with `resource`, the callable really sets `RLIMIT_AS` in the
    child (checked in a child process, so this test can never lower the limit
    of the test runner itself);
  * cgroups are not implemented and the module says so instead of returning a
    success it did not achieve.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_LIB = REPO_ROOT / "packages" / "astraos-ai" / "root" / "usr" / "lib"
if str(AI_LIB) not in sys.path:
    sys.path.insert(0, str(AI_LIB))
sys.path.insert(0, str(REPO_ROOT / "tests" / "lib"))

from astraos.ai import memory  # noqa: E402
from astraos_testlib import SkipTest  # noqa: E402

DESCRIPTION = (
    "The memory cap is parsed from the settings, applied to the model server child, "
    "and absent when it is zero"
)

MIB = 1024 * 1024


def _environ(name: str, value: str | None):
    """Set or remove an environment variable, restoring it afterwards."""

    class _Env:
        def __enter__(self):
            self.previous = os.environ.get(name)
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

        def __exit__(self, *_exc):
            if self.previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = self.previous

    return _Env()


def test_zero_means_no_cap() -> None:
    with _environ("ASTRAOS_MEMORY_CAP_MB", None):
        assert memory.memory_cap_bytes({}) == 0
        assert memory.memory_cap_bytes({"memory_cap_mb": 0}) == 0
        assert memory.preexec(0) is None


def test_a_cap_in_the_settings_becomes_bytes() -> None:
    assert memory.memory_cap_bytes({"memory_cap_mb": 512}) == 512 * MIB
    assert memory.memory_cap_bytes({"memory_cap_mb": "1536"}) == 1536 * MIB
    assert memory.memory_cap_bytes({"memory_cap": 256}) == 256 * MIB
    assert memory.memory_cap_bytes({"memory_limit_mb": 128}) == 128 * MIB


def test_the_environment_is_the_fallback() -> None:
    with _environ("ASTRAOS_MEMORY_CAP_MB", "384"):
        assert memory.memory_cap_bytes({}) == 384 * MIB


def test_a_malformed_cap_is_no_cap_not_a_crash() -> None:
    with _environ("ASTRAOS_MEMORY_CAP_MB", "lots"):
        assert memory.memory_cap_bytes({}) == 0
    assert memory.memory_cap_bytes({"memory_cap_mb": "not a number"}) == 0
    assert memory.memory_cap_bytes({"memory_cap_mb": -5}) == 0


def test_preexec_is_a_callable_only_when_there_is_a_cap() -> None:
    if memory.available():
        assert callable(memory.preexec(64 * MIB))
    else:
        assert memory.preexec(64 * MIB) is None, (
            "a platform without resource must not hand Popen a preexec_fn"
        )
    assert memory.preexec(0) is None


def test_the_cap_reaches_the_child_process() -> None:
    if not memory.available():
        raise SkipTest("this platform has no resource.setrlimit (Windows dev host)")

    probe = (
        "import resource;"
        "print(resource.getrlimit(resource.RLIMIT_AS)[0])"
    )
    limit = 256 * MIB
    done = subprocess.run(
        [sys.executable, "-c", probe],
        preexec_fn=memory.preexec(limit),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    assert int(done.stdout.decode().strip()) == limit


def test_describe_names_the_scope_and_the_platform() -> None:
    described = memory.describe({"memory_cap_mb": 1024})
    assert described["cap_bytes"] == 1024 * MIB
    assert described["cap_mb"] == 1024
    assert described["supported"] is memory.available()
    assert "model server" in described["scope"]


def test_cgroups_are_reported_as_not_implemented() -> None:
    result = memory.cgroup_limit(512 * MIB, pid=1234)
    assert result["memory_bytes"] == 512 * MIB
    assert result["pid"] == 1234
    assert result["supported"] is False
    assert "not" in result["reason"].lower() or "requires" in result["reason"].lower()
    assert memory.set_memory_limit(None, 512 * MIB) is False
