"""Tests for the machine capability profile.

What these tests pin, and why:

  * The collector reads files under an explicit root, so it is testable against a
    fixture tree and auditable against the files it claims to read. If it ever
    turns into a subprocess call or a privileged probe, this test stops being
    possible - which is the point.
  * "avx2" must never satisfy "avx": the engine builds this release ships are
    compiled with AVX on and AVX2/F16C/FMA/BMI2 off (setup.py), for the Sandy
    Bridge target, so reading that distinction wrong is the difference between a
    working assistant and a SIGILL.
  * The readiness rung is derived from the measurements against the model
    ladder's documented sizes: the reference machine shape must come out
    "ready", a no-AVX machine "unsupported", a small one "tight".
  * The recommendation is a pure function of the same numbers: the flags choose
    the engine build, and the RAM and free space choose how far up the ladder the
    machine can go. The reference machine must get the avx build and the worker
    rung - never the 4B middle brain it does not have the RAM to hold.
  * The command (`astra-ai profile`), the first-run write (`astra-ai status`) and
    the boot self-test's live check (`ai-profile`) are parts of one promise and
    are pinned here together.
"""

import importlib.util
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE = REPO_ROOT / "packages" / "astraos-ai"
MACHINE_PY = PACKAGE / "root" / "usr" / "lib" / "astraos" / "ai" / "machine.py"
CONFIG_PY = PACKAGE / "root" / "usr" / "lib" / "astraos" / "ai" / "config.py"
CLI = PACKAGE / "root" / "usr" / "bin" / "astra-ai"
SMOKE = (
    REPO_ROOT / "config" / "live-build" / "config" / "includes.chroot"
    / "usr" / "local" / "sbin" / "astraos-smoke"
)
SELF_TEST = (
    REPO_ROOT / "config" / "live-build" / "config" / "includes.chroot"
    / "usr" / "share" / "astraos" / "SELF-TEST.txt"
)

SANDY_BRIDGE = "Intel(R) Core(TM) i5-2500S CPU @ 2.70GHz"

_LOADED: dict[str, object] = {}


def _load_machine():
    """Import machine.py once; it is stdlib-only, so no sibling stubs are needed."""
    if "module" in _LOADED:
        return _LOADED["module"]
    assert MACHINE_PY.is_file(), f"the module is missing: {MACHINE_PY}"
    spec = importlib.util.spec_from_file_location("astraos_ai_machine_under_test", MACHINE_PY)
    assert spec is not None and spec.loader is not None, f"cannot load {MACHINE_PY}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _LOADED["module"] = module
    return module


def _fixture(
    root: Path,
    *,
    flags: str = "avx sse4_2 popcnt",
    cores: int = 4,
    ram_kib: int = 4_000_000,
    swap_kib: int = 0,
    card: bool = True,
    accelerator: bool = False,
    audio: bool = True,
) -> Path:
    """A machine tree shaped like the reference machine (Sandy Bridge, 4 GB)."""
    (root / "proc").mkdir(parents=True, exist_ok=True)
    blocks = []
    for index in range(cores):
        block = f"processor\t: {index}\n"
        if index == 0:
            block += f"model name\t: {SANDY_BRIDGE}\n"
            block += f"flags\t\t: fpu {flags} lm\n"
        blocks.append(block)
    (root / "proc" / "cpuinfo").write_text("\n".join(blocks), encoding="utf-8")
    (root / "proc" / "meminfo").write_text(
        f"MemTotal:       {ram_kib} kB\nSwapTotal:      {swap_kib} kB\n",
        encoding="utf-8",
    )
    if audio:
        (root / "proc" / "asound").mkdir(parents=True, exist_ok=True)
        (root / "proc" / "asound" / "cards").write_text(
            " 0 [PCH            ]: HDA-Intel - HDA Intel PCH\n", encoding="utf-8"
        )
    if card:
        device = root / "sys" / "class" / "drm" / "card0" / "device"
        device.mkdir(parents=True, exist_ok=True)
        (device / "vendor").write_text("0x8086\n", encoding="utf-8")
        (device / "device").write_text("0x0102\n", encoding="utf-8")
    if accelerator:
        (root / "sys" / "class" / "accel" / "accel0").mkdir(parents=True, exist_ok=True)
    return root


def _profile(**overrides) -> dict:
    """A ready-shaped profile for pure assess() tests (measured values injected)."""
    base = {
        "cpu": {
            "name": "test",
            "cores": 2,
            "instructions": ["avx", "sse4_2"],
            "missing_instructions": ["avx2"],
        },
        "memory": {"ram_kib": 4_000_000, "swap_kib": 0},
        "graphics": {"cards": ["card0"], "first": "0x8086:0x0102"},
        "accelerators": [],
        "audio": ["one"],
        "storage": {"free_bytes": 100 * 1024 ** 3},
    }
    base.update(overrides)
    return base


def test_the_reference_machine_is_measured_correctly() -> None:
    machine = _load_machine()
    with tempfile.TemporaryDirectory(prefix="astraos-ai-machine-") as tmp:
        profile = machine.collect(root=_fixture(Path(tmp)))
        cpu = profile["cpu"]
        assert cpu["name"] == SANDY_BRIDGE
        assert cpu["cores"] == 4
        assert cpu["instructions"] == ["avx", "sse4_2"]
        assert "avx2" in cpu["missing_instructions"]
        assert profile["memory"]["ram_kib"] == 4_000_000
        assert profile["graphics"]["cards"] == ["card0"]
        assert profile["graphics"]["first"] == "0x8086:0x0102"
        assert profile["accelerators"] == []
        assert profile["audio"] and "HDA Intel PCH" in profile["audio"][0]
        assert "rung" in profile["readiness"]


def test_avx2_in_the_flags_line_never_satisfies_avx() -> None:
    """The engine builds require AVX and are compiled with AVX2 off.

    A flags line that says "avx2" but not "avx" must come out unsupported.
    """
    machine = _load_machine()
    with tempfile.TemporaryDirectory(prefix="astraos-ai-machine-") as tmp:
        profile = machine.collect(root=_fixture(Path(tmp), flags="avx2 f16c fma bmi2"))
    assert "avx" in profile["cpu"]["missing_instructions"]
    assert "avx2" in profile["cpu"]["instructions"]
    assert profile["readiness"]["rung"] == "unsupported"


def test_the_rungs_are_derived_from_the_measurements() -> None:
    machine = _load_machine()

    ready = machine.assess(_profile())
    assert ready["rung"] == "ready"

    no_avx = machine.assess(
        _profile(
            cpu={
                "name": "test",
                "cores": 2,
                "instructions": ["sse4_2"],
                "missing_instructions": ["avx"],
            }
        )
    )
    assert no_avx["rung"] == "unsupported"

    small = machine.assess(_profile(memory={"ram_kib": 2_000_000, "swap_kib": 0}))
    assert small["rung"] == "tight"
    assert any("RAM" in reason for reason in small["why"])

    crowded = machine.assess(_profile(storage={"free_bytes": 1 * 1024 ** 3}))
    assert crowded["rung"] == "tight"
    assert any("free on /" in reason for reason in crowded["why"])


def test_plain_words_show_the_machine_and_the_readiness() -> None:
    machine = _load_machine()
    with tempfile.TemporaryDirectory(prefix="astraos-ai-machine-") as tmp:
        profile = machine.collect(root=_fixture(Path(tmp)))
    text = "\n".join(machine.plain_words(profile))
    assert SANDY_BRIDGE in text
    assert "Instructions  avx, sse4_2" in text
    assert "Not reported" in text and "avx2" in text
    assert "AI readiness" in text


def test_the_profile_is_written_and_read_back() -> None:
    machine = _load_machine()
    with tempfile.TemporaryDirectory(prefix="astraos-ai-machine-") as tmp:
        root = Path(tmp)
        profile = machine.collect(root=_fixture(root / "machine"))
        target = root / "state" / "astraos" / "machine.json"
        path = machine.write(profile, target, now="2026-10-16T00:00:00+0000")
        assert path == target and target.is_file()
        loaded = machine.load(target)
        assert loaded is not None
        assert loaded["generated_at"] == "2026-10-16T00:00:00+0000"
        assert loaded["generated_by"] == "astra-ai profile"
        assert loaded["cpu"]["name"] == SANDY_BRIDGE
        assert machine.load(root / "missing.json") is None


def test_the_profile_lives_beside_the_settings() -> None:
    text = CONFIG_PY.read_text(encoding="utf-8")
    assert "profile_file" in text
    assert "ASTRAOS_AI_PROFILE" in text
    assert "machine.json" in text


def test_the_cli_has_the_profile_command() -> None:
    text = CLI.read_text(encoding="utf-8")
    assert "from astraos.ai import machine" in text
    assert "def cmd_profile(" in text
    assert 'sub.add_parser("profile"' in text
    assert "machine.write(profile, config.PATHS.profile_file)" in text
    # status writes the profile at first run and names where it lives
    assert "if machine.load(profile_path) is None:" in text
    assert "profile_path if profile_path.exists()" in text


def test_the_self_test_measures_the_profile_as_the_live_user() -> None:
    text = SMOKE.read_text(encoding="utf-8")
    assert 'runuser -u "$LIVE_USER" -- astra-ai profile' in text
    assert 'ok "ai-profile"' in text
    assert 'bad "ai-profile"' in text
    assert "s/^written to //p" in text


def test_the_self_test_text_explains_the_check() -> None:
    text = SELF_TEST.read_text(encoding="utf-8")
    assert "ai-profile" in text
    assert "never as root" in text


def test_the_recommendation_chooses_the_build_and_the_rung_from_the_numbers() -> None:
    """Stage 2's promise: the assistant picks its own build and models.

    The reference machine is the one this distribution is tested on - Sandy Bridge,
    AVX and no AVX2, 4 GiB of RAM. It must get the avx build (the avx2 build would
    SIGILL) and the worker rung, and must NOT be told to install the 4B middle
    brain, which wants 6 GiB. A machine that really has Haswell-class flags and
    16 GiB is the other half: avx2 and the whole ladder.
    """
    machine = _load_machine()

    reference = machine.recommend(_profile())
    assert reference["engine_variant"] == "avx"
    assert reference["rung"] == "worker"
    assert [entry["tier"] for entry in reference["models"]] == ["worker", "router"]
    assert any("avx" in reason for reason in reference["why"])

    haswell = machine.recommend(
        _profile(
            cpu={
                "name": "test",
                "cores": 8,
                "instructions": ["avx", "avx2", "f16c", "fma", "bmi2", "sse4_2"],
                "missing_instructions": [],
            },
            memory={"ram_kib": 16 * 1024 * 1024, "swap_kib": 0},
        )
    )
    assert haswell["engine_variant"] == "avx2"
    assert haswell["rung"] == "full"
    assert [entry["tier"] for entry in haswell["models"]] == [
        "worker",
        "brain",
        "router",
    ]


def test_the_recommendation_says_no_rather_than_pretending() -> None:
    """Every refusal names the number that decided it, and offers no model."""
    machine = _load_machine()

    no_avx = machine.recommend(
        _profile(
            cpu={
                "name": "test",
                "cores": 2,
                "instructions": ["sse4_2"],
                "missing_instructions": ["avx"],
            }
        )
    )
    assert no_avx["rung"] == "none"
    assert no_avx["engine_variant"] is None
    assert no_avx["models"] == []

    tiny = machine.recommend(_profile(memory={"ram_kib": 1_500_000, "swap_kib": 0}))
    assert tiny["rung"] == "none" and tiny["models"] == []
    assert any("RAM" in reason for reason in tiny["why"])

    crowded = machine.recommend(_profile(storage={"free_bytes": 1 * 1024 ** 3}))
    assert crowded["rung"] == "none" and crowded["models"] == []
    assert any("free on /" in reason for reason in crowded["why"])


def test_the_written_profile_carries_the_choice_and_the_cli_shows_it() -> None:
    """The choice is written down with the measurements, not recomputed from taste."""
    machine = _load_machine()
    profile = _profile()
    profile["readiness"] = machine.assess(profile)
    profile["recommendation"] = machine.recommend(profile)

    with tempfile.TemporaryDirectory(prefix="astraos-ai-machine-") as tmp:
        target = Path(tmp) / "state" / "astraos" / "machine.json"
        machine.write(profile, target, now="2026-10-19T00:00:00+0000")
        loaded = machine.load(target)
    assert loaded is not None
    assert loaded["recommendation"]["rung"] == "worker"
    assert loaded["recommendation"]["engine_variant"] == "avx"

    text = "\n".join(machine.plain_words(loaded))
    assert "AI rung       worker" in text
    assert "Engine build  avx" in text
    assert "spark-x2.5-1.7b-q4_k_m" in text

    cli = CLI.read_text(encoding="utf-8")
    assert "machine.recommend(profile)" in cli
    assert 'print(f"  ai rung' in cli
