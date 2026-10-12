"""Acceptance procedure and honesty checks.

Two things are tested here, both about not lying to the user:

1. The documented acceptance procedures contain the steps the plan requires. A procedure
   that silently loses "remove the ISO before rebooting" produces a false failure, and a
   procedure that loses "back up first" produces a real one.

2. The build manifest and the limitations document agree about what has NOT been tested.
   If a future change marks `boot_in_virtualbox=PASS` in the manifest template while no
   boot has ever happened, that is exactly the fabrication the plan forbids, and this
   catches it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "lib"))

from astraos_testlib import read  # noqa: E402

DESCRIPTION = "acceptance procedures are complete and untested areas are recorded honestly"

VIRTUALBOX_DOC = "docs/INSTALLATION_VIRTUALBOX.md"
PHYSICAL_DOC = "docs/INSTALLATION_PHYSICAL_PC.md"
LIMITATIONS = "docs/KNOWN_LIMITATIONS.md"
MANIFEST_SCRIPT = "scripts/generate-manifest.sh"


# ---------------------------------------------------------------------------
# 1. The VirtualBox acceptance procedure
# ---------------------------------------------------------------------------

def test_virtualbox_procedure_covers_the_required_sequence() -> None:
    """Every step of the plan's §19 acceptance sequence must be documented."""
    doc = read(VIRTUALBOX_DOC).lower()

    required = {
        "checksum verification": ["sha256sum"],
        "creating the virtual machine": ["new", "memory"],
        "allocating a virtual disk": ["disk"],
        "attaching the ISO": ["iso"],
        "booting": ["boot"],
        "inspecting the boot menu": ["grub menu"],
        "entering the live desktop": ["live session"],
        "testing applications": ["terminal", "file manager", "browser"],
        "launching the installer": ["installer"],
        "installing to the virtual disk": ["partition"],
        "shutting down": ["shut down"],
        "removing the ISO": ["remove the iso"],
        "booting from the virtual disk": ["installed system"],
        "first login": ["log in"],
        "testing networking and updates": ["network", "apt update"],
        "recording failures": ["logs"],
    }

    missing = [name for name, needles in required.items()
               if not any(needle in doc for needle in needles)]
    assert not missing, (
        "docs/INSTALLATION_VIRTUALBOX.md is missing these required acceptance steps:\n  "
        + "\n  ".join(missing)
    )


def test_virtualbox_procedure_warns_about_the_iso_step() -> None:
    """The most commonly skipped step, and the one that produces a false failure."""
    doc = read(VIRTUALBOX_DOC)
    assert "remove the ISO" in doc or "Remove the ISO" in doc, (
        "the procedure does not tell the user to remove the ISO before booting the "
        "installed system, which is the step people skip and then report as a bug"
    )
    assert re.search(r"this is the step people\s+skip|step people", doc, re.I), (
        "the procedure does not flag that the ISO-removal step is the one most often "
        "skipped"
    )


# ---------------------------------------------------------------------------
# 2. The physical installation safety precautions
# ---------------------------------------------------------------------------

def test_physical_procedure_leads_with_a_warning() -> None:
    doc = read(PHYSICAL_DOC)
    head = doc[:1200].lower()
    assert "do not" in head, (
        "docs/INSTALLATION_PHYSICAL_PC.md does not open with a warning. Physical "
        "installation of an untested alpha must be discouraged before the procedure."
    )
    assert "never been booted" in doc or "no hardware has been tested" in doc, (
        "the physical installation guide does not state that the release is untested"
    )


def test_physical_procedure_requires_a_backup() -> None:
    doc = read(PHYSICAL_DOC).lower()
    assert "back up" in doc, "the procedure does not require a backup"
    assert "cannot lose" in doc or "cannot be recovered" in doc, (
        "the procedure does not explain which data must be backed up, so the requirement "
        "reads as boilerplate"
    )


def test_physical_procedure_explains_that_writing_a_usb_erases_it() -> None:
    doc = read(PHYSICAL_DOC).lower()
    assert "erases that drive" in doc or "erases" in doc, (
        "the USB writing instructions do not warn that the target drive is erased"
    )
    assert "no trailing" in doc or "not a partition" in doc, (
        "the USB instructions do not warn against passing a partition instead of the whole "
        "disk"
    )


def test_physical_procedure_does_not_automate_the_usb_write() -> None:
    """A script that guesses the target disk is how people lose their data."""
    doc = read(PHYSICAL_DOC)
    assert "there is deliberately no script" in doc or "deliberately no script" in doc, (
        "the procedure should state explicitly that AstraOS provides no automated USB "
        "writing command, and why"
    )

    # And no script should exist that would do it.
    scripts_dir = REPO_ROOT / "scripts"
    for path in scripts_dir.glob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        assert "dd if=" not in text, (
            f"{path.name} contains a raw disk write. Disk writes belong to the user, with "
            "a device they identified themselves."
        )


def test_physical_procedure_explains_the_secure_boot_consequence() -> None:
    doc = read(PHYSICAL_DOC)
    section = doc.lower()
    assert "secure boot" in section, "the procedure does not mention Secure Boot"
    assert "will refuse to boot" in section or "refuse to boot" in section, (
        "the procedure does not state that a machine enforcing Secure Boot will refuse to "
        "boot the AstraOS medium"
    )
    assert "no other supported path" in doc or "no other supported" in doc, (
        "the procedure implies there is an alternative to disabling Secure Boot when there "
        "is not"
    )


# ---------------------------------------------------------------------------
# 3. Honest recording of what was not tested
# ---------------------------------------------------------------------------

def test_manifest_marks_unverified_areas_as_untested() -> None:
    """The manifest must record UNTESTED, not PASS, for things that have not run."""
    manifest = read(MANIFEST_SCRIPT)

    for field in ("boot_in_virtualbox", "boot_legacy_bios", "boot_uefi",
                  "installer_launch", "installation_completed",
                  "installed_system_boot", "installed_system_login",
                  "networking", "physical_hardware"):
        assert f"{field}=UNTESTED" in manifest, (
            f"the manifest does not record {field} as UNTESTED. A build manifest must not "
            "claim a test that has not been performed."
        )

    assert "secure_boot=NOT_SUPPORTED" in manifest, (
        "the manifest does not record that Secure Boot is unsupported"
    )
    assert "structural=PASS" in manifest, (
        "the manifest does not record the structural validation result"
    )


def test_manifest_lists_no_fabricated_validation_passes() -> None:
    """No field may claim a runtime result the build cannot know."""
    manifest = read(MANIFEST_SCRIPT)

    fabricated = [
        f"{field}=PASS"
        for field in ("boot_in_virtualbox", "boot_uefi", "boot_legacy_bios",
                      "installer_launch", "installation_completed",
                      "installed_system_boot", "installed_system_login",
                      "physical_hardware", "networking")
        if f"{field}=PASS" in manifest
    ]
    assert not fabricated, (
        "the manifest claims results it cannot know at build time:\n  "
        + "\n  ".join(fabricated)
    )


def test_limitations_document_lists_the_untested_areas() -> None:
    """The limitations document must carry the same story as the manifest."""
    doc = read(LIMITATIONS)

    assert "UNTESTED" in doc, "the limitations document does not use the UNTESTED marker"
    assert re.search(r"no image has been (built or booted|built)", doc, re.I), (
        "the limitations document does not state that no image has been built or booted"
    )
    assert "Secure Boot is not supported" in doc, (
        "the limitations document does not state that Secure Boot is unsupported"
    )
    assert "base-files" in doc, (
        "the limitations document does not record the /etc/os-release overwrite hazard"
    )


def test_limitations_and_procedure_agree_on_the_state_of_testing() -> None:
    """A document claiming a passing test would contradict the limitations list."""
    doc = read(LIMITATIONS)
    assert "Nothing in this document has been performed yet" in read(VIRTUALBOX_DOC) or \
           "has been performed yet" in read(VIRTUALBOX_DOC), (
        "docs/INSTALLATION_VIRTUALBOX.md does not state that the procedure has not been "
        "performed, while docs/KNOWN_LIMITATIONS.md says it has not"
    )
    assert "UNKNOWN" not in doc or "UNTESTED" in doc


def test_readme_does_not_overclaim() -> None:
    """The README must not describe a working operating system when none has booted."""
    readme = read("README.md")
    assert "No ISO has been built yet" in readme or "no ISO has been built" in readme.lower(), (
        "README.md does not state that no ISO has been built, which would overclaim the "
        "state of the project"
    )
    assert re.search(r"NOT DONE", readme), (
        "README.md's status table does not mark the unperformed stages as NOT DONE"
    )
