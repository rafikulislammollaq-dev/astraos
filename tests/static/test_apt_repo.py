"""Tests for the APT repository assembly.

scripts/build-apt-repo.sh turns the build's .deb files into the archive an installed
system's apt can read. What these tests pin, and why:

  * the layout apt requires: `pool/` for the files, `dists/stable/.../Packages` (and
    its gzip) as the index, and a `Release` carrying the sizes and SHA-256 hashes apt
    compares the indices against;
  * signing is optional but never silent: `--key` produces `InRelease`/`Release.gpg`
    and exports the public keyring, and without a key the script says the output is
    unsigned - integrity without authenticity, for controlled use only;
  * the script reads its own index back before reporting success: every file the
    index names is re-hashed, and a mismatch fails the script, because an index that
    does not describe its pool is worse than no archive;
  * the build workflow assembles the archive from the packages it built and uploads
    it, and the building/roadmap documents describe that state.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "build-apt-repo.sh"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "build-iso.yml"
BUILDING = REPO_ROOT / "docs" / "BUILDING.md"

DESCRIPTION = "the APT repository assembly writes the layout apt reads, and is honest about signing"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_the_script_writes_the_layout_apt_reads() -> None:
    text = _text(SCRIPT)
    for required in (
        'pool="pool/main/${name}/$(basename "$deb")"',
        "dists/stable/main/binary-amd64",
        "gzip -9nc",
        "Filename: ",
        "Size: ",
        "SHA256: ",
    ):
        assert required in text, f"the repository layout is missing {required!r}"


def test_the_release_carries_the_hashes_of_both_indices() -> None:
    text = _text(SCRIPT)
    assert "Origin: AstraOS" in text and "Components: main" in text
    assert text.count("main/binary-amd64/Packages") >= 2, (
        "Release must name both the plain and the gzipped index"
    )
    assert "Date: %s" in text, (
        "the Release carries a date so a client can refuse a future-dated one"
    )


def test_signing_is_optional_and_never_silent() -> None:
    text = _text(SCRIPT)
    assert "--key FINGERPRINT" in text, "the usage text must document --key"
    assert "InRelease" in text and "Release.gpg" in text, (
        "signing must produce both the clearsigned InRelease and the detached signature"
    )
    assert "astraos-archive-keyring.gpg" in text, "the public half is exported for clients"
    assert "never generates" in text and "never stores one" in text, (
        "the script must say that it never generates or stores a signing key"
    )
    assert "UNSIGNED (no --key was given)" in text, (
        "an unsigned archive must say so in the script's own words, because it carries "
        "integrity hashes but no authenticity"
    )
    assert "the signature that was just written does not verify" in text, (
        "a signature that does not verify must fail the script, not be shipped"
    )


def test_the_index_is_read_back_before_success() -> None:
    text = _text(SCRIPT)
    assert "the index names a missing file" in text
    assert "size mismatch for" in text
    assert "hash mismatch for" in text
    assert "the index describes" in text, (
        "the read-back must count the packages it verified against the packages given, "
        "so a partially written index cannot pass"
    )


def test_the_rebuild_wipe_is_bounded() -> None:
    text = _text(SCRIPT)
    assert 'rm -rf "$OUT"' in text
    assert "refusing to wipe suspicious --out" in text, (
        "the rebuild deletes its output directory; a guard must refuse the paths that "
        "would make that destructive"
    )


def test_the_workflow_assembles_and_uploads_the_archive() -> None:
    workflow = _text(WORKFLOW)
    assert "./scripts/build-apt-repo.sh --debs build/live-build/packages --out dist/apt-repo" in workflow, (
        "the build job must assemble the archive from the packages it built"
    )
    assert "name: astraos-apt-repo" in workflow, "the archive must be uploaded as its own artifact"
    assert "if-no-files-found: error" in workflow.split("name: astraos-apt-repo", 1)[1][:400], (
        "an archive that failed to assemble must fail the upload, not be silently absent"
    )


def test_the_documents_describe_the_archive_and_its_state() -> None:
    building = _text(BUILDING)
    assert "build-apt-repo.sh" in building and "apt-repo" in building
    assert "no installed system has ever fetched" in building, (
        "the documentation must keep saying that no installed system has fetched "
        "updates from the archive yet; that flips only on a run record"
    )
