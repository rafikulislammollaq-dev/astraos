"""A privileged change can be taken back: copy snapshots, and a rollback that works.

`docs/ROADMAP.md`, Stage 3 asks for undo. The first implementation is a copy of
the paths that are about to change, which works on the ext4 root the image has
today; Btrfs snapshots are a later, evaluated change.

This file proves the properties a way back needs:

  * a file and a directory are captured and restored to their exact contents,
    including a directory that gained and lost files after the snapshot;
  * a path that did not exist when the snapshot was taken is removed by a
    rollback, so creating a file is undoable as well as changing one;
  * a snapshot that could not capture a path does not *delete* that path on
    rollback - the dangerous failure mode of a copy-based undo;
  * ids are generated here and an id that is a path is refused, so a rollback
    cannot be pointed at an arbitrary directory;
  * list, delete and "undo the most recent" operate on real manifests.

Everything is inside a temporary directory; nothing here touches the user's home
or the machine.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_LIB = REPO_ROOT / "packages" / "astraos-ai" / "root" / "usr" / "lib"
if str(AI_LIB) not in sys.path:
    sys.path.insert(0, str(AI_LIB))

from astraos.ai import undo  # noqa: E402

DESCRIPTION = (
    "Snapshots restore files and directories, remove paths that did not exist, and "
    "refuse an id that is a path"
)


def _manager(root: Path) -> undo.UndoManager:
    return undo.UndoManager(root / "snapshots")


def test_a_file_is_restored_to_its_exact_contents() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-undo-") as tmp:
        root = Path(tmp)
        manager = _manager(root)
        document = root / "notes.txt"
        document.write_text("before\n", encoding="utf-8")

        sid = manager.snapshot([document], label="edit notes")
        document.write_text("after\n", encoding="utf-8")
        report = manager.rollback(sid)

        assert report["ok"] is True, report
        assert document.read_text(encoding="utf-8") == "before\n"
        assert report["restored"] == [str(document)]


def test_a_directory_comes_back_with_the_files_it_had() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-undo-") as tmp:
        root = Path(tmp)
        manager = _manager(root)
        folder = root / "project"
        folder.mkdir()
        (folder / "keep.txt").write_text("kept\n", encoding="utf-8")

        sid = manager.snapshot([folder], label="before cleanup")
        (folder / "keep.txt").unlink()
        (folder / "added.txt").write_text("new\n", encoding="utf-8")

        report = manager.rollback(sid)

        assert report["ok"] is True, report
        assert (folder / "keep.txt").read_text(encoding="utf-8") == "kept\n"
        assert not (folder / "added.txt").exists(), (
            "a rollback must remove files the snapshot never contained"
        )


def test_a_path_that_did_not_exist_is_removed() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-undo-") as tmp:
        root = Path(tmp)
        manager = _manager(root)
        created = root / "created.txt"

        sid = manager.snapshot([created], label="about to create")
        created.write_text("made later\n", encoding="utf-8")
        report = manager.rollback(sid)

        assert report["ok"] is True, report
        assert not created.exists()


def test_a_failed_capture_does_not_delete_what_it_could_not_copy() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-undo-") as tmp:
        root = Path(tmp)
        manager = _manager(root)
        document = root / "important.txt"
        document.write_text("still here\n", encoding="utf-8")

        original = undo.shutil.copy2
        undo.shutil.copy2 = lambda *_a, **_k: (_ for _ in ()).throw(OSError("disk full"))
        try:
            sid = manager.snapshot([document], label="capture fails")
        finally:
            undo.shutil.copy2 = original

        report = manager.rollback(sid)
        assert report["ok"] is False
        assert any("backup missing" in error for error in report["errors"])
        assert document.exists(), "a failed backup must not be recorded as 'did not exist'"
        assert document.read_text(encoding="utf-8") == "still here\n"


def test_an_id_that_is_a_path_is_refused() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-undo-") as tmp:
        manager = _manager(Path(tmp))

        for bad in ("../elsewhere", "a/b", "..", "", "C:\\Windows"):
            report = manager.rollback(bad)
            assert report["ok"] is False, f"{bad!r} was accepted as a snapshot id"
            assert manager.delete(bad) is False


def test_list_delete_and_undo_the_most_recent() -> None:
    with tempfile.TemporaryDirectory(prefix="astraos-undo-") as tmp:
        root = Path(tmp)
        manager = _manager(root)
        document = root / "number.txt"
        document.write_text("one\n", encoding="utf-8")

        first = manager.snapshot([document], label="first")
        document.write_text("two\n", encoding="utf-8")
        second = manager.snapshot([document], label="second")
        document.write_text("three\n", encoding="utf-8")

        listed = manager.list_snapshots()
        assert [entry["id"] for entry in listed] == [first, second]
        assert [entry["label"] for entry in listed] == ["first", "second"]

        report = undo.undo(root=manager.root)
        assert report["ok"] is True, report
        assert document.read_text(encoding="utf-8") == "two\n"
        assert manager.delete(second) is True
        assert manager.delete(second) is False
        assert [entry["id"] for entry in manager.list_snapshots()] == [first]
