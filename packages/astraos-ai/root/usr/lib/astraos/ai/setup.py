"""Downloading models and building the tools, one explicit command at a time.

Why nothing here happens by itself:

    A model download is one or two gigabytes, and a llama.cpp build takes a
    compiler and twenty minutes on the reference machine. Neither belongs in
    an install, a boot, or the first run of a command that was asked a
    question. They happen when a person types `astra-ai setup --model NAME`
    or `astra-ai setup --build llama`, they say what they are doing while
    they do it, and the progress goes to stdout so it ends up in the log if
    the user redirected it.

Why no sudo, anywhere:

    Everything is written under $HOME (see config.PATHS). A system-wide model
    directory would mean a root-owned file the assistant later cannot replace,
    and a root-owned process holding a gigabyte of RAM on a machine with four.
    If something needs root, this module does not do it - it prints the
    package to install and stops.

Why the build flags are what they are:

    The machine this release is tested on is a Sandy Bridge: AVX is present,
    AVX2, F16C, FMA and BMI2 are not. llama.cpp and whisper.cpp both compile
    for the host's features by default (-DGGML_NATIVE=ON), which produces a
    binary that dies with "Illegal instruction" on the reference machine when
    the build happened on a newer one. The flags pin the instruction set
    explicitly, per variant: "avx" (the default, and what CI ships) is AVX on,
    AVX2/F16C/FMA/BMI2/AVX512 off; "avx2" is the same list with the four
    Haswell features on, for the machines that have them; "auto" picks from
    this machine's own /proc/cpuinfo. A named variant is checked against that
    file before the first compiler runs, and the choice is recorded beside the
    installed binaries so `astra-ai status` can flag a build this CPU cannot
    run.

    FMA and BMI2 are not optional extras of the AVX2 switch. With only
    GGML_AVX2=OFF, CMake still turns GGML_FMA and GGML_BMI2 on by default -
    measured on 2026-10-16, when the first real end-to-end run died with
    SIGILL (exit 132) and not one line of output, because the model loader
    reached an FMA instruction before it printed anything. A build that
    configures cleanly, links cleanly and then dies silently on the machine it
    was made for is the exact failure this list exists to prevent.

    BUILD_SHARED_LIBS=OFF makes the installed program self-contained.
    llama.cpp builds shared libraries whose RPATH points into the build tree,
    so a copied llama-server starts only while src/llama-build is still there:
    delete that tree to reclaim the disk space, and the assistant's engine
    stops loading its own libraries. The static binary is one file, about
    8 MB, with nothing outside bin_dir to depend on.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import config as _config

# Where the two upstream projects live. Cloned shallow: neither needs history
# to build, and a full llama.cpp clone is most of a gigabyte.
SOURCES = {
    "llama": "https://github.com/ggerganov/llama.cpp",
    "whisper": "https://github.com/ggerganov/whisper.cpp",
}

# The instruction-set flags explained in the module docstring, per CPU
# variant. Applied to both projects: whisper.cpp builds on the same ggml
# library and fails the same way. GGML_BLAS stays off so that the build needs
# no BLAS development package; on this hardware the difference for a 1B-3B Q4
# model is small, and a build that fails for a missing -dev package would be
# worse than one that is 10% slower.
CPU_VARIANTS: dict[str, list[str]] = {
    "avx": [
        "-DGGML_NATIVE=OFF",
        "-DGGML_AVX=ON",
        "-DGGML_AVX2=OFF",
        # FMA and BMI2 arrived with Haswell, the same generation as AVX2, and
        # ggml turns both on by default even when GGML_AVX2 is off. Leaving
        # them out is not a theoretical mistake: on the Sandy Bridge reference
        # machine the server configured, built, and then died with SIGILL and
        # zero output on the first tensor it loaded, because the log is empty
        # until the model is in memory. Measured 2026-10-16.
        "-DGGML_FMA=OFF",
        "-DGGML_BMI2=OFF",
        "-DGGML_F16C=OFF",
        "-DGGML_AVX512=OFF",
        "-DGGML_BLAS=OFF",
        # One self-contained file: see the module docstring. A shared build
        # copied out of the build tree keeps an RPATH into it and stops
        # working as soon as the tree is gone.
        "-DBUILD_SHARED_LIBS=OFF",
    ],
    # Haswell (2013) and later: the same build with the four features those
    # CPUs added. AVX-512 stays off in both variants: it is not needed for a
    # 1B-3B Q4 model, it is absent from every CPU this project is tested on,
    # and on some CPUs that have it, using it costs clocks for everyone.
    "avx2": [
        "-DGGML_NATIVE=OFF",
        "-DGGML_AVX=ON",
        "-DGGML_AVX2=ON",
        "-DGGML_FMA=ON",
        "-DGGML_BMI2=ON",
        "-DGGML_F16C=ON",
        "-DGGML_AVX512=OFF",
        "-DGGML_BLAS=OFF",
        "-DBUILD_SHARED_LIBS=OFF",
    ],
}

# What a binary built for a variant may execute, by /proc/cpuinfo flag name.
# Checked against this machine before a build starts, and against the build
# marker of the installed binaries before they are trusted - the second check
# is what catches an artifact built for another machine, which would fail the
# way the measured SIGILL failed.
VARIANT_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "avx": ("avx",),
    "avx2": ("avx", "avx2", "f16c", "fma", "bmi2"),
}

# What a bare `--build` builds. The reference machine and the artifact CI
# ships are both "avx"; "auto" is the explicit word for "the newest variant
# this CPU can run", and any named variant is checked against the local CPU
# before the first compiler runs.
DEFAULT_VARIANT = "avx"

# The default variant's flags, under the name the workflow and the tests read.
CPU_FLAGS = CPU_VARIANTS[DEFAULT_VARIANT]

# The models that may be installed, as a three-tier ladder rather than one
# list. Every entry names the tier it is for, because a user "installing a
# model" is not the decision they are actually making - they are choosing
# whether this machine can plan, only execute, or both.
#
# WHY THE LADDER AND NOT ONE RECOMMENDED MODEL
#
# The measured finding behind the split (arXiv 2601.11327v2, v2 2026-04-13) is
# that multi-agent systems with small models are planner-limited: an 8B
# orchestrator scores the same across 1.7B/8B/32B sub-agents on GAIA (23.0 /
# 23.0 / 23.6), and giving the orchestrator thinking is worth +18.2 GAIA and
# +36.7 AIME while giving the workers thinking is worth marginal or negative
# amounts. ProST (arXiv 2509.04508v2) reaches the same conclusion from the other
# side: a 14B planner with 7B workers beats 7B/14B/14B at equal parameters.
#
# So the parameter budget goes in the brain, and the executor gets the smallest
# model that follows one instruction. The pool in tiers.py loads one at a time,
# because both in memory on the reference machine is the difference between an
# assistant and a machine that swaps the desktop out.
#
# WHY THESE MODELS
#
# Spark-X2.5 is iFLYTEK's SparkLLM series, published in August-September 2026
# under Apache 2.0. Its own benchmark table (the repository README) puts the 4B
# at HLE 12.3 against Qwen3.5-4B at 8.6, Qwen3.5-2B at 2.1 and Gemma4-E4B at
# 3.9, so it is the strongest 4B-class model measured there, and at 2.4 GB the
# file fits the machine this distribution targets. The GGUF repository carries
# several hundred thousand downloads, which is adoption rather than a press
# release.
#
# Every URL below was verified against the Hugging Face API on the day this
# list was last edited: two earlier entries named repositories that do not
# exist, and a catalogue that answers 401 on the model the docs tell a user to
# install is worse than a catalogue that is missing an entry, because the user
# copied the command exactly and it still failed.
#
# The 1B-3B tier does not have to be a tool caller: it only has to classify one
# request and read one instruction, and the 1.7B of the same family delivers
# that at 1.0 GB against the 3B's 1.8 GB. SmolLM3-3B (Apache 2.0, `think` and
# `no_think` modes) stays as the alternative executor for a machine that would
# rather carry a different tokenizer.
#
# THE NUMBERS ARE FILE SIZES, NOT ESTIMATES. `astra-ai setup --list` shows
# them, and a user on a metered connection deserves a real number.
#
# BEIR's finding on vocabulary failure is why the router is here: dense models
# lose to BM25 on jargon, part numbers and error codes they never trained on,
# and a 360M classifier asked "is this one step or several?" fails the same way
# on a command nobody expected. That is why the router is optional and the
# executor default is a 3B.
MODELS: dict[str, dict] = {
    # ---- the executor: one task at a time, cheap, and never the bottleneck
    "spark-x2.5-1.7b-q4_k_m": {
        "kind": "llm",
        "tier": "executor",
        "file": "Spark-X2.5-1.7B-Q4_K_M.gguf",
        "url": "https://huggingface.co/XHToken/Spark-X2.5-1.7B-GGUF/resolve/main/"
               "Spark-X2.5-1.7B-Q4_K_M.gguf",
        "size_mb": 1056,
        "note": "THE DEFAULT EXECUTOR: 1.0 GB at Q4_K_M, Apache 2.0, the same model"
                " family as the brain - one set of chat-template behaviour to"
                " handle, and the fastest answers per step",
    },
    "smollm3-3b-q4_k_m": {
        "kind": "llm",
        "tier": "executor",
        "file": "SmolLM3-Q4_K_M.gguf",
        "url": "https://huggingface.co/ggml-org/SmolLM3-3B-GGUF/resolve/main/"
               "SmolLM3-Q4_K_M.gguf",
        "size_mb": 1827,
        "note": "the alternative executor: a different tokenizer with a no_think"
                " mode, for a user who would rather carry 1.8 GB of 3B",
    },
    "qwen2.5-1.5b-instruct-q4_k_m": {
        "kind": "llm",
        "tier": "executor",
        "file": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "url": "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/"
               "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "size_mb": 1120,
        "note": "the small executor: works on 4 GB of RAM, slower to follow a long instruction",
    },
    "qwen2.5-3b-instruct-q4_k_m": {
        "kind": "llm",
        "tier": "executor",
        "file": "qwen2.5-3b-instruct-q4_k_m.gguf",
        "url": "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/"
               "qwen2.5-3b-instruct-q4_k_m.gguf",
        "size_mb": 1930,
        "note": "a bigger executor, for a machine that can spare the wait",
    },
    # ---- the middle brain: the tier that decides quality
    "spark-x2.5-4b-q4_k_m": {
        "kind": "llm",
        "tier": "brain",
        "file": "Spark-X2.5-4B-Q4_K_M.gguf",
        "url": "https://huggingface.co/XHToken/Spark-X2.5-4B-GGUF/resolve/main/"
               "Spark-X2.5-4B-Q4_K_M.gguf",
        "size_mb": 2480,
        "note": "THE MIDDLE BRAIN: plans multi-step work, and is the model whose"
                " quality decides what the assistant can do. Apache 2.0, 1M"
                " context, HLE 12.3 against Qwen3.5-4B's 8.6. Needs 6 GB or more.",
    },
    "qwen2.5-3b-instruct-q4_k_m": {
        "kind": "llm",
        "tier": "brain",
        "file": "qwen2.5-3b-instruct-q4_k_m.gguf",
        "url": "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/"
               "qwen2.5-3b-instruct-q4_k_m.gguf",
        "size_mb": 1930,
        "note": "the middle brain when the machine has 4 GB: better answers than"
                " the 1.5B, about twice the wait per question",
    },
    # ---- the router: only for machines that want to spend the disk on it
    "smollm2-360m-instruct-q8_0": {
        "kind": "llm",
        "tier": "router",
        "file": "smollm2-360m-instruct-q8_0.gguf",
        "url": "https://huggingface.co/HuggingFaceTB/SmolLM2-360M-Instruct-GGUF/"
               "resolve/main/smollm2-360m-instruct-q8_0.gguf",
        "size_mb": 400,
        "note": "optional: sorts a request into executor, brain, or a plain answer",
    },
    "whisper-tiny.en": {
        "kind": "stt",
        "tier": "voice",
        "file": "ggml-tiny.en.bin",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.en.bin",
        "size_mb": 78,
        "note": "speech recognition for `astra-ai listen`: fast, English only",
    },
    "whisper-base.en": {
        "kind": "stt",
        "tier": "voice",
        "file": "ggml-base.en.bin",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin",
        "size_mb": 148,
        "note": "speech recognition: more accurate than tiny, still English only",
    },
    "piper-voice-lessac-medium": {
        "kind": "tts",
        "tier": "voice",
        "file": "en_US-lessac-medium.onnx",
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/"
               "lessac/medium/en_US-lessac-medium.onnx",
        "size_mb": 63,
        "note": "speaking voice for `astra-ai say` and the web page: one command",
    },
    "piper-voice-lessac-medium-json": {
        "kind": "tts-json",
        "tier": "voice",
        "file": "en_US-lessac-medium.onnx.json",
        "url": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/"
               "lessac/medium/en_US-lessac-medium.onnx.json",
        "size_mb": 1,
        "note": "the matching phoneme map for the Lessac voice",
    },
}

# What `astra-ai setup` installs when given nothing to do: the executor, and
# nothing else. The brain is a second command on purpose - a user with 4 GB who
# installs both gets a machine that swaps, and they should get to make that
# choice rather than discover it at the third question.
# `astra-ai setup --tier brain` is the same thing said the other way round.
DEFAULT_SETUP = "spark-x2.5-1.7b-q4_k_m"

RECOMMENDED = DEFAULT_SETUP

# How long a single read may block before the download is treated as dead.
# Not the whole-download timeout: a slow line with a 1 GB file can take an
# hour, and that is the user's business, not a failure.
READ_TIMEOUT = 30


class SetupError(RuntimeError):
    """Something the user can fix, in one line. The CLI prints it and stops."""


def models_of_kind(kind: str) -> list[str]:
    """The catalog entries of one kind ("llm" or "stt"), in listed order."""
    return [name for name, entry in MODELS.items() if entry.get("kind") == kind]


def model_path(name: str) -> Path:
    """Where a catalog entry is on disk, or where a download would put it.

    The image ships the executor and the tiny speech model, so the first look
    is the image's directory. A file the user downloaded has the same name in
    their directory and is found first; a model that is nowhere falls back to
    the user's directory, which is where install_model() writes it.
    """
    entry = MODELS.get(name)
    if entry is None:
        raise SetupError(
            f"unknown model: {name} - `astra-ai setup --list` shows the catalog"
        )
    found = _config.find_model(entry["file"])
    return found if found is not None else _config.PATHS.models_dir / entry["file"]


def describe() -> dict:
    """What is installed, what is missing, and where everything lives.

    A dictionary rather than printed text, because the web interface wants the
    same answers for its status page. Keys:

        model           the catalog name or file name in use, or ""
        model_file      its absolute path, or ""
        model_present   the file exists
        llama_server    the llama-server path, or ""
        models_dir      where models are kept
        bin_dir         where locally built tools are kept
        share_dir       the package's read-only content
        config_file     the settings file
        installed       every model file present in models_dir, by name
        tts / tts_tool  whether speech is possible, and with what
        stt / stt_model / stt_model_file   the same for transcription
    """
    from . import voice as _voice  # imported here: voice imports this module

    settings = _config.load_settings()
    chosen = _config.model_file(settings)

    installed = sorted(_config.installed_models())

    stt_name = str(settings.get("stt_model") or "")
    stt_file = ""
    try:
        stt_file = str(model_path(stt_name)) if stt_name in MODELS else ""
    except SetupError:
        stt_file = ""

    return {
        "model": chosen.name if chosen else str(settings.get("model") or ""),
        "model_file": str(chosen) if chosen else "",
        "model_present": chosen is not None,
        "llama_server": shutil.which("llama-server") or _found_binary("llama-server"),
        "models_dir": str(_config.PATHS.models_dir),
        "bin_dir": str(_config.PATHS.bin_dir),
        "share_dir": str(_config.PATHS.share_dir),
        "config_file": str(_config.PATHS.config_file),
        "installed": installed,
        "tts": _voice.tts_available(),
        "tts_tool": _voice.tts_tool() or "",
        "stt": _voice.stt_available(),
        "stt_model": stt_name,
        "stt_model_file": stt_file,
    }


def _found_binary(name: str) -> str:
    candidate = _config.PATHS.bin_dir / name
    return str(candidate) if candidate.is_file() else ""


def local_cpu_flags() -> set[str]:
    """The feature words this machine's /proc/cpuinfo lists.

    An unprivileged read, like every other measurement this package takes, and
    an empty set when the file cannot be read (another operating system).
    """
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() == "flags":
            return set(value.split())
    return set()


def best_variant(cpu_flags) -> str | None:
    """The newest variant a CPU with these features can run, or None.

    Pure and parameterised - the tests ask it about a Sandy Bridge and a
    Haswell without owning either - and the single place the "newest" order
    lives: last entry first in CPU_VARIANTS.
    """
    available = set(cpu_flags)
    for variant in reversed(list(CPU_VARIANTS)):
        if set(VARIANT_REQUIREMENTS[variant]) <= available:
            return variant
    return None


def resolve_variant(name: str, cpu_flags=None) -> str:
    """Turn a --variant word into a variant, checked against the CPU.

    "auto" picks the newest variant this CPU lists. A named variant is checked
    too: building an "avx2" engine on a machine without AVX2 compiles cleanly
    and then dies with SIGILL on the first tensor it loads, which is the
    measured defect this module exists to prevent. Building the oldest variant
    on a newer machine is always allowed - the requirements are a subset -
    which is exactly what CI does for the reference artifact.
    """
    flags = local_cpu_flags() if cpu_flags is None else set(cpu_flags)
    requested = (name or "").strip().lower()
    if requested in ("", "default"):
        requested = DEFAULT_VARIANT
    if requested == "auto":
        picked = best_variant(flags)
        if picked is None:
            raise SetupError(
                "this CPU lists no AVX, and every engine build from this project "
                "uses it - `astra-ai profile` shows what the CPU does list"
            )
        return picked
    if requested not in CPU_VARIANTS:
        raise SetupError(
            f"unknown engine variant: {name} - use {', '.join(CPU_VARIANTS)}, or auto"
        )
    missing = [f for f in VARIANT_REQUIREMENTS[requested] if f not in flags]
    if missing:
        runnable = best_variant(flags)
        if runnable is None:
            raise SetupError(
                f"this CPU does not list {', '.join(missing)}, nor AVX itself: no "
                "engine build from this project can run on it"
            )
        raise SetupError(
            f"this CPU does not list {', '.join(missing)}: an \"--variant {requested}\" "
            f"build would die with SIGILL on the first tensor it loads (the measured "
            f"2026-10-16 failure). Build for \"{runnable}\" instead, or use --variant auto"
        )
    return requested


def marker_path() -> Path:
    """Where the record of what the installed engines were built for lives."""
    return _config.PATHS.bin_dir / "ENGINE-BUILD.json"


def _write_marker(variant: str, targets: list[str]) -> Path:
    """Record the variant the engines now in bin_dir were built for.

    Written after a successful install, beside the binaries it describes, so
    `astra-ai status` can compare their requirements with this machine without
    parsing a binary. A `--build whisper` after a `--build llama` updates the
    marker to the newer build; a machine that wants the two halves to agree
    builds both in one command, which is also what CI and the docs say.
    """
    path = marker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "variant": variant,
                "requirements": list(VARIANT_REQUIREMENTS[variant]),
                "targets": sorted(targets),
                "built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def engine_build(cpu_flags=None) -> dict:
    """What the installed engines were built for, and whether this CPU can run it.

    Keys:

        variant      the recorded variant, or "" when nothing is recorded
        missing      requirements this CPU does not list (empty means runnable)
        built        the recorded build time, or ""

    Nothing recorded is the state for a machine that installed the binaries by
    hand; the answer then names nothing, because a claim about a binary that
    carries no record would be a guess.
    """
    try:
        data = json.loads(marker_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"variant": "", "missing": [], "built": ""}
    if not isinstance(data, dict):
        return {"variant": "", "missing": [], "built": ""}
    variant = str(data.get("variant") or "")
    requirements = data.get("requirements")
    if not isinstance(requirements, list):
        requirements = list(VARIANT_REQUIREMENTS.get(variant, ()))
    flags = local_cpu_flags() if cpu_flags is None else set(cpu_flags)
    missing = [str(f) for f in requirements if str(f) not in flags]
    return {"variant": variant, "missing": missing, "built": str(data.get("built") or "")}


def _progress(done: int, total: int) -> None:
    """One line, rewritten in place: a build log wants the final state only."""
    if total > 0:
        percent = int(done * 100 / total)
        print(f"\r  {percent:3d}%  {done / 1048576:8.1f} of {total / 1048576:.1f} MB", end="")
    else:
        print(f"\r  {done / 1048576:8.1f} MB", end="")
    sys.stdout.flush()


def _download(url: str, target: Path) -> None:
    """Fetch one file to `target`, with progress, then move it into place.

    Written to a .part file first so that a download interrupted half way
    leaves nothing that looks like a usable model. Content-Length is checked
    when the server sends one: the common failure is a truncated download over
    a flaky line, and a truncated GGUF makes llama-server say "failed to load
    model" with no hint about why.
    """
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "astra-ai/" + _config.VERSION + " (+AstraOS; model download)",
            "Accept": "application/octet-stream",
        },
    )

    part = target.with_name(target.name + ".part")
    target.parent.mkdir(parents=True, exist_ok=True)

    print(f"  from {url}")
    try:
        with urllib.request.urlopen(request, timeout=READ_TIMEOUT) as response:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            head = b""
            with open(part, "wb") as handle:
                while True:
                    chunk = response.read(262144)
                    if not chunk:
                        break
                    if not head:
                        head = chunk[:8]
                    handle.write(chunk)
                    done += len(chunk)
                    _progress(done, total)
        print()
    except urllib.error.HTTPError as exc:
        print()
        part.unlink(missing_ok=True)
        raise SetupError(
            f"the download failed: HTTP {exc.code} from {url} - the file may have "
            "been renamed upstream"
        ) from exc
    except (urllib.error.URLError, OSError) as exc:
        print()
        part.unlink(missing_ok=True)
        raise SetupError(f"the download failed: {exc}") from exc

    if total and done < total:
        part.unlink(missing_ok=True)
        raise SetupError(
            f"the download stopped early: {done} of {total} bytes - try again"
        )
    if head[:2] == b"<!" or head[:5].lower() == b"<html":
        part.unlink(missing_ok=True)
        raise SetupError(
            "the server sent a web page instead of a model file - the address is "
            "probably wrong"
        )
    if head and head[:4] == b"GGUF":
        pass  # the expected container for a llama.cpp model
    elif head and target.suffix == ".bin" and head[:4] not in (b"ggml", b"lmgg"):
        part.unlink(missing_ok=True)
        raise SetupError(
            "the file does not start with the magic bytes of a whisper model"
        )

    os.replace(part, target)
    try:
        target.chmod(0o644)
    except OSError:
        pass


def _remember(name: str, entry: dict, target: Path) -> None:
    """Record the user's explicit choice of a model, even when it was already there.

    The early return for an already-installed model used to skip this, so
    choosing the model the image ships left the settings untouched: harmless
    while it was the only model, and wrong the moment a second one arrives.
    """
    settings = _config.load_settings()
    if entry.get("kind") == "llm":
        settings["model"] = target.name
    else:
        settings["stt_model"] = name
    try:
        _config.save_settings(settings)
        print(f"settings updated: {_config.PATHS.config_file}")
    except OSError as exc:
        print(f"note: could not write {_config.PATHS.config_file}: {exc}")
        print(f"      use it with: --model {target}")


def install_model(name: str) -> Path:
    """Download one catalog model into models_dir and return its path.

    Already installed means already installed: the file is not fetched again,
    because a user who ran the command twice did not ask for two gigabytes of
    traffic. The choice is still recorded, because the command says which model
    the assistant should use. Delete the file to force a fresh download.
    """
    entry = MODELS.get(name)
    if entry is None:
        raise SetupError(
            f"unknown model: {name} - `astra-ai setup --list` shows the catalog"
        )

    target = model_path(name)
    if target.is_file() and target.stat().st_size > 0:
        print(f"already installed: {target}")
        _remember(name, entry, target)
        return target

    print(f"installing {name} (about {entry['size_mb']} MB, {entry['note']})")
    _download(entry["url"], target)

    size = target.stat().st_size
    print(f"installed: {target} ({size / 1048576:.1f} MB)")

    _remember(name, entry, target)
    return target


def _require_tools(names: list[str]) -> None:
    """Every tool a build needs, or one line naming all of the missing ones."""
    missing = [name for name in names if shutil.which(name) is None]
    if missing:
        packages = " ".join(missing)
        raise SetupError(
            f"missing build tools: {', '.join(missing)} - install them with: "
            f"astra install {packages}"
        )


def _run(argv: list[str], cwd: Path | None = None) -> None:
    """Run a build step with its output going straight to the terminal.

    Deliberately not captured: a twenty-minute compile that prints nothing
    looks like a hang, and the compiler's own error is better than any summary
    this code could write. The exit code is turned into a SetupError, which
    the CLI prints as one line.
    """
    print("  $ " + " ".join(argv))
    sys.stdout.flush()
    try:
        completed = subprocess.run(argv, cwd=str(cwd) if cwd else None)
    except FileNotFoundError as exc:
        raise SetupError(f"could not run {argv[0]}: it is not installed") from exc
    if completed.returncode != 0:
        raise SetupError(
            f"{Path(argv[0]).name} failed with exit code {completed.returncode} "
            "(its output is above)"
        )


def build_tools(which: str, variant: str = DEFAULT_VARIANT) -> None:
    """Build llama-server, whisper-cli, or both, from upstream source.

    `variant` is "avx" (the default), "avx2", or "auto" for the newest this
    CPU can run. resolve_variant() checks it against this machine's
    /proc/cpuinfo before anything is cloned, and the choice is recorded beside
    the installed binaries afterwards for `astra-ai status` to check.

    Sources are cloned into bin_dir/src, built there, and the finished
    binaries are copied into bin_dir. The build tree is left in place: a
    second run reuses it, and someone who wants to debug a failure needs the
    files that failed.
    """
    chosen = resolve_variant(variant)
    flags = CPU_VARIANTS[chosen]

    requested = (which or "").strip().lower()
    if requested in ("", "llama-server", "llama.cpp"):
        requested = "llama"
    if requested == "all":
        targets = ["llama", "whisper"]
    elif requested in SOURCES:
        targets = [requested]
    else:
        raise SetupError(f"unknown build target: {which} - use llama, whisper or all")

    _require_tools(["git", "cmake"])
    if shutil.which("c++") is None and shutil.which("g++") is None and shutil.which("clang++") is None:
        raise SetupError(
            "missing build tools: a C++ compiler - install one with: "
            "astra install build-essential"
        )

    jobs = str(max(1, min(4, os.cpu_count() or 2)))
    for target in targets:
        source = _config.PATHS.bin_dir / "src" / (target + ".cpp")
        build = _config.PATHS.bin_dir / "src" / (target + "-build")

        print(
            f"building {target} for variant {chosen} "
            f"(requires {', '.join(VARIANT_REQUIREMENTS[chosen])}; static binary)"
        )
        if (source / ".git").is_dir():
            print(f"  source already at {source}; updating it")
            _run(["git", "-C", str(source), "pull", "--ff-only"])
        else:
            source.parent.mkdir(parents=True, exist_ok=True)
            _run(["git", "clone", "--depth", "1", SOURCES[target], str(source)])

        build.mkdir(parents=True, exist_ok=True)
        configure = [
            "cmake", "-S", str(source), "-B", str(build),
            "-DCMAKE_BUILD_TYPE=Release",
            *flags,
        ]
        if target == "llama":
            # The server is a C++ program with no Python and no curl in it;
            # LLAMA_CURL=OFF keeps the build free of libcurl-dev.
            configure.append("-DLLAMA_CURL=OFF")
        _run(configure)

        # Target names moved between releases ("server" became "llama-server",
        # "main" became "whisper-cli"). Trying the new name first and the old
        # one second is cheaper than a version check, and the error when both
        # are missing still says which project failed to build.
        wanted = ["llama-server", "server"] if target == "llama" else ["whisper-cli", "main"]
        last_error = None
        for name in wanted:
            try:
                _run(["cmake", "--build", str(build), "--config", "Release",
                      "-j", jobs, "--target", name])
                last_error = None
                break
            except SetupError as exc:
                last_error = exc
        if last_error is not None:
            raise SetupError(
                f"{target} did not build: its build system has neither of the targets "
                f"{' and '.join(wanted)} this command knows"
            )

        installed = _install_binaries(build, target)
        for path in installed:
            print(f"installed: {path}")

    marker = _write_marker(chosen, targets)
    print(
        f"recorded: {marker} - the engines require "
        f"{', '.join(VARIANT_REQUIREMENTS[chosen])}, and `astra-ai status` checks "
        "this machine against that"
    )


def _install_binaries(build: Path, target: str) -> list[Path]:
    """Copy the freshly built programs out of the build tree into bin_dir."""
    names = ("llama-server", "whisper-cli", "whisper-cpp")
    found: list[Path] = []
    for name in names:
        candidates = [
            build / "bin" / name,
            build / "bin" / "Release" / name,
            build / "Release" / "bin" / name,
            build / "bin" / (name + ".exe"),
        ]
        for candidate in candidates:
            if candidate.is_file() and candidate not in found:
                destination = _config.PATHS.bin_dir / candidate.name
                shutil.copy2(candidate, destination)
                try:
                    destination.chmod(0o755)
                except OSError:
                    pass
                found.append(destination)
                break

    if not found:
        raise SetupError(
            f"{target} built, but no program was found in {build}/bin - the build "
            "layout has changed upstream"
        )
    return found
