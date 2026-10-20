"""Integration test: the ISO validator reads the listings it inspects, and its checks fire.

WHY THIS TEST MATTERS
---------------------
`scripts/validate-iso.sh` is the only thing between a built image and a published ISO, so
when it is wrong the project gets it backwards twice: a complete image is refused, and a
check that always fails is a check nobody reads again.

That is what happened. The live filesystem was unpacked and complete — 152556 inodes, with
every path the script looked for, and the in-image verification hook had already confirmed
the same paths inside the chroot minutes earlier — but the ~6 MB listing was piped into
`grep -q` from a script that sets `set -o pipefail`. `grep -q` exits the moment it matches,
`printf` on the other side of the pipe died of SIGPIPE, and pipefail then reported that
*successful* match as a failed pipeline. Every component before the end of the listing was
reported missing; only the one pattern that happened to land near the end survived. Nine
failures, one cause, and the image was fine.

This test runs the real script against stubbed `xorriso`/`unsquashfs`, so the behaviour can be
exercised in seconds on any host — no 2 GB image, no Linux, no hypervisor. The stub listing
puts the paths it looks for at the START of a large listing, which is the exact shape that
broke, and the last two scenarios assert the checks still fail when a component really is
absent and when the listing cannot be interpreted at all. A repair must not pass by making
the check toothless.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests" / "lib"))

from astraos_testlib import SkipTest  # noqa: E402

DESCRIPTION = "the ISO validator reads its listings and its checks still fire"

VALIDATOR = REPO_ROOT / "scripts" / "validate-iso.sh"
MEDIUM_HOOK = (
    REPO_ROOT
    / "config"
    / "live-build"
    / "config"
    / "hooks"
    / "live"
    / "0800-disk-info.hook.binary"
)

# The components the validator looks for inside the live filesystem: the same paths,
# spelled the way `unsquashfs -l` prints them under its `squashfs-root/` prefix.
COMPONENTS = [
    "usr/bin/astraos-info",
    "etc/astraos-release",
    "usr/bin/xfce4-session",
    "usr/sbin/lightdm",
    "usr/bin/calamares",
    "usr/share/calamares/branding/astraos",
    "usr/share/plymouth/themes/astraos",
    "usr/share/astraos/wallpapers",
    "var/lib/dpkg/info/astraos-base",
    "usr/bin/astraos-hud",
    "usr/lib/astraos-hud/astraos_hud/__init__.py",
    "usr/bin/astra-ai",
    "usr/share/astraos/ai/knowledge",
    "etc/astraos/ai-bundle.conf",
    "usr/share/astraos/ai/models/Spark-X2.5-1.7B-Q4_K_M.gguf",
    "usr/share/astraos/ai/models/ggml-tiny.en.bin",
    "usr/lib/astraos/ai/engine/avx/llama-server",
    "usr/lib/astraos/ai/engine/avx2/llama-server",
    "usr/local/bin/llama-server",
    "usr/local/bin/whisper-cli",
    "usr/share/doc/astraos-ai/NOTICE",
    "var/lib/dpkg/info/astraos-hud",
    "var/lib/dpkg/info/astraos-ai",
]

COMPONENT_DESCRIPTIONS = [
    "the astraos-info command",
    "the AstraOS release file",
    "the Xfce session",
    "the LightDM greeter",
    "the Calamares installer",
    "the AstraOS installer branding",
    "the AstraOS Plymouth theme",
    "the AstraOS wallpaper",
    "the astraos-base package",
    "the AstraOS HUD launcher",
    "the AstraOS HUD application",
    "the assistant command",
    "the assistant knowledge corpus",
    "the pinned AI bundle manifest",
    "the executor model",
    "the speech model",
    "the AVX engine",
    "the AVX2 engine",
    "the engine selector",
    "the speech selector",
    "the model licences and notice",
    "the astraos-hud package",
    "the astraos-ai package",
]

ASTRAOS_MEDIUM = "AstraOS 0.1.0 alpha (amd64, based on Debian 13) amd64 LIVE Binary 20261014-00:00"
# The exact string live-build's binary_disk wrote into an AstraOS image before the
# 0800-disk-info hook existed, which is why the medium check refused it.
DEBIAN_MEDIUM = 'Debian GNU/Linux 0.1.0 "Trixie" - Snapshot amd64 LIVE Binary 20261013-18:47'

ISO_LISTING = "\n".join(
    [
        "/EFI/boot/bootx64.efi",
        "/isolinux/isolinux.bin",
        "/boot/grub/grub.cfg",
        "/live/filesystem.squashfs",
        "/live/vmlinuz",
        "/live/initrd.img",
    ]
) + "\n"

# The stubs are exported shell functions rather than files on PATH. A stub file needs the
# executable bit, which a Windows checkout cannot store (the repository has a test about
# exactly that), and this suite has to run on a Windows development machine as well as in
# Linux CI. An exported function is found by `command -v` and is inherited by the bash
# process that runs the script, in both places.
STUBS = r"""
last_arg() { for __a in "$@"; do :; done; printf '%s' "$__a"; }

# `file(1)` has to recognise the image, or the ISO 9660 check fails before anything this
# test is about runs.
file() {
    printf 'ISO 9660 CDROM filesystem data (DOS/MBR boot sector) (bootable)\n'
}

# The dummy image is a sparse file. Hashing 200 MiB of zeros in every scenario would dominate
# the runtime of the suite, and the digest is not what is under test.
sha256sum() {
    printf '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef  %s\n' "$1"
}

xorriso() {
    case "$*" in
        *'-find / -maxdepth 3'*)
            cat "$STUB_ISO_LISTING"
            return 0
            ;;
        *'-find / -name .disk'*)
            printf '/.disk\n'
            return 0
            ;;
    esac
    case "$*" in
        *'-extract /.disk/info'*)
            printf '%s\n' "$STUB_MEDIUM_INFO" > "$(last_arg "$@")"
            return 0
            ;;
        *'-extract /live/filesystem.squashfs'*)
            head -c 3145728 /dev/zero > "$(last_arg "$@")"
            return 0
            ;;
    esac
    return 0
}

unsquashfs() {
    cat "$STUB_SQUASHFS_LISTING"
}
"""


def _listing(components: list[str], filler: int = 20000, prefix: str = "squashfs-root/") -> str:
    """A `unsquashfs -l` listing that puts the interesting paths first.

    Order matters to this test: the paths the validator looks for come before the filler, so a
    check that races on an early match reports them missing. That is the bug, and it is only
    reproducible when the match is early.
    """
    lines = [
        "Parallel unsquashfs: Using 4 processors",
        f"{filler + len(components) + 1} inodes to write",
        "",
    ]
    lines.extend(f"{prefix}{component}" for component in components)
    lines.extend(
        f"{prefix}usr/lib/x86_64-linux-gnu/filler-{index}.so" for index in range(filler)
    )
    return "\n".join(lines) + "\n"


def _dummy_iso(root: Path) -> Path:
    """A sparse file big enough to pass the size check, without writing anything to disk."""
    iso = root / "astraos-0.1.0-alpha-amd64.iso"
    with iso.open("wb") as handle:
        handle.truncate(210 * 1024 * 1024)
    return iso


def _validate(
    root: Path,
    *,
    components: list[str] = COMPONENTS,
    medium: str = ASTRAOS_MEDIUM,
    listing: str | None = None,
) -> subprocess.CompletedProcess:
    """Run the real validator against a stubbed ISO, and return its combined output."""
    if not shutil.which("bash"):
        raise SkipTest("bash is not available to run the ISO validator")
    if not VALIDATOR.is_file():
        raise SkipTest(f"{VALIDATOR.relative_to(REPO_ROOT)} does not exist")

    listing_path = root / "squashfs-listing.txt"
    listing_path.write_text(listing or _listing(components), encoding="utf-8")
    iso_listing_path = root / "iso-listing.txt"
    iso_listing_path.write_text(ISO_LISTING, encoding="utf-8")

    environment = dict(os.environ)
    environment["STUB_MEDIUM_INFO"] = medium
    environment["STUB_SQUASHFS_LISTING"] = str(listing_path)
    environment["STUB_ISO_LISTING"] = str(iso_listing_path)

    # last_arg is exported too: an imported function body cannot call a helper that was not
    # exported with it, and the failure is a confusing `command not found` inside the stub.
    wrapper = (
        STUBS
        + "\nexport -f last_arg file sha256sum xorriso unsquashfs\n"
        + 'exec bash "$1" "$2"\n'
    )
    result = subprocess.run(
        ["bash", "-c", wrapper, "astraos-iso-validator-test", str(VALIDATOR), str(_dummy_iso(root))],
        capture_output=True,
        text=True,
        timeout=300,
        errors="replace",
        env=environment,
    )
    # Every message the validator prints goes to stderr; stdout is kept so a future silent
    # print is still reported rather than lost.
    result.stdout = result.stdout + result.stderr
    return result


def test_components_in_a_large_listing_are_all_found() -> None:
    """A complete live filesystem must pass, however big the listing and wherever a match sits.

    This is the regression itself. Under the old code the paths were matched by piping the
    whole listing into `grep -q`, so every one of them except the last false-failed — the
    listing here is ~1 MB, far past the pipe buffer that makes the race certain.
    """
    with tempfile.TemporaryDirectory() as directory:
        result = _validate(Path(directory))

    output = result.stdout
    missing = [name for name in COMPONENT_DESCRIPTIONS if f"contains {name}" not in output]
    assert not missing, (
        "these components were not reported as present, though the listing contains them:\n  "
        + "\n  ".join(missing)
        + f"\n\nvalidator output:\n{output}"
    )
    assert "does NOT contain" not in output, (
        "a component was reported missing that the listing contains:\n"
        + "\n".join(line for line in output.splitlines() if "does NOT contain" in line)
    )
    assert "listed:" in output, "the validator did not report reading the listing at all"
    assert "failures: 0" in output, f"the validator found failures in a good image:\n{output}"
    assert result.returncode == 0, f"the validator refused a structurally valid image:\n{output}"


def test_a_missing_component_is_still_reported_missing() -> None:
    """The checks must fail when something really is absent.

    Without this, a repair that made every check pass unconditionally would pass the test
    above — which is the failure mode this whole file exists to prevent. Note that every
    other component must still be reported present: a wholesale failure is not a check.
    """
    absent = "usr/bin/astraos-info"
    with tempfile.TemporaryDirectory() as directory:
        result = _validate(
            Path(directory),
            components=[component for component in COMPONENTS if component != absent],
        )

    output = result.stdout
    assert "does NOT contain the astraos-info command" in output, (
        "a component that is not in the listing was reported as present:\n" + output
    )
    assert result.returncode != 0, "the validator accepted an image with a missing component"

    others = [name for name in COMPONENT_DESCRIPTIONS if name != "the astraos-info command"]
    still_ok = [name for name in others if f"contains {name}" in output]
    assert len(still_ok) == len(others), (
        "one missing component turned into several reported failures, so the checks are not "
        "independent:\n" + output
    )


def test_a_debian_named_medium_is_refused() -> None:
    """The medium check must still refuse a Debian-named image.

    This is the other half of the CI failure this work came from: live-build's binary_disk
    writes `Debian GNU/Linux <our version> "Trixie"` into .disk/info, so an unnamed medium is
    indistinguishable from an unmodified Debian image. The hook that gives the medium its
    AstraOS identity is the fix; this asserts the check it has to satisfy.
    """
    with tempfile.TemporaryDirectory() as directory:
        result = _validate(Path(directory), medium=DEBIAN_MEDIUM)

    output = result.stdout
    assert "medium identifies itself as Debian" in output, (
        "the validator accepted a Debian-named medium:\n" + output
    )
    assert f"medium info: {DEBIAN_MEDIUM}" in output, (
        "the validator did not read .disk/info, so the check above proves nothing:\n" + output
    )
    assert result.returncode != 0, "the validator accepted an image branded as Debian"


def test_a_listing_that_cannot_be_interpreted_fails_once() -> None:
    """A listing with no `squashfs-root/` paths is reported as such, once.

    The patterns are paths as `unsquashfs -l` prints them, prefixed with the directory it
    would extract into. If that prefix ever changes, the honest report is that the listing
    could not be interpreted — one failure naming the cause — instead of nine lines blaming
    the image for a defect in the validator.
    """
    with tempfile.TemporaryDirectory() as directory:
        result = _validate(Path(directory), listing=_listing(COMPONENTS, prefix=""))

    output = result.stdout
    assert "without any 'squashfs-root/' paths" in output, (
        "an uninterpretable listing was not reported:\n" + output
    )
    assert "does NOT contain" not in output, (
        "an uninterpretable listing was reported as missing components, which blames the "
        "image for a defect in the validator:\n" + output
    )
    assert result.returncode != 0, "the validator accepted an image it could not inspect"


def test_the_medium_identity_hook_satisfies_the_check_it_exists_for() -> None:
    """The hook that names the medium must produce a line the validator accepts.

    live-build's binary_disk writes `Debian GNU/Linux <our version> "Trixie"` into
    .disk/info — the title is a literal in that script and no lb option changes it — which is
    the string the validator refused. 0800-disk-info.hook.binary runs later in the binary
    stage (live-build runs binary_hooks after binary_includes and before binary_checksums and
    binary_iso) to replace it with this build's own identity.

    This runs that hook for real, in the layout live-build gives it — the binary staging
    directory as its working directory, and the staged distribution.env in the chroot tree
    beside it — and then puts the file it produced through the real check. The two are pinned
    to each other deliberately: the hook must not emit a description starting with Debian, and
    the description must name the distribution, or the image is refused at the end of a build.
    """
    if not shutil.which("bash"):
        raise SkipTest("bash is not available to run the medium identity hook")
    if not MEDIUM_HOOK.is_file():
        raise SkipTest(f"{MEDIUM_HOOK.relative_to(REPO_ROOT)} does not exist")

    with tempfile.TemporaryDirectory() as directory:
        build = Path(directory)
        staged = build / "chroot" / "usr" / "share" / "astraos" / "staged"
        staged.mkdir(parents=True)
        shutil.copy(REPO_ROOT / "config" / "distribution.env", staged / "distribution.env")
        binary = build / "binary"
        binary.mkdir()

        # live-build does `cd binary` and then runs the hook, so the hook's cwd is the binary
        # staging directory and `../chroot/...` is the chroot it was assembled from.
        result = subprocess.run(
            ["bash", str(MEDIUM_HOOK)],
            cwd=str(binary),
            capture_output=True,
            text=True,
            timeout=60,
            errors="replace",
        )
        assert result.returncode == 0, (
            "the medium identity hook failed:\n" + result.stdout + result.stderr
        )

        info = binary / ".disk" / "info"
        assert info.is_file(), (
            "the hook wrote no .disk/info, which is the whole point of it:\n"
            + result.stdout
            + result.stderr
        )
        line = info.read_text(encoding="utf-8", errors="replace").strip()

        assert not line.startswith("Debian"), (
            f"the medium still announces itself as Debian: {line!r}"
        )
        assert "AstraOS" in line, (
            f"the medium description does not name the distribution, so the validator will "
            f"refuse it: {line!r}"
        )

        validation = _validate(build, medium=line)

    output = validation.stdout
    assert "medium identifies itself as AstraOS" in output, (
        "the validator refused the medium description the hook produces, so every build would "
        "fail its own branding check:\n" + output
    )
    assert f"medium info: {line}" in output, (
        "the validator did not read the description the hook wrote:\n" + output
    )
    assert validation.returncode == 0, f"a fully branded image was refused:\n{output}"
