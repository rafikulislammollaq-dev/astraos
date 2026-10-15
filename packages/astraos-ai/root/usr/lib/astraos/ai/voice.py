"""Speaking and listening, with the tools Debian already has.

Why espeak-ng for speech and not a neural voice:

    The machine this release is tested on is a Sandy Bridge desktop with no
    GPU. A neural text-to-speech model small enough to run there in reasonable
    time sounds worse than espeak-ng, arrives as another download, and takes
    seconds to say a sentence that espeak-ng says immediately. The honest
    trade is a robotic voice that answers at once. espeak-ng is in Debian, it
    is a few megabytes, and it works with no network and no display.

Why transcription is optional and separate:

    Speech-to-text needs whisper.cpp built from source plus a model file, and
    neither is something the assistant installs by itself. When they are not
    there, stt_available() says so and transcribe() explains what is missing
    in one line, instead of failing half way through a recording.

Why every failure is a printed line and an empty result:

    This module is called from a terminal (`astra-ai say`, `astra-ai listen`)
    and from the web interface. Both have to show a sentence, not a traceback,
    and both have to keep working when there is no sound card, no microphone
    or no model - so nothing here raises.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import config as _config
from . import setup as _setup

# Ordered by preference: espeak-ng is the maintained one, espeak is the older
# package some installs still have, spd-say goes through speech-dispatcher.
TTS_TOOLS = ("espeak-ng", "espeak", "spd-say")

# whisper.cpp has renamed its command-line program twice. Any of these is
# accepted, in the assistant's own bin directory or on PATH.
STT_TOOLS = ("whisper-cli", "whisper-cpp", "whisper.cpp", "whisper")

# How much text may be spoken in one call. A long paragraph read aloud at 165
# words per minute is not a feature, it is a way to lose the user's attention.
MAX_SPOKEN_CHARS = 1200

# whisper.cpp on the reference machine transcribes a five second clip much
# faster than it plays; this is the ceiling for a long recording gone wrong.
TRANSCRIBE_TIMEOUT = 180


def _log(message: str) -> None:
    print(f"astra-ai: {message}", file=sys.stderr)


def tts_tool() -> str | None:
    for name in TTS_TOOLS:
        found = shutil.which(name)
        if found:
            return found
    return None


def tts_available() -> bool:
    """True when something on this machine can speak.

    A check of PATH only: nothing is run, so calling this from a status page
    does not make a sound.
    """
    return tts_tool() is not None


def speak(text: str) -> bool:
    """Say `text` out loud. True when the speech tool exited cleanly.

    Blocks until the sentence has been spoken, which is what `astra-ai say`
    has to do to be usable from a script.
    """
    wanted = (text or "").strip()
    if not wanted:
        _log("nothing to say")
        return False
    if len(wanted) > MAX_SPOKEN_CHARS:
        wanted = wanted[:MAX_SPOKEN_CHARS]

    tool = tts_tool()
    if tool is None:
        _log(
            "no speech tool is installed - install one with: astra install espeak-ng"
        )
        return False

    if Path(tool).name == "spd-say":
        argv = [tool, "--wait", "--", wanted]
    else:
        # -s is words per minute; 165 is espeak's own default and the speed at
        # which the voice is least unpleasant. -v en-us pins the accent, so a
        # machine with LANG=de_DE does not read English text with German rules.
        argv = [tool, "-v", "en-us", "-s", "165", "--", wanted]

    # Long text takes a long time to speak; 30 s plus a generous allowance per
    # character keeps the timeout from cutting a sentence off mid-word.
    timeout = 30 + len(wanted) // 8
    try:
        completed = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=timeout,
            text=True,
            errors="replace",
        )
    except FileNotFoundError:
        _log(f"speech tool vanished while starting: {tool}")
        return False
    except subprocess.TimeoutExpired:
        _log(f"speech took longer than {timeout}s and was stopped")
        return False
    except OSError as exc:
        _log(f"could not start {Path(tool).name}: {exc}")
        return False

    if completed.returncode != 0:
        first = (completed.stderr or "").strip().splitlines()
        detail = first[0] if first else "no output"
        _log(f"{Path(tool).name} failed (exit {completed.returncode}): {detail}")
        return False
    return True


def stt_binary() -> str | None:
    """The whisper.cpp program: the assistant's bin directory first, then PATH.

    Public because `astra-ai setup --voice` has to tell "not built yet" (a
    reason to compile) from "built, no model installed" (not a reason to
    compile anything).
    """
    for name in STT_TOOLS:
        candidate = _config.PATHS.bin_dir / name
        if candidate.is_file():
            return str(candidate)
    for name in STT_TOOLS:
        found = shutil.which(name)
        if found:
            return found
    return None


def _stt_model_path() -> Path | None:
    """The whisper model the settings point at, if the file is there.

    The name in the settings is the catalog name ("whisper-tiny.en"), and the
    file on disk is the name upstream publishes ("ggml-tiny.en.bin"). Looking
    the mapping up in setup.MODELS keeps one table for both downloads and
    transcription; without a catalog entry the setting is taken as a file
    name, so a model installed by hand still works.
    """
    settings = _config.load_settings()
    name = str(settings.get("stt_model") or "whisper-tiny.en").strip()
    if not name:
        return None

    entry = _setup.MODELS.get(name)
    filename = entry.get("file") if isinstance(entry, dict) else None
    for candidate in (filename, name, name + ".bin"):
        if not candidate:
            continue
        path = _config.PATHS.models_dir / candidate
        if path.is_file():
            return path
    return None


def stt_available() -> bool:
    """True when a whisper binary and a model file are both present."""
    return stt_binary() is not None and _stt_model_path() is not None


def transcribe(wav_bytes: bytes) -> str:
    """Turn recorded speech into text, or return "" and say what is missing.

    The audio must be 16 kHz mono WAV, which is what `astra-ai listen` records
    and what whisper.cpp expects. Empty bytes are not an error worth three
    lines of explanation: the caller recorded for a second and got nothing,
    and the answer is "no audio captured".
    """
    if not wav_bytes:
        _log("no audio was captured")
        return ""

    binary = stt_binary()
    model = _stt_model_path()
    if binary is None or model is None:
        missing = []
        if binary is None:
            missing.append("whisper.cpp (build it with: astra-ai setup --build whisper)")
        if model is None:
            missing.append(
                "a model (install one with: astra-ai setup --model whisper-tiny.en)"
            )
        _log("cannot transcribe: no " + " and no ".join(missing))
        return ""

    handle = None
    try:
        handle = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        handle.write(wav_bytes)
        handle.close()

        # -nt drops the timestamps, so stdout is the sentence and nothing else.
        argv = [binary, "-m", str(model), "-f", handle.name, "-nt", "-l", "en"]
        completed = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=TRANSCRIBE_TIMEOUT,
            text=True,
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        _log(f"transcription took longer than {TRANSCRIBE_TIMEOUT}s and was stopped")
        return ""
    except OSError as exc:
        _log(f"could not run {Path(binary).name}: {exc}")
        return ""
    finally:
        if handle is not None:
            try:
                Path(handle.name).unlink(missing_ok=True)
            except OSError:
                pass

    if completed.returncode != 0:
        first = (completed.stderr or "").strip().splitlines()
        detail = first[0] if first else "no output"
        _log(f"{Path(binary).name} failed (exit {completed.returncode}): {detail}")
        return ""

    text = " ".join(
        line.strip() for line in (completed.stdout or "").splitlines() if line.strip()
    )
    if not text:
        _log("the recording contained no speech")
    return text
