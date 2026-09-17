"""
Where DupeFinder keeps its state.

Everything the program creates lives in one folder, "DupeFinder-Daten", right
next to the exe (or next to DupeFinder.pyw when run from source). Nothing is
written to %LOCALAPPDATA% or anywhere else, so deleting that folder resets the
program completely and leaves no residue on the machine.

The location is taken from the exe's path, never from ``__file__``: a
PyInstaller one-file build runs from a temp folder that is wiped on exit.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

APP_NAME = "DupeFinder"
DATA_FOLDER = "DupeFinder-Daten"

_app_dir_override = None


def app_dir():
    """The folder the user placed the program in."""
    if _app_dir_override is not None:
        return _app_dir_override
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def set_app_dir(path):
    global _app_dir_override
    _app_dir_override = Path(path)


def data_dir():
    base = os.environ.get("DUPEFINDER_HOME")
    root = Path(base) if base else app_dir() / DATA_FOLDER
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
