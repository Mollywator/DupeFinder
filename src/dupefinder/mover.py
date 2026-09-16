"""
Moving duplicates out of the way, undoing that, and finally deleting them.

Every move run writes a journal (JSON Lines, one line per moved file, flushed
immediately) so that a crash, a power cut or a change of mind can always be
reversed. Nothing is deleted until the user explicitly asks for it, and even
then only the files this journal moved — never whatever else happens to sit in
the output folder.
"""

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from . import storage
from .scanner import is_within, normalize_group

try:
    from send2trash import send2trash
except ImportError:  # pragma: no cover
    send2trash = None

STATE_MOVED = "moved"
STATE_UNDONE = "undone"
STATE_DELETED = "deleted"


# ─── Journal ──────────────────────────────────────────────────────────────

class Journal:
    def __init__(self, path):
        self.path = Path(path)

    @classmethod
    def create(cls, scan_path, output_path):
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        journal = cls(storage.journal_dir() / f"verschoben-{stamp}.jsonl")
        journal._append({"event": "start", "scan_path": scan_path, "output_path": output_path,
                         "created": datetime.now().isoformat(timespec="seconds")})
        return journal

    def _append(self, record):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())

    def add_move(self, src, dest):
        self._append({"event": "move", "src": str(src), "dest": str(dest)})

    def mark(self, state):
        self._append({"event": state, "at": datetime.now().isoformat(timespec="seconds")})

    def read(self):
        header, moves, state = {}, [], STATE_MOVED
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # a line cut off by a crash
                    event = record.get("event")
                    if event == "start":
                        header = record
                    elif event == "move":
                        moves.append(record)
                    elif event in (STATE_UNDONE, STATE_DELETED):
                        state = event
        except OSError:
            pass
        return header, moves, state

    @property
    def state(self):
        return self.read()[2]

    @property
    def moves(self):
        return self.read()[1]


def open_journals():
    """Journals whose files are still in the output folder, newest first."""
    result = []
    for path in sorted(storage.journal_dir().glob("verschoben-*.jsonl"), reverse=True):
        journal = Journal(path)
        header, moves, state = journal.read()
        if state == STATE_MOVED and moves:
            result.append(journal)
    return result


# ─── Move ─────────────────────────────────────────────────────────────────

def _unique_destination(dest):
    if not dest.exists():
        return dest
    counter = 1
    while True:
        candidate = dest.with_name(f"{dest.stem}_{counter}{dest.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _still_same(record):
    """The file still exists and was not replaced since the scan."""
    path = Path(record["path"])
    try:
        st = path.stat()
    except OSError:
        return False
    if "size" in record and st.st_size != record["size"]:
        return False
    return True


def move_duplicates(scan_path, output_path, groups, stop_event, emit):
    """
    Move every duplicate into ``output_path``, mirroring its folder structure.

    A duplicate is only moved while at least one file of its group that is
    meant to be kept still exists — otherwise a scan result from days ago
    could move away the last remaining copy of a photo.
    """
    output_root = Path(output_path)
    output_root.mkdir(parents=True, exist_ok=True)
    groups = [normalize_group(g) for g in groups]
    total = sum(len(g["duplicates"]) for g in groups)
    journal = Journal.create(scan_path, output_path)
    moved = skipped = errors = done = 0

    emit(("status", "Duplikate werden verschoben..."))
    for group in groups:
        kept = [group["original"]] + group.get("also_keep", [])
        kept_paths = {os.path.normcase(os.path.abspath(k["path"])) for k in kept}
        keeper_exists = any(_still_same(k) for k in kept)
        for dupe in group["duplicates"]:
            if stop_event.is_set():
                emit(("log", f"Abgebrochen. {moved} von {total} verschoben."))
                emit(("move_stopped", {"moved": moved, "errors": errors, "skipped": skipped,
                                       "journal": str(journal.path)}))
                return
            done += 1
            if done % 25 == 0:
                emit(("progress", done, total, "Verschieben"))
            src = Path(dupe["path"])
            if not keeper_exists:
                skipped += 1
                emit(("log", f"Übersprungen (Original fehlt oder wurde verändert): {src}"))
                continue
            if os.path.normcase(os.path.abspath(src)) in kept_paths or is_within(src, output_root):
                skipped += 1
                continue
            if not _still_same(dupe):
                skipped += 1
                emit(("log", f"Übersprungen (nicht mehr vorhanden oder verändert): {src}"))
                continue
            try:
                rel = src.relative_to(scan_path)
            except ValueError:
                rel = Path(src.name)
            dest = _unique_destination(output_root / rel)
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dest))
                journal.add_move(src, dest)
                moved += 1
            except OSError as e:
                errors += 1
                emit(("log", f"FEHLER: {src} -> {e}"))

    emit(("progress", total, total, "Verschieben"))
    emit(("log", f"Fertig: {moved} verschoben, {skipped} übersprungen, {errors} Fehler."))
    emit(("move_done", {"moved": moved, "errors": errors, "skipped": skipped, "journal": str(journal.path)}))


# ─── Undo ─────────────────────────────────────────────────────────────────

def _prune_empty_dirs(paths, stop_at):
    """Remove folders left empty by undo/delete, never ``stop_at`` itself."""
    stop = os.path.normcase(os.path.abspath(stop_at))
    for path in sorted({Path(p).parent for p in paths}, key=lambda p: len(str(p)), reverse=True):
        current = path
        while os.path.normcase(os.path.abspath(current)) != stop and is_within(current, stop_at):
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent


def undo(journal, emit):
    header, moves, state = journal.read()
    if state != STATE_MOVED:
        emit(("log", "Dieser Vorgang wurde bereits rückgängig gemacht oder gelöscht."))
        emit(("undo_done", {"restored": 0, "conflicts": 0}))
        return
    restored = conflicts = 0
    emit(("status", "Wird rückgängig gemacht..."))
    for i, move in enumerate(reversed(moves)):
        if i % 25 == 0:
            emit(("progress", i, len(moves), "Rückgängig"))
        src, dest = Path(move["src"]), Path(move["dest"])
        if not dest.exists():
            continue  # already restored or removed by hand
        if src.exists():
            conflicts += 1
            emit(("log", f"Nicht zurückgelegt, am Ursprungsort liegt schon eine Datei: {src}"))
            continue
        try:
            src.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dest), str(src))
            restored += 1
        except OSError as e:
            conflicts += 1
            emit(("log", f"FEHLER beim Zurücklegen: {dest} -> {e}"))
    if conflicts == 0:
        journal.mark(STATE_UNDONE)
    if header.get("output_path"):
        _prune_empty_dirs([m["dest"] for m in moves], header["output_path"])
    emit(("progress", 1, 1, "Rückgängig"))
    emit(("log", f"{restored} Dateien zurückgelegt, {conflicts} Konflikte."))
    emit(("undo_done", {"restored": restored, "conflicts": conflicts}))


# ─── Delete ───────────────────────────────────────────────────────────────

DRIVE_REMOTE = 4


def has_recycle_bin(path):
    """
    Network drives and UNC shares have no recycle bin: Windows deletes files
    there permanently, without saying so. Callers must ask before that happens.
    """
    path = os.path.abspath(str(path))
    if path.startswith("\\\\"):
        return False
    if os.name != "nt":
        return True
    try:
        import ctypes

        root = os.path.splitdrive(path)[0] + "\\"
        return ctypes.windll.kernel32.GetDriveTypeW(root) != DRIVE_REMOTE
    except Exception:
        return False


def pending_files(journal):
    return [m["dest"] for m in journal.moves if Path(m["dest"]).exists()]


def delete_moved(journal, emit, permanent=False):
    """Send the files a journal moved to the recycle bin (or delete them if ``permanent``)."""
    header, moves, state = journal.read()
    files = [m["dest"] for m in moves if Path(m["dest"]).exists()]
    deleted = errors = 0
    emit(("status", "Aussortierte Dateien werden gelöscht..."))
    for i, path in enumerate(files):
        if i % 25 == 0:
            emit(("progress", i, len(files), "Löschen"))
        try:
            if permanent or send2trash is None:
                os.remove(path)
            else:
                send2trash(path)
            deleted += 1
        except Exception as e:
            errors += 1
            emit(("log", f"FEHLER beim Löschen: {path} -> {e}"))
    if errors == 0:
        journal.mark(STATE_DELETED)
    if header.get("output_path"):
        _prune_empty_dirs(files, header["output_path"])
    emit(("progress", 1, 1, "Löschen"))
    target = "endgültig gelöscht" if permanent else "in den Papierkorb gelegt"
    emit(("log", f"{deleted} Dateien {target}, {errors} Fehler."))
    emit(("delete_done", {"deleted": deleted, "errors": errors, "permanent": permanent}))
