"""Constrained notation patches: agent proposes symbols, the compiler writes MusicXML.

The first operation is ``ottava`` (8va/8vb).  It is emitted as standard MusicXML
``<octave-shift>`` directions at explicit anchors, so MuseScore builds the Ottava spanner and the
agent never has to serialize mscx ids or location fractions.
"""

from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree

from .core.document import Document

OTTAAVA_SUBTYPES = {"8va": "up", "8vb": "down"}


def score_map(doc: Document) -> dict:
    """Stable note anchors for an agent choosing patch start/end positions."""
    measures = []
    for number, measure in doc.iter_measures():
        staves: dict[str, list[dict]] = {}
        for event in doc.events(measure):
            if event.rest:
                continue
            pitch = event.element.findtext("pitch/step")
            octave = event.element.findtext("pitch/octave")
            if not pitch or not octave:
                continue
            staves.setdefault(event.staff, []).append(
                {
                    "voice": event.voice,
                    "onset": round(event.onset, 4),
                    "duration": round(event.duration, 4),
                    "pitch": f"{pitch}{octave}",
                }
            )
        measures.append({"number": number, "staves": staves})
    return {"measures": measures}


def load_patches(path: str | Path | None) -> dict:
    if not path:
        return {"patches": []}
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def validate_patches(payload: dict, doc: Document | None = None) -> list[str]:
    problems: list[str] = []
    patches = payload.get("patches")
    if not isinstance(patches, list):
        return ["patches must be an array"]
    measure_count = len(doc.measures()) if doc is not None else None
    for index, patch in enumerate(patches):
        prefix = f"patches[{index}]"
        if not isinstance(patch, dict):
            problems.append(f"{prefix}: must be an object")
            continue
        if patch.get("op") != "ottava":
            problems.append(f"{prefix}: unsupported op {patch.get('op')!r}")
            continue
        if patch.get("mode") not in (None, "add", "replace", "remove"):
            problems.append(f"{prefix}: mode must be add/replace/remove")
        if patch.get("subtype") not in OTTAAVA_SUBTYPES:
            problems.append(f"{prefix}: subtype must be 8va or 8vb")
        if not isinstance(patch.get("staff"), int) or patch["staff"] < 1:
            problems.append(f"{prefix}: staff must be a positive integer")
        start = patch.get("start") or {}
        end = patch.get("end") or {}
        for label, anchor in (("start", start), ("end", end)):
            if not isinstance(anchor, dict):
                problems.append(f"{prefix}: {label} must be an object")
                continue
            if not isinstance(anchor.get("measure"), int) or anchor["measure"] < 1:
                problems.append(f"{prefix}: {label}.measure must be positive")
            if measure_count is not None and anchor.get("measure", 0) > measure_count:
                problems.append(f"{prefix}: {label}.measure exceeds {measure_count}")
            if not isinstance(anchor.get("beat"), (int, float)) or anchor["beat"] < 0:
                problems.append(f"{prefix}: {label}.beat must be non-negative")
        if (
            isinstance(start.get("measure"), int)
            and isinstance(end.get("measure"), int)
            and (end["measure"], float(end.get("beat") or 0))
            <= (start["measure"], float(start.get("beat") or 0))
        ):
            problems.append(f"{prefix}: end must be after start")
        if not (patch.get("page") or patch.get("bbox") or patch.get("crop")):
            problems.append(f"{prefix}: page/bbox evidence is required")
    return problems


def apply_patches(doc: Document, payload: dict) -> int:
    """Apply validated ottava patches; returns the number of directions written."""
    divisions = doc.divisions()
    measures = doc.measures()
    next_number = _next_octave_number(doc)
    changed = 0
    for patch in payload.get("patches") or []:
        start = patch["start"]
        end = patch["end"]
        subtype = patch["subtype"]
        staff = str(patch["staff"])
        mode = patch.get("mode") or "add"
        if mode in ("replace", "remove"):
            changed += remove_octave_shifts(doc, staff)
        if mode == "remove":
            continue
        number = str(patch.get("number") or next_number)
        next_number += 1
        start_measure = measures[start["measure"] - 1]
        end_measure = measures[end["measure"] - 1]
        _insert_octave(
            start_measure,
            float(start.get("beat") or 0),
            staff,
            "start",
            OTTAAVA_SUBTYPES[subtype],
            number,
            divisions,
        )
        _insert_octave(
            end_measure,
            float(end.get("beat") or 0),
            staff,
            "stop",
            OTTAAVA_SUBTYPES[subtype],
            number,
            divisions,
        )
        changed += 2
    return changed


def remove_octave_shifts(doc: Document, staff: str) -> int:
    """Remove all octave-shift directions on one staff; returns directions removed."""
    removed = 0
    for measure in doc.measures():
        for direction in list(measure.findall("direction")):
            if direction.find("direction-type/octave-shift") is None:
                continue
            if (direction.findtext("staff") or "1") != staff:
                continue
            measure.remove(direction)
            removed += 1
    return removed


def list_octave_shifts(doc: Document) -> list[dict]:
    """Read back the octave shifts so a review can compare them with the page."""
    result = []
    for number, measure in doc.iter_measures():
        for direction in measure.findall("direction"):
            shift = direction.find("direction-type/octave-shift")
            if shift is None:
                continue
            result.append(
                {
                    "measure": number,
                    "staff": direction.findtext("staff") or "1",
                    "type": shift.get("type"),
                    "size": shift.get("size"),
                    "number": shift.get("number"),
                }
            )
    return result


def _insert_octave(measure, beat: float, staff: str, kind: str, direction: str, number: str, divisions: float) -> None:
    direction_element = ElementTree.Element("direction", {"placement": "above"})
    direction_type = ElementTree.SubElement(direction_element, "direction-type")
    attributes = {"type": direction if kind == "start" else "stop", "number": number}
    if kind == "start":
        attributes["size"] = "8"
    ElementTree.SubElement(direction_type, "octave-shift", attributes)
    ElementTree.SubElement(direction_element, "staff").text = staff
    index = _insertion_index(measure, beat, staff, divisions)
    measure.insert(index, direction_element)


def _insertion_index(measure, beat: float, staff: str, divisions: float) -> int:
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


def _next_octave_number(doc: Document) -> int:
    used = []
    for element in doc.root.iter("octave-shift"):
        value = element.get("number")
        if value and value.isdigit():
            used.append(int(value))
    return max(used, default=0) + 1
