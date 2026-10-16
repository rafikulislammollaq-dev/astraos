"""Install-exercise tests.

scripts/install-boot-test.sh is the only thing in this repository that installs the
image it built and boots the result, and three more halves ship inside that image: the
guest install driver (astraos-install and its unit), the CI-only presets, and the
self-test's installed-mode branch. All of them lie if edited carelessly, so the cheap
invariants are asserted here rather than being discovered by an ISO build or a
half-hour QEMU run:

  * the install switch must be its own exact word ("astraos.ci.install=1"): systemd
    matches a condition without "=" against the beginning of a command line word, so
    the shared bare prefix "astraos.ci" would let the boot self-test fire during an
    install and power the machine off in the middle of the copy;
  * the CI presets are appended to copies of the shipped module configs and must not
    duplicate a key the shipped file already sets - a repeated YAML key silently picks
    one of the two values and the loser is invisible;
  * the password the wizard is given must be generated per run and written nowhere:
    not into the seed, not into a log, not into this repository;
  * every destructive step belongs to Calamares, through its own UI - the guest driver
    must never partition or format anything itself;
  * the installed-mode switches must reach the installed system's kernel command line,
    or the self-test runs its live-mode expectations against a system with no live
    session and fails for the wrong reason.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

DESCRIPTION = (
    "the install exercise drives the real installer, boots the installed system, and "
    "keeps the two machine switches exact"
)

HOST_SCRIPT = REPO_ROOT / "scripts" / "install-boot-test.sh"
INCLUDES = REPO_ROOT / "config" / "live-build" / "config" / "includes.chroot"
DRIVER = INCLUDES / "usr" / "local" / "sbin" / "astraos-install"
UNIT = INCLUDES / "etc" / "systemd" / "system" / "astraos-install.service"
SMOKE = INCLUDES / "usr" / "local" / "sbin" / "astraos-smoke"
SMOKE_UNIT = INCLUDES / "etc" / "systemd" / "system" / "astraos-smoke.service"
SERVICES_HOOK = (
    REPO_ROOT / "config" / "live-build" / "config" / "hooks" / "live"
    / "0400-services.hook.chroot"
)
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "build-iso.yml"
PARTITION_CONF = REPO_ROOT / "installer" / "calamares" / "modules" / "partition.conf"
USERS_CONF = REPO_ROOT / "installer" / "calamares" / "modules" / "users.conf"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _code(path: Path) -> str:
    """The file without comment-only lines: comments may name what code must not do."""
    return "\n".join(
        line for line in _text(path).splitlines() if not line.lstrip().startswith("#")
    )


def test_the_two_machine_switches_are_exact_words() -> None:
    """The prefix trap, made a pinned fact in both directions.

    systemd's ConditionKernelCommandLine without "=" matches the beginning of a
    command line word, so a bare "astraos.ci" condition fires for "astraos.ci=1",
    "astraos.ci.install=1" and "astraos.ci.installed=1" alike. The install boot must
    not start the self-test (it screenshots and powers off mid-install), and the
    self-test boots must not start the installer.
    """
    host = _text(HOST_SCRIPT)
    phase1 = [
        line
        for line in host.splitlines()
        if line.startswith("APPEND=") and "astraos.ci.install=1" in line
    ]
    assert phase1, "the install boot must carry the install switch on its command line"
    assert "astraos.ci=1" not in phase1[0], (
        "the install boot must not also carry the self-test's switch"
    )

    unit = _text(UNIT)
    assert "ConditionKernelCommandLine=astraos.ci.install=1" in unit, (
        "the install driver would start on installs it was never gated for"
    )
    assert not re.search(r"^ConditionKernelCommandLine=astraos\.ci$", unit, re.M), (
        "the bare prefix would also fire for the self-test's and the installed-mode "
        "boots (systemd matches it against the beginning of a command line word)"
    )

    smoke_unit = _text(SMOKE_UNIT)
    assert "ConditionKernelCommandLine=astraos.ci=1" in smoke_unit, (
        "the self-test unit must be gated on the exact word so the install exercise's "
        "boots cannot start it"
    )


def test_the_installed_system_boots_with_the_installed_switches() -> None:
    host = _text(HOST_SCRIPT)
    assert "qemu-img convert" in host and "losetup -Pf" in host, (
        "the installed disk must be converted and loop-mounted to patch its boot"
    )
    patch_lines = [line for line in host.splitlines() if "patch_append=" in line]
    assert patch_lines, "no grub.cfg patch line found"
    patch = patch_lines[0]
    for token in ("console=ttyS0", "astraos.ci=1", "astraos.ci.installed=1", "username=${ASTRAOS_LIVE_USER}"):
        assert token in patch, f"the installed kernel line is missing {token}"
    assert "if=virtio,format=raw" in host, (
        "the installed disk must be booted by its own firmware, with no medium"
    )
    assert "astraos-ci login:" in host, (
        "the login prompt naming the installed hostname is a required proof"
    )
    assert "ASTRAOS-SMOKE: mode: installed" in host, (
        "the installed self-test must have to say it ran in installed mode"
    )
    assert not re.search(r"^APPEND=.*findiso", host, re.M), (
        "findiso names an ISO file for live-boot to loop-mount; the attached CD-ROM "
        "is found by live-boot's own scan (run 38864588609 died learning this)"
    )


def test_the_ci_seed_cannot_repeat_a_shipped_key() -> None:
    """The shipped partition.conf states both choices; the CI copy must not append them blind.

    A duplicated top-level key in YAML does not merge: one of the two values wins and
    the loser is dead configuration that still looks like policy. The shipped
    partition.conf sets `initialPartitioningChoice`/`initialSwapChoice` (the disk-safety
    rule: nothing is erased without an active choice), so the CI copy comments those
    lines out before appending the exercise's own values, and the host script refuses a
    finished copy with a repeated key outright.
    """
    partition = _text(PARTITION_CONF)
    for key in ("initialPartitioningChoice", "initialSwapChoice"):
        assert re.search(rf"^{key}:", partition, re.M), (
            f"{key} left the shipped partition.conf; the CI seed's comment-out step "
            "must be revisited together with it"
        )

    users = _text(USERS_CONF)
    for key in ("presets", "hostname"):
        assert not re.search(rf"^{key}:", users, re.M), (
            f"{key} now exists in the shipped users.conf; the CI append would create "
            "a duplicate key"
        )

    host = _text(HOST_SCRIPT)
    assert "for key in initialPartitioningChoice initialSwapChoice" in host, (
        "the shipped choice lines must be neutralised in the CI copy"
    )
    assert "CI install exercise replaced this line" in host, (
        "the commented-out shipped lines must say why they were replaced"
    )
    for appended in (
        "initialPartitioningChoice: eraseDisk",
        "initialSwapChoice: none",
        "value: \"AstraOS CI\"",
        "value: \"astraos-ci\"",
        "editable: false",
        "template: astraos-ci",
    ):
        assert appended in host, f"the CI seed no longer carries: {appended}"
    assert "uniq -d" in host and "repeats the top-level key" in host, (
        "the host script must check its finished seed for duplicated keys before the "
        "guest reads it"
    )


def test_the_password_is_generated_per_run_and_written_nowhere() -> None:
    host = _text(HOST_SCRIPT)
    assert "import secrets" in host, (
        "the password must be generated, not committed"
    )
    assert "${#PASSWORD}" in host, (
        "the transcript may print the password's length, never the password"
    )
    assert 'INSTALL_TEST_PASSWORD="$PASSWORD"' in host, (
        "the typing helper receives the password through the environment, not argv"
    )
    assert not re.search(r'^PASSWORD="[a-z0-9]', host, re.M), (
        "a literal password assignment in the host script"
    )


def test_the_guest_driver_never_partitions_or_formats_anything() -> None:
    """Every destructive step belongs to Calamares, through its own UI."""
    code = _code(DRIVER)
    for tool in ("mkfs", "parted", "sgdisk", "wipefs", "fdisk", "dd "):
        assert tool not in code, (
            f"the guest driver must not call {tool!r}: it drives the installer, it is "
            "not one"
        )


def test_the_guest_driver_keeps_the_output_contract() -> None:
    driver = _text(DRIVER)
    assert "ASTRAOS-INSTALL:" in driver, "the host greps this marker"
    assert "calamares exited rc=" in driver, "the host greps this marker"
    assert '"$SEED/done"' in driver, "the report file is how phase 1 is judged"
    assert "mount -t 9p" in driver and "astraos-ci" in driver, (
        "the driver reads its presets from the QEMU share"
    )
    assert "quit-at-end" in driver, (
        "CI cannot click the finished page; the driver has to make it quit"
    )
    assert "windowExpanding" in driver, (
        "the window must be pinned so the remote pointer's coordinates mean something"
    )
    assert "systemctl poweroff" in driver, (
        "the power-off is the caller's signal that the guest is finished"
    )


def test_the_self_test_has_an_installed_mode() -> None:
    smoke = _text(SMOKE)
    assert "astraos.ci.installed" in smoke, "the installed mode reads this switch"
    assert "MODE=installed" in smoke and "MODE=live" in smoke, (
        "the self-test must say which system it is testing"
    )
    for name in (
        "installed-greeter",
        "installed-policy-file",
        "installed-no-autologin",
        "installed-no-live-user",
        "installed-user",
    ):
        assert name in smoke, f"the installed-mode check {name!r} is gone"


def test_the_install_unit_is_enabled_and_wanted_by_the_desktop_target() -> None:
    unit = _text(UNIT)
    assert "ExecStart=/usr/local/sbin/astraos-install" in unit
    assert "WantedBy=graphical.target" in unit, (
        "the driver needs the desktop session's X server, like the self-test"
    )
    assert "TimeoutStartSec" in unit, (
        "the unit start covers the whole Calamares run; a default timeout would kill "
        "an install mid-copy"
    )
    hook = _text(SERVICES_HOOK)
    assert "astraos-install.service" in hook, (
        "the unit must be enabled during the build or it never starts"
    )


def test_the_workflow_runs_the_exercise() -> None:
    workflow = _text(WORKFLOW)
    assert re.search(r"^      install_boot:", workflow, re.M), (
        "the dispatch inputs must be able to switch the install exercise"
    )
    assert "Install the ISO onto a disk and boot it" in workflow, (
        "the install-boot job is gone from the workflow"
    )
    assert "./scripts/install-boot-test.sh --timeout 45 --out install-out iso/*.iso" in workflow, (
        "the job must run the exercise against the built ISO"
    )
    assert "astraos-install-test" in workflow, (
        "the evidence artifact name is part of the contract"
    )
