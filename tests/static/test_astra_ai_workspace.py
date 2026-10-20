"""The writing and checking half of the research tool set.

What this file is for:

  * `write_file` writes only inside the assistant's own workspace. A relative
    path is joined to it; `../` and an absolute path elsewhere are refused, so
    the tool cannot be talked into editing the user's documents or the system.
  * `compare_files` reads two authorised documents and returns a real unified
    diff, or says they are identical.
  * `read_pdf` extracts text through `pdftotext`, and reports a missing tool, a
    scanned PDF with no text layer, and a failed extraction as messages rather
    than tracebacks.
  * `verify_citations` checks every quoted passage against the sources it was
    given - a path, a list of paths, a mapping of names, or literal text - and
    a quote with no source is a failed citation, not a silent pass.

The home and the workspace are temporary directories, so a test that writes a
file cannot leave one in the developer's own home. No test needs a model, a
display, or a PDF tool installed: the subprocess seam is replaced.
"""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_LIB = REPO_ROOT / "packages" / "astraos-ai" / "root" / "usr" / "lib"
if str(AI_LIB) not in sys.path:
    sys.path.insert(0, str(AI_LIB))

from astraos.ai import actions, guard, worker  # noqa: E402

DESCRIPTION = (
    "The workspace, PDF, comparison and citation tools stay inside their limits "
    "and report every refusal"
)


@contextlib.contextmanager
def _home(tmp: str):
    previous = os.environ.get("ASTRAOS_FILES_HOME")
    os.environ["ASTRAOS_FILES_HOME"] = tmp
    try:
        yield Path(tmp)
    finally:
        if previous is None:
            os.environ.pop("ASTRAOS_FILES_HOME", None)
        else:
            os.environ["ASTRAOS_FILES_HOME"] = previous


@contextlib.contextmanager
def _workspace(tmp: str):
    previous = os.environ.get(actions.WORKSPACE_ENV)
    os.environ[actions.WORKSPACE_ENV] = tmp
    try:
        yield Path(tmp)
    finally:
        if previous is None:
            os.environ.pop(actions.WORKSPACE_ENV, None)
        else:
            os.environ[actions.WORKSPACE_ENV] = previous


@contextlib.contextmanager
def _machine(pdf_text: str = "", pdf_code: int = 0, pdftotext: str | None = "/usr/bin/pdftotext"):
    """Replace the two functions read_pdf uses to reach pdftotext."""
    calls: list[list[str]] = []
    original = (actions._which, actions._run)

    def which(tool: str):  # noqa: ANN001 - mirrors actions._which
        return pdftotext if tool == "pdftotext" else None

    def run(argv, timeout=30):  # noqa: ANN001 - mirrors actions._run
        calls.append(list(argv))
        return (pdf_code, pdf_text)

    actions._which, actions._run = which, run
    try:
        yield calls
    finally:
        actions._which, actions._run = original


def _documents(home: Path) -> Path:
    documents = home / "Documents"
    documents.mkdir(parents=True, exist_ok=True)
    return documents


# ---------------------------------------------------------------------------
# write_file
# ---------------------------------------------------------------------------


def test_write_file_creates_a_file_inside_the_workspace() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-workspace-") as tmp:
        with _workspace(tmp) as workspace:
            message = actions.write_file("reports/notes.txt", "hello")

            written = workspace / "reports" / "notes.txt"
            assert written.read_text(encoding="utf-8") == "hello"
            assert str(written) in message
            assert "5 bytes" in message


def test_write_file_accepts_an_absolute_path_inside_the_workspace() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-workspace-") as tmp:
        with _workspace(tmp) as workspace:
            target = workspace / "abs.txt"
            actions.write_file(str(target), "absolute")
            assert target.read_text(encoding="utf-8") == "absolute"


def test_write_file_refuses_a_path_outside_the_workspace() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-workspace-") as tmp:
        with tempfile.TemporaryDirectory(prefix="astraos-elsewhere-") as outside:
            with _workspace(tmp):
                for path in ("../escape.txt", str(Path(outside) / "escape.txt")):
                    try:
                        actions.write_file(path, "no")
                    except actions.ActionError as exc:
                        assert "outside the workspace" in str(exc), (
                            f"{path} was refused for the wrong reason: {exc}"
                        )
                    else:
                        raise AssertionError(f"{path} was written outside the workspace")


def test_write_file_is_catalogued_as_a_confirmed_modify() -> None:
    assert guard.level_of("write_file") == "modify"
    result = actions.execute(
        {"action": "write_file", "args": {"path": "x.txt", "content": "x"}},
        confirmed=False,
    )
    assert result["ok"] is False
    assert result["refused"] is True


# ---------------------------------------------------------------------------
# compare_files
# ---------------------------------------------------------------------------


def test_compare_files_says_when_two_documents_are_identical() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-files-") as tmp:
        with _home(tmp) as home:
            documents = _documents(home)
            left = documents / "left.txt"
            right = documents / "right.txt"
            left.write_text("one\ntwo\n", encoding="utf-8")
            right.write_text("one\ntwo\n", encoding="utf-8")

            assert "identical" in actions.compare_files(str(left), str(right))


def test_compare_files_returns_a_unified_diff() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-files-") as tmp:
        with _home(tmp) as home:
            documents = _documents(home)
            left = documents / "left.txt"
            right = documents / "right.txt"
            left.write_text("one\ntwo\n", encoding="utf-8")
            right.write_text("one\nthree\n", encoding="utf-8")

            diff = actions.compare_files(str(left), str(right))
            assert "-two" in diff and "+three" in diff
            assert str(left) in diff and str(right) in diff


def test_compare_files_refuses_a_file_outside_the_read_folders() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-files-") as tmp:
        with _home(tmp) as home:
            documents = _documents(home)
            inside = documents / "inside.txt"
            inside.write_text("x", encoding="utf-8")
            outside = home / "outside.txt"
            outside.write_text("y", encoding="utf-8")

            try:
                actions.compare_files(str(inside), str(outside))
            except actions.ActionError as exc:
                assert "outside the folders" in str(exc)
            else:
                raise AssertionError("compare_files read a file outside the read folders")


# ---------------------------------------------------------------------------
# read_pdf
# ---------------------------------------------------------------------------


def test_read_pdf_returns_the_extracted_text() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-files-") as tmp:
        with _home(tmp) as home:
            document = _documents(home) / "report.pdf"
            document.write_bytes(b"%PDF-1.4 test")
            with _machine(pdf_text="the extracted page") as calls:
                assert actions.read_pdf(str(document)) == "the extracted page"
            assert calls and calls[0][0].endswith("pdftotext")
            assert "-layout" in calls[0]


def test_read_pdf_names_the_missing_tool() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-files-") as tmp:
        with _home(tmp) as home:
            document = _documents(home) / "report.pdf"
            document.write_bytes(b"%PDF-1.4 test")
            with _machine(pdftotext=None):
                try:
                    actions.read_pdf(str(document))
                except actions.ActionError as exc:
                    assert "pdftotext" in str(exc)
                    assert "poppler-utils" in str(exc)
                else:
                    raise AssertionError("read_pdf succeeded without pdftotext")


def test_read_pdf_explains_a_scanned_pdf_and_a_failure() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-files-") as tmp:
        with _home(tmp) as home:
            document = _documents(home) / "scan.pdf"
            document.write_bytes(b"%PDF-1.4 scan")

            with _machine(pdf_text=""):
                assert "no text layer" in actions.read_pdf(str(document))

            with _machine(pdf_text="Syntax Error: broken", pdf_code=1):
                try:
                    actions.read_pdf(str(document))
                except actions.ActionError as exc:
                    assert "pdftotext failed" in str(exc)
                    assert "Syntax Error" in str(exc)
                else:
                    raise AssertionError("a failing pdftotext was reported as success")


# ---------------------------------------------------------------------------
# verify_citations
# ---------------------------------------------------------------------------


def test_citations_resolve_against_a_source_path() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-files-") as tmp:
        with _home(tmp) as home:
            source = _documents(home) / "source.txt"
            source.write_text("The budget grew by ten percent this year.", encoding="utf-8")

            results = actions.verify_citations(
                'The report says "The budget grew by ten percent" (source.txt).',
                sources=str(source),
            )
            assert len(results) == 1
            assert results[0]["ok"] is True, results[0]
            assert results[0]["matched"] == str(source)

            absent = actions.verify_citations(
                'The report says "The budget shrank by ten percent" (source.txt).',
                sources=str(source),
            )
            assert absent[0]["ok"] is False
            assert "not found" in absent[0]["error"]


def test_citations_resolve_against_a_named_mapping_and_literal_text() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-files-") as tmp:
        with _home(tmp) as home:
            source = _documents(home) / "source.txt"
            source.write_text("A named passage lives here.", encoding="utf-8")

            named = actions.verify_citations(
                'The brief explains "A named passage" (the brief).',
                sources={"the brief": str(source)},
            )
            assert named[0]["ok"] is True, named[0]

        literal = actions.verify_citations(
            'The sheet says "A literal passage" (the sheet).',
            sources="the sheet: A literal passage appears in this line",
        )
        assert literal[0]["ok"] is True, literal[0]


def test_a_citation_with_no_source_fails_instead_of_passing() -> None:
    results = actions.verify_citations(
        'The report says "a passage nobody supplied" (missing.txt).',
        sources=[],
    )
    assert results[0]["ok"] is False
    assert "no source" in results[0]["error"]

    no_sources = actions.verify_citations('The report says "a passage nobody supplied".')
    assert no_sources[0]["ok"] is False
    assert "no sources" in no_sources[0]["error"]


def test_an_artifact_with_no_citations_is_not_a_failure() -> None:
    results = actions.verify_citations("A plain answer with no quotation.", sources=[])
    assert len(results) == 1
    assert results[0]["ok"] is True
    assert results[0]["note"] == "no citations found"


def test_the_new_tools_are_catalogued_with_the_promised_levels() -> None:
    for name in ("read_pdf", "compare_files", "verify_citations"):
        assert name in actions.ACTIONS
        assert guard.level_of(name) == "observe"
    assert "write_file" in actions.ACTIONS
    assert guard.level_of("write_file") == "modify"


def test_the_worker_reads_the_written_file_and_the_citations_back() -> None:
    """A step that claims to write or verify is checked, not taken at its word."""
    with tempfile.TemporaryDirectory(prefix="astraos-workspace-") as tmp:
        with _workspace(tmp):
            args = {"path": "checked.txt", "content": "checked"}
            assert worker._verify_write_file(args, {"output": ""}) is False, (
                "a file that did not exist was reported as written"
            )
            actions.write_file("checked.txt", "checked")
            assert worker._verify_write_file(args, {"output": ""}) is True
            assert worker._verify_write_file(
                {"path": "checked.txt", "content": "different"}, {"output": ""}
            ) is False

    with tempfile.TemporaryDirectory(prefix="astraos-files-") as tmp:
        with _home(tmp) as home:
            source = _documents(home) / "source.txt"
            source.write_text("The measured passage is here.", encoding="utf-8")
            good = {
                "artifact": 'The report says "The measured passage" (source.txt).',
                "sources": str(source),
            }
            bad = {
                "artifact": 'The report says "A passage not measured" (source.txt).',
                "sources": str(source),
            }
            assert worker._verify_citations(good, {"output": ""}) is True
            assert worker._verify_citations(bad, {"output": ""}) is False

