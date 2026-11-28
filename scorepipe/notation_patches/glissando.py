"""Glissando notation patch validation, application, verification, and inspection."""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.document import Document
from .common import (
    GLISSANDO_LINE_TYPES,
    _find_base_events_at,
    _insert_notation_child,
    _next_direction_number,
    _positive_integer,
    _resolve_patch_part,
    _validate_anchor,
)


def _validate_glissando(
    patch: dict, doc: Document | None, prefix: str, require_acceptance: bool = False
) -> list[str]:
    problems: list[str] = []
    if require_acceptance and patch.get("status") not in (None, "accepted"):
        problems.append(f"{prefix}: glissando patch must be accepted before apply")
    _part_id, part, part_problems = _resolve_patch_part(patch, doc, prefix)
    problems.extend(part_problems)
    measure_count = len(doc.part_measures(part)) if doc is not None and part is not None else None
    if patch.get("mode") not in (None, "add", "replace", "remove"):
        problems.append(f"{prefix}: mode must be add/replace/remove")
    if not _positive_integer(patch.get("staff")):
        problems.append(f"{prefix}: staff must be a positive integer")
    if patch.get("voice") is not None and (
        not isinstance(patch.get("voice"), str) or not patch["voice"].strip()
    ):
        problems.append(f"{prefix}: voice must be a non-empty string")
    if patch.get("line_type") not in (None, *GLISSANDO_LINE_TYPES):
        problems.append(f"{prefix}: line_type must be wavy/solid/dashed/dotted")
    if patch.get("text") is not None and not isinstance(patch.get("text"), str):
        problems.append(f"{prefix}: text must be a string")

    start = patch.get("start")
    end = patch.get("end")
    problems.extend(_validate_anchor(start, prefix, "start", measure_count))
    problems.extend(_validate_anchor(end, prefix, "end", measure_count))
    valid_bounds = (
        isinstance(start, dict)
        and isinstance(end, dict)
        and isinstance(start.get("measure"), int)
        and isinstance(end.get("measure"), int)
        and isinstance(start.get("beat"), (int, float))
        and isinstance(end.get("beat"), (int, float))
    )
    if valid_bounds and (end["measure"], float(end["beat"])) <= (
        start["measure"],
        float(start["beat"]),
    ):
        problems.append(f"{prefix}: end must be strictly after start")
    if doc is not None and part is not None and valid_bounds and _positive_integer(patch.get("staff")):
        measures = doc.part_measures(part)
        if 1 <= start["measure"] <= len(measures):
            if not _find_base_events_at(
                doc,
                measures[start["measure"] - 1],
                part,
                staff=str(patch["staff"]),
                beat=float(start["beat"]),
                voice=patch.get("voice"),
            ):
                problems.append(
                    f"{prefix}: no pitched note at start m{start['measure']} beat {start['beat']} staff {patch['staff']}"
                )
        if 1 <= end["measure"] <= len(measures):
            if not _find_base_events_at(
                doc,
                measures[end["measure"] - 1],
                part,
                staff=str(patch["staff"]),
                beat=float(end["beat"]),
                voice=patch.get("voice"),
            ):
                problems.append(
                    f"{prefix}: no pitched note at end m{end['measure']} beat {end['beat']} staff {patch['staff']}"
                )
    if not (patch.get("page") or patch.get("bbox") or patch.get("crop")):
        problems.append(f"{prefix}: page/bbox evidence is required")
    if not isinstance(patch.get("evidence"), str) or not patch["evidence"].strip():
        problems.append(f"{prefix}: evidence is required")
    return problems


def _next_glissando_number(doc: Document, part_id: str) -> int:
    return _next_direction_number(doc, "glissando", part_id)


def _apply_glissando(
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
    voice = patch.get("voice")
    mode = patch.get("mode") or "add"
    line_type = patch.get("line_type") or "wavy"
    text = patch.get("text")
    changed = 0

    if mode in ("replace", "remove"):
        changed += remove_glissandos(doc, staff, part_id=part_id)
    if mode == "remove":
        return changed, next_number

    start_events = _find_base_events_at(
        doc,
        measures[start["measure"] - 1],
        part,
        staff=staff,
        beat=float(start["beat"]),
        voice=voice,
    )
    end_events = _find_base_events_at(
        doc,
        measures[end["measure"] - 1],
        part,
        staff=staff,
        beat=float(end["beat"]),
        voice=voice,
    )
    if not start_events or not end_events:
        return changed, next_number

    number = str(next_number)
    start_el = ElementTree.Element(
        "glissando", {"line-type": line_type, "number": number, "type": "start"}
    )
    if text:
        start_el.text = text
    _insert_notation_child(start_events[0].element, start_el)

    stop_el = ElementTree.Element(
        "glissando", {"line-type": line_type, "number": number, "type": "stop"}
    )
    _insert_notation_child(end_events[0].element, stop_el)
    return changed + 2, next_number + 1


def remove_glissandos(doc: Document, staff: str, *, part_id: str | None = None) -> int:
    removed = 0
    for current_part, _part, _number, measure in doc.iter_part_measures():
        if part_id is not None and current_part != part_id:
            continue
        for note in measure.iter("note"):
            if (note.findtext("staff") or "1") != staff:
                continue
            notations = note.find("notations")
            if notations is None:
                continue
            for child in list(notations.findall("glissando")):
                notations.remove(child)
                removed += 1
            if len(notations) == 0:
                note.remove(notations)
    return removed


def _verify_glissando(doc: Document, patch: dict, prefix: str) -> list[str]:
    part_id, part, part_problems = _resolve_patch_part(patch, doc, prefix)
    if part_problems or part is None:
        return part_problems
    staff = str(patch.get("staff"))
    start = patch["start"]
    end = patch["end"]
    items = [item for item in list_glissandos(doc, part_id=part_id) if item["staff"] == staff]
    if patch.get("mode") == "remove":
        if items:
            return [f"{prefix}: glissando remains on staff {staff}"]
        return []
    starts = {
        item["number"]: item
        for item in items
        if item["type"] == "start"
        and item["measure"] == start["measure"]
        and abs(item["beat"] - float(start["beat"])) <= 1e-3
    }
    stops = {
        item["number"]: item
        for item in items
        if item["type"] == "stop"
        and item["measure"] == end["measure"]
        and abs(item["beat"] - float(end["beat"])) <= 1e-3
    }
    if not (set(starts) & set(stops)):
        return [
            f"{prefix}: glissando m{start['measure']}:{start['beat']}->m{end['measure']}:{end['beat']} missing"
        ]
    return []


def list_glissandos(doc: Document, part_id: str | None = None) -> list[dict]:
    """Read back glissando notations with measure/beat/staff positions."""
    result = []
    for current_part, part, number, measure in doc.iter_part_measures():
        if part_id is not None and current_part != part_id:
            continue
        divisions = doc.effective_divisions(measure, part)
        for event in doc.events(measure, divisions):
            if event.chord or event.rest:
                continue
            for gliss in event.element.findall("notations/glissando"):
                result.append(
                    {
                        "part": current_part,
                        "measure": number,
                        "beat": round(event.onset, 4),
                        "staff": event.staff,
                        "voice": event.voice,
                        "type": gliss.get("type"),
                        "number": gliss.get("number"),
                        "line_type": gliss.get("line-type") or "wavy",
                        "text": (gliss.text or "").strip() or None,
                    }
                )
    return result
