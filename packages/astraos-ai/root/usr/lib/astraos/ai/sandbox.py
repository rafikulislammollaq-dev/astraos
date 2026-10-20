"""Sandboxing for the model server: confine llama-server to its own cage.

WHY THIS EXISTS
    Astra Guard decides what the assistant may do, but the model server itself
    (llama-server) is a separate process that runs the weights. If it is
    compromised or goes wrong, nothing should let it write outside the model
    folder. This module builds the command line that runs it inside bubblewrap
    (preferred) or firejail, and reports honestly when neither is available.

WHAT IT DOES AND DOES NOT ISOLATE
    The filesystem confinement is the part that works today: the whole root is
    mounted read-only, the model directory is explicitly read-only, and the
    process gets a private /tmp and /dev/shm. The server needs no writable path
    of its own, so that is a real boundary.

    Network isolation is deliberately *not* part of the llama-server cage,
    although `sandbox_command(network=False)` can build one for another caller.
    The reason is structural: the assistant talks to llama-server over HTTP on
    127.0.0.1. A new network namespace has its own loopback, so a server inside
    it cannot be reached from the process that started it. Unsharing the network
    would not protect the assistant; it would break it. `confine_llama_server()`
    therefore keeps the host network and says so in the info dictionary, rather
    than shipping a command that silently cannot answer. A no-network engine
    needs a different transport (a Unix socket or a proxy in the namespace), and
    that is future work, not a flag.

WHY A PROBE
    A sandbox binary on PATH is not proof that it can run: some kernels disable
    unprivileged user namespaces, and the installed bubblewrap then fails with a
    one-line error. `probe()` runs the cheapest possible command through the
    wrapper so a caller can fall back before starting the model, instead of
    watching llama-server exit for a reason that has nothing to do with llama.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Iterable

SANDBOX_TOOLS = ("bwrap", "bubblewrap", "firejail")

DEFAULT_MODEL_DIR_READONLY = True
# The server is reached over loopback, so the host network is shared by default.
DEFAULT_SHARE_NETWORK = True


def tool() -> str | None:
    """The full path of the sandbox binary to use, or None."""
    for name in ("bwrap", "bubblewrap", "firejail"):
        found = shutil.which(name)
        if found:
            return found
    return None


def available() -> bool:
    """True when a sandbox binary is on PATH.

    This does not prove it can run here; `probe()` answers that question.
    """
    return tool() is not None


def _flavour(found: str) -> str:
    return "firejail" if "firejail" in Path(found).name.lower() else "bwrap"


def probe() -> dict:
    """Run a harmless command inside the sandbox. Returns what happened.

    An empty info["tool"] means no sandbox binary is installed. A tool with
    ok False means it is installed but cannot start a sandbox in this kernel or
    account; the caller should run unsandboxed and say so.
    """
    found = tool()
    if found is None:
        return {"ok": False, "tool": "", "reason": "no sandbox binary on PATH"}
    argv = [found]
    if _flavour(found) == "bwrap":
        argv += [
            "--ro-bind", "/", "/",
            "--proc", "/proc",
            "--dev", "/dev",
            "--tmpfs", "/tmp",
        ]
        argv += ["--", "/bin/true"]
    else:
        argv += ["--quiet", "--", "/bin/true"]
    try:
        done = subprocess.run(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "tool": found, "reason": str(exc)}
    if done.returncode != 0:
        detail = done.stderr.decode("utf-8", "replace").strip().splitlines()
        return {
            "ok": False,
            "tool": found,
            "reason": detail[-1] if detail else f"exit {done.returncode}",
        }
    return {"ok": True, "tool": found, "reason": ""}


def sandbox_command(
    argv: list[str],
    *,
    model_dir: str | Path | None = None,
    network: bool = DEFAULT_SHARE_NETWORK,
    read_only_model: bool = DEFAULT_MODEL_DIR_READONLY,
    extra_ro: Iterable[str | Path] = (),
    extra_rw: Iterable[str | Path] = (),
    die_with_parent: bool = True,
) -> tuple[list[str], dict]:
    """Wrap `argv` in a sandbox. Returns (wrapped_argv, info).

    `network=False` asks for a new network namespace. That is correct for a
    process that only needs its own loopback (and is what a future Unix-socket
    transport would use), but it makes a TCP server unreachable from its parent;
    see the module docstring. `confine_llama_server()` keeps it shared.

    When no sandbox binary is available, the original argv is returned unchanged
    and info["sandboxed"] is False, so a caller can detect the gap honestly
    instead of pretending it ran confined.
    """
    argv = list(argv or [])
    info = {
        "sandboxed": False,
        "tool": "",
        "network_shared": bool(network),
        "network_isolated": False,
        "read_only_model": bool(read_only_model),
        "model_dir": str(model_dir) if model_dir is not None else None,
    }

    found = tool()
    if found is None:
        info["reason"] = "no sandbox binary (bwrap/bubblewrap/firejail) on PATH"
        return argv, info

    flavour = _flavour(found)
    info["sandboxed"] = True
    info["tool"] = found
    info["flavour"] = flavour

    if flavour == "firejail":
        wrapped = [found, "--quiet"]
        if not network:
            wrapped.append("--net=none")
            info["network_isolated"] = True
        if model_dir is not None and read_only_model:
            wrapped.append(f"--read-only={model_dir}")
        for path in extra_ro:
            wrapped.append(f"--read-only={path}")
        for path in extra_rw:
            wrapped.append(f"--read-write={path}")
        wrapped += ["--"] + argv
        return wrapped, info

    # bubblewrap
    wrapped = [found]
    if die_with_parent:
        wrapped.append("--die-with-parent")
    wrapped.append("--new-session")
    if not network:
        wrapped.append("--unshare-net")
        info["network_isolated"] = True
    # A read-only root keeps the system libraries readable but not writable.
    wrapped += ["--ro-bind", "/", "/"]
    # Writable scratch space for the server's runtime files. /dev/shm is
    # separate on Linux and some thread pools expect it to exist.
    wrapped += ["--tmpfs", "/tmp", "--tmpfs", "/dev/shm"]
    if model_dir is not None:
        model_path = str(model_dir)
        if read_only_model:
            wrapped += ["--ro-bind", model_path, model_path]
        else:
            wrapped += ["--bind", model_path, model_path]
    for path in extra_ro:
        p = str(path)
        wrapped += ["--ro-bind", p, p]
    for path in extra_rw:
        p = str(path)
        wrapped += ["--bind", p, p]
    # proc/dev so the process can function.
    wrapped += ["--proc", "/proc", "--dev", "/dev"]
    wrapped += ["--"] + argv
    return wrapped, info


def confine_llama_server(argv, model_dir=None, **kwargs):
    """Alias for sandbox_command, named for the roadmap's target.

    The network is kept shared on purpose (see the module docstring), so this
    function refuses to accept `network=False`: a server that cannot be reached
    is not a confined server, it is a stalled one.
    """
    if kwargs.get("network") is False:
        raise ValueError(
            "llama-server is reached over 127.0.0.1; a private network namespace "
            "would make it unreachable. Leave network shared."
        )
    return sandbox_command(argv, model_dir=model_dir, **kwargs)


def confine(argv, model_dir=None, **kwargs):
    return confine_llama_server(argv, model_dir=model_dir, **kwargs)


def apply_sandbox(argv, model_dir=None, **kwargs):
    wrapped, _info = confine_llama_server(argv, model_dir=model_dir, **kwargs)
    return wrapped


def is_sandboxed(argv) -> bool:
    if not argv:
        return False
    name = Path(str(argv[0])).name.lower()
    return name in {"bwrap", "bubblewrap", "firejail"}


# Aliases kept because the module is new and callers may use either spelling.
sandbox = sandbox_command
wrap = sandbox_command
wrap_command = sandbox_command
build = sandbox_command
build_command = sandbox_command
sandbox_llama_server = confine_llama_server
apply = apply_sandbox


__all__ = [
    "available",
    "tool",
    "probe",
    "sandbox_command",
    "confine_llama_server",
    "confine",
    "apply_sandbox",
    "is_sandboxed",
    "sandbox",
    "wrap",
    "wrap_command",
    "build",
    "build_command",
    "sandbox_llama_server",
    "apply",
]
