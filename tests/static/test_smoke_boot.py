"""Boot self-test tests.

scripts/smoke-boot.sh is the only thing in this repository that boots the ISO it builds,
and config/live-build/config/includes.chroot ships the guest half of that test. Both
halves lie if they are edited carelessly, so the cheap invariants are asserted here
rather than being discovered an ISO build later:

  * the QEMU command line must mirror the live identity in config/distribution.env
    rather than retype it - a divergence there boots a different system than the ISO's
    own boot entry would have booted, and the difference would be invisible;
  * the guest's output contract (the markers scripts/smoke-boot.sh greps for) must be
    kept, or a PASS image fails the workflow for the wrong reason;
  * the self-test must never run during a normal boot: the unit is gated on "astraos.ci",
    because a mechanical power-off on a user's desktop is not a feature;
  * a non-executable script inside the image would fail the self-test for a reason that
    has nothing to do with the image, so the staging step must set the mode itself - a
    checkout on a Windows filesystem cannot carry the executable bit.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DESCRIPTION = (
    "the boot self-test boots the built ISO, mirrors the live identity, and never runs "
    "on a normal boot"
)

HOST_SCRIPT = REPO_ROOT / "scripts" / "smoke-boot.sh"
INCLUDES = REPO_ROOT / "config" / "live-build" / "config" / "includes.chroot"
GUEST_SCRIPT = INCLUDES / "usr" / "local" / "sbin" / "astraos-smoke"
UNIT = INCLUDES / "etc" / "systemd" / "system" / "astraos-smoke.service"
SELF_TEST_DOC = INCLUDES / "usr" / "share" / "astraos" / "SELF-TEST.txt"
SERVICES_HOOK = (
    REPO_ROOT / "config" / "live-build" / "config" / "hooks" / "live"
    / "0400-services.hook.chroot"
)
COMPAT_HOOK = (
    REPO_ROOT / "config" / "live-build" / "config" / "hooks" / "live"
    / "0900-compat.hook.chroot"
)
CONFIGURE = REPO_ROOT / "scripts" / "configure-live-build.sh"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "build-iso.yml"
HARDWARE_LIST = REPO_ROOT / "config" / "package-lists" / "35-hardware.list.chroot"
COMPAT_LIST = REPO_ROOT / "config" / "package-lists" / "45-compatibility.list.chroot"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_the_host_script_boots_with_the_self_test_switch() -> None:
    text = _text(HOST_SCRIPT)
    assert "astraos.ci=1" in text, "the self-test switch is what makes the image check itself"
    assert "console=ttyS0" in text, "without a serial console the result cannot be read"
    assert "findiso=/live/filesystem.squashfs" in text, (
        "the live medium must be found explicitly: no bootloader config ran"
    )


def test_the_host_script_takes_the_live_identity_from_distribution_env() -> None:
    text = _text(HOST_SCRIPT)
    assert "config/distribution.env" in text
    for name in ("ASTRAOS_LIVE_USER", "ASTRAOS_LIVE_FULLNAME", "ASTRAOS_LIVE_HOSTNAME"):
        assert name in text, f"{name} must come from the single definition of the identity"
    assert "username=astra" not in text, (
        "the live user is retyped here instead of read from config/distribution.env; "
        "the QEMU boot would then diverge from the ISO's own boot entry"
    )


def test_the_host_script_prefers_kvm_and_can_fall_back() -> None:
    text = _text(HOST_SCRIPT)
    assert "/dev/kvm" in text
    assert "-enable-kvm" in text
    assert "-cpu max" in text, "emulation is the fallback and needs its own CPU model"


def test_the_host_script_only_passes_on_a_pass_result() -> None:
    text = _text(HOST_SCRIPT)
    assert "ASTRAOS-SMOKE: RESULT:" in text
    assert "RESULT: PASS" in text
    assert "exit 1" in text, "a missing or failed result must fail the script"


def test_the_host_script_screenshots_through_the_qemu_monitor() -> None:
    text = _text(HOST_SCRIPT)
    assert "screendump" in text
    assert "monitor.sock" in text, "the monitor socket is how the screenshot is requested"


def test_the_guest_self_test_keeps_the_output_contract() -> None:
    text = _text(GUEST_SCRIPT)
    assert text.startswith("#!/bin/sh")
    for marker in (
        "ASTRAOS-SMOKE: ok ",
        "ASTRAOS-SMOKE: FAIL ",
        "RESULT: PASS",
        "RESULT: FAIL",
    ):
        assert marker in text, f"the output contract marker {marker!r} is missing"


def test_the_guest_self_test_ends_by_powering_the_machine_off() -> None:
    assert "systemctl poweroff" in _text(GUEST_SCRIPT), (
        "the power-off is the caller's signal that the guest is finished"
    )


def test_the_unit_runs_only_with_the_switch() -> None:
    text = _text(UNIT)
    assert "ConditionKernelCommandLine=astraos.ci" in text, (
        "without the condition the self-test would run on user machines"
    )
    assert "ExecStart=/usr/local/sbin/astraos-smoke" in text


def test_the_services_hook_enables_the_self_test_unit() -> None:
    assert "enable_unit astraos-smoke.service" in _text(SERVICES_HOOK), (
        "the unit is inert without the condition, but it must be pulled into the boot "
        "transaction for the condition to ever be evaluated"
    )


def test_staging_sets_the_self_test_mode_explicitly() -> None:
    text = _text(CONFIGURE)
    assert "config/includes.chroot" in text, (
        "config/live-build/config/includes.chroot must be staged into the build tree"
    )
    assert "astraos-smoke" in text and "chmod 0755" in text, (
        "the script's executable bit must be set by the staging step: a checkout on a "
        "Windows filesystem cannot carry one"
    )


def test_the_iso_workflow_runs_the_boot_self_test() -> None:
    text = _text(WORKFLOW)
    assert "smoke-boot:" in text
    assert "scripts/smoke-boot.sh" in text
    assert "smoke_boot" in text, "the job must be switchable from the manual trigger"
    assert "astraos-boot-self-test" in text, "the evidence artifact must be uploaded"


def test_the_compatibility_lists_ship_what_they_claim() -> None:
    hardware = _text(HARDWARE_LIST)
    for package in (
        "fwupd",
        "zram-tools",
        "intel-media-va-driver",
        "vainfo",
        "ntfs-3g",
        "exfatprogs",
    ):
        assert package in hardware, f"{package} is missing from 35-hardware.list.chroot"
    compat = _text(COMPAT_LIST)
    for package in (
        "flatpak",
        "wine",
        "libavcodec-extra",
        "ffmpeg",
        "timeshift",
        "gdebi",
    ):
        assert package in compat, f"{package} is missing from 45-compatibility.list.chroot"


def test_the_flathub_hook_only_points_at_the_store() -> None:
    text = _text(COMPAT_HOOK)
    assert "https://flathub.org/repo/flathub.flatpakrepo" in text
    assert "flatpak install" not in text, (
        "the hook may point at Flathub, never install an application in the build"
    )
