"""Boot-menu tests.

scripts/boot-menu-test.sh boots the built ISO the way a machine does: QEMU's own
firmware starts the ISO's boot record (BIOS) or EFI system partition (UEFI), the
bootloader's menu appears, and its default entry boots the kernel with the command line
the menu itself carries. scripts/smoke-boot.sh covers the kernel and the live system
with a kernel the host supplied; the menu path a user's firmware actually takes is what
this exercise covers.

The pins here are the ones that make the exercise mean something:

  * the guest must be started by the ISO's own boot path: no kernel, no initrd and no
    command line on the QEMU command line - if the host supplies any of them, the
    exercise silently degrades into the smoke test it exists to complement;
  * the serial console is where the evidence lives, and only the shipped menu entries
    can put it there: console=ttyS0 must be part of LIVE_APPEND, so a boot that reaches
    the login prompt proves the ISO's own entries are right;
  * astraos.ci must never reach LIVE_APPEND or the menu script's executable text: it
    makes the guest run the self-test and power itself off, which is a CI behavior, not
    a desktop one;
  * the workflow runs every firmware path and keeps every log, and the Secure Boot run
    must actually enforce signatures - OVMF's secboot firmware plus the Microsoft-key
    variable store - or fail loudly: a blank key store would leave the run proving
    nothing while looking green;
  * the secure run must also be able to start at all: OVMF's secboot build is
    SMM_REQUIRE and stops without a byte of output on a machine that has no SMM, so
    its QEMU command line carries the Q35 machine, the SMM-protected pflash global
    and S3 disabled - the first two secure attempts each burned their whole wait on
    a screen that was never initialized, which reads like a slow boot and is not one.

Comment lines are stripped before the script's executable text is checked, following
the repository's rule that a script's comments may explain a trap in prose while its
code must not commit the mistake being explained.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DESCRIPTION = (
    "the boot-menu exercise boots the ISO through its own bootloaders and keeps the "
    "menu path honest"
)

MENU_SCRIPT = REPO_ROOT / "scripts" / "boot-menu-test.sh"
AUTO_CONFIG = REPO_ROOT / "config" / "live-build" / "auto" / "config"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "build-iso.yml"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _code(path: Path) -> str:
    """The file's executable text: comment-only lines removed."""
    return "\n".join(
        line for line in _text(path).splitlines() if not line.lstrip().startswith("#")
    )


def _live_append() -> str:
    match = re.search(r'LIVE_APPEND="([^"]*)"', _text(AUTO_CONFIG))
    assert match, "LIVE_APPEND is no longer defined in config/live-build/auto/config"
    return match.group(1)


def test_the_menu_script_boots_the_isos_own_path_not_a_supplied_kernel() -> None:
    code = _code(MENU_SCRIPT)
    assert "-cdrom" in code and "-boot d" in code, (
        "the ISO must be attached as a bootable CD-ROM: that is how the firmware finds "
        "the boot record"
    )
    for token in ("-kernel", "-initrd", "-append"):
        assert token not in code, (
            f"the QEMU command line carries {token!r}: the guest would be started with "
            "a kernel, an initrd or a command line that the host supplied, so the ISO's "
            "own boot path - the thing this exercise exists to prove - would never run"
        )


def test_the_shipped_menu_entries_carry_the_serial_console() -> None:
    live_append = _live_append()
    assert "console=ttyS0,115200n8" in live_append, (
        "the exercise's pass condition is the login prompt on the serial console, and "
        "only the menu entry itself can put it there: console=ttyS0 must be part of "
        "LIVE_APPEND (it is also the serial-console debugging path on hardware that has "
        "a serial port)"
    )
    assert "astraos.ci" not in live_append, (
        "the self-test switch must never ship in the boot menus: it makes the guest "
        "power the machine off, which is a CI behavior, not a desktop one"
    )


def test_the_menu_script_never_carries_the_self_test_switch() -> None:
    assert "astraos.ci" not in _code(MENU_SCRIPT), (
        "the menu exercise's code must not add the self-test switch: it boots the "
        "shipped default entry and stops at the login prompt"
    )


def test_the_default_entry_is_accepted_through_the_monitor() -> None:
    code = _code(MENU_SCRIPT)
    assert "sendkey ret" in code, (
        "nothing presses Enter for the menu's default entry, so the exercise would "
        "silently depend on live-build's own menu timeout"
    )
    assert "monitor.sock" in code, "the monitor socket is how the keypress is delivered"


def test_a_failed_boot_keeps_a_capture_of_the_guest_screen() -> None:
    code = _code(MENU_SCRIPT)
    assert "screendump" in code, (
        "a boot that fails before the kernel starts (a firmware refusing the medium, a "
        "bootloader that never appears) draws its reason on the graphical console only; "
        "without a capture the failure is an empty serial log and a guess"
    )
    assert "monitor.sock" in code, "the capture goes through QEMU's monitor socket"
    assert "screen.ppm" in code, (
        "the capture must be kept with the rest of the evidence, not thrown away with "
        "the work directory"
    )


def test_the_script_waits_for_the_live_systems_login_prompt() -> None:
    code = _code(MENU_SCRIPT)
    assert "config/distribution.env" in code and "ASTRAOS_LIVE_HOSTNAME" in code, (
        "the expected prompt must come from the single definition of the live identity"
    )
    assert "BOOT FAILED!" in code and "Kernel panic" in code, (
        "a boot that died in the initramfs or the kernel must be reported immediately, "
        "not by burning the whole wait"
    )
    assert "exit 1" in code, "a missing login prompt must fail the script"
    match = re.search(r"TIMEOUT_MINUTES=(\d+)", code)
    assert match and int(match.group(1)) >= 20, (
        "the measured emulated boot to the login prompt was about 144 s through the "
        "smoke path and the menu path adds firmware and the bootloader in front of "
        "that; the wait must stay far above the measurement because runner speeds vary"
    )


def test_the_efi_run_uses_the_matched_ovmf_pair() -> None:
    code = _code(MENU_SCRIPT)
    assert "OVMF" in code and "if=pflash" in code, (
        "the UEFI path needs OVMF attached as pflash code plus a writable variable "
        "store; the two must be a matched pair"
    )
    assert "ovmf package" in code, "the failure message must name the package to install"


def test_the_secure_run_enforces_signatures_or_fails() -> None:
    """Secure Boot enforcement is the whole point: a soft run would prove nothing."""
    code = _code(MENU_SCRIPT)
    assert "bios|efi|secure" in code, "the secure medium is gone from the script"
    assert "secboot" in code, (
        "the secure run must use OVMF's Secure Boot firmware (secboot); the plain "
        "build verifies nothing"
    )
    assert "OVMF_VARS_4M.ms.fd" in code or "OVMF_VARS.ms.fd" in code, (
        "Secure Boot is enforced only with the Microsoft keys enrolled in the variable "
        "store; the run must use that store"
    )
    assert "the run would prove nothing" in code, (
        "a missing Microsoft-key store must fail the run loudly - falling back to a "
        "blank store would leave Secure Boot unenforced and the evidence worthless"
    )
    assert "firmware.txt" in code and "sha256sum" in code, (
        "the exact firmware pair and its hashes must be kept with the evidence, so the "
        "run can be audited"
    )
    assert "-machine" in code and "q35,smm=on" in code, (
        "OVMF's secboot firmware is built with SMM_REQUIRE: on a machine without SMM it "
        "stops before it draws or prints anything, which reads as a hang (both earlier "
        "secure attempts died exactly that way: an empty serial log and a screen that "
        "was never initialized)"
    )
    assert "driver=cfi.pflash01,property=secure,value=on" in code, (
        "the pflash must be the SMM-protected one; that global is what libvirt adds "
        "for the same firmware, because Secure Boot's variable locking depends on it"
    )
    assert "ICH9-LPC.disable_s3=1" in code, (
        "S3 resume is the one path OVMF's SMM code does not come back from under "
        "emulation; every documented Secure Boot invocation disables it"
    )


def test_the_image_carries_the_signed_secure_boot_chain() -> None:
    text = _text(AUTO_CONFIG)
    assert "--uefi-secure-boot enable" in text, (
        "the image must ask live-build for the signed chain; without it the ISO is "
        "unsigned and a Secure Boot machine refuses it before any menu appears"
    )
    assert "--uefi-secure-boot disable" not in text
    bootstrap = _text(REPO_ROOT / "scripts" / "bootstrap-build-environment.sh")
    for package in ("shim-signed", "grub-efi-amd64-signed"):
        assert package in bootstrap, (
            f"{package} provides the signed binaries live-build copies into the EFI "
            "system partition; without it the Secure Boot build fails"
        )


def test_the_workflow_runs_every_menu_path_and_keeps_their_logs() -> None:
    text = _text(WORKFLOW)
    assert "boot-menus:" in text
    assert "scripts/boot-menu-test.sh" in text
    for medium in ("--medium bios", "--medium efi", "--medium secure"):
        assert medium in text, (
            f"one dispatch must exercise every firmware path; {medium} is gone"
        )
    assert "ovmf" in text, "the job installs the UEFI firmware it needs"
    assert "astraos-boot-menus" in text, "the evidence artifact must be uploaded"
    assert text.count("inputs.smoke_boot") >= 2, (
        "both booting jobs belong to the same manual switch, as the workflow's input "
        "description says"
    )
