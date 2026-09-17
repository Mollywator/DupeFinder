"""Similarity behaviour at the "same image" level (100 %) versus looser levels."""

from PIL import Image, ImageDraw

from conftest import make_photo
from dupefinder import scanner


def run(root, out, stop, events, threshold):
    scanner.scan(str(root), str(out), stop, events, None, threshold)
    return events.last("done")


def save_copy(src, dest, size=None, quality=70):
    with Image.open(src) as img:
        if size:
            img = img.resize(size)
        img.save(dest, quality=quality)
    return dest


def test_quality_copy_is_still_found_at_100(tmp_path, stop, events):
    root = tmp_path / "Bilder"
    original = make_photo(root / "original.png", 3, size=(1200, 900))
    save_copy(original, root / "whatsapp.jpg", size=(600, 450))

    done = run(root, tmp_path / "out", stop, events, 100)
    assert done["similar"] == 1
    assert done["similar_groups"][0]["original"]["path"] == str(original)


def test_painted_stroke_is_not_proposed_at_100(tmp_path, stop, events):
    root = tmp_path / "Bilder"
    original = make_photo(root / "original.png", 4, size=(1200, 900))
    with Image.open(original) as img:
        edited = img.copy()
    ImageDraw.Draw(edited).line([(700, 100), (760, 600)], fill=(30, 120, 255), width=5)
    edited.save(root / "bemalt.png")

    assert run(root, tmp_path / "out", stop, events, 100)["similar"] == 0
    events.clear()
    # At a looser level it is meant to show up — there it is a "similar" image.
    assert run(root, tmp_path / "out", stop, events, 90)["similar"] == 1


def test_changed_text_in_a_screenshot_is_not_proposed_at_100(tmp_path, stop, events):
    root = tmp_path / "Bilder"
    root.mkdir(parents=True)
    for name, status in (("screenshot_a.png", "Status OK"), ("screenshot_b.png", "Status FEHLER")):
        img = Image.new("RGB", (900, 600), (22, 44, 55))
        d = ImageDraw.Draw(img)
        for row in range(10):
            y = 40 + row * 50
            d.rectangle([20, y, 700, y + 40], fill=(30, 60, 70) if row % 2 else (40, 70, 80))
            d.text((30, y + 12), f"Eintrag {row}  {status if row == 4 else 'Status OK'}", fill=(220, 220, 220))
        img.save(root / name)

    assert run(root, tmp_path / "out", stop, events, 100)["similar"] == 0


def test_tiny_and_flat_images_are_not_compared(tmp_path, stop, events):
    root = tmp_path / "Bilder"
    root.mkdir(parents=True)
    Image.new("RGB", (8, 45), (12, 12, 12)).save(root / "mini_a.png")
    Image.new("RGB", (1, 1), (0, 0, 0)).save(root / "mini_b.png")
    Image.new("RGB", (193, 12), (200, 200, 200)).save(root / "mini_c.png")
    Image.new("RGB", (243, 166), (0, 0, 0)).save(root / "schwarz.png")
    Image.new("RGB", (400, 300), (5, 5, 5)).save(root / "fast_schwarz.png")

    done = run(root, tmp_path / "out", stop, events, 100)
    assert done["similar"] == 0
    assert done["duplicates"] == 0


def test_verification_metric_separates_reencoding_from_edits(tmp_path):
    photo = make_photo(tmp_path / "foto.png", 5, size=(1000, 750))
    copy = save_copy(photo, tmp_path / "kopie.jpg", size=(500, 375), quality=55)
    with Image.open(photo) as img:
        edited = img.copy()
    ImageDraw.Draw(edited).line([(500, 80), (560, 500)], fill=(255, 60, 60), width=4)
    edited.save(tmp_path / "bemalt.png")

    assert scanner.looks_identical(photo, copy) is True
    assert scanner.looks_identical(photo, tmp_path / "bemalt.png") is False


def test_unreadable_file_never_counts_as_identical(tmp_path):
    photo = make_photo(tmp_path / "foto.png", 6)
    broken = tmp_path / "kaputt.png"
    broken.write_bytes(b"not an image")
    assert scanner.looks_identical(photo, broken) is False


def test_same_resolution_keeps_the_older_file(tmp_path, stop, events):
    """An edited copy is newer and can be the larger file — the original must win."""
    import os

    root = tmp_path / "Bilder"
    original = make_photo(root / "original.png", 8, size=(800, 600))
    with Image.open(original) as img:
        edited = img.copy()
    ImageDraw.Draw(edited).line([(400, 60), (430, 400)], fill=(30, 120, 255), width=3)
    edited.save(root / "bemalt.png")
    os.utime(original, (1_000_000, 1_000_000))
    os.utime(root / "bemalt.png", (2_000_000, 2_000_000))
    assert (root / "bemalt.png").stat().st_size > original.stat().st_size

    done = run(root, tmp_path / "out", stop, events, 90)
    assert done["similar"] == 1
    group = done["similar_groups"][0]
    assert group["original"]["path"] == str(original)
    assert [d["path"] for d in group["duplicates"]] == [str(root / "bemalt.png")]
