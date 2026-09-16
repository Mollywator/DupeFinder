<!-- Inherits from ~/.claude/CLAUDE.md — do not duplicate global rules here -->

# Project: DupeFinder

Python 3.12 · CustomTkinter desktop app · PyInstaller one-file exe · end user: non-technical family member.

## Commands
- `python -m pytest -q` — test suite (must stay green)
- `start.bat` — run from source
- `pwsh ./build.ps1` — build `dist/DupeFinder.exe`
- Release: bump `src/dupefinder/__init__.py` `__version__`, tag `vX.Y.Z`, push tag → CI publishes exe

## Key Rules
- **Never lose a photo.** Moves are journaled and undoable; a duplicate only moves while a kept file of its group still exists and is unchanged. Deletion is a separate confirmed step, recycle bin only, explicit warning where no bin exists (network drives, UNC).
- Similar-image groups are star clusters around the best image (no transitive chaining) and are always reviewed in the UI before moving.
- UI text is German; code, comments, docs, commits English.
- Runtime state only under `storage.data_dir()` (`%LOCALAPPDATA%\DupeFinder`), never next to the code — the frozen exe runs from a temp dir.
- No private data in git: scan results, reports, journals and photos contain real names/paths (see `.gitignore`).
- Keep `requirements.txt` in sync with `pyproject.toml` dependencies.
