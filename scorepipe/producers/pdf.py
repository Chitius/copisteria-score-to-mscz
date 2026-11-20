"""Text-layer facts from a PDF, via poppler's `pdftotext -bbox`.

Two stages, both data-only:

1. `extract_words` reads the PDF text layer into positioned words;
2. `assign_measures` maps a word to a measure using a layout file that gives each measure's
   bounding box on its page (page width/height in PDF points).

The layout file is produced by the OMR/front-end side; this module never guesses a measure from a
word's text alone.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from xml.etree import ElementTree

from .base import FactSet


def find_pdftotext(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    found = shutil.which("pdftotext")
    if found:
        return found
    raise RuntimeError(
        "pdftotext not found: install poppler or pass its path / set SCOREPIPE_PDFTOTEXT"
    )


def extract_words(pdf: str | Path, pdftotext: str | None = None) -> list[dict]:
    binary = find_pdftotext(pdftotext)
    completed = subprocess.run(
        [binary, "-bbox", str(pdf), "-"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"pdftotext failed: {(completed.stderr or '').strip()[:500]}")
    root = ElementTree.fromstring(completed.stdout)
    words: list[dict] = []
    for page_index, page in enumerate(_pages(root), start=1):
        for word in page.iter():
            if not word.tag.endswith("word"):
                continue
            text = (word.text or "").strip()
            if not text:
                continue
            try:
                words.append(
                    {
                        "page": page_index,
                        "text": text,
                        "x0": float(word.get("xMin") or 0),
                        "y0": float(word.get("yMin") or 0),
                        "x1": float(word.get("xMax") or 0),
                        "y1": float(word.get("yMax") or 0),
                    }
                )
            except ValueError:
                continue
    return words


def _pages(root: ElementTree.Element) -> list[ElementTree.Element]:
    return [element for element in root.iter() if element.tag.endswith("page")]


def assign_measures(words: list[dict], layout: dict) -> list[dict]:
    """Map each word to the measure whose box contains its centre."""
    boxes: dict[int, list[dict]] = {}
    for page in layout.get("pages") or []:
        boxes[int(page.get("page") or 0)] = list(page.get("measures") or [])
    marks: list[dict] = []
    for word in words:
        center_x = (word["x0"] + word["x1"]) / 2
        center_y = (word["y0"] + word["y1"]) / 2
        for measure in boxes.get(int(word["page"]), []):
            if not (
                float(measure.get("x0", 0)) <= center_x <= float(measure.get("x1", 0))
                and float(measure.get("y0", 0)) <= center_y <= float(measure.get("y1", 0))
            ):
                continue
            marks.append(
                {
                    "measure": int(measure.get("number") or 0),
                    "beat": 0,
                    "placement": "above",
                    "text": word["text"],
                }
            )
            break
    return marks


class PdfTextProducer:
    """A producer over a PDF text layer; marks need a layout, words do not."""

    name = "pdf-text-layer"

    def __init__(
        self,
        pdf: str | Path,
        layout: dict | None = None,
        pdftotext: str | None = None,
    ):
        self.pdf = Path(pdf)
        self.layout = layout
        self.pdftotext = pdftotext

    def produce(self, input_path: Path) -> FactSet:
        words = extract_words(self.pdf, self.pdftotext)
        marks = assign_measures(words, self.layout) if self.layout else []
        return FactSet(marks=marks, words=words, source=str(self.pdf))
