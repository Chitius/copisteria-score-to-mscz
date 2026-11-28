"""Ornament and single-note tremolo notation patch validation, application, verification, and inspection."""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.document import Document
from .common import (
    ORNAMENT_KINDS,
    _find_base_events_at,
    _insert_notation_child,
    _positive_integer,
    _resolve_patch_part,
)

_KIND_TO_TAG = {
    "trill": "trill-mark",
    "mordent": "mordent",
    "inverted-mordent": "inverted-mordent",
    "turn": "turn",
    "inverted-turn": "inverted-turn",
    "delayed-turn": "delayed-turn",
    "tremolo": "tremolo",
}
_TAG_TO_KIND = {tag: kind for kind, tag in _KIND_TO_TAG.items()}


def _validate_ornament(
    patch: dict, doc: Document | None, prefix: str, require_acceptance: bool = False
) -> list[str]:
    problems: list[str] = []
    if require_acceptance and patch.get("status") not in (None, "accepted"):
        problems.append(f"{prefix}: ornament patch must be accepted before apply")
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
    kind = patch.get("kind")
    if kind not in ORNAMENT_KINDS:
        problems.append(f"{prefix}: unsupported ornament kind {kind!r}")
    slashes = patch.get("slashes")
    if slashes is not None:
        if kind != "tremolo":
            problems.append(f"{prefix}: slashes is only valid when kind='tremolo'")
        elif isinstance(slashes, bool) or not isinstance(slashes, int) or not (1 <= slashes <= 5):
            problems.append(f"{prefix}: slashes must be an integer between 1 and 5")
    if patch.get("placement") not in (None, "above", "below"):
        problems.append(f"{prefix}: placement must be above/below")
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
            include_rests=False,
        )
        if not events:
            problems.append(
                f"{prefix}: no pitched note anchor at m{measure_num} beat {beat} staff {patch['staff']}"
            )
    if not (patch.get("page") or patch.get("bbox") or patch.get("crop")):
        problems.append(f"{prefix}: page/bbox evidence is required")
    if not isinstance(patch.get("evidence"), str) or not patch["evidence"].strip():
        problems.append(f"{prefix}: evidence is required")
    return problems


def _apply_ornament(
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
    kind = patch["kind"]
    tag = _KIND_TO_TAG[kind]
    slashes = patch.get("slashes", 2)
    placement = patch.get("placement")
    events = _find_base_events_at(
        doc, measure, part, staff=staff, beat=beat, voice=voice, include_rests=False
    )
    if not events:
        return 0

    changed = 0
    if mode in ("replace", "remove"):
        target_tag = tag if mode == "remove" else None
        for event in events:
            changed += _remove_ornaments(event.element, tag=target_tag)
    if mode == "remove":
        return changed

    target = events[0].element
    notations = target.find("notations")
    ornaments = notations.find("ornaments") if notations is not None else None
    if ornaments is None:
        ornaments = ElementTree.Element("ornaments")
        _insert_notation_child(target, ornaments)
    existing = ornaments.find(tag)
    if kind == "tremolo":
        if existing is not None and existing.get("type", "single") == "single" and (existing.text or "").strip() == str(slashes):
            return changed
        if existing is None:
            existing = ElementTree.SubElement(ornaments, "tremolo", {"type": "single"})
        else:
            existing.set("type", "single")
        existing.text = str(slashes)
        return changed + 1

    if existing is not None:
        return changed
    attrs = {"placement": placement} if placement is not None else {}
    ElementTree.SubElement(ornaments, tag, attrs)
    return changed + 1


def _remove_ornaments(note: ElementTree.Element, *, tag: str | None = None) -> int:
    notations = note.find("notations")
    if notations is None:
        return 0
    removed = 0
    for ornaments in list(notations.findall("ornaments")):
        if tag is None:
            notations.remove(ornaments)
            removed += 1
        else:
            for child in list(ornaments.findall(tag)):
                ornaments.remove(child)
                removed += 1
            if len(ornaments) == 0:
                notations.remove(ornaments)
    if len(notations) == 0:
        note.remove(notations)
    return removed


def _verify_ornament(doc: Document, patch: dict, prefix: str) -> list[str]:
    part_id, part, part_problems = _resolve_patch_part(patch, doc, prefix)
    if part_problems or part is None:
        return part_problems
    staff = str(patch.get("staff"))
    measure = patch.get("measure")
    beat = float(patch.get("beat") or 0)
    kind = patch.get("kind")
    found = [
        item
        for item in list_ornaments(doc, part_id=part_id)
        if item["measure"] == measure
        and item["staff"] == staff
        and abs(item["beat"] - beat) <= 1e-3
    ]
    if patch.get("mode") == "remove":
        if any(item["kind"] == kind for item in found):
            return [f"{prefix}: ornament {kind!r} still present at m{measure} beat {beat} staff {staff}"]
        return []
    matches = [item for item in found if item["kind"] == kind]
    if not matches:
        return [f"{prefix}: ornament {kind!r} missing at m{measure} beat {beat} staff {staff}"]
    if kind == "tremolo":
        slashes = patch.get("slashes", 2)
        if not any(item.get("slashes") == slashes for item in matches):
            return [f"{prefix}: tremolo slashes mismatch at m{measure} beat {beat} staff {staff}"]
    return []


def list_ornaments(doc: Document, part_id: str | None = None) -> list[dict]:
    """Read back ornaments and single-note tremolos with measure/beat/staff positions."""
    result = []
    for current_part, part, number, measure in doc.iter_part_measures():
        if part_id is not None and current_part != part_id:
            continue
        divisions = doc.effective_divisions(measure, part)
        for event in doc.events(measure, divisions):
            if event.chord or event.rest:
                continue
            for ornaments in event.element.findall("notations/ornaments"):
                for child in ornaments:
                    kind = _TAG_TO_KIND.get(child.tag)
                    if kind is None:
                        continue
                    entry = {
                        "part": current_part,
                        "measure": number,
                        "beat": round(event.onset, 4),
                        "staff": event.staff,
                        "voice": event.voice,
                        "kind": kind,
                    }
                    if kind == "tremolo" and (child.text or "").strip().isdigit():
                        entry["slashes"] = int(child.text.strip())
                    result.append(entry)
    return result
