"""Tests for the proof page and the software bill of materials.

Two scripts write the evidence a reader is asked to trust:

  * scripts/generate-proof-page.py turns a run's CI artifacts into one page: the
    image, the live self-test, the three boot paths, the install and the archive.
  * scripts/generate-sbom.py writes an SPDX 2.3 bill of materials for the packages
    the build produced.

Both are tested by running them, not by reading their source. The properties that
matter are behavioural:

  * the page says what the artifacts say - the check count, the hash, whether each
    boot path reached the login prompt - and nothing more;
  * a missing artifact is reported as missing. "Not shown in this run" is a
    sentence the page is allowed to write; a pass it cannot see is not;
  * the bill of materials names each package with its version, its SHA-256 and its
    licence, and says plainly which parts are Debian's own.

The fixtures are built here rather than kept as files: a synthetic evidence tree
and a synthetic .deb, both written from the formats the scripts read, so the tests
do not depend on a run having happened.
"""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PROOF_SCRIPT = REPO_ROOT / "scripts" / "generate-proof-page.py"
SBOM_SCRIPT = REPO_ROOT / "scripts" / "generate-sbom.py"

DESCRIPTION = "the proof page and the bill of materials say what the evidence says"


def _run(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _evidence(root: Path) -> Path:
    """A synthetic evidence tree with the shape a CI run produces."""
    evidence = root / "evidence"

    live = evidence / "self-test"
    live.mkdir(parents=True)
    (live / "serial.log").write_text(
        "[  44.541124] astraos-smoke[1558]: ASTRAOS-SMOKE: ok hud-on-screen the dashboard is up\n"
        "[  44.900000] astraos-smoke[1558]: ASTRAOS-SMOKE: RESULT: PASS (63 checks, 0 failed)\n",
        encoding="utf-8",
    )
    (live / "screenshot.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)

    for medium in ("bios", "efi", "secure"):
        folder = evidence / "menus" / f"menus-{medium}"
        folder.mkdir(parents=True)
        (folder / "serial.log").write_text(
            "AstraOS 0.2.0 Alpha\nastra-live login: ", encoding="utf-8"
        )
    (evidence / "menus" / "menus-secure" / "firmware.txt").write_text(
        "0123  /usr/share/OVMF/OVMF_CODE_4M.secboot.fd\n", encoding="utf-8"
    )

    install = evidence / "install"
    install.mkdir(parents=True)
    (install / "done").write_text("rc=0\n", encoding="utf-8")
    (install / "serial2.log").write_text(
        "astraos-smoke[1148]: ASTRAOS-SMOKE: mode: installed\n"
        "astraos-smoke[1148]: ASTRAOS-SMOKE: RESULT: PASS (55 checks, 0 failed)\n",
        encoding="utf-8",
    )
    (install / "calamares-session.log").write_text(
        'Starting job "unpackfs" ( 10 / 27 )\nStarting job "bootloader" ( 26 / 27 )\n',
        encoding="utf-8",
    )
    (install / "greeter.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)

    logs = evidence / "build-logs" / "logs"
    logs.mkdir(parents=True)
    (logs / "build-20261020T061511Z.log").write_text(
        "[astraos:checksums] computing sha256 for astraos-0.2.0-alpha-amd64.iso\n"
        "[astraos:checksums] sha256 = " + ("ab" * 32) + "\n"
        "passed: 33   warnings: 1   failures: 0\n"
        "RESULT: the image passed STRUCTURAL validation.\n"
        "Get:8 file:/packages ./ astraos-system-tools 0.2.0 [8688 B]\n",
        encoding="utf-8",
    )

    archive = evidence / "apt-repo" / "dists" / "stable" / "main" / "binary-amd64"
    archive.mkdir(parents=True)
    (archive / "Packages").write_text(
        "Package: astraos-ai\nPackage: astraos-base\n", encoding="utf-8"
    )
    (evidence / "apt-repo" / "dists" / "stable" / "Release").write_text(
        "Origin: AstraOS\nSuite: stable\n", encoding="utf-8"
    )
    return evidence


def _write_deb(path: Path, control: str) -> None:
    """Write a .deb (an ar archive holding a control tarball) the way dpkg does."""
    control_tar = io.BytesIO()
    with tarfile.open(fileobj=control_tar, mode="w:gz") as tar:
        payload = control.encode("utf-8")
        info = tarfile.TarInfo("./control")
        info.size = len(payload)
        info.mode = 0o644
        tar.addfile(info, io.BytesIO(payload))

    data_tar = io.BytesIO()
    with tarfile.open(fileobj=data_tar, mode="w:gz") as tar:
        payload = b"#!/bin/sh\necho astraos\n"
        info = tarfile.TarInfo("./usr/bin/astraos-example")
        info.size = len(payload)
        info.mode = 0o755
        tar.addfile(info, io.BytesIO(payload))

    members = (
        ("debian-binary", b"2.0\n"),
        ("control.tar.gz", control_tar.getvalue()),
        ("data.tar.gz", data_tar.getvalue()),
    )
    with path.open("wb") as handle:
        handle.write(b"!<arch>\n")
        for name, data in members:
            handle.write(f"{name:<16}{0:<12}{0:<6}{0:<6}{100644:<8}{len(data):<10}`\n".encode())
            handle.write(data)
            if len(data) % 2:
                handle.write(b"\n")


def test_the_page_reports_what_the_artifacts_say() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-proof-") as workdir:
        root = Path(workdir)
        evidence = _evidence(root)
        out = root / "proof.md"
        result = _run(PROOF_SCRIPT, "--evidence", str(evidence), "--out", str(out),
                      "--run-id", "1234567890")
        assert result.returncode == 0, f"the script failed: {result.stderr}"
        page = out.read_text(encoding="utf-8")

        assert "PASS (63 checks, 0 failed)" in page, "the self-test result is not on the page"
        assert ("ab" * 32) in page, "the image's hash is not on the page"
        assert "33 passed, 0 failures, 1 warning" in page, (
            "the structural check summary is not on the page"
        )
        assert page.count("| yes |") == 3, (
            "the three boot paths must each say whether they reached the login prompt"
        )
        assert "rc=0" in page, "the install's result is not on the page"
        assert "PASS (55 checks, 0 failed)" in page, "the installed system's result is missing"
        assert "2 packages" in page, "the archive's package count is not on the page"
        assert "It is unsigned." in page, "the archive's signing state is not on the page"
        assert "A fresh container updated from it" in page, (
            "the build log records a container installing from the archive; the page "
            "must say so"
        )
        assert "not shown in this run" not in page.lower(), (
            "every artifact was present, so the page must not claim any of them missing"
        )
        assert "What this run does not prove" in page, (
            "the page must end with what it does not prove, or it reads like a "
            "guarantee"
        )


def test_the_page_never_claims_what_it_cannot_see() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-proof-missing-") as workdir:
        root = Path(workdir)
        evidence = _evidence(root)
        out = root / "proof.md"

        # Take the install away: the page must report it as missing, not pass it.
        for path in (evidence / "install").iterdir():
            path.unlink()
        (evidence / "install").rmdir()
        result = _run(PROOF_SCRIPT, "--evidence", str(evidence), "--out", str(out))
        assert result.returncode == 0, f"the script failed: {result.stderr}"
        page = out.read_text(encoding="utf-8")
        assert "Not shown in this run: the install exercise." in page, (
            "a missing artifact must be reported as missing"
        )
        assert "rc=0" not in page, "the page claimed an install result it cannot see"

        # Take the build log away: the hash must go with it.
        for path in (evidence / "build-logs" / "logs").iterdir():
            path.unlink()
        result = _run(PROOF_SCRIPT, "--evidence", str(evidence), "--out", str(out))
        page = out.read_text(encoding="utf-8")
        assert ("ab" * 32) not in page, "the page kept a hash whose log is gone"
        assert "not shown in this run" in page.lower()

        # And a page that is asked for nothing at all still says what is missing.
        empty = root / "empty"
        empty.mkdir()
        result = _run(PROOF_SCRIPT, "--evidence", str(empty), "--out", str(out))
        assert result.returncode == 0
        page = out.read_text(encoding="utf-8")
        assert "not shown in this run" in page.lower()
        assert "What this run does not prove" in page


def test_the_bill_of_materials_names_each_package() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-sbom-") as workdir:
        root = Path(workdir)
        debs = root / "packages"
        debs.mkdir()
        control = (
            "Package: astraos-example\n"
            "Version: 1.2.3\n"
            "Architecture: amd64\n"
            "Maintainer: AstraOS Project <maintainers@astraos.invalid>\n"
            "Section: utils\n"
            "Description: An example package for the test\n"
            " A line of description.\n"
        )
        deb = debs / "astraos-example_1.2.3_amd64.deb"
        _write_deb(deb, control)

        out = root / "astraos.spdx.json"
        result = _run(SBOM_SCRIPT, "--debs", str(debs), "--out", str(out),
                      "--name", "astraos-test")
        assert result.returncode == 0, f"the script failed: {result.stderr}"
        document = json.loads(out.read_text(encoding="utf-8"))

        assert document["spdxVersion"] == "SPDX-2.3"
        assert document["name"] == "astraos-test"
        assert document["dataLicense"] == "CC0-1.0"
        assert len(document["packages"]) == 1
        package = document["packages"][0]
        assert package["name"] == "astraos-example"
        assert package["versionInfo"] == "1.2.3"
        assert package["licenseConcluded"] == "MIT"
        expected = hashlib.sha256(deb.read_bytes()).hexdigest()
        assert package["checksums"][0]["checksumValue"] == expected, (
            "the bill of materials must record the hash of the file it describes"
        )
        assert package["checksums"][0]["algorithm"] == "SHA256"
        purl = package["externalRefs"][0]["referenceLocator"]
        assert purl == "pkg:deb/debian/astraos-example@1.2.3?arch=amd64"
        assert document["relationships"][0]["relationshipType"] == "DESCRIBES"
        assert "Debian 13" in document["creationInfo"]["comment"], (
            "the document must say which parts are Debian's own and keep their licences"
        )


def test_the_bill_of_materials_refuses_an_empty_directory() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-sbom-empty-") as workdir:
        root = Path(workdir)
        debs = root / "packages"
        debs.mkdir()
        result = _run(SBOM_SCRIPT, "--debs", str(debs), "--out", str(root / "out.json"))
        assert result.returncode == 2, (
            "a bill of materials with no packages is a lie; the script must refuse it"
        )
        assert not (root / "out.json").exists()
