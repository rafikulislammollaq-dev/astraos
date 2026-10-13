"""The image build must refuse to ship a private key, and must name the file that blocked it.

`tests/security/test_security_config.py` checks the policy files. This module runs the real
scanner that the build hook invokes, against trees built for the occasion, because both of
the defects this replaced were only visible when it ran:

  * a text search failed a real build on a Debian file which merely *names* the armor
    format, and
  * the failure printed the pattern that had been searched for rather than the file that
    matched, so the build stopped with nothing to investigate.

A scanner that cannot name its finding, or that reports documentation as a leaked key, is a
scanner people learn to ignore. Both properties are pinned here.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL = REPO_ROOT / "packages" / "astraos-base" / "root" / "usr" / "bin" / "astraos-scan-secrets"

DESCRIPTION = "the credential scan recognises real keys, ignores mere mentions, and names paths"

# A syntactically complete armored private key. The payload is nonsense, which is the point:
# the scan must recognise the shape, not the key.
ARMORED_KEY = (
    "-----BEGIN PGP PRIVATE KEY BLOCK-----\n"
    "\n"
    "lQHYBGXk1e0BBADJ7ZQ0kM0nT0nO2pQm4xZ8mQ5f6y7m2k9p1Kx0M2r3V8n4Q1b2\n"
    "c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0u1v2w3x4y5z6a7b8c9d0e1f2g3h4\n"
    "=Ab3d\n"
    "-----END PGP PRIVATE KEY BLOCK-----\n"
)

PUBLIC_KEY = (
    "-----BEGIN PGP PUBLIC KEY BLOCK-----\n"
    "\n"
    "mQENBGXk1e0BCADJ7ZQ0kM0nT0nO2pQm4xZ8mQ5f6y7m2k9p1Kx0M2r3V8n4Q1b2\n"
    "-----END PGP PUBLIC KEY BLOCK-----\n"
)


def _shell() -> str:
    for candidate in ("sh", "bash"):
        found = shutil.which(candidate)
        if found:
            return found
    raise AssertionError("no shell interpreter is available to run astraos-scan-secrets")


def _run(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run the shipped scanner against `root`, with the path spelled the way the tool sees it."""
    return subprocess.run(
        [_shell(), str(TOOL), "--root", root.as_posix(), *arguments],
        capture_output=True, text=True, timeout=120,
    )


def _write(root: Path, relative: str, content: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_an_armored_private_key_is_found_and_the_path_is_named() -> None:
    """The failure has to say which file it found, or the build stops for nothing."""
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        key = _write(root, "etc/ssl/leaked.key", ARMORED_KEY)
        result = _run(root)

    assert result.returncode == 1, (
        "astraos-scan-secrets did not fail on a file containing an armored private key. "
        f"Output:\n{result.stdout}{result.stderr}"
    )
    assert key.as_posix() in result.stdout, (
        "the scan failed without naming the file that matched, so the build log would not "
        f"contain the path that has to be fixed. Output:\n{result.stdout}"
    )


def test_a_magic_database_entry_is_not_a_leaked_key() -> None:
    """A magic(5) pattern naming the armor format is data, not a credential.

    This is the shape of the file that failed a real image build: the armor header appears
    inside a pattern line, so it is not a line on its own and there is no key body.
    """
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        magic = _write(root, "etc/magic", "0\tstring\t-----BEGIN PGP PRIVATE KEY BLOCK-----\n")
        result = _run(root)

    assert result.returncode == 0, (
        "a magic(5) entry naming the armor format stopped the scan; the image build would "
        f"fail on a Debian data file. Output:\n{result.stdout}"
    )
    assert magic.as_posix() in result.stdout, (
        "the file is ignored silently. A mention has to be reported as a mention: that is "
        "what makes the difference between a reviewed mention and a missed key visible."
    )


def test_prose_that_names_the_format_is_not_a_leaked_key() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        _write(
            root,
            "etc/astraos-policy/NOTES",
            "Never commit a BEGIN PGP PRIVATE KEY or an RSA PRIVATE KEY to this repository.\n",
        )
        result = _run(root)

    assert result.returncode == 0, (
        f"documentation naming the format was reported as a key:\n{result.stdout}"
    )


def test_an_armor_header_followed_by_prose_is_not_a_key() -> None:
    """A header only starts a key when the block that follows it carries key material."""
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        _write(
            root,
            "etc/example.conf",
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "Replace this example with the file described in the manual.\n",
        )
        result = _run(root)

    assert result.returncode == 0, (
        f"an example header followed by prose was reported as a key:\n{result.stdout}"
    )


def test_a_truncated_key_without_its_footer_is_still_a_finding() -> None:
    """A key pasted without its last line must not become invisible."""
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        key = _write(
            root,
            "root/id_ecdsa",
            "-----BEGIN EC PRIVATE KEY-----\n"
            "MHcCAQEEIO0nT0nO2pQm4xZ8mQ5f6y7m2k9p1Kx0M2r3V8n4Q1b2\n",
        )
        result = _run(root)

    assert result.returncode == 1, (
        f"a key without its END line was not reported:\n{result.stdout}"
    )
    assert key.as_posix() in result.stdout


def test_unsupported_key_forms_are_recognised() -> None:
    """The forms the previous fixed list of patterns missed are keys too.

    `-----BEGIN PRIVATE KEY-----` is the PKCS#8 form OpenSSL 3 writes by default, including
    for the snakeoil key live-build removes; `PGP SECRET KEY` is the pre-2.0 GnuPG armor.
    Neither was in the pattern list this replaced.
    """
    for header, footer, relative in (
        ("PRIVATE KEY", "PRIVATE KEY", "etc/ssl/pkcs8.key"),
        ("ENCRYPTED PRIVATE KEY", "ENCRYPTED PRIVATE KEY", "etc/ssl/encrypted.key"),
        ("PGP SECRET KEY BLOCK", "PGP SECRET KEY BLOCK", "etc/legacy.asc"),
        ("OPENSSH PRIVATE KEY", "OPENSSH PRIVATE KEY", "root/id_rsa"),
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            key = _write(
                root,
                relative,
                f"-----BEGIN {header}-----\n"
                "b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW\n"
                f"-----END {footer}-----\n",
            )
            result = _run(root)

        assert result.returncode == 1, (
            f"a '{header}' block was not reported as a key:\n{result.stdout}"
        )
        assert key.as_posix() in result.stdout


def test_a_public_key_block_is_not_a_finding() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        _write(root, "etc/apt/trusted.gpg.d/debian.asc", PUBLIC_KEY)
        result = _run(root)

    assert result.returncode == 0, (
        f"a public key block was reported as a private key:\n{result.stdout}"
    )


def test_a_binary_file_that_contains_the_marker_is_reported_as_a_note() -> None:
    """A compiled-in parser constant is not an armored key, and must not stop the build.

    Binaries are reported rather than ignored: that keeps the difference between "the scan
    looked and found nothing" and "the scan could not read this" visible in the log.
    """
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        binary = root / "etc" / "firmware.bin"
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_bytes(b"\x00\x01\x02BEGIN PGP PRIVATE KEY BLOCK-----\x00\x03\x04")
        result = _run(root)

    assert result.returncode == 0, (
        "a binary file holding the armor text as data stopped the scan; a compiled-in "
        f"parser constant would fail the image build. Output:\n{result.stdout}"
    )
    assert binary.as_posix() in result.stdout, (
        "the binary was ignored silently, so an unexplained match in this file could not be "
        "diagnosed from the log"
    )


def test_scan_directories_that_do_not_exist_are_skipped() -> None:
    """The image has no /home or /srv contents to speak of; a missing directory is normal."""
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        _write(root, "etc/hosts", "127.0.0.1 localhost\n")
        result = _run(root)

    assert result.returncode == 0, (
        f"the scan failed because one of its default directories is absent:\n{result.stderr}"
    )


def test_an_explicit_directory_that_does_not_exist_is_an_error() -> None:
    """Reporting "clean" for a directory that was never read is worse than no check at all."""
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        result = _run(root, "etc/does-not-exist")

    assert result.returncode == 2, (
        "the scan accepted a directory that does not exist, so a typo in the directory "
        f"name would be reported as a clean image. Exit was {result.returncode}: "
        f"{result.stdout}{result.stderr}"
    )
    assert "does-not-exist" in result.stderr


def test_bad_arguments_are_rejected() -> None:
    shell = _shell()

    missing_value = subprocess.run(
        [shell, str(TOOL), "--root"], capture_output=True, text=True, timeout=120
    )
    assert missing_value.returncode == 2, "--root without a directory was accepted"

    unknown = subprocess.run(
        [shell, str(TOOL), "--scan-everything"], capture_output=True, text=True, timeout=120
    )
    assert unknown.returncode == 2, "an unknown option was accepted instead of refused"

    help_text = subprocess.run(
        [shell, str(TOOL), "--help"], capture_output=True, text=True, timeout=120
    )
    assert help_text.returncode == 0 and "usage:" in help_text.stdout, (
        "--help does not print the usage"
    )


def test_the_tool_is_shipped_and_is_a_posix_shell_script() -> None:
    """The hook runs this from inside the chroot, so it has to be in the image.

    It is a /bin/sh script on purpose: /bin/sh is dash in Debian, and the tool must not
    depend on which shell is installed. tests/static/test_scripts.py checks the executable
    bit in the git index, which is what makes the file runnable after a checkout.
    """
    assert TOOL.is_file(), f"{TOOL.relative_to(REPO_ROOT)} is missing"
    assert TOOL.read_bytes().startswith(b"#!/bin/sh"), (
        "the tool must be a /bin/sh script so that it runs whatever /bin/sh is in the image"
    )
