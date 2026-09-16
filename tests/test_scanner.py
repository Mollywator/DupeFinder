import os
import shutil
import threading

from PIL import Image

from conftest import make_pair, make_photo
from dupefinder import scanner, storage


def run_scan(root, out, stop, events, threshold=None, resume=None):
    scanner.scan(str(root), str(out), stop, events, resume, threshold)
    return events.last("done")


def test_exact_duplicates_keep_oldest(tmp_path, stop, events):
    root = tmp_path / "Bilder"
    original, copy = make_pair(root)
    make_photo(root / "c" / "anders.jpg", 2)

    done = run_scan(root, tmp_path / "out", stop, events)

    assert done["duplicates"] == 1
    group = done["groups"][0]
    assert group["original"]["path"] == str(original)
    assert [d["path"] for d in group["duplicates"]] == [str(copy)]


def test_empty_files_are_not_duplicates(tmp_path, stop, events):
    root = tmp_path / "Bilder"
    root.mkdir()
    (root / "leer1.jpg").write_bytes(b"")
    (root / "leer2.jpg").write_bytes(b"")
    assert run_scan(root, tmp_path / "out", stop, events)["duplicates"] == 0


def test_output_folder_inside_scan_is_skipped(tmp_path, stop, events):
    root = tmp_path / "Bilder"
    photo = make_photo(root / "foto.jpg", 1)
    out = root / "Aussortiert"
    out.mkdir()
    shutil.copy(photo, out / "foto.jpg")
    assert run_scan(root, out, stop, events)["duplicates"] == 0


def test_similar_images_grouped_best_first(tmp_path, stop, events):
    root = tmp_path / "Bilder"
    big = make_photo(root / "gross.png", 7, size=(1600, 1200))
    small = root / "whatsapp.jpg"
    with Image.open(big) as img:
        img.resize((400, 300)).save(small, quality=60)
    make_photo(root / "anderes.png", 99, size=(1600, 1200))

    done = run_scan(root, tmp_path / "out", stop, events, threshold=90)

    assert done["similar"] == 1
    group = done["similar_groups"][0]
    assert group["original"]["path"] == str(big)
    assert [d["path"] for d in group["duplicates"]] == [str(small)]


def test_exif_rotated_original_matches_rotated_copy(tmp_path, stop, events):
    root = tmp_path / "Bilder"
    source = make_photo(root / "tmp.png", 11, size=(1200, 900))
    with Image.open(source) as img:
        exif = Image.Exif()
        exif[0x0112] = 6  # camera stores "rotate 90° clockwise" as a flag only
        img.save(root / "handy.jpg", quality=95, exif=exif)
        img.transpose(Image.Transpose.ROTATE_270).resize((450, 600)).save(root / "whatsapp.jpg", quality=70)
    source.unlink()

    done = run_scan(root, tmp_path / "out", stop, events, threshold=95)
    assert done["similar"] == 1


def test_similar_scan_reuses_cached_phash(tmp_path, stop, events, monkeypatch):
    root = tmp_path / "Bilder"
    make_photo(root / "a.png", 1)
    make_photo(root / "b.png", 2)
    run_scan(root, tmp_path / "out", stop, events, threshold=90)

    def fail(_):
        raise AssertionError("perceptual hash recomputed despite cache")

    monkeypatch.setattr(scanner, "perceptual_info", fail)
    run_scan(root, tmp_path / "out", stop, events, threshold=90, resume=storage.load_progress())


def test_cluster_does_not_chain():
    # A~B (distance 4) and B~C (distance 4) but A and C are 8 apart.
    a, b, c = "0000000000000000", "000000000000000f", "00000000000000ff"
    assert scanner.cluster_similar([a, b, c], priority=[0, 1, 2], max_distance=4) == [(0, [1])]


def test_cluster_center_is_highest_priority():
    a, b = "ffffffffffffffff", "fffffffffffffffe"
    assert scanner.cluster_similar([a, b], priority=[5, 1], max_distance=2) == [(1, [0])]


def test_stop_saves_partial_progress(tmp_path, events):
    root = tmp_path / "Bilder"
    make_photo(root / "foto.jpg", 1)
    stop = threading.Event()
    stop.set()
    scanner.scan(str(root), str(tmp_path / "out"), stop, events)
    assert "stopped" in events.kinds()
    assert storage.load_progress()["scan_complete"] is False


def test_changed_file_invalidates_cache(tmp_path, stop, events):
    root = tmp_path / "Bilder"
    original, copy = make_pair(root)
    run_scan(root, tmp_path / "out", stop, events)
    progress = storage.load_progress()
    assert progress["file_hashes"][str(original)]["full_hash"]

    # Same size, different content: the cached hash must not be trusted.
    data = bytearray(copy.read_bytes())
    data[-100] ^= 0xFF
    copy.write_bytes(bytes(data))
    os.utime(copy, (2_000_000, 2_000_000))
    events.clear()
    assert run_scan(root, tmp_path / "out", stop, events, resume=progress)["duplicates"] == 0


def test_validate_paths(tmp_path):
    root = tmp_path / "Bilder"
    root.mkdir()
    assert scanner.validate_paths(str(tmp_path / "fehlt"), str(tmp_path / "out"))
    assert scanner.validate_paths(str(root), "")
    assert scanner.validate_paths(str(root), str(root))
    assert scanner.validate_paths(str(root), str(tmp_path))  # scan folder inside output folder
    assert scanner.validate_paths(str(root), str(root / "Aussortiert")) is None


def test_legacy_group_is_normalized():
    group = scanner.normalize_group({"original": "X:/a.jpg", "duplicates": [{"path": "X:/b.jpg", "size": 1}]})
    assert group["original"] == {"path": "X:/a.jpg"}
    assert group["type"] == "exact"


def test_atomic_write_leaves_no_temp_files(isolated_home):
    storage.save_progress({"a": 1})
    storage.save_progress({"a": 2})
    assert storage.load_progress() == {"a": 2}
    assert [p.name for p in isolated_home.iterdir()] == ["progress.json"]
