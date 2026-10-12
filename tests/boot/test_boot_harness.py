"""Tests for the automated boot harness.

The harness boots the ISO, so it cannot be treated casually. These tests verify its safety
properties and, crucially, that it reports BLOCKED rather than success when it cannot run.
That last one is executed for real: the script is run in a state where it cannot boot, and
its exit code is checked.

Set ASTRAOS_RUN_VM_TEST=1 to additionally run a real boot attempt. Without it, a host with
no hypervisor just gets a SKIP with the reason, which is the honest result.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "lib"))

from astraos_testlib import (  # noqa: E402
    REPO_ROOT as LIB_ROOT,
    SkipTest,
    newest_iso,
    read,
    require_tool,
    run_command,
    which,
)

DESCRIPTION = "the boot harness is safe and reports BLOCKED instead of passing"

HARNESS = "tests/boot/run-vm-test.sh"


def test_harness_exists_and_is_valid_shell() -> None:
    path = REPO_ROOT / HARNESS
    assert path.is_file(), f"{HARNESS} is missing"

    shell = which("bash") or which("sh")
    if not shell:
        raise SkipTest("no shell is available to syntax-check the harness")

    result = run_command([shell, "-n", str(path)])
    assert result.returncode == 0, f"{HARNESS} has a syntax error:\n{result.stderr}"


def test_harness_cannot_touch_host_disks() -> None:
    """The harness must never reference a host block device.

    It boots an image and inspects the result. It has no reason to name a real device, and
    a bug there would be catastrophic rather than merely wrong.
    """
    text = read(HARNESS)
    offenders = []
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        # /dev/sdX, /dev/nvmeXnY, /dev/hdX, /dev/vdX are host-style device paths.
        for match in re.finditer(r"/dev/(sd[a-z]|nvme\d|hd[a-z]|vd[a-z])", stripped):
            offenders.append(f"{HARNESS}:{lineno}: {match.group(0)}")
    assert not offenders, (
        "the boot harness references a block device, which risks destroying a host disk:\n  "
        + "\n  ".join(offenders)
    )


def test_harness_refuses_to_run_without_an_image() -> None:
    """Executed for real: with no usable image the harness must exit 2 (BLOCKED).

    Exit 2 specifically, not 0. A test harness that reports success when it skipped is the
    exact failure mode plan §18 forbids, so this asserts the exit code rather than
    trusting the message.
    """
    shell = which("bash")
    if not shell:
        raise SkipTest("bash is required to run the harness")

    path = REPO_ROOT / HARNESS
    # Point it at a path that does not exist, so it cannot proceed to a boot.
    result = run_command([shell, str(path), str(REPO_ROOT / "dist" / "does-not-exist.iso")],
                         timeout=120, cwd=REPO_ROOT)

    assert result.returncode == 2, (
        "the harness did not exit 2 when it could not boot. "
        f"exit code was {result.returncode}; a BLOCKED result must not look like success.\n"
        f"stdout:\n{result.stdout[-800:]}"
    )
    assert "BLOCKED" in result.stdout, (
        "the harness did not say BLOCKED when it could not run:\n" + result.stdout[-800:]
    )


def test_harness_requires_a_graphical_marker_to_pass() -> None:
    """A kernel message alone must not count as a successful boot."""
    text = read(HARNESS)
    assert "GRAPHICAL" in text, (
        "the harness has no graphical-session marker, so it could pass on a boot that "
        "never reached a desktop"
    )
    assert "check_markers" in text, "the harness does not use its marker check"
    # The pass condition must require all three stages.
    assert re.search(r"\[ \"\$kernel\" = \"yes\" \] && \[ \"\$systemd\" = \"yes\" \] && \[ \"\$graphical\" = \"yes\" \]",
                     text), (
        "the harness pass condition does not require the kernel, systemd AND the graphical "
        "session to have started"
    )


def test_harness_cleans_up_what_it_creates() -> None:
    """A boot test that leaves VMs and disks behind is a boot test nobody runs twice."""
    text = read(HARNESS)
    assert "unregistervm" in text, "the harness does not unregister the VM it creates"
    assert "--delete" in text, "the harness does not delete the VM it creates"
    assert "rm -f \"$disk\"" in text or "rm -f '$disk'" in text, (
        "the harness does not remove the disposable disk it creates"
    )


def test_harness_verifies_the_checksum_before_booting() -> None:
    """Booting an image whose checksum fails would test something other than the release."""
    text = read(HARNESS)
    assert "sha256sum -c" in text, "the harness boots the image without verifying its checksum"


def test_virtualisation_readiness() -> None:
    """Report whether a boot test is possible here, and skip honestly if it is not."""
    iso = newest_iso()
    qemu = which("qemu-system-x86_64")
    vbox = which("VBoxManage")

    print(f"  image present    : {'yes' if iso else 'no'}")
    print(f"  qemu-system-x86_64: {'yes' if qemu else 'no'}")
    print(f"  VBoxManage       : {'yes' if vbox else 'no'}")
    print(f"  ASTRAOS_RUN_VM_TEST: {os.environ.get('ASTRAOS_RUN_VM_TEST', 'unset')}")

    if iso is None:
        raise SkipTest("no ISO has been built, so no boot can be attempted")
    if not qemu and not vbox:
        raise SkipTest("no hypervisor is installed, so no boot can be attempted")

    if os.environ.get("ASTRAOS_RUN_VM_TEST") != "1":
        raise SkipTest(
            "a hypervisor and an image are available; set ASTRAOS_RUN_VM_TEST=1 to "
            "actually boot (this takes several minutes)"
        )

    # A real boot attempt was requested.
    result = run_command(["bash", str(REPO_ROOT / HARNESS), "--timeout", "300"],
                         timeout=600, cwd=REPO_ROOT)
    print(result.stdout[-2000:])
    assert result.returncode == 0, (
        f"the boot test failed with exit code {result.returncode}"
    )


def test_acceptance_documentation_matches_the_harness_expectations() -> None:
    """Both paths must state that a screenshot is not proof of a usable desktop."""
    doc = read("docs/INSTALLATION_VIRTUALBOX.md")
    assert "not tested" in doc.lower() or "UNTESTED" in doc, (
        "docs/INSTALLATION_VIRTUALBOX.md does not state which steps are untested"
    )
    harness = read(HARNESS)
    assert "does not prove" in harness, (
        "the harness captures a screenshot without saying that a screenshot is not proof "
        "the desktop is usable"
    )
