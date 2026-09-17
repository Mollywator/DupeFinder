# Changelog

## 1.4.0

- **Everything is reviewed before it moves.** Exact copies now open the same review window as
  similar images, with thumbnails and checkboxes, plus an "Einfach alle nehmen" button that
  accepts every suggestion at once.
- **The program no longer deletes anything.** After moving it says so and opens the output
  folder: deleting means deleting that one folder by hand, which cannot hit an original.
  The delete button and the Send2Trash dependency are gone.
- **Honest suggestion label.** The kept file is the highest resolution and, on a tie, the
  OLDEST file — an edited copy is newer and can even be the larger one. The label now reads
  "Vorschlag: höchste Auflösung" or "Vorschlag: ältestes Bild" instead of "beste Qualität".

## 1.3.0

- **100 % now means visually identical.** Every similarity hit at that level is verified pixel
  by pixel (blurred, so compression noise drops out). Painted strokes, changed text in a
  screenshot or a different head position are rejected instead of proposed. Calibrated on
  public sample images: re-encoded and resized copies score 0.000 %, a painted stroke 0.27 %,
  a changed line of text 0.011–0.029 %; the limit is 0.005 %.
- **Tiny and flat images are left out of the similarity scan** (under 32 px on a side, or
  near single-colour). A folder of accidental mini-screenshots no longer forms one big group.
  They are still found as exact copies.
- Known limit: an edit in a colour close to its background (a blue stroke on blue sky) can
  still pass the check.

## 1.2.0

- **All data next to the exe.** Settings, scan cache, report and undo journals live in a
  `DupeFinder-Daten` folder beside `DupeFinder.exe`; nothing is written anywhere else.
  Deleting everything except the exe resets the program completely.
- **Tidy first start.** If the exe is started in a folder that holds other files, it moves
  itself into a `DupeFinder` subfolder and says so. This check runs only on the first start.

## 1.1.0

- **Similarity search calibrated on real photos.** 256-bit perceptual hash; at 100 % the
  same photo is found in any size or quality and the lower-quality copy is set aside.
  The slider now explains what each level finds and what is never matched.
- **Faster on network drives.** File size and date come from the directory listing;
  hashing runs several files in parallel.
- **Rotated phone photos** (EXIF orientation) now match their messenger copies.
- **Safety hardening.** Symlinks and NTFS junctions are skipped, a file is never moved
  when it is the same physical file as its kept original, the kept original must be
  unchanged, every move is journaled before it happens, deletion only runs while the
  kept original still exists and never falls back to permanent deletion, and
  destructive confirmations default to "No".

## 1.0.0

- First release as a standalone project: German UI, review window for similar images,
  journaled moves with undo, deletion to the recycle bin as a separate step.
