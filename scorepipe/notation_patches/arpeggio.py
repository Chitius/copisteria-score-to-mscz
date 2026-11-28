"""Arpeggio / non-arpeggiate notation patch validation, application, verification, and inspection."""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.document import Document
from .common import (
    ARPEGGIO_DIRECTIONS,
    ARPEGGIO_KINDS,
    _find_base_events_at,
    _insert_notation_child,
    _next_direction_number,
    _positive_integer,
    _resolve_patch_part,
)


def _patch_staves(patch: dict) -> list[int] | None:
    staves = patch.get("staves")
    if staves is not None:
        if (
            not isinstance(staves, list)
            or not staves
            or any(not _positive_integer(value) for value in staves)
            or len(set(staves)) != len(staves)
        ):
            return None
        return list(staves)
    staff = patch.get("staff")
    if _positive_integer(staff):
        return [staff]
    return None


def _chord_notes_at(
    doc: Document,
    measure: ElementTree.Element,
    part: ElementTree.Element,
    *,
    staff: str,
    beat: float,
    voice: str | None = None,
) -> list:
    divisions = doc.effective_divisions(measure, part)
    base_events = _find_base_events_at(
        doc, measure, part, staff=staff, beat=beat, voice=voice, include_rests=False
    )
    if not base_events:
        return []
    target_voice = base_events[0].voice
    return [
        event
        for event in doc.events(measure, divisions)
        if not event.rest
        and event.staff == staff
        and event.voice == target_voice
        and abs(event.onset - beat) <= 1e-3
    ]


def _validate_arpeggio(
    patch: dict, doc: Document | None, prefix: str, require_acceptance: bool = False
) -> list[str]:
    problems: list[str] = []
    if require_acceptance and patch.get("status") not in (None, "accepted"):
        problems.append(f"{prefix}: arpeggio patch must be accepted before apply")
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
    staves = _patch_staves(patch)
    if staves is None:
        problems.append(f"{prefix}: staff or unique positive staves array is required")
    if patch.get("voice") is not None and (
        not isinstance(patch.get("voice"), str) or not patch["voice"].strip()
    ):
        problems.append(f"{prefix}: voice must be a non-empty string")
    kind = patch.get("kind") or "arpeggiate"
    if kind not in ARPEGGIO_KINDS:
        problems.append(f"{prefix}: kind must be arpeggiate/non-arpeggiate")
    direction = patch.get("direction")
    if direction is not None:
        if direction not in ARPEGGIO_DIRECTIONS:
            problems.append(f"{prefix}: direction must be none/up/down")
        elif kind != "arpeggiate" and direction != "none":
            problems.append(f"{prefix}: direction is only valid when kind='arpeggiate'")
    if (
        doc is not None
        and part is not None
        and _positive_integer(measure_num)
        and measure_num <= len(doc.part_measures(part))
        and not isinstance(beat, bool)
        and isinstance(beat, (int, float))
        and beat >= 0
        and staves is not None
    ):
        measure = doc.part_measures(part)[measure_num - 1]
        for staff in staves:
            events = _chord_notes_at(
                doc, measure, part, staff=str(staff), beat=float(beat), voice=patch.get("voice")
            )
            if not events:
                problems.append(
                    f"{prefix}: no pitched note at m{measure_num} beat {beat} staff {staff}"
                )
    if not (patch.get("page") or patch.get("bbox") or patch.get("crop")):
        problems.append(f"{prefix}: page/bbox evidence is required")
    if not isinstance(patch.get("evidence"), str) or not patch["evidence"].strip():
        problems.append(f"{prefix}: evidence is required")
    return problems


def _apply_arpeggio(
    doc: Document,
    part_id: str,
    part: ElementTree.Element,
    patch: dict,
    next_number: int,
) -> tuple[int, int]:
    measure = doc.part_measures(part)[patch["measure"] - 1]
    beat = float(patch["beat"])
    staves = sorted(_patch_staves(patch) or [1])
    voice = patch.get("voice")
    mode = patch.get("mode") or "add"
    kind = patch.get("kind") or "arpeggiate"
    direction = patch.get("direction") or "none"
    changed = 0

    groups = [
        _chord_notes_at(doc, measure, part, staff=str(staff), beat=beat, voice=voice)
        for staff in staves
    ]
    if any(not group for group in groups):
        return 0, next_number

    if mode in ("replace", "remove"):
        for group in groups:
            for event in group:
                changed += _remove_arpeggios(event.element)
    if mode == "remove":
        return changed, next_number

    number = str(next_number)
    if kind == "arpeggiate":
        for group in groups:
            base = group[0].element
            attrs = {"number": number}
            if direction in ("up", "down"):
                attrs["direction"] = direction
            _insert_notation_child(base, ElementTree.Element("arpeggiate", attrs))
            changed += 1
        return changed, next_number + 1

    # non-arpeggiate bracket requires top and bottom ends
    top_note = groups[0][-1].element
    bottom_note = groups[-1][0].element
    if top_note is bottom_note:
        _insert_notation_child(
            top_note, ElementTree.Element("non-arpeggiate", {"type": "top", "number": number})
        )
        changed += 1
    else:
        _insert_notation_child(
            top_note, ElementTree.Element("non-arpeggiate", {"type": "top", "number": number})
        )
        _insert_notation_child(
            bottom_note,
            ElementTree.Element("non-arpeggiate", {"type": "bottom", "number": number}),
        )
        changed += 2
    return changed, next_number + 1


def _remove_arpeggios(note: ElementTree.Element) -> int:
    notations = note.find("notations")
    if notations is None:
        return 0
    removed = 0
    for child in list(notations):
        if child.tag in ("arpeggiate", "non-arpeggiate"):
            notations.remove(child)
            removed += 1
    if len(notations) == 0:
        note.remove(notations)
    return removed


def _next_arpeggio_number(doc: Document, part_id: str) -> int:
    return max(
        _next_direction_number(doc, "arpeggiate", part_id),
        _next_direction_number(doc, "non-arpeggiate", part_id),
    )


def _verify_arpeggio(doc: Document, patch: dict, prefix: str) -> list[str]:
    part_id, part, part_problems = _resolve_patch_part(patch, doc, prefix)
    if part_problems or part is None:
        return part_problems
    measure = patch.get("measure")
    beat = float(patch.get("beat") or 0)
    staves = [str(s) for s in (_patch_staves(patch) or [])]
    kind = patch.get("kind") or "arpeggiate"
    found = [
        item
        for item in list_arpeggios(doc, part_id=part_id)
        if item["measure"] == measure
        and abs(item["beat"] - beat) <= 1e-3
        and item["kind"] == kind
        and item["staff"] in staves
    ]
    if patch.get("mode") == "remove":
        if found:
            return [f"{prefix}: {kind} still present at m{measure} beat {beat}"]
        return []
    found_staves = {item["staff"] for item in found}
    missing = [s for s in staves if s not in found_staves]
    if missing:
        return [f"{prefix}: {kind} missing at m{measure} beat {beat} staff {','.join(missing)}"]
    if len(staves) > 1 and kind == "arpeggiate":
        numbers = {item["number"] for item in found if item["number"] is not None}
        if len(numbers) != 1:
            return [f"{prefix}: cross-staff arpeggio numbers do not match at m{measure} beat {beat}"]
    return []


def list_arpeggios(doc: Document, part_id: str | None = None) -> list[dict]:
    """Read back arpeggiate and non-arpeggiate marks with measure/beat/staff positions."""
    result = []
    for current_part, part, number, measure in doc.iter_part_measures():
        if part_id is not None and current_part != part_id:
            continue
        divisions = doc.effective_divisions(measure, part)
        for event in doc.events(measure, divisions):
            if event.rest:
                continue
            for child in event.element.findall("notations/*"):
                if child.tag not in ("arpeggiate", "non-arpeggiate"):
                    continue
                result.append(
                    {
                        "part": current_part,
                        "measure": number,
                        "beat": round(event.onset, 4),
                        "staff": event.staff,
                        "voice": event.voice,
                        "kind": child.tag,
                        "number": child.get("number"),
                        "direction": child.get("direction") or "none",
                        "type": child.get("type"),
                    }
                )
    return result
