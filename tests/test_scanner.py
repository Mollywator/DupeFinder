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


def test_100_percent_tolerates_reencoding_only():
    assert scanner.max_distance_for(100) == scanner.max_distance_for(scanner.IDENTICAL_SIMILARITY) == 7
    assert scanner.max_distance_for(80) == 51


def test_every_slider_value_has_a_description():
    texts = {scanner.describe_level(p) for p in range(80, 101)}
    assert len(texts) == len(scanner.LEVEL_DESCRIPTIONS)


# ─── Data location and first-start placement ──────────────────────────────

from dupefinder import placement


def fake_exe(folder):
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / "DupeFinder.exe"
    exe.write_bytes(b"MZ")
    return exe


def test_data_lives_next_to_the_program(tmp_path, monkeypatch):
    monkeypatch.delenv("DUPEFINDER_HOME")
    monkeypatch.setattr(storage, "_app_dir_override", tmp_path)
    assert storage.data_dir() == tmp_path / "DupeFinder-Daten"
    storage.save_settings({"a": 1})
    assert (tmp_path / "DupeFinder-Daten" / "settings.json").exists()


def test_first_start_in_clean_folder_stays(tmp_path, monkeypatch):
    monkeypatch.delenv("DUPEFINDER_HOME")
    exe = fake_exe(tmp_path / "Programm")
    assert placement.first_start(exe) is None
    assert exe.exists()
    assert (exe.parent / "DupeFinder-Daten" / placement.MARKER).exists()


def test_first_start_in_crowded_folder_moves_into_subfolder(tmp_path, monkeypatch):
    monkeypatch.delenv("DUPEFINDER_HOME")
    downloads = tmp_path / "Downloads"
    exe = fake_exe(downloads)
    (downloads / "rechnung.pdf").write_bytes(b"x")

    moved = placement.first_start(exe)

    assert moved == downloads / "DupeFinder" / "DupeFinder.exe"
    assert moved.exists() and not exe.exists()
    assert (downloads / "DupeFinder" / "DupeFinder-Daten" / placement.MARKER).exists()
    assert sorted(p.name for p in downloads.iterdir()) == ["DupeFinder", "rechnung.pdf"]


def test_check_runs_only_on_first_start(tmp_path, monkeypatch):
    monkeypatch.delenv("DUPEFINDER_HOME")
    exe = fake_exe(tmp_path / "Programm")
    placement.first_start(exe)
    (exe.parent / "notiz.txt").write_text("später dazugelegt")
    assert placement.first_start(exe) is None
    assert exe.exists()


def test_existing_foreign_subfolder_is_not_reused(tmp_path, monkeypatch):
    monkeypatch.delenv("DUPEFINDER_HOME")
    desktop = tmp_path / "Desktop"
    exe = fake_exe(desktop)
    (desktop / "DupeFinder").mkdir()
    (desktop / "DupeFinder" / "fremd.txt").write_text("x")

    moved = placement.first_start(exe)
    assert moved.parent.name == "DupeFinder (2)"
    assert (desktop / "DupeFinder" / "fremd.txt").exists()


def test_locked_exe_is_copied_and_cleaned_up_later(tmp_path, monkeypatch):
    monkeypatch.delenv("DUPEFINDER_HOME")
    downloads = tmp_path / "Downloads"
    exe = fake_exe(downloads)
    (downloads / "anderes.zip").write_bytes(b"x")
    scheduled = []

    def locked(src, dst):
        raise PermissionError("in use")

    monkeypatch.setattr(placement.os, "replace", locked)
    monkeypatch.setattr(placement, "_delete_after_exit", scheduled.append)

    moved = placement.first_start(exe)
    assert moved.exists() and exe.exists()
    assert scheduled == [exe]


def test_all_modules_compile_and_import():
    import importlib

    for name in ("gui", "review", "placement", "mover", "scanner", "storage"):
        importlib.import_module(f"dupefinder.{name}")

