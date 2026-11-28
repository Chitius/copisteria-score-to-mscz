"""Dynamic mark notation patch validation, application, verification, and inspection."""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.document import Document
from .common import (
    DYNAMIC_MARKS,
    _direction_insertion_index,
    _positive_integer,
    _resolve_patch_part,
)


def _validate_dynamic(
    patch: dict, doc: Document | None, prefix: str, require_acceptance: bool = False
) -> list[str]:
    problems: list[str] = []
    if require_acceptance and patch.get("status") not in (None, "accepted"):
        problems.append(f"{prefix}: dynamic patch must be accepted before apply")
    _part_id, part, part_problems = _resolve_patch_part(patch, doc, prefix)
    problems.extend(part_problems)
    measure_count = len(doc.part_measures(part)) if doc is not None and part is not None else None
    if patch.get("mode") not in (None, "add", "replace", "remove"):
        problems.append(f"{prefix}: mode must be add/replace/remove")
    if not _positive_integer(patch.get("measure")):
        problems.append(f"{prefix}: measure must be a positive integer")
    elif measure_count is not None and patch["measure"] > measure_count:
        problems.append(f"{prefix}: measure exceeds {measure_count}")
    beat = patch.get("beat")
    if isinstance(beat, bool) or not isinstance(beat, (int, float)) or beat < 0:
        problems.append(f"{prefix}: beat must be non-negative")
    if not _positive_integer(patch.get("staff")):
        problems.append(f"{prefix}: staff must be a positive integer")
    if patch.get("mark") not in DYNAMIC_MARKS:
        problems.append(f"{prefix}: unsupported dynamic mark {patch.get('mark')!r}")
    if patch.get("placement") not in (None, "above", "below"):
        problems.append(f"{prefix}: placement must be above/below")
    if not (patch.get("page") or patch.get("bbox") or patch.get("crop")):
        problems.append(f"{prefix}: page/bbox evidence is required")
    if not isinstance(patch.get("evidence"), str) or not patch["evidence"].strip():
        problems.append(f"{prefix}: evidence is required")
    return problems


def _apply_dynamic(
    doc: Document,
    part_id: str,
    part: ElementTree.Element,
    patch: dict,
) -> int:
    measures = doc.part_measures(part)
    measure = measures[patch["measure"] - 1]
    divisions = doc.effective_divisions(measure, part)
    staff = str(patch["staff"])
    beat = float(patch["beat"])
    mark = patch["mark"]
    mode = patch.get("mode") or "add"
    placement = patch.get("placement") or "below"
    changed = 0

    if mode in ("replace", "remove"):
        changed += _remove_dynamics_at(measure, staff, beat, divisions)
    if mode == "remove":
        return changed

    direction_el = ElementTree.Element("direction", {"placement": placement})
    direction_type = ElementTree.SubElement(direction_el, "direction-type")
    dynamics_el = ElementTree.SubElement(direction_type, "dynamics")
    ElementTree.SubElement(dynamics_el, mark)
    ElementTree.SubElement(direction_el, "staff").text = staff
    index = _direction_insertion_index(measure, beat, staff, divisions)
    measure.insert(index, direction_el)
    return changed + 1


def _verify_dynamic(doc: Document, patch: dict, prefix: str) -> list[str]:
    part_id, part, part_problems = _resolve_patch_part(patch, doc, prefix)
    if part_problems or part is None:
        return part_problems
    staff = str(patch.get("staff"))
    measure = patch.get("measure")
    beat = float(patch.get("beat") or 0)
    mark = patch.get("mark")
    found = [
        item
        for item in list_dynamics(doc, part_id=part_id)
        if item["measure"] == measure
        and item["staff"] == staff
        and abs(item["beat"] - beat) <= 1e-3
    ]
    if patch.get("mode") == "remove":
        if any(item["mark"] == mark for item in found):
            return [f"{prefix}: dynamic {mark!r} still present at m{measure} beat {beat}"]
        return []
    if not any(item["mark"] == mark for item in found):
        return [f"{prefix}: dynamic {mark!r} missing at m{measure} beat {beat} staff {staff}"]
    return []


def _remove_dynamics_at(
    measure: ElementTree.Element, staff: str, beat: float, divisions: float
) -> int:
    removed = 0
    cursor = 0.0
    for child in list(measure):
        if child.tag in ("backup", "forward"):
            value = int(child.findtext("duration") or 0)
            cursor += -value if child.tag == "backup" else value
            continue
        if child.tag == "note":
            if child.find("chord") is None:
                cursor += int(child.findtext("duration") or 0)
            continue
        if child.tag != "direction":
            continue
        if child.find("direction-type/dynamics") is None:
            continue
        if (child.findtext("staff") or "1") != staff:
            continue
        offset = int(child.findtext("offset") or 0)
        onset = (cursor + offset) / divisions
        if abs(onset - beat) <= 1e-3:
            measure.remove(child)
            removed += 1
    return removed


def list_dynamics(doc: Document, part_id: str | None = None) -> list[dict]:
    """Read back dynamic directions with measure/beat/staff positions."""
    result = []
    for current_part, part, number, measure in doc.iter_part_measures():
        if part_id is not None and current_part != part_id:
            continue
        divisions = doc.effective_divisions(measure, part)
        cursor = 0.0
        for child in measure:
            if child.tag in ("backup", "forward"):
                value = int(child.findtext("duration") or 0)
                cursor += -value if child.tag == "backup" else value
                continue
            if child.tag == "note":
                if child.find("chord") is None:
                    cursor += int(child.findtext("duration") or 0)
                continue
            if child.tag != "direction":
                continue
            dyn = child.find("direction-type/dynamics")
            if dyn is None or len(dyn) == 0:
                continue
            offset = int(child.findtext("offset") or 0)
            onset = (cursor + offset) / divisions
            for tag_el in dyn:
                result.append(
                    {
                        "part": current_part,
                        "measure": number,
                        "beat": round(onset, 4),
                        "staff": child.findtext("staff") or "1",
                        "mark": tag_el.tag,
                    }
                )
    return result
