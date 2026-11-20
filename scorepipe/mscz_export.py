"""Export the repaired MusicXML to MuseScore, then run the display passes on the result.

This is the missing link between the two IRs: the structural pipeline owns the MusicXML, MuseScore
converts it, and the display pipeline then fixes what the importer re-created (hidden rests, padding
voices, tempo text). The conversion is a boundary, not a pass, so it runs once between the phases.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .core.document import Document
from .core.mscz import MsczArchive
from .core.mscx_invariants import MSCX_VERIFIERS
from .core.pass_base import Context
from .core.pipeline import RunReport, run_display
from .passes import DISPLAY_PASSES

COMMON_PATHS = (
    r"S:\Program Files\MuseScore 4\bin\MuseScore4.exe",
    r"C:\Program Files\MuseScore 4\bin\MuseScore4.exe",
    r"C:\Program Files\MuseScore 4\bin\MuseScore4.exe",
)


def find_musescore(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    from_env = os.environ.get("MSCORE") or os.environ.get("MUSESCORE")
    if from_env:
        return from_env
    found = shutil.which("MuseScore4") or shutil.which("mscore")
    if found:
        return found
    for candidate in COMMON_PATHS:
        if Path(candidate).is_file():
            return candidate
    raise RuntimeError("MuseScore not found: pass --musescore or set MSCORE")


def convert(musicxml: str | Path, mscz: str | Path, musescore: str | None = None) -> None:
    binary = find_musescore(musescore)
    destination = Path(mscz)
    destination.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [binary, "-f", "-o", str(destination), str(musicxml)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0 or not destination.is_file():
        raise RuntimeError(f"MuseScore conversion failed: {(completed.stderr or '').strip()[:500]}")


def export_and_display(
    document: Document,
    mscz_path: str | Path,
    ctx: Context,
    musescore: str | None = None,
    work_musicxml: str | Path | None = None,
) -> RunReport:
    """Write the MusicXML, convert it, run the display fixpoint and re-save the archive."""
    destination = Path(mscz_path)
    intermediate = Path(work_musicxml) if work_musicxml else destination.with_suffix(".musicxml")
    document.save(intermediate)
    try:
        convert(intermediate, destination, musescore)
        archive = MsczArchive.open(destination)
        display_ctx = Context(facts=dict(ctx.facts), options=dict(ctx.options))
        report = run_display(archive.document, display_ctx, DISPLAY_PASSES, MSCX_VERIFIERS)
        archive.save(destination)
        return report
    finally:
        if work_musicxml is None and intermediate.exists():
            intermediate.unlink()
