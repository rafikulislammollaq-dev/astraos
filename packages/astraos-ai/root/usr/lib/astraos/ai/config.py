"""Where the assistant keeps its files, and how its settings are read.

Why everything lives in the user's home directory:

    The assistant either works entirely inside one account or it does not work
    at all on the machine this release is tested on. An Intel Sandy Bridge
    desktop with no GPU cannot host a shared AI service, and a system-wide
    model directory would mean root-owned downloads, root-owned settings and a
    root-owned server process - three things this package refuses to create.
    So the models, the compiled binaries and the settings file all live under
    $HOME, they are installed by the user who wants them, and another account
    on the same machine can install its own copy without touching this one.

Why the settings file is JSON:

    json is in the standard library. The image has python3 and python3-gi and
    no pip, so anything the assistant reads or writes must parse with what
    Python already ships. A corrupt or half-written file is treated as "no
    settings yet" rather than as a crash: the assistant always has to reach a
    state where it can tell the user what is wrong.

Why LAN_DEFAULT is False:

    The local model server and the web interface bind 127.0.0.1. Turning that
    into "reachable from the network" is a deliberate, separate decision
    (`astra-ai serve --lan`), never a default, because a desktop that answers
    chat requests from the whole network is a different security posture from
    the one docs/SECURITY.md describes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# See the module docstring. Do not change this without changing the CLI help
# and docs/SECURITY.md together.
LAN_DEFAULT = False

# The version of the assistant itself. Not read from /etc/astraos-release at
# run time: the command has to be able to say what it is even when the file it
# would read is missing, and a version that depends on the image it is running
# in cannot be compared against a package changelog.
VERSION = "0.2.0"


def _home() -> Path:
    """The user's home directory, without depending on $HOME being set.

    A session launched from a display manager always has HOME, but a unit or a
    script started from cron may not, and Path.home() raises RuntimeError in
    that case. Falling back to the passwd database, then to /tmp, keeps the
    failure mode "the assistant has no settings" instead of "the assistant
    cannot start".
    """
    home = os.environ.get("HOME")
    if home:
        return Path(home)
    try:
        import pwd

        return Path(pwd.getpwuid(os.getuid()).pw_dir)
    except Exception:  # noqa: BLE001 - any failure here has the same answer
        return Path("/tmp")


def _data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or (_home() / ".local" / "share"))


def _config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or (_home() / ".config"))


class PATHS:
    """The filesystem locations the assistant uses.

    A namespace rather than an instance: every module needs the same values,
    nothing needs to construct them, and the build script installs the tree at
    a fixed place, so the only reason to read any of this at run time is the
    per-user part.

        share_dir    read-only content shipped by the package (prompts, docs)
        models_dir   downloaded model files, one .gguf or .bin per model
        bin_dir      locally built binaries (llama-server, whisper-cli)
        config_file  the settings file written by save_settings()
        profile_file the machine capability profile written by `astra-ai profile`

    Every one is an absolute pathlib.Path. The environment overrides
    exist for testing and for a user who keeps large files on another disk;
    they are not part of the interface anything else should depend on.
    """

    share_dir = Path(os.environ.get("ASTRAOS_AI_SHARE_DIR") or "/usr/share/astraos/ai")
    models_dir = Path(
        os.environ.get("ASTRAOS_AI_MODELS_DIR") or (_data_home() / "astraos" / "ai" / "models")
    )
    bin_dir = Path(
        os.environ.get("ASTRAOS_AI_BIN_DIR") or (_data_home() / "astraos" / "ai" / "bin")
    )
    config_file = Path(
        os.environ.get("ASTRAOS_AI_CONFIG") or (_config_home() / "astraos" / "ai.json")
    )
    profile_file = Path(
        os.environ.get("ASTRAOS_AI_PROFILE") or (_config_home() / "astraos" / "machine.json")
    )


# The settings the rest of the package reads. Every key is optional in the
# file: load_settings() starts from this dictionary and lets the file override
# what it recognises.
#
# The numbers assume the release's reference machine - a Sandy Bridge desktop,
# no GPU, 4 GB of RAM - and are the ones that keep a 1B-3B Q4 model inside it:
#
#   threads     half the cores, capped at 4. llama.cpp scales badly past the
#               physical core count and a busy CPU makes the whole desktop
#               stutter while the model is thinking.
#   context     4096 tokens. The KV cache costs memory on top of the weights,
#               and doubling this is the usual reason a machine that could run
#               the model starts swapping.
#   gpu_layers  0, and it is not a knob to raise on this hardware: there is no
#               GPU whose layers could be offloaded.
DEFAULTS: dict = {
    "model": "",
    "stt_model": "whisper-tiny.en",
    "host": "127.0.0.1",
    "port": 8642,
    "lan": LAN_DEFAULT,
    "threads": max(1, min(4, (os.cpu_count() or 2) // 2)),
    "context": 4096,
    "gpu_layers": 0,
    "temperature": 0.3,
    "max_tokens": 512,
    "stream": True,
}


def load_settings() -> dict:
    """The settings, with DEFAULTS filled in for everything the file omits.

    Never raises. A missing file, an unreadable one, a truncated one or one
    that holds a JSON list instead of an object all produce the defaults, and
    the next save_settings() replaces the broken file.

    Values are kept only when their type matches the default's, or when the
    key is not known at all (the web interface may store its own keys here).
    That check is not decoration: a hand-edited "port": "http://x" would
    otherwise reach urllib and fail with a message about a bad port number,
    several layers away from the line that caused it.
    """
    settings = dict(DEFAULTS)
    try:
        raw = PATHS.config_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return settings
    try:
        stored = json.loads(raw)
    except ValueError:
        return settings
    if not isinstance(stored, dict):
        return settings

    for key, value in stored.items():
        if key not in DEFAULTS:
            settings[key] = value
            continue
        expected = DEFAULTS[key]
        if isinstance(expected, bool):
            if isinstance(value, bool):
                settings[key] = value
        elif isinstance(expected, int):
            # JSON has no integers and floats apart; accept a whole number that
            # arrived as 8642.0 and reject anything else.
            if isinstance(value, int) and not isinstance(value, bool):
                settings[key] = value
            elif isinstance(value, float) and value.is_integer():
                settings[key] = int(value)
        elif isinstance(expected, float):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                settings[key] = float(value)
        elif isinstance(expected, str):
            if isinstance(value, str):
                settings[key] = value
    return settings


def save_settings(d: dict) -> None:
    """Write the settings file.

    Written to a temporary file in the same directory and then renamed, so a
    reader (the web interface, a second terminal) either sees the old file or
    the new one, never half of the new one.

    Raises OSError if the file cannot be written - a read-only home directory
    is something the caller must be able to report - but never writes anywhere
    other than PATHS.config_file.
    """
    target = PATHS.config_file
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".new")
    text = json.dumps(d, indent=2, sort_keys=True) + "\n"
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(temporary, target)


def model_file(settings: dict | None = None) -> Path | None:
    """The model file to load, or None when no model has been installed.

    Resolution order:
      1. settings["model"], as an absolute path or as a file name in models_dir
      2. the only *.gguf file in models_dir, when there is exactly one

    The second rule exists so that `astra-ai setup --model NAME` followed by
    `astra-ai ask ...` works without a second command to select the model. Two
    or more models and no setting means None: guessing between them would make
    the answer depend on directory order, which is not a decision the user made.
    """
    settings = settings if isinstance(settings, dict) else load_settings()

    chosen = str(settings.get("model") or "").strip()
    if chosen:
        candidate = Path(chosen).expanduser()
        if candidate.is_file():
            return candidate
        candidate = PATHS.models_dir / candidate
        if candidate.is_file():
            return candidate
        return None

    try:
        found = sorted(PATHS.models_dir.glob("*.gguf"))
    except OSError:
        return None
    return found[0] if len(found) == 1 else None


def model_name(settings: dict | None = None) -> str:
    """A human-readable name for the model that model_file() would return."""
    path = model_file(settings)
    return path.name if path else ""
