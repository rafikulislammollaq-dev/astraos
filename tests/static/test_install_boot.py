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
  * the wizard is advanced by clicks, never by Return: Calamares 3.3 marks no default
    button, and run 39024106426 spent a whole walk finding that out;
  * every click target is an offset from the client area the driver finds in its own
    screendump - the window is always Calamares' 1024x520 minimum (a smaller branding
    size is clamped up to it), and the users page's two password fields sit side by
    side on one row;
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


def test_the_wizard_is_advanced_by_clicks_and_the_targets_are_found_on_screen() -> None:
    """Calamares marks no default button, and the window is never 800x520.

    Run 39024106426 drove the whole walk and the wizard was still on its first page at
    the deadline: Return presses reach no button in Calamares 3.3 (ViewManager never
    marks a default), every click aimed at the centre of an 800x520 window that the
    branding size asked for but Calamares clamps up to its 1024x520 minimum, and the
    users page's password fields are side by side on one row rather than the stacked
    pair the driver typed into. The driver now clicks Next and locates the client area
    in its own screendump first; these pins keep all three facts from slipping back.
    """
    code = _code(HOST_SCRIPT)
    assert "sendkey ret" not in code, (
        "Return cannot advance a Calamares page; the wizard must be clicked through"
    )
    assert "def client_rect(" in code, (
        "the driver must locate the client area in a screendump instead of trusting a "
        "screen position the window manager picked"
    )
    for offset in (
        'client["right"] - 151',
        'client["right"] - 726',
        'client["right"] - 521',
        'client["top"] + 224',
    ):
        assert offset in code, (
            "the click targets are offsets from the located client area, measured on "
            "run 39024106426's screenshots and reproduced against a local Calamares "
            "3.3.14; %s left the driver" % offset
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
        "the window must stay noexpand and centred: a maximised window moves every "
        "click target away from the offsets the exercise was measured at"
    )
    assert "systemctl poweroff" in driver, (
        "the power-off is the caller's signal that the guest is finished"
    )
    assert "XAUTHORITY=${SESSION_XAUTH:-/home/${LIVE_USER}/.Xauthority}" in driver, (
        "the driver must prefer the session's own X authority (its /proc environ) and "
        "fall back to the live account's home, not guess between them"
    )
    assert 'say "session XAUTHORITY: $XAUTHORITY"' in driver, (
        "the chosen X authority must be printed into the evidence"
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


def test_the_driver_has_a_usb_controller_to_click_with() -> None:
    """usb-tablet needs a USB bus: the exercise's first CI run died without one.

    "-device usb-tablet" on a machine with no USB controller makes
    qemu-system-x86_64 exit before the guest boots ("No 'usb-bus' bus found for
    device 'usb-tablet'", run 38919644411), so the controller must be on the command
    line and defined before the tablet that attaches to it.
    """
    code = _code(HOST_SCRIPT)
    assert "qemu-xhci" in code, (
        "the phase-1 QEMU command must bring its own USB controller; usb-tablet alone "
        "kills QEMU at startup"
    )
    assert code.index("qemu-xhci") < code.index("usb-tablet"), (
        "the controller must be defined before the tablet that attaches to it"
    )


def test_the_clicks_are_absolute_and_not_addressed_to_a_named_device() -> None:
    """Three runs, three traps, all within three lines of QMP.

    * Run 39049818027 drove the walk with HMP's mouse_move, which is a *relative* move
      (hmp_mouse_move queues qemu_input_queue_rel) delivered to whichever pointer
      registered first - the i8042 PS/2 mouse - while the live session's X server
      follows the absolute usb-tablet. Every coordinate went out as a thousand-pixel
      delta, the pointer pinned itself to a screen corner, and the wizard never left
      its Welcome page for a full 45 minutes.
    * Run 39103628321 moved the driver to QMP and reached the first click, where QEMU
      aborted: naming the device on an input event walks the consoles, and the fixed
      text console `-vga std` creates has no "device" property to find
      ("Property 'qemu-fixed-text-console.device' not found", qemu1.out).
    * Run 39105685521 dropped the device name, and every screendump from 02 to 09 still
      shows the Welcome page. Two reasons, both in QEMU's own source: an absolute axis
      is addressed in 0..0x7FFF rather than in pixels, and an event's device is chosen
      per event as the first handler whose mask intersects - the PS/2 mouse for "btn",
      because it registers before the tablet and claims BTN as well.

    So: QMP, absolute axes, no "device", values scaled into the pointer's own units, and
    the tablet made current before the first click. Which device that is must be read
    from QEMU rather than assumed, so the driver asks query-mice and acts on the answer.
    """
    code = _code(HOST_SCRIPT)
    assert '"type": "abs"' in code, (
        "pointer moves must be absolute QMP input-send-event axes; a relative move is "
        "not a position"
    )
    assert "input-send-event" in code, (
        "the pointer must be driven through QMP's input-send-event"
    )
    assert "mouse_move" not in code, (
        "HMP's mouse_move is relative and lands on the PS/2 mouse; using it again is "
        "what kept the wizard on its first page for 45 minutes"
    )
    assert '"device":' not in code, (
        "naming a device on an input event aborts QEMU on -vga std (run 39103628321)"
    )
    assert "query-mice" in code, (
        "which pointer is absolute, and which is current, must be read from QEMU and "
        "written to the evidence rather than assumed"
    )
    assert "select_tablet()" in code and "mouse_set" in code, (
        "the tablet must be made the current pointer before a click: QEMU routes each "
        'event to the first handler whose mask intersects, and for "btn" that is the '
        "PS/2 mouse - run 39105685521 aimed with one device and pressed with another"
    )
    assert '-qmp "unix:$WORK/monitor1.sock' in code, (
        "the phase-1 monitor socket must be a QMP one; HMP cannot express an absolute "
        "position. (Phase 2 keeps the human monitor on purpose: it only screendumps "
        "the greeter and never touches the pointer.)"
    )


def test_the_pointer_is_addressed_in_the_pointer_s_own_units() -> None:
    """Pixels are not a position the tablet can be given; 0..0x7FFF is.

    Run 39105685521 sent the pixel column and row as raw "abs" values. QEMU passes an
    abs value through untouched (qmp_input_send_event) and the tablet takes it as its
    own logical coordinate (hw/input/hid.c, "e->xdx = evt->abs.value"), whose range is
    0..0x7FFF (include/ui/input.h). So 1002 and 670 meant about 3% and 2% of the screen:
    the pointer sat at roughly 39x16, every click hit the wallpaper, and nothing
    anywhere said so, because the commands were accepted and the replies were valid. A
    GUI scales before the event leaves it (qemu_input_scale_axis does the arithmetic);
    a QMP client has to do the same itself.
    """
    code = _code(HOST_SCRIPT)
    assert "ABS_MAX = 0x7FFF" in code, (
        "the absolute pointer's range is QEMU's, not the screen's, and belongs where "
        "the scaling happens"
    )
    assert "def to_abs(" in code, (
        "pixel coordinates must be converted to the pointer's units at one boundary"
    )
    assert '{"axis": "x", "value": to_abs(x, size["w"])}' in code, (
        "the x axis must be scaled by the framebuffer's own width, taken from the "
        "screendump rather than assumed"
    )
    assert '{"axis": "y", "value": to_abs(y, size["h"])}' in code, (
        "the y axis must be scaled by the framebuffer's own height"
    )
    assert '"value": x}' not in code and '"value": y}' not in code, (
        "a raw pixel value on an abs axis is exactly what run 39105685521 sent: QEMU "
        "cannot tell it from a scaled one, and the pointer lands in a corner"
    )


def test_the_click_walk_hashes_the_wizard_and_not_the_desktop() -> None:
    """A digest that reaches x=0 is not measuring the wizard.

    Run 39105685521's welcome reference was taken while the wallpaper was still
    unpainted, and by the end of the walk it had been painted. The digest started at
    x=0, so it compared a wallpaper as well as a page: it announced that the clicks had
    registered, and the run then spent its full 45 minutes watching a wizard still on
    Welcome - the one failure this check exists to report in about two minutes.
    client_rect() had the left edge all along and simply did not return it.
    """
    code = _code(HOST_SCRIPT)
    assert 'return {"top": top, "bottom": bottom, "left": left, "right": right}' in code, (
        "the located region must carry its left edge; without it the digest falls back "
        "to the screen's, which includes the desktop"
    )
    assert 'left, right = max(0, rect["left"]), min(rect["right"], width)' in code, (
        "the digest must start at the located left edge"
    )
    assert "left, right = 0," not in code, (
        "a digest from x=0 compares the desktop's wallpaper, which is not the wizard; "
        "that is what made run 39105685521 report a walk that never happened"
    )
    assert '"left": 126' in code, (
        "the recorded fallback region must exclude the desktop as well - it is the "
        "window's left edge on the layout those values were measured from"
    )


def test_the_driver_reports_an_unresponsive_pointer_instead_of_waiting() -> None:
    """A wizard that did not move must be named in minutes, not after the whole budget.

    The 45 minutes of run 39049818027 were spent watching an untouched Welcome page
    because nothing could tell the host the walk had failed. The driver now hashes the
    client area of its first and last screendump, and the host stops waiting when the
    driver gives up - so the next failure of this kind costs about two minutes.
    """
    code = _code(HOST_SCRIPT)
    assert "def client_digest(" in code, (
        "the walk must be able to measure whether the client area changed at all"
    )
    assert "the clicks did not register" in code, (
        "an unchanged client area across the whole walk must be named as what it is"
    )
    host = _text(HOST_SCRIPT)
    assert "kill -0 \"$UI_DRIVER_PID\"" in host, (
        "the wait loop must notice the driver giving up instead of running out the clock"
    )
    assert "the wizard driver stopped before the installer reported" in host, (
        "a driver that gave up must reach the verdict as its own named problem"
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


def test_a_dead_installer_is_caught_before_the_deadline() -> None:
    """A Calamares that never initializes must not cost the whole timeout.

    Run 38940011841 ran the full 45-minute budget against a guest showing
    "Calamares Initialization Failed": the destructive phase never started, the report
    file was never written, and the verdict said only that no report appeared. The wait
    loop now watches the console log the installer streams into the seed share and gives
    up in seconds with a name for what happened.
    """
    code = _code(HOST_SCRIPT)
    assert "Calamares Initialization Failed" in code, (
        "the wait loop must notice a Calamares that never drew a page; the driver alone "
        "cannot, because it clicks at coordinates regardless of what is on screen"
    )
    assert 'problems+=("phase 1: ${init_failure}")' in code, (
        "an initialization failure must reach the verdict as its own problem, not as "
        "'the installer never wrote its report'"
    )
