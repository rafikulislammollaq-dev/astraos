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


def _state_home() -> Path:
    """Where the machine keeps what it did, as opposed to what it is set to.

    XDG separates state from configuration for exactly this reason: the audit
    log is not a setting, and deleting a config file must not delete the record
    of what was run.
    """
    return Path(os.environ.get("XDG_STATE_HOME") or (_home() / ".local" / "state"))


class PATHS:
    """The filesystem locations the assistant uses.

    A namespace rather than an instance: every module needs the same values,
    nothing needs to construct them, and the build script installs the tree at
    a fixed place, so the only reason to read any of this at run time is the
    per-user part.

        share_dir    read-only content shipped by the package (prompts, docs)
        models_dir   downloaded model files, one .gguf or .bin per model
        system_models_dir  model files the image ships, read-only
        bin_dir      locally built binaries (llama-server, whisper-cli)
        config_file  the settings file written by save_settings()
        profile_file the machine capability profile written by `astra-ai profile`
        audit_file   Astra Guard's append-only record of every action decision

    Every one is an absolute pathlib.Path. The environment overrides
    exist for testing and for a user who keeps large files on another disk;
    they are not part of the interface anything else should depend on.
    """

    share_dir = Path(os.environ.get("ASTRAOS_AI_SHARE_DIR") or "/usr/share/astraos/ai")
    models_dir = Path(
        os.environ.get("ASTRAOS_AI_MODELS_DIR") or (_data_home() / "astraos" / "ai" / "models")
    )
    # The model files the image itself ships. Read-only, and searched after the
    # user's directory: a download with the same name must shadow the shipped
    # copy, not be shadowed by it. An image without a bundle simply has no
    # directory here, which is why every reader treats it as optional.
    system_models_dir = Path(
        os.environ.get("ASTRAOS_AI_SYSTEM_MODELS_DIR")
        or "/usr/share/astraos/ai/models"
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
    audit_file = Path(
        os.environ.get("ASTRAOS_GUARD_AUDIT")
        or (_state_home() / "astraos" / "guard" / "audit.jsonl")
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
    # "auto" confines the model server when bubblewrap/firejail can actually
    # run here; "on" refuses to start without a sandbox; "off" runs it bare.
    "sandbox": "auto",
    # 0 means no address-space cap. A positive value is applied to the model
    # server process, not to the assistant or the desktop.
    "memory_cap_mb": 0,
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


def model_dirs() -> list[Path]:
    """Every directory a model file may be in, in resolution order.

    The user's directory comes first so a downloaded file wins over a copy the
    image shipped. The image's directory is read-only and may not exist on a
    system where the assistant was installed from packages rather than an ISO.
    """
    directories = [PATHS.models_dir]
    system = Path(PATHS.system_models_dir)
    if system != PATHS.models_dir:
        directories.append(system)
    return directories


def find_model(name: str) -> Path | None:
    """The first existing file called *name*, in the user's directory then the image's.

    An absolute path is checked as itself: a setting may point at a model on
    another disk. A bare name is looked up in each directory, which is how the
    tier code passes catalog file names.
    """
    text = str(name or "").strip()
    if not text:
        return None
    candidate = Path(text).expanduser()
    if candidate.is_absolute():
        return candidate if candidate.is_file() else None
    for directory in model_dirs():
        path = directory / candidate
        if path.is_file():
            return path
    return None


def installed_models() -> dict[str, Path]:
    """Every model file visible, by file name; the user's copy wins on a tie.

    A dictionary rather than a list because the same file may exist in both
    directories, and counting it twice would make `model_file()` report "two
    models, choose one" after a user downloaded a model the image already had.
    """
    found: dict[str, Path] = {}
    for directory in model_dirs():
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            continue
        for path in entries:
            try:
                if path.is_file() and path.name not in found:
                    found[path.name] = path
            except OSError:
                continue
    return found


def model_file(settings: dict | None = None) -> Path | None:
    """The model file to load, or None when no model has been installed.

    Resolution order:
      1. settings["model"], as an absolute path or as a file name in a model
         directory (the user's first, then the one the image ships)
      2. the only *.gguf file visible, when there is exactly one

    The second rule exists so that `astra-ai setup --model NAME` followed by
    `astra-ai ask ...` works without a second command to select the model, and
    so the model the image ships is used on first boot with no setup at all.
    Two or more models and no setting means None: guessing between them would
    make the answer depend on directory order, which is not a decision the user
    made.
    """
    settings = settings if isinstance(settings, dict) else load_settings()

    chosen = str(settings.get("model") or "").strip()
    if chosen:
        return find_model(chosen)

    found = [
        path for name, path in installed_models().items() if name.lower().endswith(".gguf")
    ]
    return found[0] if len(found) == 1 else None


def model_name(settings: dict | None = None) -> str:
    """A human-readable name for the model that model_file() would return."""
    path = model_file(settings)
    return path.name if path else ""
