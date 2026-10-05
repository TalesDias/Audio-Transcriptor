"""First-run self-install (Linux only).

When launched as a downloaded AppImage or standalone binary — not yet living
in its install location — copy the running executable into ~/.local/bin and
register a desktop entry + icon, so the app shows up in the menu and behaves
like an installed application instead of a file sitting in ~/Downloads.

No-op when running from source (`python -m transcritor`) or once already
installed.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .config import XDG_DATA_HOME

ASSETS_DIR = Path(__file__).parent / "assets"
BIN_DIR = Path.home() / ".local" / "bin"
INSTALLED_BIN = BIN_DIR / "transcritor"
APPLICATIONS_DIR = XDG_DATA_HOME / "applications"
ICON_DIR = XDG_DATA_HOME / "icons" / "hicolor" / "scalable" / "apps"


def _running_executable() -> Path | None:
    """Path of the binary actually being executed: the AppImage file itself
    (its runtime exposes the original path via $APPIMAGE, not the temp mount
    it runs from), or a frozen PyInstaller binary invoked directly."""
    appimage = os.environ.get("APPIMAGE")
    if appimage:
        return Path(appimage).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return None


def ensure_installed() -> None:
    if sys.platform != "linux":
        return

    exe = _running_executable()
    if exe is None or exe == INSTALLED_BIN.resolve():
        return

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(exe, INSTALLED_BIN)
    INSTALLED_BIN.chmod(0o755)

    APPLICATIONS_DIR.mkdir(parents=True, exist_ok=True)
    desktop_entry = (ASSETS_DIR / "transcritor.desktop").read_text().replace("@BIN@", str(INSTALLED_BIN))
    (APPLICATIONS_DIR / "transcritor.desktop").write_text(desktop_entry)

    ICON_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ASSETS_DIR / "transcritor.svg", ICON_DIR / "transcritor.svg")

    try:
        subprocess.run(["update-desktop-database", str(APPLICATIONS_DIR)], capture_output=True)
    except FileNotFoundError:
        pass


def remove_installed() -> bool:
    """Undo ensure_installed(). Returns False if nothing was installed."""
    paths = (INSTALLED_BIN, APPLICATIONS_DIR / "transcritor.desktop", ICON_DIR / "transcritor.svg")
    found = [p for p in paths if p.exists()]
    for p in found:
        p.unlink()

    try:
        subprocess.run(["update-desktop-database", str(APPLICATIONS_DIR)], capture_output=True)
    except FileNotFoundError:
        pass

    return bool(found)
