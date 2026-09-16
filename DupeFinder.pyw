"""Entry point for double-click starts and the PyInstaller build."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from dupefinder.gui import main  # noqa: E402

main()
