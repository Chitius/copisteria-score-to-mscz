"""Shared constants, score-anchor map, patch loader, and XML helpers."""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

from ..core.document import Document

OTTAAVA_SUBTYPES = {"8va": "up", "8vb": "down"}
CLEF_SIGNS = {"G", "F", "C"}
NOTE_TYPE_BEATS = {
    "maxima": Fraction(32),
    "long": Fraction(16),
    "breve": Fraction(8),
    "whole": Fraction(4),
    "half": Fraction(2),
    "quarter": Fraction(1),
    "eighth": Fraction(1, 2),
    "16th": Fraction(1, 4),
    "32nd": Fraction(1, 8),
    "64th": Fraction(1, 16),
    "128th": Fraction(1, 32),
    "256th": Fraction(1, 64),
    "512th": Fraction(1, 128),
    "1024th": Fraction(1, 256),
}


def score_map(doc: Document) -> dict:
    """Stable note anchors for an agent choosing patch start/end positions."""
    measures = []
    for number, measure in doc.iter_measures():
        staves: dict[str, list[dict]] = {}
        for event in doc.events(measure):
            if event.rest:
                continue
            note = event.element
            pitch = _pitch_name(note)
            if pitch is None:
                continue
            modification = note.find("time-modification")
            staves.setdefault(event.staff, []).append(
                {
                    "voice": event.voice,
                    "onset": round(event.onset, 4),
                    "duration": round(event.duration, 4),
                    "pitch": pitch,
                    "alter": _alter(note),
                    "chord": event.chord,
                    "type": note.findtext("type"),
                    "dots": len(note.findall("dot")),
                    "actual": _integer_text(modification, "actual-notes"),
                    "normal": _integer_text(modification, "normal-notes"),
                }
            )
        measures.append({"number": number, "staves": staves})
    return {"measures": measures}


def load_patches(path: str | Path | None) -> dict:
    if not path:
        return {"patches": []}
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _positive_integer(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _alter(note) -> int | float:
    text = note.findtext("pitch/alter")
    try:
        value = float(text or 0)
    except ValueError:
        return 0
    return int(value) if value.is_integer() else value


def _pitch_name(note) -> str | None:
    step = note.findtext("pitch/step")
    octave = note.findtext("pitch/octave")
    if not step or not octave:
        return None
    alter = _alter(note)
    if isinstance(alter, int) and alter > 0:
        accidental = "#" * alter
    elif isinstance(alter, int) and alter < 0:
        accidental = "b" * -alter
    else:
        accidental = ""
    return f"{step}{accidental}{octave}"


def _integer_text(element, path: str) -> int | None:
    if element is None:
        return None
    text = element.findtext(path)
    try:
        return int(text) if text is not None else None
    except ValueError:
        return None
