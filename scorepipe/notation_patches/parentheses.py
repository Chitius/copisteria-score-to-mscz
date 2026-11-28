"""Parenthesized notehead / cautionary accidental patch validation, application, verification, and inspection."""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.document import Document
from .common import (
    PARENTHESES_TARGETS,
    _alter,
    _pitch_name,
    _positive_integer,
    _resolve_patch_part,
)

_ACCIDENTAL_BY_ALTER = {
    -2: "flat-flat",
    -1: "flat",
    0: "natural",
    1: "sharp",
    2: "double-sharp",
}
_BEFORE_ACCIDENTAL = {"grace", "cue", "chord", "pitch", "rest", "duration", "tie", "instrument", "footnote", "level", "voice", "type", "dot"}
_BEFORE_NOTEHEAD = _BEFORE_ACCIDENTAL | {"accidental", "time-modification", "stem"}


def _matching_notes(
    doc: Document,
    measure: ElementTree.Element,
    part: ElementTree.Element,
    *,
    staff: str,
    beat: float,
    pitch: str,
    voice: str | None = None,
) -> list:
    divisions = doc.effective_divisions(measure, part)
    target_pitch = pitch.strip()
    matches = []
    for event in doc.events(measure, divisions):
        if event.rest:
            continue
        if event.staff != staff:
            continue
        if voice is not None and event.voice != str(voice):
            continue
        if abs(event.onset - beat) > 1e-3:
            continue
        if _pitch_name(event.element) == target_pitch:
            matches.append(event)
    return matches


def _insert_note_child(
    note: ElementTree.Element, child: ElementTree.Element, before_tags: set[str]
) -> None:
    insert_at = 0
    for index, existing in enumerate(list(note)):
        if existing.tag in before_tags:
            insert_at = index + 1
    note.insert(insert_at, child)


def _validate_parentheses(
    patch: dict, doc: Document | None, prefix: str, require_acceptance: bool = False
) -> list[str]:
    problems: list[str] = []
    if require_acceptance and patch.get("status") not in (None, "accepted"):
        problems.append(f"{prefix}: parentheses patch must be accepted before apply")
    _part_id, part, part_problems = _resolve_patch_part(patch, doc, prefix)
    problems.extend(part_problems)
    measure_count = len(doc.part_measures(part)) if doc is not None and part is not None else None
    if patch.get("mode") not in (None, "add", "remove"):
        problems.append(f"{prefix}: mode must be add/remove")
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
    pitch = patch.get("pitch")
    if not isinstance(pitch, str) or len(pitch.strip()) < 2:
        problems.append(f"{prefix}: pitch is required")
    target = patch.get("target") or "notehead"
    if target not in PARENTHESES_TARGETS:
        problems.append(f"{prefix}: target must be notehead/accidental/both")
    if (
        doc is not None
        and part is not None
        and _positive_integer(measure_num)
        and measure_num <= len(doc.part_measures(part))
        and not isinstance(beat, bool)
        and isinstance(beat, (int, float))
        and beat >= 0
        and _positive_integer(patch.get("staff"))
        and isinstance(pitch, str)
        and len(pitch.strip()) >= 2
    ):
        measure = doc.part_measures(part)[measure_num - 1]
        matches = _matching_notes(
            doc,
            measure,
            part,
            staff=str(patch["staff"]),
            beat=float(beat),
            pitch=pitch,
            voice=patch.get("voice"),
        )
        if not matches:
            problems.append(
                f"{prefix}: no note matching pitch {pitch!r} at m{measure_num} beat {beat} staff {patch['staff']}"
            )
    if not (patch.get("page") or patch.get("bbox") or patch.get("crop")):
        problems.append(f"{prefix}: page/bbox evidence is required")
    if not isinstance(patch.get("evidence"), str) or not patch["evidence"].strip():
        problems.append(f"{prefix}: evidence is required")
    return problems


def _apply_parentheses(
    doc: Document,
    part_id: str,
    part: ElementTree.Element,
    patch: dict,
) -> int:
    measure = doc.part_measures(part)[patch["measure"] - 1]
    staff = str(patch["staff"])
    beat = float(patch["beat"])
    pitch = patch["pitch"]
    voice = patch.get("voice")
    target = patch.get("target") or "notehead"
    mode = patch.get("mode") or "add"
    matches = _matching_notes(
        doc, measure, part, staff=staff, beat=beat, pitch=pitch, voice=voice
    )
    if not matches:
        return 0

    changed = 0
    note = matches[0].element
    if mode == "remove":
        if target in ("notehead", "both"):
            nh = note.find("notehead")
            if nh is not None and nh.get("parentheses") == "yes":
                nh.attrib.pop("parentheses", None)
                if (nh.text or "").strip() == "normal" and not nh.attrib:
                    note.remove(nh)
                changed += 1
        if target in ("accidental", "both"):
            acc = note.find("accidental")
            if acc is not None and acc.get("parentheses") == "yes":
                acc.attrib.pop("parentheses", None)
                changed += 1
        return changed

    if target in ("notehead", "both"):
        nh = note.find("notehead")
        if nh is None:
            nh = ElementTree.Element("notehead", {"parentheses": "yes"})
            nh.text = "normal"
            _insert_note_child(note, nh, _BEFORE_NOTEHEAD)
            changed += 1
        elif nh.get("parentheses") != "yes":
            nh.set("parentheses", "yes")
            changed += 1

    if target in ("accidental", "both"):
        acc = note.find("accidental")
        if acc is None:
            alter = _alter(note)
            acc_text = _ACCIDENTAL_BY_ALTER.get(int(alter) if isinstance(alter, (int, float)) else 0, "natural")
            acc = ElementTree.Element("accidental", {"parentheses": "yes"})
            acc.text = acc_text
            _insert_note_child(note, acc, _BEFORE_ACCIDENTAL)
            changed += 1
        elif acc.get("parentheses") != "yes":
            acc.set("parentheses", "yes")
            changed += 1

    return changed


def _verify_parentheses(doc: Document, patch: dict, prefix: str) -> list[str]:
    part_id, part, part_problems = _resolve_patch_part(patch, doc, prefix)
    if part_problems or part is None:
        return part_problems
    measure = patch.get("measure")
    beat = float(patch.get("beat") or 0)
    staff = str(patch.get("staff"))
    pitch = (patch.get("pitch") or "").strip()
    target = patch.get("target") or "notehead"
    mode = patch.get("mode") or "add"
    found = [
        item
        for item in list_parentheses(doc, part_id=part_id)
        if item["measure"] == measure
        and item["staff"] == staff
        and abs(item["beat"] - beat) <= 1e-3
        and item["pitch"] == pitch
    ]
    if mode == "remove":
        for item in found:
            if target in ("notehead", "both") and item["notehead"]:
                return [f"{prefix}: notehead parentheses still present on {pitch} at m{measure} beat {beat}"]
            if target in ("accidental", "both") and item["accidental"]:
                return [f"{prefix}: accidental parentheses still present on {pitch} at m{measure} beat {beat}"]
        return []
    if not found:
        return [f"{prefix}: parentheses missing on {pitch} at m{measure} beat {beat} staff {staff}"]
    item = found[0]
    if target in ("notehead", "both") and not item["notehead"]:
        return [f"{prefix}: notehead parentheses missing on {pitch} at m{measure} beat {beat}"]
    if target in ("accidental", "both") and not item["accidental"]:
        return [f"{prefix}: accidental parentheses missing on {pitch} at m{measure} beat {beat}"]
    return []


def list_parentheses(doc: Document, part_id: str | None = None) -> list[dict]:
    """Read back parenthesized noteheads and accidentals with measure/beat/staff/pitch."""
    result = []
    for current_part, part, number, measure in doc.iter_part_measures():
        if part_id is not None and current_part != part_id:
            continue
        divisions = doc.effective_divisions(measure, part)
        for event in doc.events(measure, divisions):
            if event.rest:
                continue
            nh = event.element.find("notehead")
            acc = event.element.find("accidental")
            has_nh = nh is not None and nh.get("parentheses") == "yes"
            has_acc = acc is not None and acc.get("parentheses") == "yes"
            if not (has_nh or has_acc):
                continue
            result.append(
                {
                    "part": current_part,
                    "measure": number,
                    "beat": round(event.onset, 4),
                    "staff": event.staff,
                    "voice": event.voice,
                    "pitch": _pitch_name(event.element),
                    "notehead": has_nh,
                    "accidental": has_acc,
                }
            )
    return result
