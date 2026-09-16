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


def test_delete_only_touches_journal_files(tmp_path, stop, events, monkeypatch):
    root, out = tmp_path / "Bilder", tmp_path / "out"
    make_pair(root)
    move(root, out, scan_groups(root, out, stop, events), stop, events)
    unrelated = out / "eigene_datei.txt"
    unrelated.write_text("nicht anfassen")

    trashed = []

    def fake_trash(path):
        trashed.append(path)
        os.remove(path)

    monkeypatch.setattr(mover, "send2trash", fake_trash)
    mover.delete_moved(mover.open_journals()[0], events)

    assert len(trashed) == 1
    assert unrelated.exists()
    assert mover.open_journals() == []


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


def test_unc_path_has_no_recycle_bin():
    assert mover.has_recycle_bin(r"\\nas\bilder\foto.jpg") is False


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
