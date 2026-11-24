"""Locate external tools without hard-coding one machine's install paths.

The skill runs on more than one workstation: MuseScore may live on ``C:``, ``S:`` or in a
portable directory.  Discovery therefore looks at, in order: an explicit path, the environment,
``PATH``, the Windows ``App Paths`` registry, and every fixed drive's ``Program Files``.
"""

from __future__ import annotations

import os
import shutil
import string
from pathlib import Path

WINDOWS_RELATIVE = Path("MuseScore 4") / "bin" / "MuseScore4.exe"
EXECUTABLE_NAMES = ("MuseScore4.exe", "MuseScore4", "musescore4", "mscore4", "mscore")
ENVIRONMENT_VARIABLES = ("MUSESCORE_EXE", "MSCORE", "MUSESCORE")


def _environment_candidates() -> list[str]:
    return [os.environ[name] for name in ENVIRONMENT_VARIABLES if os.environ.get(name)]


def _path_candidates() -> list[str]:
    found = []
    for name in EXECUTABLE_NAMES:
        located = shutil.which(name)
        if located:
            found.append(located)
    return found


def _registry_candidates() -> list[str]:
    try:
        import winreg
    except ImportError:  # not on Windows
        return []
    locations = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\MuseScore4.exe"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\MuseScore4.exe"),
    )
    found = []
    for root, subkey in locations:
        try:
            with winreg.OpenKey(root, subkey) as key:
                value, _ = winreg.QueryValueEx(key, "")
        except OSError:
            continue
        if value:
            found.append(value)
    return found


def _drive_candidates() -> list[str]:
    roots: list[Path] = []
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        value = os.environ.get(variable)
        if value:
            roots.append(Path(value))
    for letter in string.ascii_uppercase:
        roots.append(Path(f"{letter}:\\Program Files"))
    candidates = [str(root / WINDOWS_RELATIVE) for root in roots]
    candidates.extend(
        [
            "/Applications/MuseScore 4.app/Contents/MacOS/mscore",
            "/usr/bin/musescore4",
            "/usr/bin/mscore4",
        ]
    )
    return candidates


def find_musescore(explicit: str | None = None) -> str | None:
    """Return the first existing MuseScore executable, or ``None``."""
    for candidate in (
        *([explicit] if explicit else []),
        *_environment_candidates(),
        *_path_candidates(),
        *_registry_candidates(),
        *_drive_candidates(),
    ):
        if candidate and Path(candidate).is_file():
            return str(candidate)
    return None
