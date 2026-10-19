"""The file tools: read the user's own folders, and only the user's own folders.

What this file is for:

  * A search finds a file in Documents and does not find one in the home
    directory beside it. A read of a file outside the six folders is refused
    with the list of folders, not with a stack trace.
  * The refusal is on the *resolved* path, so a symlink inside Documents that
    points somewhere else does not become a window into that somewhere else.
  * A binary file is refused rather than decoded into noise, and a file over the
    cap is refused rather than turned into a one-megabyte answer.
  * The two tools are in the catalog and Astra Guard reads them as `observe`,
    which is what makes them reachable by the model without a confirmation while
    still leaving a record in the audit log.

The home is ASTRAOS_FILES_HOME rather than the runner's real home: a test that
reads the developer's Documents is a test that fails on a machine that has no
Documents, and passes for the wrong reason on one that does.
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

from astraos.ai import actions, guard  # noqa: E402

DESCRIPTION = (
    "The file tools read only the user's folders, refuse escapes and binaries, "
    "and are catalogued as observe"
)


@contextlib.contextmanager
def _files_home(tmp: str):
    """A temporary home for the six folders, restored however the test ends."""
    previous = os.environ.get("ASTRAOS_FILES_HOME")
    os.environ["ASTRAOS_FILES_HOME"] = tmp
    try:
        yield Path(tmp)
    finally:
        if previous is None:
            os.environ.pop("ASTRAOS_FILES_HOME", None)
        else:
            os.environ["ASTRAOS_FILES_HOME"] = previous


def _documents(home: Path) -> Path:
    documents = home / "Documents"
    documents.mkdir(parents=True, exist_ok=True)
    return documents


def test_search_finds_a_file_in_the_users_folders_and_not_beside_them() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-files-") as tmp:
        with _files_home(tmp) as home:
            documents = _documents(home)
            (documents / "budget-2026.txt").write_text("the numbers", encoding="utf-8")
            (home / "private-notes.txt").write_text("not this one", encoding="utf-8")

            found = actions.search_files("budget")
            assert "budget-2026.txt" in found
            assert str(documents) in found, "the result does not say where the file is"
            assert "private-notes.txt" not in found, (
                "the search walked outside the folders it may read"
            )


def test_search_can_be_narrowed_to_one_folder_and_refuses_another() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-files-") as tmp:
        with _files_home(tmp) as home:
            documents = _documents(home)
            (documents / "report.txt").write_text("x", encoding="utf-8")
            elsewhere = home / "Elsewhere"
            elsewhere.mkdir()

            assert "report.txt" in actions.search_files("report", folder=str(documents))
            try:
                actions.search_files("report", folder=str(elsewhere))
            except actions.ActionError as exc:
                assert "outside the folders" in str(exc)
            else:
                raise AssertionError("a folder outside the allowed roots was searched")


def test_read_returns_text_and_refuses_an_escape() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-files-") as tmp:
        with _files_home(tmp) as home:
            documents = _documents(home)
            note = documents / "note.txt"
            note.write_text("hello from Documents", encoding="utf-8")
            (home / "secret.txt").write_text("not for you", encoding="utf-8")

            assert actions.read_file(str(note)) == "hello from Documents"
            assert actions.read_file("Documents/note.txt") == "hello from Documents"

            for path in ("../secret.txt", str(home / "secret.txt"), "/etc/passwd"):
                try:
                    actions.read_file(path)
                except actions.ActionError as exc:
                    assert "outside the folders" in str(exc), (
                        f"{path} was refused for the wrong reason: {exc}"
                    )
                else:
                    raise AssertionError(f"{path} was read; the roots are not enforced")


def test_a_symlinked_folder_cannot_become_a_window_out() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-files-") as tmp:
        with _files_home(tmp) as home:
            documents = _documents(home)
            outside = home / "Elsewhere"
            outside.mkdir()
            (outside / "leak.txt").write_text("outside", encoding="utf-8")
            link = documents / "link"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                # Windows without symlink privilege; the resolved-path check is
                # still exercised by the absolute and ../ cases above.
                return

            found = actions.search_files("leak")
            assert "leak.txt" not in found, "the search followed a symlink out of Documents"
            try:
                actions.read_file(str(link / "leak.txt"))
            except actions.ActionError as exc:
                assert "outside the folders" in str(exc)
            else:
                raise AssertionError("a file behind a symlink out of Documents was read")


def test_read_refuses_a_binary_file_and_a_file_over_the_cap() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-files-") as tmp:
        with _files_home(tmp) as home:
            documents = _documents(home)
            binary = documents / "picture.txt"
            binary.write_bytes(b"\x89PNG\x00\x01\x02")
            big = documents / "big.txt"
            big.write_bytes(b"x" * (actions.MAX_READ_BYTES + 1))

            for path, expected in ((binary, "binary"), (big, "at most")):
                try:
                    actions.read_file(str(path))
                except actions.ActionError as exc:
                    assert expected in str(exc), (
                        f"{path.name} was refused for the wrong reason: {exc}"
                    )
                else:
                    raise AssertionError(f"{path.name} was read")


def test_a_missing_file_is_an_error_not_an_empty_answer() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-files-") as tmp:
        with _files_home(tmp) as home:
            documents = _documents(home)
            try:
                actions.read_file(str(documents / "absent.txt"))
            except actions.ActionError as exc:
                assert "no such file" in str(exc)
            else:
                raise AssertionError("a missing file returned a result")


def test_the_tools_are_catalogued_and_the_guard_reads_them_as_observe() -> None:
    for name in ("search_files", "read_file"):
        assert name in actions.ACTIONS, f"{name} is not in the catalog"
        assert guard.level_of(name) == "observe", (
            f"{name} is not observe, so the model would need a confirmation to read"
        )


def test_execute_reads_through_the_catalog_and_reports_the_level() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-files-") as tmp:
        with _files_home(tmp) as home:
            documents = _documents(home)
            note = documents / "note.txt"
            note.write_text("read me", encoding="utf-8")

            result = actions.execute(
                {"action": "read_file", "args": {"path": str(note)}}
            )
            assert result["ok"] is True
            assert result["output"] == "read me"
            assert result["level"] == "observe"
