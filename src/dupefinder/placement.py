"""
First-start placement of the packaged exe.

On its very first start the program checks whether it was dropped into a
folder that also holds other files (Downloads, the desktop, ...). If so it
moves itself into its own subfolder, so its data folder does not add to the
clutter there. A marker in the data folder records that this check ran; to
start over, delete everything next to the exe except the exe itself.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import storage

MARKER = "erster-start.txt"
SUBFOLDER = "DupeFinder"
IGNORED = {"desktop.ini", "thumbs.db", ".ds_store"}

MARKER_TEXT = (
    "DupeFinder: erster Start wurde geprüft.\n"
    "Zum kompletten Zurücksetzen alles außer der DupeFinder.exe löschen.\n"
)


def is_first_start(folder):
    return not (Path(folder) / storage.DATA_FOLDER / MARKER).exists()


def _crowded(folder, exe):
    for entry in folder.iterdir():
        if entry == exe or entry.name == storage.DATA_FOLDER or entry.name.lower() in IGNORED:
            continue
        return True
    return False


def _free_subfolder(folder):
    n = 1
    while True:
        candidate = folder / (SUBFOLDER if n == 1 else f"{SUBFOLDER} ({n})")
        if not candidate.exists() or (candidate.is_dir() and not any(candidate.iterdir())):
            return candidate
        n += 1


def _delete_after_exit(path):
    """
    Remove the old exe once this program has exited. A running exe cannot
    always be renamed (the bootloader keeps it open), so it is copied and the
    original is cleaned up by a hidden helper that waits for both processes.
    """
    quoted = str(path).replace("'", "''")
    script = (
        f"Wait-Process -Id {os.getpid()},{os.getppid()} -ErrorAction SilentlyContinue; "
        f"for ($i = 0; $i -lt 30; $i++) {{ "
        f"try {{ Remove-Item -LiteralPath '{quoted}' -Force -ErrorAction Stop; break }} "
        f"catch {{ Start-Sleep -Seconds 1 }} }}"
    )
    subprocess.Popen(
        ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", script],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0),
        close_fds=True,
    )


def _move_self(exe, dest):
    try:
        os.replace(exe, dest)
    except OSError:
        shutil.copy2(exe, dest)
        _delete_after_exit(exe)


def check_writable(folder):
    """Raise OSError when nothing can be stored in ``folder``."""
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile(dir=folder):
        pass


def first_start(exe):
    """
    Run the first-start check for the program at ``exe``.

    Returns the exe's new path when it moved itself into a subfolder, None
    otherwise. Raises OSError when the move failed; the program then stays
    where it is and the check runs again on the next start.
    """
    exe = Path(exe)
    folder = exe.parent
    if not is_first_start(folder):
        return None
    moved = None
    if _crowded(folder, exe):
        target = _free_subfolder(folder)
        target.mkdir(exist_ok=True)
        dest = target / exe.name
        try:
            _move_self(exe, dest)
        except OSError:
            try:
                target.rmdir()
            except OSError:
                pass
            raise
        old_data = folder / storage.DATA_FOLDER
        if old_data.is_dir():
            shutil.move(str(old_data), str(target / storage.DATA_FOLDER))
        folder, moved = target, dest
    storage.set_app_dir(folder)
    (storage.data_dir() / MARKER).write_text(MARKER_TEXT, encoding="utf-8")
    return moved


def running_exe():
    """Path of the packaged exe, or None when running from source."""
    return Path(sys.executable).resolve() if getattr(sys, "frozen", False) else None
