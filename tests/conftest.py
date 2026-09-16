import os
import shutil
import threading

import numpy as np
import pytest
from PIL import Image


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Keep progress files and journals out of the real %LOCALAPPDATA%."""
    home = tmp_path / "_appdata"
    monkeypatch.setenv("DUPEFINDER_HOME", str(home))
    return home


class Recorder(list):
    def __call__(self, msg):
        self.append(msg)

    def last(self, kind):
        return next(m[1] for m in reversed(self) if m[0] == kind)

    def kinds(self):
        return [m[0] for m in self]


@pytest.fixture
def events():
    return Recorder()


@pytest.fixture
def stop():
    return threading.Event()


def make_photo(path, seed, size=(640, 480), quality=95):
    """A structured random image — distinct seeds give visually distinct pictures."""
    rng = np.random.default_rng(seed)
    small = rng.integers(0, 256, (36, 48, 3), dtype=np.uint8)  # photo-like detail at all frequencies
    img = Image.fromarray(small).resize(size, Image.BICUBIC)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in (".jpg", ".jpeg"):
        img.save(path, quality=quality)
    else:
        img.save(path)
    return path


def make_pair(root):
    """An older original plus a byte-identical copy in another folder."""
    original = make_photo(root / "2020" / "foto.jpg", 1)
    copy = root / "Kopien" / "foto.jpg"
    copy.parent.mkdir(parents=True)
    shutil.copy(original, copy)
    os.utime(original, (1_000_000, 1_000_000))
    return original, copy
