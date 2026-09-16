"""
Duplicate detection.

Phases 1-3 find byte-identical files (size -> 64 KB partial hash -> full hash).
Phase 4 finds visually similar images via perceptual hashing.

Fully local — no network calls. Progress is reported through ``emit``, which
receives tuples such as ("status", text) or ("progress", current, total, phase);
the GUI feeds them from a queue.
"""

import hashlib
import os
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from . import storage

try:
    import numpy as np
    from PIL import Image, ImageOps
    import imagehash

    PERCEPTUAL_AVAILABLE = True
except ImportError:  # pragma: no cover - the packaged build always has them
    PERCEPTUAL_AVAILABLE = False

EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".webp", ".heic", ".heif",
    ".cr2", ".nef", ".arw", ".dng",
    ".mp4", ".mov", ".avi", ".mkv",
}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".webp"}

# HEIC needs a decoder Pillow does not ship with; register it when present so
# iPhone photos take part in the visual comparison instead of exact-match only.
try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    IMAGE_EXTENSIONS |= {".heic", ".heif"}
except ImportError:
    pass

if PERCEPTUAL_AVAILABLE:
    # Scanned photo libraries contain panoramas and scans far beyond Pillow's
    # decompression-bomb limit; these are the user's own files, not hostile input.
    Image.MAX_IMAGE_PIXELS = None
    _POPCOUNT = np.unpackbits(np.arange(256, dtype=np.uint8)[:, None], axis=1).sum(axis=1)

PARTIAL_HASH_SIZE = 65536  # 64 KB
# 256-bit perceptual hash. Calibrated on ~1,300 real phone photos: the 64-bit
# hash needed a looser threshold to catch every re-encoded copy and then also
# grabbed twice as many burst shots, while 256 bits separates the two cleanly.
HASH_SIZE = 16
HASH_BITS = HASH_SIZE * HASH_SIZE
PHASH_KEY = "phash16"  # cache key; entries from the old 64-bit hash are ignored
# Re-encoding alone moves a 256-bit hash by up to ~3 %, so "100 %" in the UI
# means "the same photo in any quality", not "bit-identical hash".
IDENTICAL_SIMILARITY = 97
AUTOSAVE_SECONDS = 60
IO_WORKERS = 8


# ─── Paths ────────────────────────────────────────────────────────────────

def norm(path):
    return os.path.normcase(os.path.abspath(str(path)))


def is_within(path, root):
    try:
        return os.path.commonpath([norm(path), norm(root)]) == norm(root)
    except ValueError:  # different drives
        return False


def validate_paths(scan_path, output_path):
    """Return a German error message, or None when the paths are usable."""
    if not scan_path or not Path(scan_path).is_dir():
        return "Der Such-Ordner existiert nicht."
    if not output_path:
        return "Bitte einen Ordner für aussortierte Dateien angeben."
    if norm(scan_path) == norm(output_path):
        return "Such-Ordner und Aussortiert-Ordner dürfen nicht derselbe Ordner sein."
    if is_within(scan_path, output_path):
        return "Der Such-Ordner darf nicht im Aussortiert-Ordner liegen."
    return None


# ─── Hashing ──────────────────────────────────────────────────────────────

def partial_hash(filepath, size=PARTIAL_HASH_SIZE):
    h = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            h.update(f.read(size))
    except OSError:
        return None
    return h.hexdigest()


def full_hash(filepath):
    h = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            while chunk := f.read(1 << 20):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def perceptual_info(filepath):
    """Return (phash hex, pixel count) or None if the image cannot be decoded."""
    if not PERCEPTUAL_AVAILABLE:
        return None
    try:
        with Image.open(filepath) as img:
            pixels = img.size[0] * img.size[1]
            # JPEG draft mode decodes at a fraction of the size; phash shrinks
            # to 64x64 anyway, so this is a large speedup for no accuracy loss.
            img.draft("RGB", (256, 256))
            # Phones often store rotation as an EXIF flag while messengers bake it
            # into the pixels; without this the two copies never match.
            img = ImageOps.exif_transpose(img)
            return str(imagehash.phash(img.convert("RGB"), hash_size=HASH_SIZE)), pixels
    except Exception:
        return None


def format_size(size_bytes):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


# ─── Similarity clustering ────────────────────────────────────────────────

def _hex_to_words(hex_hashes):
    """Split each hex hash into 64-bit words: shape (n, words)."""
    return np.array(
        [[int(h[k:k + 16], 16) for k in range(0, len(h), 16)] for h in hex_hashes], dtype=np.uint64
    ).reshape(len(hex_hashes), -1)


def _distances(values, i):
    x = np.bitwise_xor(values, values[i])
    if hasattr(np, "bitwise_count"):
        return np.bitwise_count(x).sum(axis=1)
    return _POPCOUNT[x.view(np.uint8)].reshape(len(x), -1).sum(axis=1)


def cluster_similar(hex_hashes, priority, max_distance):
    """
    Group hashes around a center so that EVERY member is within
    ``max_distance`` of its center.

    The earlier union-find grouping chained matches: A~B and B~C put A and C
    together even when they look nothing alike, which on burst photos moved
    genuinely different pictures. Here the best image (lowest ``priority``)
    claims its neighbours first, and nothing joins a group by resembling a
    member instead of the kept image.

    Returns a list of (center_index, [member_index, ...]).
    """
    n = len(hex_hashes)
    if n < 2:
        return []
    values = _hex_to_words(hex_hashes)
    assigned = np.zeros(n, dtype=bool)
    groups = []
    for i in sorted(range(n), key=lambda k: priority[k]):
        if assigned[i]:
            continue
        assigned[i] = True
        hits = np.nonzero((~assigned) & (_distances(values, i) <= max_distance))[0]
        if len(hits):
            assigned[hits] = True
            groups.append((i, sorted(hits.tolist(), key=lambda k: priority[k])))
    return groups


def max_distance_for(threshold_percent):
    effective = min(threshold_percent, IDENTICAL_SIMILARITY)
    return int((1.0 - effective / 100) * HASH_BITS)


# What each slider range finds, measured on ~1,300 real phone photos
# (same photo re-encoded / resized, pairs shot <=2 s apart, seconds, minutes,
# hours and days apart). Shown to the user under the slider.
LEVEL_DESCRIPTIONS = [
    (97, "Nur dasselbe Foto in anderer Größe oder Qualität (verkleinert, per WhatsApp verschickt, "
         "stärker komprimiert). Findet davon praktisch alle – aussortiert wird die schlechtere Fassung. "
         "Selten dabei: Serienfotos aus derselben Sekunde, die praktisch gleich aussehen (etwa 2 von 10)."),
    (93, "Zusätzlich leicht bearbeitete Fassungen (heller oder dunkler) und einzelne fast identische "
         "Serienfotos aus derselben Sekunde."),
    (88, "Zusätzlich Serienfotos mit kleinen Unterschieden wie geschlossene Augen oder leicht gedrehter Kopf "
         "(etwa 4 von 10 solcher Serienbilder). Bitte in der Vorschau genau ansehen."),
    (80, "Findet die meisten Serienfotos (etwa 6 von 10) und vereinzelt Fotos, die einige Sekunden "
         "auseinander liegen. Hier ist Prüfen in der Vorschau Pflicht."),
]
LEVEL_FOOTNOTE = ("Nie gefunden (gemessen bis 70 %): Fotos, die Minuten, Stunden oder Tage auseinander liegen. "
                  "Nicht erkannt: zugeschnittene Bilder und Bilder mit Rand.")


def describe_level(threshold_percent):
    for minimum, text in LEVEL_DESCRIPTIONS:
        if threshold_percent >= minimum:
            return text
    return LEVEL_DESCRIPTIONS[-1][1]


# ─── Scan ─────────────────────────────────────────────────────────────────

class _Cache:
    """Hash cache keyed by path, invalidated when size or mtime change."""

    def __init__(self, entries):
        self.entries = entries

    def get(self, path, stats):
        size, mtime = stats
        entry = self.entries.get(path)
        if entry is not None and entry.get("size") == size and entry.get("mtime") == mtime:
            return entry
        entry = {"size": size, "mtime": mtime}
        self.entries[path] = entry
        return entry


class _Scan:
    def __init__(self, scan_path, output_path, stop_event, emit, resume_data):
        self.scan_path = scan_path
        self.output_path = output_path
        self.stop_event = stop_event
        self.emit = emit
        entries = {}
        if resume_data and resume_data.get("file_hashes"):
            if norm(resume_data.get("scan_path", "")) == norm(scan_path):
                entries = resume_data["file_hashes"]
            else:
                emit(("log", "Anderer Such-Ordner als beim letzten Mal — alter Zwischenstand verworfen."))
        self.cache = _Cache(entries)
        self.last_save = time.monotonic()

    def stopped(self):
        if not self.stop_event.is_set():
            return False
        self.save_partial()
        self.emit(("log", "Zwischenstand gespeichert."))
        self.emit(("stopped", None))
        return True

    def save_partial(self):
        storage.save_progress({
            "scan_path": self.scan_path,
            "output_path": self.output_path,
            "file_hashes": self.cache.entries,
            "scan_complete": False,
            "last_updated": datetime.now().isoformat(timespec="seconds"),
        })
        self.last_save = time.monotonic()

    def autosave(self):
        if time.monotonic() - self.last_save > AUTOSAVE_SECONDS:
            self.save_partial()

    def fill_cache(self, files, stats, key, compute, label):
        """
        Compute ``key`` for every file whose cache entry lacks it.

        Runs on a thread pool: on a network drive nearly all of the time is spent
        waiting for the NAS, and hashing releases the GIL, so several files in
        flight at once are many times faster than one after another. Results are
        written back on this thread only. Returns False when cancelled.
        """
        total = len(files)
        todo = [fp for fp in files if key not in self.cache.get(str(fp), stats[str(fp)])]
        done = total - len(todo)
        self.emit(("progress", done, total, label))
        with ThreadPoolExecutor(max_workers=IO_WORKERS) as pool:
            for start in range(0, len(todo), IO_WORKERS * 4):
                if self.stopped():
                    return False
                batch = todo[start:start + IO_WORKERS * 4]
                for fp, values in zip(batch, pool.map(_safe(compute), batch)):
                    if values is None:
                        self.emit(("log", f"WARNUNG: Nicht lesbar: {fp}"))
                    else:
                        self.cache.entries[str(fp)].update(values)
                done += len(batch)
                self.emit(("progress", done, total, label))
                self.emit(("current_file", str(batch[-1])))
                self.autosave()
        return not self.stopped()


def _safe(compute):
    def run(fp):
        try:
            return compute(fp)
        except Exception:
            return None
    return run


def _as_entry(key, value):
    return {key: value} if value else None


def _dots(number):
    return f"{number:,}".replace(",", ".")


def _walk(root, output_path, emit):
    """
    Yield (path, size, mtime) for every supported file below ``root``.

    Size and date come from the directory listing itself (os.scandir). Asking
    for them per file costs one network round trip each: measured on a NAS
    share, 1,974 files took 272 s that way versus 8 s from the listing.
    """
    stack = [root]
    while stack:
        directory = stack.pop()
        if is_within(directory, output_path):
            continue
        try:
            with os.scandir(directory) as it:
                entries = sorted(it, key=lambda e: e.name.lower())
        except OSError:
            emit(("log", f"WARNUNG: Ordner nicht lesbar: {directory}"))
            continue
        subdirs = []
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    subdirs.append(entry.path)
                elif os.path.splitext(entry.name)[1].lower() in EXTENSIONS:
                    st = entry.stat(follow_symlinks=False)
                    yield Path(entry.path), st.st_size, int(st.st_mtime)
            except OSError:
                emit(("log", f"WARNUNG: Nicht lesbar: {entry.path}"))
        stack.extend(reversed(subdirs))


def _file_record(path, stats, **extra):
    record = {"path": str(path), "size": stats[0], "mtime": stats[1]}
    record.update(extra)
    return record


def scan(scan_path, output_path, stop_event, emit, resume_data=None, similarity_threshold=None):
    """Run a full scan. Emits ("done", summary) on success."""
    s = _Scan(scan_path, output_path, stop_event, emit, resume_data)

    # ── Phase 1: collect files with size and date ────────────────────────
    emit(("status", "Phase 1: Dateien werden gesammelt..."))
    all_files = []
    stats = {}
    size_map = defaultdict(list)
    for fp, size, mtime in _walk(scan_path, output_path, emit):
        all_files.append(fp)
        stats[str(fp)] = (size, mtime)
        # Empty files all hash alike but are not copies of one another.
        if size > 0:
            size_map[size].append(fp)
        if len(all_files) % 500 == 0:
            if s.stopped():
                return
            emit(("current_file", str(fp.parent)))
            emit(("progress", 0, 0, f"{_dots(len(all_files))} Dateien gefunden"))
    if s.stopped():
        return
    total = len(all_files)
    emit(("log", f"{_dots(total)} Dateien gefunden."))

    candidates = [fp for files in size_map.values() if len(files) >= 2 for fp in files]

    # ── Phase 2 + 3: partial, then full hash ─────────────────────────────
    def hash_phase(files, key, func, label):
        if not s.fill_cache(files, stats, key, lambda fp: _as_entry(key, func(fp)), label):
            return None
        groups = defaultdict(list)
        for fp in files:
            value = s.cache.entries[str(fp)].get(key)
            if value:
                groups[(stats[str(fp)][0], value)].append(fp)
        return [fp for group in groups.values() if len(group) >= 2 for fp in group]

    emit(("status", "Phase 2: Dateianfänge vergleichen..."))
    partial_matches = hash_phase(candidates, "partial_hash", partial_hash, "Teil-Prüfsumme")
    if partial_matches is None:
        return

    emit(("status", "Phase 3: Dateien vollständig vergleichen..."))
    full_matches = hash_phase(partial_matches, "full_hash", full_hash, "Prüfsumme")
    if full_matches is None:
        return
    by_hash = defaultdict(list)
    for fp in full_matches:
        by_hash[s.cache.entries[str(fp)]["full_hash"]].append(fp)
    full_groups = list(by_hash.values())

    # ── Exact duplicates ─────────────────────────────────────────────────
    exact_groups = []
    exact_dupe_paths = set()
    saved_bytes = 0
    for files in full_groups:
        # Oldest file is the original; on a tie the shorter path (less nested).
        files.sort(key=lambda f: (stats[str(f)][1], len(str(f)), str(f)))
        original, dupes = files[0], files[1:]
        group = {
            "type": "exact",
            "hash": s.cache.entries[str(original)]["full_hash"],
            "original": _file_record(original, stats[str(original)]),
            "duplicates": [_file_record(d, stats[str(d)]) for d in dupes],
        }
        for d in dupes:
            exact_dupe_paths.add(str(d))
            saved_bytes += stats[str(d)][0]
        exact_groups.append(group)
    total_dupes = len(exact_dupe_paths)
    emit(("log", f"{total_dupes:,} exakte Duplikate gefunden.".replace(",", ".")))

    # ── Phase 4: visual similarity ───────────────────────────────────────
    similar_groups = []
    total_similar = 0
    if similarity_threshold is not None and PERCEPTUAL_AVAILABLE:
        emit(("status", "Phase 4: Ähnliche Bilder suchen..."))
        max_distance = max_distance_for(similarity_threshold)
        images = [
            fp for fp in all_files
            if fp.suffix.lower() in IMAGE_EXTENSIONS
            and str(fp) in stats and stats[str(fp)][0] > 0
            and str(fp) not in exact_dupe_paths
        ]
        emit(("log", f"{len(images):,} Bilder werden auf Ähnlichkeit geprüft (Schwelle {similarity_threshold} %).".replace(",", ".")))

        def compute(fp):
            info = perceptual_info(fp)
            # Undecodable images are cached as such, so they are not retried every scan.
            return {PHASH_KEY: info[0], "pixels": info[1]} if info else {PHASH_KEY: None, "pixels": 0}

        if not s.fill_cache(images, stats, PHASH_KEY, compute, "Ähnlichkeit"):
            return
        hashed = []  # (path, phash, pixels)
        for fp in images:
            entry = s.cache.entries[str(fp)]
            if entry.get(PHASH_KEY):
                hashed.append((fp, entry[PHASH_KEY], entry["pixels"]))

        emit(("status", "Phase 4: Bilder werden verglichen..."))
        emit(("progress", 0, 1, "Vergleichen"))
        priority = [(-px, -stats[str(fp)][0], len(str(fp)), str(fp)) for fp, _, px in hashed]
        for center, members in cluster_similar([h for _, h, _ in hashed], priority, max_distance):
            best = hashed[center]
            group = {
                "type": "similar",
                "original": _file_record(best[0], stats[str(best[0])], pixels=best[2]),
                "duplicates": [
                    _file_record(hashed[m][0], stats[str(hashed[m][0])], pixels=hashed[m][2])
                    for m in members
                ],
            }
            for m in members:
                saved_bytes += stats[str(hashed[m][0])][0]
            total_similar += len(members)
            similar_groups.append(group)
        emit(("log", f"{total_similar:,} ähnliche Bilder in {len(similar_groups):,} Gruppen gefunden.".replace(",", ".")))

    write_report(scan_path, output_path, exact_groups, similar_groups, total_dupes, total_similar, saved_bytes)

    progress = {
        "scan_path": scan_path,
        "output_path": output_path,
        # Drop entries for files that no longer exist, so the cache tracks the
        # folder instead of accumulating every path ever seen.
        "file_hashes": {k: v for k, v in s.cache.entries.items() if k in stats},
        "duplicate_groups": exact_groups,
        "similar_groups": similar_groups,
        "total_dupes": total_dupes,
        "total_similar": total_similar,
        "saved_bytes": saved_bytes,
        "similarity_threshold": similarity_threshold,
        "scan_complete": True,
        "last_updated": datetime.now().isoformat(timespec="seconds"),
    }
    storage.save_progress(progress)

    emit(("done", {
        "duplicates": total_dupes,
        "similar": total_similar,
        "saved_bytes": saved_bytes,
        "groups": exact_groups,
        "similar_groups": similar_groups,
    }))


def write_report(scan_path, output_path, exact_groups, similar_groups, total_dupes, total_similar, saved_bytes):
    lines = [
        f"DupeFinder Bericht — {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        f"Such-Ordner:       {scan_path}",
        f"Aussortiert-Ordner: {output_path}",
        "=" * 60, "",
        "EXAKTE DUPLIKATE (Byte für Byte identisch)",
        "-" * 40, "",
    ]
    for g in exact_groups:
        lines.append(f"  Behalten:    {g['original']['path']}")
        lines.extend(f"  Duplikat:    {d['path']}" for d in g["duplicates"])
        lines.append("")
    if similar_groups:
        lines += ["", "ÄHNLICHE BILDER", "-" * 40, ""]
        for g in similar_groups:
            lines.append(f"  Beste Qualität: {g['original']['path']}")
            lines.extend(f"  Ähnlich:        {d['path']}" for d in g["duplicates"])
            lines.append("")
    lines += [
        "=" * 60,
        f"Gesamt: {total_dupes + total_similar} Duplikate ({total_dupes} exakt, {total_similar} ähnlich), "
        f"{format_size(saved_bytes)} freizugeben.",
    ]
    try:
        storage.report_file().write_text("\n".join(lines), encoding="utf-8")
    except OSError:
        pass


def normalize_group(group):
    """Accept groups saved by the pre-1.0 script, where 'original' was a plain path."""
    original = group.get("original")
    if isinstance(original, str):
        group["original"] = {"path": original}
    group.setdefault("type", "exact")
    return group
