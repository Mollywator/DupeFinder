"""
Where DupeFinder keeps its state.

Everything lives under %LOCALAPPDATA%\\DupeFinder. The old layout wrote next to
the script, which breaks as soon as the program is packaged: a PyInstaller
one-file build unpacks into a fresh temp folder on every start, so the scan
cache and the undo journals would vanish with each run.
"""

import json
import os
import tempfile
from pathlib import Path

APP_NAME = "DupeFinder"


def data_dir():
    base = os.environ.get("DUPEFINDER_HOME")
    if base:
        root = Path(base)
    else:
        local = os.environ.get("LOCALAPPDATA")
        root = Path(local) / APP_NAME if local else Path.home() / f".{APP_NAME.lower()}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def progress_file():
    return data_dir() / "progress.json"


def report_file():
    return data_dir() / "bericht.txt"


def settings_file():
    return data_dir() / "settings.json"


def journal_dir():
    path = data_dir() / "journale"
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def write_json(path, data):
    """
    Write atomically: a crash or a full disk mid-write must never leave a
    truncated file behind, because a corrupt progress file silently throws
    away hours of hashing.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False


def load_progress():
    return read_json(progress_file())


def save_progress(data):
    return write_json(progress_file(), data)


def clear_results(data):
    """Drop finished results but keep the hash cache for the next scan."""
    if not data:
        return
    for key in ("duplicate_groups", "similar_groups"):
        data[key] = []
    data["total_dupes"] = 0
    data["total_similar"] = 0
    data["saved_bytes"] = 0
    data["scan_complete"] = False
    save_progress(data)


def load_settings():
    return read_json(settings_file()) or {}


def save_settings(settings):
    write_json(settings_file(), settings)
