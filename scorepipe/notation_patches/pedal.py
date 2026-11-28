"""Pedal notation patch validation, application, verification, and inspection."""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.document import Document
from .common import (
    _direction_insertion_index,
    _next_direction_number,
    _positive_integer,
    _resolve_patch_part,
    _validate_anchor,
)


def _validate_pedal(
    patch: dict, doc: Document | None, prefix: str, require_acceptance: bool = False
) -> list[str]:
    problems: list[str] = []
    if require_acceptance and patch.get("status") not in (None, "accepted"):
        problems.append(f"{prefix}: pedal patch must be accepted before apply")
    _part_id, part, part_problems = _resolve_patch_part(patch, doc, prefix)
    problems.extend(part_problems)
    measure_count = len(doc.part_measures(part)) if doc is not None and part is not None else None
    if patch.get("mode") not in (None, "add", "replace", "remove"):
        problems.append(f"{prefix}: mode must be add/replace/remove")
    if not _positive_integer(patch.get("staff")):
        problems.append(f"{prefix}: staff must be a positive integer")
    if patch.get("placement") not in (None, "above", "below"):
        problems.append(f"{prefix}: placement must be above/below")
    if patch.get("line") is not None and not isinstance(patch.get("line"), bool):
        problems.append(f"{prefix}: line must be a boolean")

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

    changes = patch.get("changes")
    if changes is not None:
        if not isinstance(changes, list):
            problems.append(f"{prefix}: changes must be an array")
        else:
            for index, change in enumerate(changes):
                problems.extend(
                    _validate_anchor(change, prefix, f"changes[{index}]", measure_count)
                )
                if (
                    isinstance(change, dict)
                    and isinstance(start, dict)
                    and isinstance(end, dict)
                    and isinstance(change.get("measure"), int)
                    and isinstance(start.get("measure"), int)
                    and isinstance(end.get("measure"), int)
                    and isinstance(change.get("beat"), (int, float))
                    and isinstance(start.get("beat"), (int, float))
                    and isinstance(end.get("beat"), (int, float))
                ):
                    point = (change["measure"], float(change["beat"]))
                    start_pt = (start["measure"], float(start["beat"]))
                    end_pt = (end["measure"], float(end["beat"]))
                    if not (start_pt < point < end_pt):
                        problems.append(
                            f"{prefix}: changes[{index}] must fall strictly between start and end"
                        )

    if not (patch.get("page") or patch.get("bbox") or patch.get("crop")):
        problems.append(f"{prefix}: page/bbox evidence is required")
    if not isinstance(patch.get("evidence"), str) or not patch["evidence"].strip():
        problems.append(f"{prefix}: evidence is required")
    return problems


def _apply_pedal(
    doc: Document,
    part_id: str,
    part: ElementTree.Element,
    patch: dict,
    next_number: int,
) -> tuple[int, int]:
    measures = doc.part_measures(part)
    start = patch["start"]
    end = patch["end"]
    staff = str(patch["staff"])
    mode = patch.get("mode") or "add"
    placement = patch.get("placement") or "below"
    use_line = patch.get("line", True)
    changed = 0
    if mode in ("replace", "remove"):
        changed += remove_pedals(
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

    events: list[tuple[dict, str]] = [(start, "start")]
    for change in patch.get("changes") or []:
        events.append((change, "change"))
    events.append((end, "stop"))

    for anchor, kind in events:
        measure = measures[anchor["measure"] - 1]
        divisions = doc.effective_divisions(measure, part)
        direction_el = _pedal_direction(staff, kind, number, placement, use_line)
        index = _direction_insertion_index(measure, float(anchor.get("beat") or 0), staff, divisions)
        measure.insert(index, direction_el)
        changed += 1
    return changed, next_number


def _pedal_direction(
    staff: str, kind: str, number: str, placement: str, use_line: bool
) -> ElementTree.Element:
    direction_el = ElementTree.Element("direction", {"placement": placement})
    direction_type = ElementTree.SubElement(direction_el, "direction-type")
    attrs = {
        "type": kind,
        "number": number,
        "line": "yes" if use_line else "no",
        "sign": "no" if use_line else "yes",
    }
    ElementTree.SubElement(direction_type, "pedal", attrs)
    ElementTree.SubElement(direction_el, "staff").text = staff
    return direction_el


def _verify_pedal(doc: Document, patch: dict, prefix: str) -> list[str]:
    part_id, part, part_problems = _resolve_patch_part(patch, doc, prefix)
    if part_problems or part is None:
        return part_problems
    staff = str(patch.get("staff"))
    start_measure = (patch.get("start") or {}).get("measure")
    end_measure = (patch.get("end") or {}).get("measure")
    pedals = list_pedals(doc, part_id=part_id)
    if patch.get("mode") == "remove":
        remaining = [
            p
            for p in pedals
            if p["staff"] == staff and start_measure <= p["measure"] <= end_measure
        ]
        return [f"{prefix}: pedal directions still present in m{start_measure}..m{end_measure}"] if remaining else []

    starts = [
        (index, p)
        for index, p in enumerate(pedals)
        if p["staff"] == staff and p["type"] == "start" and p["measure"] == start_measure
    ]
    if not starts:
        return [f"{prefix}: pedal start missing at m{start_measure} staff {staff}"]
    for start_index, start_p in starts:
        stops = [
            stop_index
            for stop_index, stop_p in enumerate(pedals)
            if stop_index > start_index
            and stop_p["staff"] == staff
            and stop_p["type"] == "stop"
            and stop_p["number"] == start_p["number"]
            and stop_p["measure"] == end_measure
        ]
        if not stops:
            continue
        stop_index = stops[0]
        between = pedals[start_index + 1 : stop_index]
        missing_change = False
        for change in patch.get("changes") or []:
            if not any(
                p["staff"] == staff
                and p["type"] == "change"
                and p["number"] == start_p["number"]
                and p["measure"] == change["measure"]
                for p in between
            ):
                missing_change = True
                break
        if not missing_change:
            return []
    return [f"{prefix}: pedal stop/change missing or does not match its start"]


def remove_pedals(
    doc: Document,
    staff: str,
    part_id: str | None = None,
    *,
    start_measure: int | None = None,
    end_measure: int | None = None,
) -> int:
    """Remove pedal directions on one staff (optionally scoped to a measure range)."""
    removed = 0
    for current_part, _part, number, measure in doc.iter_part_measures():
        if part_id is not None and current_part != part_id:
            continue
        if start_measure is not None and number < start_measure:
            continue
        if end_measure is not None and number > end_measure:
            continue
        for direction in list(measure.findall("direction")):
            if direction.find("direction-type/pedal") is None:
                continue
            if (direction.findtext("staff") or "1") != staff:
                continue
            measure.remove(direction)
            removed += 1
    return removed


def list_pedals(doc: Document, part_id: str | None = None) -> list[dict]:
    """Read back pedal directions in document order."""
    result = []
    for current_part, _part, number, measure in doc.iter_part_measures():
        if part_id is not None and current_part != part_id:
            continue
        for direction in measure.findall("direction"):
            pedal = direction.find("direction-type/pedal")
            if pedal is None:
                continue
            result.append(
                {
                    "part": current_part,
                    "measure": number,
                    "staff": direction.findtext("staff") or "1",
                    "type": pedal.get("type"),
                    "number": pedal.get("number") or "1",
                    "line": pedal.get("line"),
                }
            )
    return result


def _next_pedal_number(doc: Document, part_id: str | None = None) -> int:
    return _next_direction_number(doc, "pedal", part_id)
