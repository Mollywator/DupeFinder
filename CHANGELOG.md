# Changelog

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
