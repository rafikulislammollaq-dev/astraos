"""The image really carries the assistant it says it carries.

This is a repository-consistency test, not a boot test. It checks the three
places that must agree for the claim to be true:

  * config/live-build/config/includes.chroot/etc/astraos/ai-bundle.conf pins an
    engine release and two model files by exact revision and SHA-256;
  * 0650-ai.hook.chroot fetches those exact values, checks every hash, and
    installs a selector that picks the engine variant this CPU can run;
  * the image's verify hook and the boot self-test assert the files and execute
    the pieces (Guard's audit chain, the model, the engine, the file tools).

A model URL that says /resolve/main/ is not pinned: it can change under the
build. A fetch that does not name its hash is not verified. Both are failures
here, because both would make the image's claim depend on a stranger's upload.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONF = (
    REPO_ROOT
    / "config"
    / "live-build"
    / "config"
    / "includes.chroot"
    / "etc"
    / "astraos"
    / "ai-bundle.conf"
)
HOOK = (
    REPO_ROOT
    / "config"
    / "live-build"
    / "config"
    / "hooks"
    / "live"
    / "0650-ai.hook.chroot"
)
VERIFY = (
    REPO_ROOT
    / "config"
    / "live-build"
    / "config"
    / "hooks"
    / "live"
    / "0700-verify.hook.chroot"
)
SMOKE = (
    REPO_ROOT
    / "config"
    / "live-build"
    / "config"
    / "includes.chroot"
    / "usr"
    / "local"
    / "sbin"
    / "astraos-smoke"
)
AI_DOC = REPO_ROOT / "docs" / "AI.md"

DESCRIPTION = (
    "The bundle is pinned by revision and SHA-256, every fetch is verified, and "
    "the image and boot self-test assert the assistant it ships"
)


def _settings() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in CONF.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Z0-9_]+)=\"([^\"]*)\"", line)
        assert match, f"ai-bundle.conf has an unparseable line: {line}"
        values[match.group(1)] = match.group(2)
    return values


def test_every_input_is_pinned_and_https() -> None:
    values = _settings()
    required = (
        "ASTRAOS_AI_ENGINE_AVX_URL",
        "ASTRAOS_AI_ENGINE_AVX_SHA256",
        "ASTRAOS_AI_ENGINE_AVX2_URL",
        "ASTRAOS_AI_ENGINE_AVX2_SHA256",
        "ASTRAOS_AI_MODEL_URL",
        "ASTRAOS_AI_MODEL_SHA256",
        "ASTRAOS_AI_MODEL_BYTES",
        "ASTRAOS_AI_WHISPER_URL",
        "ASTRAOS_AI_WHISPER_SHA256",
        "ASTRAOS_AI_WHISPER_BYTES",
    )
    missing = [name for name in required if not values.get(name)]
    assert not missing, f"ai-bundle.conf does not set {missing}"

    for name in (
        "ASTRAOS_AI_ENGINE_AVX_URL",
        "ASTRAOS_AI_ENGINE_AVX2_URL",
        "ASTRAOS_AI_MODEL_URL",
        "ASTRAOS_AI_WHISPER_URL",
    ):
        assert values[name].startswith("https://"), f"{name} is not https"
    for name in (
        "ASTRAOS_AI_ENGINE_AVX_SHA256",
        "ASTRAOS_AI_ENGINE_AVX2_SHA256",
        "ASTRAOS_AI_MODEL_SHA256",
        "ASTRAOS_AI_WHISPER_SHA256",
    ):
        assert re.fullmatch(r"[0-9a-f]{64}", values[name]), f"{name} is not a SHA-256"
    for name in ("ASTRAOS_AI_MODEL_BYTES", "ASTRAOS_AI_WHISPER_BYTES"):
        assert values[name].isdigit() and int(values[name]) > 0, f"{name} is not a size"

    assert "/releases/download/" in values["ASTRAOS_AI_ENGINE_AVX_URL"]
    for name in ("ASTRAOS_AI_MODEL_URL", "ASTRAOS_AI_WHISPER_URL"):
        assert re.search(r"/resolve/[0-9a-f]{40}/", values[name]), (
            f"{name} does not name a revision; /resolve/main/ can change under the build"
        )
        assert "/resolve/main/" not in values[name]

    assert int(values["ASTRAOS_AI_MODEL_BYTES"]) > 1_000_000_000, (
        "the executor is about 1 GB; a much smaller number is probably a mistake"
    )


def test_the_hook_verifies_every_fetch_before_installing_it() -> None:
    hook = HOOK.read_text(encoding="utf-8")
    assert "set -eu" in hook
    assert "sha256sum" in hook
    assert '[ "$got" = "$expected" ]' in hook, "the hook does not compare the hash"
    assert "return 1" in hook, "a checksum mismatch does not stop the fetch"

    for value in (
        "ASTRAOS_AI_ENGINE_AVX_URL",
        "ASTRAOS_AI_ENGINE_AVX_SHA256",
        "ASTRAOS_AI_ENGINE_AVX2_URL",
        "ASTRAOS_AI_ENGINE_AVX2_SHA256",
        "ASTRAOS_AI_MODEL_URL",
        "ASTRAOS_AI_MODEL_SHA256",
        "ASTRAOS_AI_WHISPER_URL",
        "ASTRAOS_AI_WHISPER_SHA256",
    ):
        assert f"${{{value}:-}}" in hook or f"${value}" in hook, (
            f"the hook never uses {value}"
        )
    assert "curl -fL" in hook, "a failed HTTP status must fail the fetch"
    assert "curl | sh" not in hook and "| sh" not in hook
    assert "tar -xzf" in hook and "--no-same-owner" in hook


def test_the_engine_selector_uses_the_flags_the_build_requires() -> None:
    hook = HOOK.read_text(encoding="utf-8")
    for flag in ("avx2", "f16c", "fma", "bmi2", "avx"):
        assert flag in hook, f"the selector never checks {flag}"
    assert "/usr/lib/astraos/ai/engine/avx2/@PROGRAM@" in hook
    assert "/usr/lib/astraos/ai/engine/avx/@PROGRAM@" in hook
    assert "exec " in hook, "the wrapper does not exec the engine"
    assert "this CPU has no AVX" in hook, "a CPU with no AVX gets SIGILL, not a message"


def test_the_image_and_the_boot_self_test_assert_the_bundle() -> None:
    verify = VERIFY.read_text(encoding="utf-8")
    assert "Spark-X2.5-1.7B-Q4_K_M.gguf" in verify
    assert "ggml-tiny.en.bin" in verify
    assert "/usr/lib/astraos/ai/engine/avx/llama-server" in verify
    assert "/usr/lib/astraos/ai/engine/avx2/llama-server" in verify
    assert "/usr/local/bin/llama-server" in verify

    smoke = SMOKE.read_text(encoding="utf-8")
    for check in ("ai-bundle", "ai-engine", "ai-guard", "ai-guard-chain", "ai-files"):
        assert f'"{check}"' in smoke, f"the boot self-test does not check {check}"
    assert "Spark-X2.5-1.7B-Q4_K_M.gguf" in smoke
    assert "guard.verify()" in smoke
    assert "ASTRAOS_FILES_HOME" in smoke


def test_the_documentation_says_the_image_ships_a_model() -> None:
    text = AI_DOC.read_text(encoding="utf-8")
    assert "ships the executor" in text, (
        "docs/AI.md still leaves the reader expecting an empty image"
    )
    assert "Nothing is fetched when the package is installed" not in text, (
        "docs/AI.md still says nothing is fetched, but the image build fetches the model"
    )


def test_the_iso_validator_looks_for_the_bundle_inside_the_squashfs() -> None:
    """A structural check of the ISO surface cannot see a missing model.

    `scripts/validate-iso.sh` already looks inside the live filesystem for the
    assistant command. These are the bytes that command needs to answer with no
    network; a build that skipped the fetch hook must fail validation, not ship a
    smaller image that claims to be complete.
    """
    validator = (REPO_ROOT / "scripts" / "validate-iso.sh").read_text(encoding="utf-8")
    expected = (
        "squashfs-root/etc/astraos/ai-bundle.conf",
        "squashfs-root/usr/share/astraos/ai/models/Spark-X2.5-1.7B-Q4_K_M.gguf",
        "squashfs-root/usr/share/astraos/ai/models/ggml-tiny.en.bin",
        "squashfs-root/usr/lib/astraos/ai/engine/avx/llama-server",
        "squashfs-root/usr/lib/astraos/ai/engine/avx2/llama-server",
        "squashfs-root/usr/local/bin/llama-server",
        "squashfs-root/usr/local/bin/whisper-cli",
        "squashfs-root/usr/share/doc/astraos-ai/NOTICE",
    )
    missing = [path for path in expected if path not in validator]
    assert not missing, f"validate-iso.sh does not look for {missing}"
