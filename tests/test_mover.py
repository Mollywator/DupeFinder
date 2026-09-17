import os

from conftest import make_pair, make_photo
from dupefinder import mover, scanner
from dupefinder.review import build_approved_groups


def scan_groups(root, out, stop, events):
    scanner.scan(str(root), str(out), stop, events)
    return events.last("done")["groups"]


def move(root, out, groups, stop, events):
    mover.move_duplicates(str(root), str(out), groups, stop, events)
    return events.last("move_done")


def test_move_mirrors_structure_and_undo_restores(tmp_path, stop, events):
    root, out = tmp_path / "Bilder", tmp_path / "out"
    original, copy = make_pair(root)

    info = move(root, out, scan_groups(root, out, stop, events), stop, events)
    assert info["moved"] == 1
    assert not copy.exists() and original.exists()
    assert (out / "Kopien" / "foto.jpg").exists()

    mover.undo(mover.open_journals()[0], events)
    assert copy.exists()
    assert not (out / "Kopien").exists()  # emptied folders are cleaned up
    assert mover.open_journals() == []


def test_nothing_moved_when_original_is_gone(tmp_path, stop, events):
    root, out = tmp_path / "Bilder", tmp_path / "out"
    original, copy = make_pair(root)
    groups = scan_groups(root, out, stop, events)
    original.unlink()  # deleted by hand after the scan

    assert move(root, out, groups, stop, events)["moved"] == 0
    assert copy.exists()


def test_changed_duplicate_is_skipped(tmp_path, stop, events):
    root, out = tmp_path / "Bilder", tmp_path / "out"
    _, copy = make_pair(root)
    groups = scan_groups(root, out, stop, events)
    copy.write_bytes(copy.read_bytes() + b"edited")

    assert move(root, out, groups, stop, events)["skipped"] == 1
    assert copy.exists()


def test_name_collision_gets_suffix(tmp_path, stop, events):
    root, out = tmp_path / "Bilder", tmp_path / "out"
    make_pair(root)
    (out / "Kopien").mkdir(parents=True)
    (out / "Kopien" / "foto.jpg").write_bytes(b"schon da")

    move(root, out, scan_groups(root, out, stop, events), stop, events)
    assert (out / "Kopien" / "foto_1.jpg").exists()
    assert (out / "Kopien" / "foto.jpg").read_bytes() == b"schon da"


def test_undo_does_not_overwrite_new_file(tmp_path, stop, events):
    root, out = tmp_path / "Bilder", tmp_path / "out"
    _, copy = make_pair(root)
    move(root, out, scan_groups(root, out, stop, events), stop, events)
    copy.write_bytes(b"neue Datei am alten Platz")

    mover.undo(mover.open_journals()[0], events)
    assert events.last("undo_done")["conflicts"] == 1
    assert copy.read_bytes() == b"neue Datei am alten Platz"
    assert mover.open_journals()  # still undoable / deletable


def test_journal_survives_torn_line(tmp_path, stop, events):
    root, out = tmp_path / "Bilder", tmp_path / "out"
    make_pair(root)
    move(root, out, scan_groups(root, out, stop, events), stop, events)
    journal = mover.open_journals()[0]
    with open(journal.path, "a", encoding="utf-8") as f:
        f.write('{"event": "mo')  # power cut mid-write
    assert len(journal.moves) == 1


def test_stop_during_move_is_undoable(tmp_path, events):
    import threading

    root, out = tmp_path / "Bilder", tmp_path / "out"
    make_pair(root)
    stop = threading.Event()
    groups = scan_groups(root, out, stop, events)
    stop.set()
    mover.move_duplicates(str(root), str(out), groups, stop, events)
    assert "move_stopped" in events.kinds()


def test_review_keeps_at_least_one_file():
    group = {"original": {"path": "a"}, "duplicates": [{"path": "b"}, {"path": "c"}]}
    approved = build_approved_groups([group, group, group], [{"b"}, {"a", "b", "c"}, set()])
    assert len(approved) == 1
    assert approved[0]["original"] == {"path": "a"}
    assert approved[0]["also_keep"] == [{"path": "c"}]
    assert approved[0]["duplicates"] == [{"path": "b"}]


def test_review_can_keep_a_different_image(tmp_path, stop, events):
    root, out = tmp_path / "Bilder", tmp_path / "out"
    a = make_photo(root / "a.jpg", 1)
    b = make_photo(root / "b.jpg", 2)
    group = {"type": "similar", "original": {"path": str(a)}, "duplicates": [{"path": str(b)}]}
    move(root, out, build_approved_groups([group], [{str(a)}]), stop, events)
    assert not a.exists() and b.exists()


# ─── Safety hardening ─────────────────────────────────────────────────────

import subprocess
import sys

import pytest

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="NTFS junctions")


def make_junction(link, target):
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)


@windows_only
def test_junction_is_not_reported_as_duplicate(tmp_path, stop, events):
    root, out = tmp_path / "Bilder", tmp_path / "out"
    make_photo(root / "Urlaub" / "foto.jpg", 1)
    make_junction(root / "Verknuepfung", root / "Urlaub")
    assert scan_groups(root, out, stop, events) == []


@windows_only
def test_same_physical_file_is_never_moved(tmp_path, stop, events):
    root, out = tmp_path / "Bilder", tmp_path / "out"
    photo = make_photo(root / "Urlaub" / "foto.jpg", 1)
    make_junction(root / "Verknuepfung", root / "Urlaub")
    alias = root / "Verknuepfung" / "foto.jpg"
    group = {"type": "exact", "original": {"path": str(photo)}, "duplicates": [{"path": str(alias)}]}

    assert move(root, out, [group], stop, events)["moved"] == 0
    assert photo.exists()


def test_keeper_edited_after_scan_blocks_move(tmp_path, stop, events):
    root, out = tmp_path / "Bilder", tmp_path / "out"
    original, copy = make_pair(root)
    groups = scan_groups(root, out, stop, events)
    os.utime(original, (3_000_000, 3_000_000))  # edited/replaced since the scan

    assert move(root, out, groups, stop, events)["moved"] == 0
    assert copy.exists()


def test_failed_move_is_not_undone_or_deleted(tmp_path, stop, events, monkeypatch):
    root, out = tmp_path / "Bilder", tmp_path / "out"
    _, copy = make_pair(root)
    groups = scan_groups(root, out, stop, events)

    def broken_move(src, dest):
        raise OSError("disk full")

    monkeypatch.setattr(mover.shutil, "move", broken_move)
    assert move(root, out, groups, stop, events)["errors"] == 1
    assert copy.exists()
    assert mover.open_journals() == []


def test_journal_written_before_the_move(tmp_path, stop, events, monkeypatch):
    root, out = tmp_path / "Bilder", tmp_path / "out"
    make_pair(root)
    groups = scan_groups(root, out, stop, events)
    seen = []
    real_move = mover.shutil.move

    def spy(src, dest):
        seen.append(len(mover.Journal(next(mover.storage.journal_dir().glob("*.jsonl"))).moves))
        return real_move(src, dest)

    monkeypatch.setattr(mover.shutil, "move", spy)
    move(root, out, groups, stop, events)
    assert seen == [1]


def test_review_keeps_the_group_type(tmp_path):
    exact = {"type": "exact", "hash": "abc", "original": {"path": "a"}, "duplicates": [{"path": "b"}]}
    approved = build_approved_groups([exact], [{"b"}])
    assert approved[0]["type"] == "exact"
    assert approved[0]["hash"] == "abc"


def test_keep_reason_never_claims_quality():
    from dupefinder.review import _keep_reason

    keeper = {"path": "a", "pixels": 400, "mtime": 10}
    assert _keep_reason(keeper, [{"path": "b", "pixels": 100, "mtime": 5}]) == "Vorschlag: höchste Auflösung"
    assert _keep_reason(keeper, [{"path": "b", "pixels": 400, "mtime": 20}]) == "Vorschlag: ältestes Bild"
    assert "Qualität" not in _keep_reason(keeper, [{"path": "b"}])
