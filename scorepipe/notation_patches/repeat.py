"""Repeat barline notation patch validation, application, verification, and inspection."""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.document import Document
from .common import (
    REPEAT_DIRECTIONS,
    _find_barline,
    _get_or_create_barline,
    _positive_integer,
    _prune_empty_barline,
    _resolve_patch_part,
    _sort_barline_children,
)

_BAR_STYLE_BY_DIRECTION = {
    "forward": "heavy-light",
    "backward": "light-heavy",
}


def _validate_repeat(
    patch: dict, doc: Document | None, prefix: str, require_acceptance: bool = False
) -> list[str]:
    problems: list[str] = []
    if require_acceptance and patch.get("status") not in (None, "accepted"):
        problems.append(f"{prefix}: repeat patch must be accepted before apply")
    _part_id, part, part_problems = _resolve_patch_part(patch, doc, prefix)
    problems.extend(part_problems)
    measure_count = len(doc.part_measures(part)) if doc is not None and part is not None else None
    if patch.get("mode") not in (None, "add", "replace", "remove"):
        problems.append(f"{prefix}: mode must be add/replace/remove")
    if not _positive_integer(patch.get("measure")):
        problems.append(f"{prefix}: measure must be a positive integer")
    elif measure_count is not None and patch["measure"] > measure_count:
        problems.append(f"{prefix}: measure exceeds {measure_count}")
    direction = patch.get("direction")
    if direction not in REPEAT_DIRECTIONS:
        problems.append(f"{prefix}: direction must be forward/backward")
    times = patch.get("times")
    if times is not None:
        if isinstance(times, bool) or not isinstance(times, int) or times < 2:
            problems.append(f"{prefix}: times must be an integer >= 2")
        elif direction == "forward":
            problems.append(f"{prefix}: times is only valid on backward repeats")
    if not (patch.get("page") or patch.get("bbox") or patch.get("crop")):
        problems.append(f"{prefix}: page/bbox evidence is required")
    if not isinstance(patch.get("evidence"), str) or not patch["evidence"].strip():
        problems.append(f"{prefix}: evidence is required")
    return problems


def _apply_repeat(
    doc: Document,
    part_id: str,
    part: ElementTree.Element,
    patch: dict,
) -> int:
    measures = doc.part_measures(part)
    measure = measures[patch["measure"] - 1]
    direction = patch["direction"]
    location = "left" if direction == "forward" else "right"
    mode = patch.get("mode") or "add"
    times = patch.get("times")
    changed = 0

    if mode in ("replace", "remove"):
        changed += _remove_repeat(measure, location, direction)
    if mode == "remove":
        return changed

    barline = _get_or_create_barline(measure, location)
    expected_style = _BAR_STYLE_BY_DIRECTION[direction]
    bar_style = barline.find("bar-style")
    if bar_style is None:
        bar_style = ElementTree.SubElement(barline, "bar-style")
        bar_style.text = expected_style
        changed += 1
    elif (bar_style.text or "").strip() != expected_style:
        bar_style.text = expected_style
        changed += 1

    existing_repeat = next(
        (el for el in barline.findall("repeat") if el.get("direction") == direction),
        None,
    )
    if existing_repeat is None:
        attrs = {"direction": direction}
        if times is not None:
            attrs["times"] = str(times)
        ElementTree.SubElement(barline, "repeat", attrs)
        changed += 1
    else:
        desired_times = str(times) if times is not None else None
        if existing_repeat.get("times") != desired_times:
            if desired_times is None:
                existing_repeat.attrib.pop("times", None)
            else:
                existing_repeat.set("times", desired_times)
            changed += 1

    _sort_barline_children(barline)
    return changed


def _remove_repeat(measure: ElementTree.Element, location: str, direction: str) -> int:
    barline = _find_barline(measure, location)
    if barline is None:
        return 0
    removed = 0
    for repeat in list(barline.findall("repeat")):
        if repeat.get("direction") == direction:
            barline.remove(repeat)
            removed += 1
    bar_style = barline.find("bar-style")
    if bar_style is not None and (bar_style.text or "").strip() == _BAR_STYLE_BY_DIRECTION[direction]:
        barline.remove(bar_style)
        removed += 1
    _prune_empty_barline(measure, barline)
    return removed


def _verify_repeat(doc: Document, patch: dict, prefix: str) -> list[str]:
    part_id, part, part_problems = _resolve_patch_part(patch, doc, prefix)
    if part_problems or part is None:
        return part_problems
    measure = patch.get("measure")
    direction = patch.get("direction")
    found = [
        item
        for item in list_repeats(doc, part_id=part_id)
        if item["measure"] == measure and item["direction"] == direction
    ]
    if patch.get("mode") == "remove":
        if found:
            return [f"{prefix}: repeat {direction!r} still present at m{measure}"]
        return []
    if not found:
        return [f"{prefix}: repeat {direction!r} missing at m{measure}"]
    return []


def list_repeats(doc: Document, part_id: str | None = None) -> list[dict]:
    """Read back repeat barlines with measure numbers and directions."""
    result = []
    for current_part, _part, number, measure in doc.iter_part_measures():
        if part_id is not None and current_part != part_id:
            continue
        for barline in measure.findall("barline"):
            location = barline.get("location") or "right"
            for repeat in barline.findall("repeat"):
                entry = {
                    "part": current_part,
                    "measure": number,
                    "location": location,
                    "direction": repeat.get("direction"),
                }
                times_text = repeat.get("times")
                if times_text and times_text.isdigit():
                    entry["times"] = int(times_text)
                result.append(entry)
    return result
