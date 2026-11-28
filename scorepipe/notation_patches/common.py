"""Shared constants, score-anchor map, patch loader, and XML helpers."""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree

from ..core.document import Document

OTTAAVA_SUBTYPES = {"8va": "up", "8vb": "down"}
CLEF_SIGNS = {"G", "F", "C"}
WEDGE_SUBTYPES = ("crescendo", "diminuendo")
DYNAMIC_MARKS = (
    "p",
    "pp",
    "ppp",
    "pppp",
    "ppppp",
    "pppppp",
    "f",
    "ff",
    "fff",
    "ffff",
    "fffff",
    "ffffff",
    "mp",
    "mf",
    "sf",
    "sfp",
    "sfpp",
    "fp",
    "rf",
    "rfz",
    "sfz",
    "sffz",
    "fz",
    "n",
    "pf",
    "sfzp",
)
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


def _part_score_map(doc: Document, part: ElementTree.Element) -> list[dict]:
    measures = []
    for number, measure in enumerate(doc.part_measures(part), start=1):
        staves: dict[str, list[dict]] = {}
        for event in doc.events(measure, doc.effective_divisions(measure, part)):
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
    return measures


def score_map(doc: Document) -> dict:
    """Stable note anchors for an agent choosing patch start/end positions."""
    parts = list(doc.iter_parts())
    if len(parts) <= 1:
        return {"measures": _part_score_map(doc, parts[0][1]) if parts else []}
    by_part = {part_id: {"measures": _part_score_map(doc, part)} for part_id, part in parts}
    return {"measures": by_part[parts[0][0]]["measures"], "parts": by_part}


def _resolve_patch_part(
    patch: dict, doc: Document | None, prefix: str
) -> tuple[str | None, ElementTree.Element | None, list[str]]:
    part_id = patch.get("part")
    if part_id is not None and (not isinstance(part_id, str) or not part_id.strip()):
        return None, None, [f"{prefix}: part must be a non-empty string"]
    if doc is None:
        return part_id, None, []
    try:
        part = doc.part_by_id(part_id)
    except ValueError:
        return part_id, None, [f"{prefix}: unknown part {part_id!r}"]
    resolved_id = part.get("id") or "P1"
    return resolved_id, part, []


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


def _direction_insertion_index(measure, beat: float, staff: str, divisions: float) -> int:
    target = beat * divisions
    cursor = 0.0
    previous = None
    children = list(measure)
    for index, child in enumerate(children):
        if child.tag in ("backup", "forward"):
            value = int(child.findtext("duration") or 0)
            cursor += -value if child.tag == "backup" else value
            previous = None
            continue
        if child.tag != "note":
            continue
        text = child.findtext("duration")
        if text is None:
            continue
        duration = int(text)
        chord = child.find("chord") is not None
        onset = previous if chord and previous is not None else cursor
        if not chord:
            cursor += duration
        previous = onset
        note_staff = child.findtext("staff") or "1"
        if note_staff == staff and onset >= target - 1e-6:
            return index
    return len(children)


def _next_direction_number(doc: Document, tag: str, part_id: str | None = None) -> int:
    used = []
    scope = doc.part_by_id(part_id) if part_id is not None else doc.root
    for element in scope.iter(tag):
        value = element.get("number")
        if value and value.isdigit():
            used.append(int(value))
    return max(used, default=0) + 1


def _validate_anchor(anchor, prefix: str, label: str, measure_count: int | None) -> list[str]:
    problems: list[str] = []
    if not isinstance(anchor, dict):
        return [f"{prefix}: {label} must be an object"]
    if not _positive_integer(anchor.get("measure")):
        problems.append(f"{prefix}: {label}.measure must be positive")
    elif measure_count is not None and anchor["measure"] > measure_count:
        problems.append(f"{prefix}: {label}.measure exceeds {measure_count}")
    beat = anchor.get("beat")
    if isinstance(beat, bool) or not isinstance(beat, (int, float)) or beat < 0:
        problems.append(f"{prefix}: {label}.beat must be non-negative")
    return problems
