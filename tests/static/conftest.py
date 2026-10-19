"""Suite-wide settings that must exist before astraos.ai is imported.

The assistant writes Astra Guard's audit log under XDG_STATE_HOME, which is the
right place for a real user and the wrong place for a test run: a suite must not
leave records in the home directory of whoever runs it, and a record from a test
must not be mistaken for a record of something that happened on that machine.

config.PATHS is a namespace of class attributes, so the environment is read once,
at import. That is why this lives in conftest.py: pytest imports it before any
test module, and therefore before the first `from astraos.ai import ...`.
"""

import os
import tempfile
from pathlib import Path

_STATE = Path(tempfile.mkdtemp(prefix="astraos-tests-state-"))
os.environ.setdefault("XDG_STATE_HOME", str(_STATE))
os.environ.setdefault(
    "ASTRAOS_GUARD_AUDIT", str(_STATE / "astraos" / "guard" / "audit.jsonl")
)
