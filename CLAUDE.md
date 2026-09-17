<!-- Inherits from ~/.claude/CLAUDE.md — do not duplicate global rules here -->

# Project: DupeFinder

Python 3.12 · CustomTkinter desktop app · PyInstaller one-file exe · end user: non-technical family member.

## Commands
- `python -m pytest -q` — test suite (must stay green)
- `start.bat` — run from source
- `pwsh ./build.ps1` — build `dist/DupeFinder.exe`
- Release: bump `src/dupefinder/__init__.py` `__version__`, tag `vX.Y.Z`, push tag → CI publishes exe

## Key Rules
- **Never lose a photo.** Moves are journaled and undoable; a duplicate only moves while a kept file of its group still exists and is unchanged. **The program never deletes** — the user removes the output folder by hand; do not add a delete function.
- Every group — exact copies too — is reviewed in the UI before moving. Similar groups are star clusters around the suggested file (no transitive chaining).
- The suggested file to keep = highest resolution, on a tie the OLDEST file; never call it "best quality" in the UI (an edited copy can be the larger file).
- Similarity uses a 256-bit pHash; slider levels and their German descriptions (`scanner.LEVEL_DESCRIPTIONS`) are calibrated on real photos — re-measure before changing thresholds. Never commit benchmark data or example images.
- UI text is German; code, comments, docs, commits English.
- Runtime state only under `storage.data_dir()` = `DupeFinder-Daten` next to the exe (user requirement: no residue anywhere else). Derive the location from `sys.executable`, never `__file__` — the frozen exe runs from a temp dir.
- No private data in git: scan results, reports, journals and photos contain real names/paths (see `.gitignore`).
- Keep `requirements.txt` in sync with `pyproject.toml` dependencies.
