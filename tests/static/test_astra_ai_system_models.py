"""The model the image ships is found before anyone downloads anything.

What this file is for:

  * A model in the image's read-only directory is a model the assistant can
    use. `config.model_file()` returns it with no setting, `tiers.pick_model()`
    sees it, `setup.describe()` reports it, and the speech path finds the
    whisper file beside it.
  * A user's download shadows the image's copy of the *same name*, and is never
    counted as a second model; two differently named models still require a
    choice, exactly as before.
  * `astra-ai setup --model` on a model the image already has does not download
    a second gigabyte: it reuses the image's copy and records the choice.

The tests replace the three PATHS attributes rather than the process home, and
restore them however the test ends. A test that writes into the developer's
~/.local/share/astraos would pass on this machine and fail on a clean one.
"""

from __future__ import annotations

import contextlib
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_LIB = REPO_ROOT / "packages" / "astraos-ai" / "root" / "usr" / "lib"
if str(AI_LIB) not in sys.path:
    sys.path.insert(0, str(AI_LIB))

from astraos.ai import config, setup, tiers, voice  # noqa: E402

DESCRIPTION = (
    "The image's model is discovered by config, tiers, setup and voice, and a "
    "user's copy of the same name wins without counting twice"
)

SPARK = "Spark-X2.5-1.7B-Q4_K_M.gguf"
WHISPER = "ggml-tiny.en.bin"


@contextlib.contextmanager
def _paths(root: Path):
    """Point the user, image and settings paths at a temporary tree."""
    previous = (
        config.PATHS.models_dir,
        config.PATHS.system_models_dir,
        config.PATHS.config_file,
    )
    config.PATHS.models_dir = root / "user"
    config.PATHS.system_models_dir = root / "image"
    config.PATHS.config_file = root / "ai.json"
    (root / "user").mkdir()
    (root / "image").mkdir()
    try:
        yield root
    finally:
        (
            config.PATHS.models_dir,
            config.PATHS.system_models_dir,
            config.PATHS.config_file,
        ) = previous


def _write(path: Path, text: str = "model") -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_the_image_model_is_found_with_no_setting() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-models-") as tmp:
        with _paths(Path(tmp)) as root:
            bundled = _write(root / "image" / SPARK)

            assert config.model_file({}) == bundled
            assert config.model_name({}) == SPARK
            assert config.installed_models()[SPARK] == bundled


def test_the_users_copy_of_the_same_name_wins_and_is_not_a_second_model() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-models-") as tmp:
        with _paths(Path(tmp)) as root:
            _write(root / "image" / SPARK, "shipped")
            downloaded = _write(root / "user" / SPARK, "downloaded")

            assert config.model_file({}) == downloaded
            assert config.model_file({"model": SPARK}) == downloaded
            assert list(config.installed_models()) == [SPARK]


def test_two_different_models_still_need_a_choice() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-models-") as tmp:
        with _paths(Path(tmp)) as root:
            bundled = _write(root / "image" / SPARK)
            other = _write(root / "user" / "qwen2.5-3b-instruct-q4_k_m.gguf")

            assert config.model_file({}) is None
            assert config.model_file({"model": SPARK}) == bundled
            assert config.model_file({"model": other.name}) == other


def test_the_tiers_see_the_image_model() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-models-") as tmp:
        with _paths(Path(tmp)) as root:
            _write(root / "image" / SPARK)

            assert tiers._installed_models() == [SPARK]
            assert tiers.pick_model("worker", {}) == SPARK


def test_setup_reports_the_image_model_as_installed() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-models-") as tmp:
        with _paths(Path(tmp)) as root:
            bundled = _write(root / "image" / SPARK)

            assert setup.model_path("spark-x2.5-1.7b-q4_k_m") == bundled
            described = setup.describe()
            assert described["model"] == SPARK
            assert described["model_file"] == str(bundled)
            assert described["model_present"] is True
            assert SPARK in described["installed"]


def test_setup_does_not_download_a_model_the_image_already_has() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-models-") as tmp:
        with _paths(Path(tmp)) as root:
            bundled = _write(root / "image" / SPARK)

            installed = setup.install_model("spark-x2.5-1.7b-q4_k_m")

            assert installed == bundled
            assert not (root / "user" / SPARK).exists(), (
                "setup copied the image's model into the user's directory"
            )
            assert config.load_settings()["model"] == SPARK


def test_voice_finds_the_image_speech_model() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-models-") as tmp:
        with _paths(Path(tmp)) as root:
            speech = _write(root / "image" / WHISPER, "speech")

            assert voice._stt_model_path() == speech
