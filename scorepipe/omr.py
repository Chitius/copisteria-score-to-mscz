"""OMR front-end: run an external converter command and return the page files it wrote.

The concrete converter (copisteria or anything else) is supplied by the caller as a command
string with two placeholders:

    --omr 'python -m copisteria.cli {pdf} {outdir}'

The loader then merges the produced page MusicXML exactly as if the pages had been passed as a
directory. Keeping the command external means the pipeline does not grow a dependency on one
particular OMR tool.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def run_omr(command: str, pdf: str | Path, outdir: str | Path) -> list[Path]:
    destination = Path(outdir)
    destination.mkdir(parents=True, exist_ok=True)
    formatted = command.format(pdf=str(pdf), outdir=str(destination))
    completed = subprocess.run(
        formatted,
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"OMR command failed ({completed.returncode}): {detail[:800]}")
    pages = sorted(destination.glob("*.musicxml"))
    if not pages:
        raise RuntimeError(f"OMR command produced no page MusicXML in {destination}")
    return pages


def default_python() -> str:
    return sys.executable
