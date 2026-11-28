"""Volta / ending bracket notation patch validation, application, verification, and inspection."""

from __future__ import annotations

import re
from xml.etree import ElementTree

from ..core.document import Document
from .common import (
    VOLTA_STOP_TYPES,
    _find_barline,
    _get_or_create_barline,
    _positive_integer,
    _prune_empty_barline,
    _resolve_patch_part,
    _sort_barline_children,
)

_ENDING_NUMBER_RE = re.compile(r"^\d+(?:\s*,\s*\d+)*$")


def _normalize_ending_number(value: str) -> str:
    return ", ".join(part.strip() for part in value.split(","))


def _validate_volta(
    patch: dict, doc: Document | None, prefix: str, require_acceptance: bool = False
) -> list[str]:
    problems: list[str] = []
    if require_acceptance and patch.get("status") not in (None, "accepted"):
        problems.append(f"{prefix}: volta patch must be accepted before apply")
    _part_id, part, part_problems = _resolve_patch_part(patch, doc, prefix)
    problems.extend(part_problems)
    measure_count = len(doc.part_measures(part)) if doc is not None and part is not None else None
    if patch.get("mode") not in (None, "add", "replace", "remove"):
        problems.append(f"{prefix}: mode must be add/replace/remove")
    start_m = patch.get("start_measure")
    end_m = patch.get("end_measure")
    if not _positive_integer(start_m):
        problems.append(f"{prefix}: start_measure must be a positive integer")
    elif measure_count is not None and start_m > measure_count:
        problems.append(f"{prefix}: start_measure exceeds {measure_count}")
    if not _positive_integer(end_m):
        problems.append(f"{prefix}: end_measure must be a positive integer")
    elif measure_count is not None and end_m > measure_count:
        problems.append(f"{prefix}: end_measure exceeds {measure_count}")
    if _positive_integer(start_m) and _positive_integer(end_m) and end_m < start_m:
        problems.append(f"{prefix}: end_measure must not be before start_measure")
    number = patch.get("number")
    if not isinstance(number, str) or not _ENDING_NUMBER_RE.match(number.strip()):
        problems.append(f"{prefix}: number must be a comma-separated ending number string (e.g. '1' or '1, 2')")
    if patch.get("stop_type") not in (None, *VOLTA_STOP_TYPES):
        problems.append(f"{prefix}: stop_type must be stop/discontinue")
    if patch.get("text") is not None and not isinstance(patch.get("text"), str):
        problems.append(f"{prefix}: text must be a string")
    if not (patch.get("page") or patch.get("bbox") or patch.get("crop")):
        problems.append(f"{prefix}: page/bbox evidence is required")
    if not isinstance(patch.get("evidence"), str) or not patch["evidence"].strip():
        problems.append(f"{prefix}: evidence is required")
    return problems


def _apply_volta(
    doc: Document,
    part_id: str,
    part: ElementTree.Element,
    patch: dict,
) -> int:
    measures = doc.part_measures(part)
    start_measure = measures[patch["start_measure"] - 1]
    end_measure = measures[patch["end_measure"] - 1]
    number = _normalize_ending_number(patch["number"])
    stop_type = patch.get("stop_type") or "stop"
    mode = patch.get("mode") or "add"
    text = patch.get("text")
    changed = 0

    if mode in ("replace", "remove"):
        changed += _remove_ending(start_measure, "left", number)
        changed += _remove_ending(end_measure, "right", number)
    if mode == "remove":
        return changed

    left_barline = _get_or_create_barline(start_measure, "left")
    start_ending = next(
        (
            el
            for el in left_barline.findall("ending")
            if el.get("type") == "start" and _normalize_ending_number(el.get("number") or "") == number
        ),
        None,
    )
    if start_ending is None:
        start_ending = ElementTree.SubElement(
            left_barline, "ending", {"number": number, "type": "start"}
        )
        if text:
            start_ending.text = text
        changed += 1
    else:
        desired_text = text if text else None
        if (start_ending.text or None) != desired_text:
            start_ending.text = desired_text
            changed += 1
    _sort_barline_children(left_barline)

    right_barline = _get_or_create_barline(end_measure, "right")
    stop_ending = next(
        (
            el
            for el in right_barline.findall("ending")
            if el.get("type") in VOLTA_STOP_TYPES
            and _normalize_ending_number(el.get("number") or "") == number
        ),
        None,
    )
    if stop_ending is None:
        ElementTree.SubElement(right_barline, "ending", {"number": number, "type": stop_type})
        changed += 1
    elif stop_ending.get("type") != stop_type:
        stop_ending.set("type", stop_type)
        changed += 1
    _sort_barline_children(right_barline)
    return changed


def _remove_ending(measure: ElementTree.Element, location: str, number: str) -> int:
    barline = _find_barline(measure, location)
    if barline is None:
        return 0
    removed = 0
    for ending in list(barline.findall("ending")):
        if _normalize_ending_number(ending.get("number") or "") == number:
            barline.remove(ending)
            removed += 1
    _prune_empty_barline(measure, barline)
    return removed


def _verify_volta(doc: Document, patch: dict, prefix: str) -> list[str]:
    part_id, part, part_problems = _resolve_patch_part(patch, doc, prefix)
    if part_problems or part is None:
        return part_problems
    start_m = patch.get("start_measure")
    end_m = patch.get("end_measure")
    number = _normalize_ending_number(patch.get("number") or "")
    stop_type = patch.get("stop_type") or "stop"
    endings = list_voltas(doc, part_id=part_id)
    has_start = any(
        item["measure"] == start_m and item["type"] == "start" and item["number"] == number
        for item in endings
    )
    has_stop = any(
        item["measure"] == end_m and item["type"] == stop_type and item["number"] == number
        for item in endings
    )
    if patch.get("mode") == "remove":
        if has_start or has_stop:
            return [f"{prefix}: volta {number!r} still present on m{start_m}-m{end_m}"]
        return []
    problems: list[str] = []
    if not has_start:
        problems.append(f"{prefix}: volta {number!r} start missing at m{start_m}")
    if not has_stop:
        problems.append(f"{prefix}: volta {number!r} {stop_type} missing at m{end_m}")
    return problems


def list_voltas(doc: Document, part_id: str | None = None) -> list[dict]:
    """Read back volta ending brackets with measure numbers and types."""
    result = []
    for current_part, _part, number, measure in doc.iter_part_measures():
        if part_id is not None and current_part != part_id:
            continue
        for barline in measure.findall("barline"):
            location = barline.get("location") or "right"
            for ending in barline.findall("ending"):
                result.append(
                    {
                        "part": current_part,
                        "measure": number,
                        "location": location,
                        "number": _normalize_ending_number(ending.get("number") or ""),
                        "type": ending.get("type"),
                        "text": (ending.text or "").strip() or None,
                    }
                )
    return result
