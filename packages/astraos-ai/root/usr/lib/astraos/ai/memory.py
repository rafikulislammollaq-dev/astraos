"""Memory cap for the model server: cgroup/setrlimit around llama-server.

WHY THIS EXISTS
    A weak model that loops can take the whole machine with it. The roadmap
    (Stage 4, budgets) asks for a memory cap around the model server. On Linux
    this is done with resource.setrlimit (RLIMIT_AS / RLIMIT_RSS) in the child
    before exec, or a cgroup limit. This module provides both the pure decision
    (how many bytes) and the application, and degrades honestly on platforms
    without the primitives (such as this Windows development host).
"""

from __future__ import annotations

import os
try:
    import resource
except ImportError:  # pragma: no cover - Windows dev host
    resource = None
from typing import Optional

DEFAULT_MEMORY_CAP_MB = 0  # 0 means "no cap"


def memory_cap_bytes(settings: dict | None = None) -> int:
    """How many bytes the model server may use. 0 means unlimited."""
    settings = settings or {}
    raw = settings.get("memory_cap_mb", settings.get("memory_cap", settings.get("memory_limit_mb")))
    if raw is None:
        raw = os.environ.get("ASTRAOS_MEMORY_CAP_MB", "0")
    try:
        mb = float(raw)
    except (TypeError, ValueError):
        mb = 0.0
    if mb <= 0:
        return 0
    return int(mb * 1024 * 1024)


def available() -> bool:
    """True when this platform can cap a child's address space."""
    return resource is not None


def apply_rlimit(memory_bytes: int) -> bool:
    """Apply an address-space cap to the *current* process. Returns True on success.

    This is irreversible for the life of the process (RLIMIT_AS can be lowered,
    never raised by an unprivileged process), so the engine does not call it:
    the cap belongs in `preexec()` and therefore in the model server child.
    It is kept for callers that are themselves the process to be capped.
    """
    if memory_bytes <= 0 or resource is None:
        return False
    try:
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        return True
    except (ValueError, OSError, AttributeError):
        return False


def preexec(memory_bytes: int):
    """Return a preexec_fn (or None) for subprocess.Popen."""
    if memory_bytes <= 0 or resource is None:
        return None

    def _limit():
        try:
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        except (ValueError, OSError, AttributeError):
            pass

    return _limit


def set_memory_limit(process_or_pid, memory_bytes: int) -> bool:
    """Best-effort cap on an already-running process. Returns True if applied."""
    # Applying to a running pid requires cgroups/ptrace; not portable. Report
    # honestly that it was not applied rather than pretending.
    return False


def cgroup_limit(memory_bytes: int, pid: int | None = None) -> dict:
    """Describe a cgroup limit (does not create one on its own)."""
    return {
        "memory_bytes": int(memory_bytes or 0),
        "pid": pid,
        "supported": False,
        "reason": "cgroup application requires root and a writable cgroup v2 mount",
    }


def cap_for(settings: dict | None = None) -> int:
    return memory_cap_bytes(settings)


def describe(settings: dict | None = None) -> dict:
    """What the cap is and whether this platform can apply it, for `status`."""
    cap = memory_cap_bytes(settings)
    return {
        "cap_bytes": cap,
        "cap_mb": round(cap / 1048576) if cap else 0,
        "supported": available(),
        "scope": "the model server process only",
    }


# Aliases
memory_limit = memory_cap_bytes
memory_limit_bytes = memory_cap_bytes
get_memory_cap = memory_cap_bytes
apply_memory_cap = apply_rlimit
apply_cap = apply_rlimit
setrlimit_cap = apply_rlimit
memory_cap = memory_cap_bytes


__all__ = [
    "memory_cap_bytes",
    "apply_rlimit",
    "preexec",
    "set_memory_limit",
    "cgroup_limit",
    "cap_for",
    "describe",
    "available",
    "memory_limit",
    "memory_limit_bytes",
    "get_memory_cap",
    "apply_memory_cap",
    "apply_cap",
    "setrlimit_cap",
    "memory_cap",
    "DEFAULT_MEMORY_CAP_MB",
]
