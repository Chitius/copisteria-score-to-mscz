"""Fermata notation patch validation, application, verification, and inspection."""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.document import Document
from .common import (
    FERMATA_SHAPES,
    FERMATA_TYPES,
    _find_base_events_at,
    _insert_notation_child,
    _positive_integer,
    _resolve_patch_part,
)


def _validate_fermata(
    patch: dict, doc: Document | None, prefix: str, require_acceptance: bool = False
) -> list[str]:
    problems: list[str] = []
    if require_acceptance and patch.get("status") not in (None, "accepted"):
        problems.append(f"{prefix}: fermata patch must be accepted before apply")
    _part_id, part, part_problems = _resolve_patch_part(patch, doc, prefix)
    problems.extend(part_problems)
    measure_count = len(doc.part_measures(part)) if doc is not None and part is not None else None
    if patch.get("mode") not in (None, "add", "replace", "remove"):
        problems.append(f"{prefix}: mode must be add/replace/remove")
    measure_num = patch.get("measure")
    if not _positive_integer(measure_num):
        problems.append(f"{prefix}: measure must be a positive integer")
    elif measure_count is not None and measure_num > measure_count:
        problems.append(f"{prefix}: measure exceeds {measure_count}")
    beat = patch.get("beat")
    if isinstance(beat, bool) or not isinstance(beat, (int, float)) or beat < 0:
        problems.append(f"{prefix}: beat must be non-negative")
    if not _positive_integer(patch.get("staff")):
        problems.append(f"{prefix}: staff must be a positive integer")
    if patch.get("voice") is not None and (
        not isinstance(patch.get("voice"), str) or not patch["voice"].strip()
    ):
        problems.append(f"{prefix}: voice must be a non-empty string")
    if patch.get("type") not in (None, *FERMATA_TYPES):
        problems.append(f"{prefix}: type must be upright/inverted")
    if patch.get("shape") not in (None, *FERMATA_SHAPES):
        problems.append(f"{prefix}: shape must be normal/angled/square")
    if (
        doc is not None
        and part is not None
        and _positive_integer(measure_num)
        and measure_num <= len(doc.part_measures(part))
        and not isinstance(beat, bool)
        and isinstance(beat, (int, float))
        and beat >= 0
        and _positive_integer(patch.get("staff"))
    ):
        measure = doc.part_measures(part)[measure_num - 1]
        events = _find_base_events_at(
            doc,
            measure,
            part,
            staff=str(patch["staff"]),
            beat=float(beat),
            voice=patch.get("voice"),
            include_rests=True,
        )
        if not events:
            problems.append(
                f"{prefix}: no note/rest anchor at m{measure_num} beat {beat} staff {patch['staff']}"
            )
    if not (patch.get("page") or patch.get("bbox") or patch.get("crop")):
        problems.append(f"{prefix}: page/bbox evidence is required")
    if not isinstance(patch.get("evidence"), str) or not patch["evidence"].strip():
        problems.append(f"{prefix}: evidence is required")
    return problems


def _apply_fermata(
    doc: Document,
    part_id: str,
    part: ElementTree.Element,
    patch: dict,
) -> int:
    measure = doc.part_measures(part)[patch["measure"] - 1]
    staff = str(patch["staff"])
    beat = float(patch["beat"])
    voice = patch.get("voice")
    mode = patch.get("mode") or "add"
    fermata_type = patch.get("type") or "upright"
    shape = patch.get("shape") or "normal"
    events = _find_base_events_at(
        doc, measure, part, staff=staff, beat=beat, voice=voice, include_rests=True
    )
    if not events:
        return 0

    changed = 0
    if mode in ("replace", "remove"):
        for event in events:
            changed += _remove_fermatas(event.element)
    if mode == "remove":
        return changed

    target = events[0].element
    existing = target.findall("notations/fermata")
    desired_text = None if shape == "normal" else shape
    if any(
        (el.get("type") or "upright") == fermata_type
        and ((el.text or "").strip() or None) == desired_text
        for el in existing
    ):
        return changed
    fermata = ElementTree.Element("fermata", {"type": fermata_type})
    if desired_text is not None:
        fermata.text = desired_text
    _insert_notation_child(target, fermata)
    return changed + 1


def _remove_fermatas(note: ElementTree.Element) -> int:
    notations = note.find("notations")
    if notations is None:
        return 0
    removed = 0
    for child in list(notations.findall("fermata")):
        notations.remove(child)
        removed += 1
    if len(notations) == 0:
        note.remove(notations)
    return removed


def _verify_fermata(doc: Document, patch: dict, prefix: str) -> list[str]:
    part_id, part, part_problems = _resolve_patch_part(patch, doc, prefix)
    if part_problems or part is None:
        return part_problems
    staff = str(patch.get("staff"))
    measure = patch.get("measure")
    beat = float(patch.get("beat") or 0)
    fermata_type = patch.get("type") or "upright"
    found = [
        item
        for item in list_fermatas(doc, part_id=part_id)
        if item["measure"] == measure
        and item["staff"] == staff
        and abs(item["beat"] - beat) <= 1e-3
    ]
    if patch.get("mode") == "remove":
        if found:
            return [f"{prefix}: fermata still present at m{measure} beat {beat} staff {staff}"]
        return []
    if not any(item["type"] == fermata_type for item in found):
        return [
            f"{prefix}: fermata ({fermata_type}) missing at m{measure} beat {beat} staff {staff}"
        ]
    return []


def list_fermatas(doc: Document, part_id: str | None = None) -> list[dict]:
    """Read back fermata notations with measure/beat/staff positions."""
    result = []
    for current_part, part, number, measure in doc.iter_part_measures():
        if part_id is not None and current_part != part_id:
            continue
        divisions = doc.effective_divisions(measure, part)
        for event in doc.events(measure, divisions):
            if event.chord:
                continue
            for fermata in event.element.findall("notations/fermata"):
                result.append(
                    {
                        "part": current_part,
                        "measure": number,
                        "beat": round(event.onset, 4),
                        "staff": event.staff,
                        "voice": event.voice,
                        "type": fermata.get("type") or "upright",
                        "shape": (fermata.text or "").strip() or "normal",
                    }
                )
    return result
