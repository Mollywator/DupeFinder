# DupeFinder

Finds duplicate photos and videos in a folder tree and moves them aside — fully
offline, nothing is ever deleted without asking.

- **Exact duplicates** (byte-identical copies) via size → 64 KB partial hash → full SHA-256.
- **Similar images** (resized, recompressed, sent via WhatsApp) via perceptual hashing.
  Each similar group is shown with thumbnails for review before anything moves.
- **Safe by design:** duplicates are *moved* into a separate folder, mirroring the
  original structure. Every move run is journaled and can be undone. Deleting
  (to the recycle bin; with an explicit warning on network drives) is a separate,
  confirmed step.
- Scans can be cancelled and resumed; hashes are cached between runs.
- Similarity levels are calibrated on real photos: **100 %** finds the same photo in any size or
  quality; lower levels add edited copies and burst shots. The UI explains each level.
- Links and junctions are never followed, so a file can never be reported as its own duplicate.
- Network drives: file stats come from the directory listing and hashing runs in parallel.

## Anleitung (Deutsch)

1. `DupeFinder.exe` aus dem neuesten [Release](../../releases/latest) herunterladen und starten.
   Beim ersten Start kann Windows SmartScreen warnen („Weitere Informationen“ → „Trotzdem ausführen“),
   weil das Programm nicht signiert ist.
2. **Hier suchen:** den Bilder-Ordner wählen. **Aussortieren nach:** einen Ordner für die Duplikate.
3. **Suche starten.** Große Sammlungen dauern beim ersten Mal länger; Abbrechen ist jederzeit möglich,
   beim nächsten Start geht es dort weiter.
4. **Duplikate aussortieren.** Ähnliche Bilder werden vorher mit Vorschau angezeigt — nur Angehaktes wird verschoben.
5. Danach fragt das Programm, ob die aussortierten Dateien gelöscht werden sollen (Papierkorb).
   Bis dahin macht **Letztes Aussortieren rückgängig** alles wieder wie vorher.

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
```

```bash
start.bat
```

```bash
pwsh ./build.ps1
```

`build.ps1` produces `dist/DupeFinder.exe` (PyInstaller, one file, no Python needed).

### Layout

| Path | Purpose |
|---|---|
| `src/dupefinder/scanner.py` | File collection, hashing phases, similarity clustering, report |
| `src/dupefinder/mover.py` | Move with journal, undo, delete to recycle bin |
| `src/dupefinder/review.py` | Thumbnail review window for similar groups |
| `src/dupefinder/gui.py` | Main window (German UI) |
| `src/dupefinder/storage.py` | State in `DupeFinder-Daten` next to the exe (atomic writes) |
| `src/dupefinder/placement.py` | First start: moves the exe into its own subfolder if its folder holds other files |
| `tests/` | pytest suite for scanner and mover |

### State on disk

All runtime data lives in one folder, `DupeFinder-Daten`, right next to the exe (or next to
`DupeFinder.pyw` when run from source; override with `DUPEFINDER_HOME`). Nothing is written anywhere
else — delete everything except the exe to reset completely. On the first start the exe moves itself
into a `DupeFinder` subfolder if its folder contains other files. Contents:
`progress.json` (hash cache + last results), `bericht.txt` (report), `settings.json`,
`journale/*.jsonl` (one journal per move run).

### Releasing

Bump `__version__` in `src/dupefinder/__init__.py`, commit, then tag `vX.Y.Z` and push the tag.
CI runs the tests, builds the exe and attaches it to a GitHub release.
