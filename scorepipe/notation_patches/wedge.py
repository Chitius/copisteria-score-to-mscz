"""Wedge (crescendo/diminuendo hairpin) notation patch validation, application, and verification."""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.document import Document
from .common import (
    WEDGE_SUBTYPES,
    _direction_insertion_index,
    _next_direction_number,
    _positive_integer,
    _resolve_patch_part,
    _validate_anchor,
)


def _validate_wedge(
    patch: dict, doc: Document | None, prefix: str, require_acceptance: bool = False
) -> list[str]:
    problems: list[str] = []
    if require_acceptance and patch.get("status") not in (None, "accepted"):
        problems.append(f"{prefix}: wedge patch must be accepted before apply")
    _part_id, part, part_problems = _resolve_patch_part(patch, doc, prefix)
    problems.extend(part_problems)
    measure_count = len(doc.part_measures(part)) if doc is not None and part is not None else None
    if patch.get("mode") not in (None, "add", "replace", "remove"):
        problems.append(f"{prefix}: mode must be add/replace/remove")
    if patch.get("subtype") not in WEDGE_SUBTYPES:
        problems.append(f"{prefix}: subtype must be crescendo or diminuendo")
    if not _positive_integer(patch.get("staff")):
        problems.append(f"{prefix}: staff must be a positive integer")
    if patch.get("placement") not in (None, "above", "below"):
        problems.append(f"{prefix}: placement must be above/below")
    if patch.get("niente") is not None and not isinstance(patch.get("niente"), bool):
        problems.append(f"{prefix}: niente must be a boolean")

    start = patch.get("start")
    end = patch.get("end")
    problems.extend(_validate_anchor(start, prefix, "start", measure_count))
    problems.extend(_validate_anchor(end, prefix, "end", measure_count))
    if (
        isinstance(start, dict)
        and isinstance(end, dict)
        and isinstance(start.get("measure"), int)
        and isinstance(end.get("measure"), int)
        and isinstance(start.get("beat"), (int, float))
        and isinstance(end.get("beat"), (int, float))
        and (end["measure"], float(end["beat"])) < (start["measure"], float(start["beat"]))
    ):
        problems.append(f"{prefix}: end must not be before start")

    if not (patch.get("page") or patch.get("bbox") or patch.get("crop")):
        problems.append(f"{prefix}: page/bbox evidence is required")
    if not isinstance(patch.get("evidence"), str) or not patch["evidence"].strip():
        problems.append(f"{prefix}: evidence is required")
    return problems


def _apply_wedge(
    doc: Document,
    part_id: str,
    part: ElementTree.Element,
    patch: dict,
    next_number: int,
) -> tuple[int, int]:
    measures = doc.part_measures(part)
    start = patch["start"]
    end = patch["end"]
    subtype = patch["subtype"]
    staff = str(patch["staff"])
    mode = patch.get("mode") or "add"
    placement = patch.get("placement") or "below"
    niente = bool(patch.get("niente", False))
    changed = 0
    if mode in ("replace", "remove"):
        changed += remove_wedges(
            doc,
            staff,
            part_id=part_id,
            start_measure=start["measure"],
            end_measure=end["measure"],
        )
    if mode == "remove":
        return changed, next_number

    number = str(patch.get("number") or next_number)
    next_number += 1

    start_measure = measures[start["measure"] - 1]
    end_measure = measures[end["measure"] - 1]
    start_el = _wedge_direction(staff, subtype, number, placement, niente=niente)
    stop_el = _wedge_direction(staff, "stop", number, placement, niente=False)

    start_beat = float(start.get("beat") or 0)
    end_beat = float(end.get("beat") or 0)
    start_index = _direction_insertion_index(
        start_measure, start_beat, staff, doc.effective_divisions(start_measure, part)
    )
    if start["measure"] == end["measure"] and abs(end_beat - start_beat) <= 1e-6:
        # Insert stop first at start_index + 1 (if a chord/note exists at start_index), or after start
        end_index = min(len(start_measure), start_index + 1)
        start_measure.insert(end_index, stop_el)
        start_measure.insert(start_index, start_el)
    else:
        start_measure.insert(start_index, start_el)
        end_index = _direction_insertion_index(
            end_measure, end_beat, staff, doc.effective_divisions(end_measure, part)
        )
        end_measure.insert(end_index, stop_el)
    return changed + 2, next_number


def _wedge_direction(
    staff: str, wedge_type: str, number: str, placement: str, *, niente: bool
) -> ElementTree.Element:
    direction_el = ElementTree.Element("direction", {"placement": placement})
    direction_type = ElementTree.SubElement(direction_el, "direction-type")
    attrs = {"type": wedge_type, "number": number}
    if niente:
        attrs["niente"] = "yes"
    ElementTree.SubElement(direction_type, "wedge", attrs)
    ElementTree.SubElement(direction_el, "staff").text = staff
    return direction_el


def _verify_wedge(doc: Document, patch: dict, prefix: str) -> list[str]:
    part_id, part, part_problems = _resolve_patch_part(patch, doc, prefix)
    if part_problems or part is None:
        return part_problems
    staff = str(patch.get("staff"))
    start_measure = (patch.get("start") or {}).get("measure")
    end_measure = (patch.get("end") or {}).get("measure")
    wedges = list_wedges(doc, part_id=part_id)
    if patch.get("mode") == "remove":
        remaining = [
            w
            for w in wedges
            if w["staff"] == staff and start_measure <= w["measure"] <= end_measure
        ]
        return [f"{prefix}: wedge directions still present in m{start_measure}..m{end_measure}"] if remaining else []

    subtype = patch.get("subtype")
    starts = [
        (index, w)
        for index, w in enumerate(wedges)
        if w["staff"] == staff and w["type"] == subtype and w["measure"] == start_measure
    ]
    if not starts:
        return [f"{prefix}: wedge {subtype} start missing at m{start_measure} staff {staff}"]
    if not any(
        any(
            stop_index > start_index
            and stop["staff"] == staff
            and stop["type"] == "stop"
            and stop["number"] == start["number"]
            and stop["measure"] == end_measure
            for stop_index, stop in enumerate(wedges)
        )
        for start_index, start in starts
    ):
        return [f"{prefix}: wedge stop missing or does not match its start"]
    return []


def remove_wedges(
    doc: Document,
    staff: str,
    part_id: str | None = None,
    *,
    start_measure: int | None = None,
    end_measure: int | None = None,
) -> int:
    """Remove wedge directions on one staff (optionally scoped to a measure range)."""
    removed = 0
    for current_part, _part, number, measure in doc.iter_part_measures():
        if part_id is not None and current_part != part_id:
            continue
        if start_measure is not None and number < start_measure:
            continue
        if end_measure is not None and number > end_measure:
            continue
        for direction in list(measure.findall("direction")):
            if direction.find("direction-type/wedge") is None:
                continue
            if (direction.findtext("staff") or "1") != staff:
                continue
            measure.remove(direction)
            removed += 1
    return removed


def list_wedges(doc: Document, part_id: str | None = None) -> list[dict]:
    """Read back wedge directions in document order."""
    result = []
    for current_part, _part, number, measure in doc.iter_part_measures():
        if part_id is not None and current_part != part_id:
            continue
        for direction in measure.findall("direction"):
            wedge = direction.find("direction-type/wedge")
            if wedge is None:
                continue
            result.append(
                {
                    "part": current_part,
                    "measure": number,
                    "staff": direction.findtext("staff") or "1",
                    "type": wedge.get("type"),
                    "number": wedge.get("number") or "1",
                }
            )
    return result


def _next_wedge_number(doc: Document, part_id: str | None = None) -> int:
    return _next_direction_number(doc, "wedge", part_id)
