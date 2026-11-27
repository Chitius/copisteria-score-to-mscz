"""Ottava (8va/8vb) notation patch validation, application, and verification."""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.document import Document
from .common import OTTAAVA_SUBTYPES


def _validate_ottava(
    patch: dict, doc: Document | None, prefix: str, require_acceptance: bool = False
) -> list[str]:
    problems: list[str] = []
    if require_acceptance:
        status = patch.get("status")
        if status not in (None, "accepted"):
            problems.append(f"{prefix}: ottava patch must be accepted before apply")
    measure_count = len(doc.measures()) if doc is not None else None
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


def _apply_ottava(
    doc: Document,
    measures: list,
    patch: dict,
    divisions: float,
    next_number: int,
) -> tuple[int, int]:
    start = patch["start"]
    end = patch["end"]
    subtype = patch["subtype"]
    staff = str(patch["staff"])
    mode = patch.get("mode") or "add"
    changed = 0
    if mode in ("replace", "remove"):
        changed += remove_octave_shifts(doc, staff)
    if mode == "remove":
        return changed, next_number
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
    return changed + 2, next_number


def _verify_ottava(doc: Document, patch: dict, prefix: str) -> list[str]:
    if patch.get("mode") == "remove":
        return []
    shifts = list_octave_shifts(doc)
    staff = str(patch.get("staff"))
    expected_type = OTTAAVA_SUBTYPES.get(patch.get("subtype"))
    start_measure = (patch.get("start") or {}).get("measure")
    end_measure = (patch.get("end") or {}).get("measure")
    starts = [
        shift
        for shift in shifts
        if shift["staff"] == staff
        and shift["type"] == expected_type
        and shift["size"] == "8"
        and shift["measure"] == start_measure
    ]
    if not starts:
        return [f"{prefix}: ottava start missing or has the wrong type/size/measure"]
    if not any(
        any(
            stop["staff"] == staff
            and stop["type"] == "stop"
            and stop["number"] == start["number"]
            and stop["measure"] == end_measure
            for stop in shifts
        )
        for start in starts
    ):
        return [f"{prefix}: ottava stop missing or does not match its start"]
    return []


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


def _insert_octave(
    measure, beat: float, staff: str, kind: str, direction: str, number: str, divisions: float
) -> None:
    # 8vb is printed under the staff it lowers; keeping it "above" drew the bracket between the
    # staves (measured on the First Step delivery).
    placement = "below" if direction == "down" else "above"
    direction_element = ElementTree.Element("direction", {"placement": placement})
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
