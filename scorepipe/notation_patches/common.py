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
REPEAT_DIRECTIONS = ("forward", "backward")
VOLTA_STOP_TYPES = ("stop", "discontinue")
FERMATA_TYPES = ("upright", "inverted")
FERMATA_SHAPES = ("normal", "angled", "square")
NAVIGATION_MARKS = ("segno", "coda")
ORNAMENT_KINDS = (
    "trill",
    "mordent",
    "inverted-mordent",
    "turn",
    "inverted-turn",
    "delayed-turn",
    "tremolo",
)
GLISSANDO_LINE_TYPES = ("wavy", "solid", "dashed", "dotted")
ARPEGGIO_KINDS = ("arpeggiate", "non-arpeggiate")
ARPEGGIO_DIRECTIONS = ("none", "up", "down")
PARENTHESES_TARGETS = ("notehead", "accidental", "both")
SUPPORTED_PATCH_OPS = (
    "tuplet",
    "ottava",
    "clef",
    "pedal",
    "wedge",
    "dynamic",
    "repeat",
    "volta",
    "fermata",
    "navigation",
    "ornament",
    "glissando",
    "arpeggio",
    "parentheses",
)
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


_BARLINE_ORDER = {
    "bar-style": 0,
    "footnote": 1,
    "level": 2,
    "wavy-line": 3,
    "segno": 4,
    "coda": 5,
    "fermata": 6,
    "ending": 7,
    "repeat": 8,
}

_NOTATIONS_ORDER = {
    "footnote": 0,
    "level": 1,
    "tied": 2,
    "slur": 3,
    "tuplet": 4,
    "glissando": 5,
    "slide": 6,
    "ornaments": 7,
    "technical": 8,
    "articulations": 9,
    "dynamics": 10,
    "fermata": 11,
    "arpeggiate": 12,
    "non-arpeggiate": 13,
    "accidental-mark": 14,
    "other-notation": 15,
}


def _find_barline(measure: ElementTree.Element, location: str) -> ElementTree.Element | None:
    for child in measure.findall("barline"):
        loc = child.get("location") or "right"
        if loc == location:
            return child
    return None


def _get_or_create_barline(measure: ElementTree.Element, location: str) -> ElementTree.Element:
    existing = _find_barline(measure, location)
    if existing is not None:
        return existing
    barline = ElementTree.Element("barline", {"location": location})
    if location == "left":
        insert_at = 0
        for index, child in enumerate(list(measure)):
            if child.tag in ("print", "bookmark", "link"):
                insert_at = index + 1
            else:
                break
        measure.insert(insert_at, barline)
    else:
        measure.append(barline)
    return barline


def _sort_barline_children(barline: ElementTree.Element) -> None:
    children = list(barline)
    children.sort(key=lambda el: _BARLINE_ORDER.get(el.tag, 99))
    for child in list(barline):
        barline.remove(child)
    for child in children:
        barline.append(child)


def _prune_empty_barline(measure: ElementTree.Element, barline: ElementTree.Element | None) -> None:
    if barline is not None and len(barline) == 0:
        measure.remove(barline)


def _ensure_notations(note: ElementTree.Element) -> ElementTree.Element:
    notations = note.find("notations")
    if notations is not None:
        return notations
    notations = ElementTree.Element("notations")
    insert_at = len(note)
    for index, child in enumerate(list(note)):
        if child.tag in ("lyric", "play", "listen"):
            insert_at = index
            break
    note.insert(insert_at, notations)
    return notations


def _insert_notation_child(note: ElementTree.Element, child: ElementTree.Element) -> ElementTree.Element:
    notations = _ensure_notations(note)
    order = _NOTATIONS_ORDER.get(child.tag, 99)
    insert_at = len(notations)
    for index, existing in enumerate(list(notations)):
        if _NOTATIONS_ORDER.get(existing.tag, 99) > order:
            insert_at = index
            break
    notations.insert(insert_at, child)
    return notations


def _find_base_events_at(
    doc: Document,
    measure: ElementTree.Element,
    part: ElementTree.Element,
    *,
    staff: str,
    beat: float,
    voice: str | None = None,
    include_rests: bool = False,
) -> list:
    divisions = doc.effective_divisions(measure, part)
    matches = []
    for event in doc.events(measure, divisions):
        if event.chord:
            continue
        if not include_rests and event.rest:
            continue
        if event.staff != staff:
            continue
        if voice is not None and event.voice != str(voice):
            continue
        if abs(event.onset - beat) <= 1e-3:
            matches.append(event)
    return matches
