"""Constrained corrections: apply human-accepted pitch/octave/duration fixes at unique anchors."""

from __future__ import annotations

import json
import math
import re
from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree

from .core.document import Document
from .notation_patches.common import (
    NOTE_TYPE_BEATS,
    _pitch_name,
    _positive_integer,
    _resolve_patch_part,
)

CORRECTION_KINDS = {"pitch", "octave", "duration"}
_PITCH_RE = re.compile(r"^([A-Ga-g])(#{1,2}|b{1,2})?(-?\d+)$")
_DURATION_RE = re.compile(r"^([A-Za-z0-9]+)(\.*)$")
_ACCIDENTAL_TEXT = {
    -2: "flat-flat",
    -1: "flat",
    0: None,
    1: "sharp",
    2: "double-sharp",
}


def load_corrections(path: str | Path) -> tuple[list[dict], dict | None]:
    """Load corrections from either a list file or a facts/envelope object."""
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if isinstance(payload, list):
        return payload, None
    if isinstance(payload, dict):
        items = payload.get("corrections")
        if items is None:
            items = []
        if not isinstance(items, list):
            raise ValueError("corrections field must be a JSON array")
        return items, payload
    raise ValueError("corrections file must be a JSON array or object")


def save_corrections(path: str | Path, corrections: list[dict], envelope: dict | None = None) -> None:
    if envelope is not None:
        updated = dict(envelope)
        updated["corrections"] = corrections
        data = updated
    else:
        data = corrections
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_pitch(value) -> tuple[str, int, int] | None:
    if not isinstance(value, str):
        return None
    match = _PITCH_RE.match(value.strip())
    if not match:
        return None
    step = match.group(1).upper()
    acc = match.group(2) or ""
    alter = acc.count("#") - acc.count("b")
    octave = int(match.group(3))
    return step, alter, octave


def _format_pitch(step: str, alter: int, octave: int) -> str:
    if alter > 0:
        acc = "#" * alter
    elif alter < 0:
        acc = "b" * -alter
    else:
        acc = ""
    return f"{step}{acc}{octave}"


def _parse_duration(value) -> tuple[str, int, Fraction] | None:
    if not isinstance(value, str):
        return None
    match = _DURATION_RE.match(value.strip().lower())
    if not match:
        return None
    note_type = match.group(1)
    dots = len(match.group(2))
    base = NOTE_TYPE_BEATS.get(note_type)
    if base is None:
        return None
    multiplier = Fraction(2) - Fraction(1, 2**dots)
    return note_type, dots, base * multiplier


def _resolve_kind(correction: dict) -> str | None:
    kind = correction.get("kind")
    if kind is not None:
        return kind if kind in CORRECTION_KINDS else None
    if _parse_pitch(correction.get("from")) and _parse_pitch(correction.get("to")):
        return "pitch"
    if _parse_duration(correction.get("from")) and _parse_duration(correction.get("to")):
        return "duration"
    return None


def _note_duration_beats(note: ElementTree.Element, divisions: float) -> Fraction | None:
    note_type = note.findtext("type")
    if note_type and note_type in NOTE_TYPE_BEATS:
        dots = len(note.findall("dot"))
        base = NOTE_TYPE_BEATS[note_type]
        return base * (Fraction(2) - Fraction(1, 2**dots))
    text = note.findtext("duration")
    if text is None or not divisions:
        return None
    try:
        return Fraction(int(text) / divisions).limit_denominator(128)
    except ValueError:
        return None


def _find_targets(
    correction: dict,
    doc: Document,
    *,
    match_value: str,
    kind: str,
    include_voice: bool = True,
) -> tuple[list[ElementTree.Element], ElementTree.Element | None, float]:
    _part_id, part, part_problems = _resolve_patch_part(correction, doc, "correction")
    if part_problems or part is None:
        return [], None, 0.0
    measures = doc.part_measures(part)
    measure_num = correction["measure"]
    if not (1 <= measure_num <= len(measures)):
        return [], None, 0.0
    measure = measures[measure_num - 1]
    divisions = doc.effective_divisions(measure, part)
    beat = float(correction["beat"])
    staff = str(correction["staff"])
    voice = str(correction["voice"]) if include_voice and correction.get("voice") is not None else None

    expected_pitch = _parse_pitch(match_value) if kind in ("pitch", "octave") else None
    expected_pitch_name = _format_pitch(*expected_pitch) if expected_pitch else None
    expected_duration = _parse_duration(match_value) if kind == "duration" else None

    matches: list[ElementTree.Element] = []
    for event in doc.events(measure, divisions):
        if event.rest:
            continue
        if event.staff != staff:
            continue
        if voice is not None and event.voice != voice:
            continue
        if abs(event.onset - beat) > 1e-6:
            continue
        if kind in ("pitch", "octave"):
            if _pitch_name(event.element) == expected_pitch_name:
                matches.append(event.element)
        elif kind == "duration" and expected_duration is not None:
            actual_beats = _note_duration_beats(event.element, divisions)
            if actual_beats is not None and abs(float(actual_beats) - float(expected_duration[2])) < 1e-6:
                matches.append(event.element)
    return matches, part, divisions


def validate_corrections(
    corrections: list[dict],
    doc: Document | None = None,
    *,
    require_acceptance: bool = False,
) -> list[str]:
    """Validate correction entries and verify exact unique note anchors when ``doc`` is given."""
    problems: list[str] = []
    if not isinstance(corrections, list):
        return ["corrections must be an array"]

    for index, correction in enumerate(corrections):
        prefix = f"corrections[{index}]"
        if not isinstance(correction, dict):
            problems.append(f"{prefix}: must be an object")
            continue
        status = correction.get("status")
        if status not in (None, "proposed", "accepted", "rejected"):
            problems.append(f"{prefix}: status must be proposed/accepted/rejected")
            continue
        if require_acceptance and status != "accepted":
            problems.append(f"{prefix}: correction must be accepted before apply")
            continue
        if status == "rejected":
            continue

        _part_id, part, part_problems = _resolve_patch_part(correction, doc, prefix)
        problems.extend(part_problems)

        measure = correction.get("measure")
        if not _positive_integer(measure):
            problems.append(f"{prefix}: measure must be a positive integer")
        elif doc is not None and part is not None and measure > len(doc.part_measures(part)):
            problems.append(f"{prefix}: measure {measure} exceeds {len(doc.part_measures(part))}")

        beat = correction.get("beat")
        if (
            isinstance(beat, bool)
            or not isinstance(beat, (int, float))
            or not math.isfinite(beat)
            or beat < 0
        ):
            problems.append(f"{prefix}: beat must be a non-negative number")

        staff = correction.get("staff")
        if not _positive_integer(staff):
            problems.append(f"{prefix}: staff must be a positive integer")

        voice = correction.get("voice")
        if voice is not None and (
            isinstance(voice, bool)
            or (not isinstance(voice, (int, str)))
            or (isinstance(voice, str) and not voice.strip())
            or (isinstance(voice, int) and voice < 1)
        ):
            problems.append(f"{prefix}: voice must be a positive integer or non-empty string")

        raw_kind = correction.get("kind")
        if raw_kind is not None and raw_kind not in CORRECTION_KINDS:
            problems.append(f"{prefix}: kind must be pitch/octave/duration")
        kind = _resolve_kind(correction)
        if kind is None:
            problems.append(
                f"{prefix}: from/to must be valid pitches (for pitch/octave) or note types (for duration)"
            )
        else:
            if kind in ("pitch", "octave"):
                from_p = _parse_pitch(correction.get("from"))
                to_p = _parse_pitch(correction.get("to"))
                if from_p is None or to_p is None:
                    problems.append(f"{prefix}: from and to must be valid pitches like C4 or F#5")
                elif from_p == to_p:
                    problems.append(f"{prefix}: from and to are identical")
                elif kind == "octave" and (from_p[0], from_p[1]) != (to_p[0], to_p[1]):
                    problems.append(f"{prefix}: octave correction must preserve step and accidental")
            elif kind == "duration":
                from_d = _parse_duration(correction.get("from"))
                to_d = _parse_duration(correction.get("to"))
                if from_d is None or to_d is None:
                    problems.append(f"{prefix}: from and to must be valid note types like quarter or eighth.")
                elif from_d == to_d:
                    problems.append(f"{prefix}: from and to are identical")

        if not _positive_integer(correction.get("page")):
            problems.append(f"{prefix}: page must be a positive integer")
        if not (correction.get("bbox") or correction.get("crop")):
            problems.append(f"{prefix}: bbox or crop evidence is required")
        if not isinstance(correction.get("evidence"), str) or not correction["evidence"].strip():
            problems.append(f"{prefix}: evidence is required")

        if doc is not None and not problems:
            matches, _part, _divisions = _find_targets(
                correction, doc, match_value=correction["from"], kind=kind, include_voice=True
            )
            if len(matches) == 0:
                problems.append(
                    f"{prefix}: anchor matched no note at m{measure} beat {beat} staff {staff} from {correction['from']!r}"
                )
            elif len(matches) > 1:
                problems.append(
                    f"{prefix}: ambiguous anchor matched {len(matches)} notes at m{measure} beat {beat} staff {staff}; specify voice"
                )
    return problems


def apply_corrections(doc: Document, corrections: list[dict]) -> int:
    """Apply accepted corrections to ``doc``; refuses non-unique anchors."""
    accepted = [item for item in corrections if item.get("status") == "accepted"]
    if not accepted:
        return 0
    problems = validate_corrections(accepted, doc, require_acceptance=True)
    if problems:
        raise ValueError("; ".join(problems))

    changed = 0
    for correction in accepted:
        kind = _resolve_kind(correction)
        assert kind is not None
        matches, _part, divisions = _find_targets(
            correction, doc, match_value=correction["from"], kind=kind, include_voice=True
        )
        if len(matches) != 1:
            raise ValueError(
                f"correction at m{correction['measure']} beat {correction['beat']} matched {len(matches)} notes"
            )
        note = matches[0]
        if kind in ("pitch", "octave"):
            _apply_pitch(note, correction["to"])
        else:
            _apply_duration(note, correction["to"], divisions)
        changed += 1
    return changed


def verify_corrections(doc: Document, corrections: list[dict]) -> list[str]:
    """Verify that accepted corrections are present at their anchors after the pipeline."""
    problems: list[str] = []
    for index, correction in enumerate(corrections):
        if correction.get("status") != "accepted":
            continue
        prefix = f"corrections[{index}]"
        kind = _resolve_kind(correction)
        if kind is None:
            problems.append(f"{prefix}: unsupported correction kind")
            continue
        matches, _part, _divisions = _find_targets(
            correction, doc, match_value=correction["to"], kind=kind, include_voice=False
        )
        if not matches:
            problems.append(
                f"{prefix}: corrected note {correction['to']!r} missing at m{correction['measure']} beat {correction['beat']} staff {correction['staff']}"
            )
    return problems


def _apply_pitch(note: ElementTree.Element, target: str) -> None:
    parsed = _parse_pitch(target)
    assert parsed is not None
    step, alter, octave = parsed
    pitch_el = note.find("pitch")
    if pitch_el is None:
        raise ValueError("cannot apply pitch correction to unpitched note")
    step_el = pitch_el.find("step")
    if step_el is None:
        step_el = ElementTree.SubElement(pitch_el, "step")
    step_el.text = step

    alter_el = pitch_el.find("alter")
    if alter != 0:
        if alter_el is None:
            alter_el = ElementTree.Element("alter")
            children = list(pitch_el)
            oct_idx = next((i for i, c in enumerate(children) if c.tag == "octave"), len(children))
            pitch_el.insert(oct_idx, alter_el)
        alter_el.text = str(alter)
    elif alter_el is not None:
        pitch_el.remove(alter_el)

    octave_el = pitch_el.find("octave")
    if octave_el is None:
        octave_el = ElementTree.SubElement(pitch_el, "octave")
    octave_el.text = str(octave)

    accidental_el = note.find("accidental")
    accidental_name = _ACCIDENTAL_TEXT.get(alter)
    if accidental_name is not None:
        if accidental_el is None:
            accidental_el = ElementTree.SubElement(note, "accidental")
        accidental_el.text = accidental_name
    elif accidental_el is not None:
        note.remove(accidental_el)


def _apply_duration(note: ElementTree.Element, target: str, divisions: float) -> None:
    parsed = _parse_duration(target)
    assert parsed is not None
    note_type, dots, beats = parsed
    ticks = int(round(float(beats) * divisions))
    duration_el = note.find("duration")
    if duration_el is None:
        duration_el = ElementTree.SubElement(note, "duration")
    duration_el.text = str(ticks)

    type_el = note.find("type")
    if type_el is None:
        type_el = ElementTree.SubElement(note, "type")
    type_el.text = note_type

    for existing_dot in list(note.findall("dot")):
        note.remove(existing_dot)
    if dots:
        type_idx = list(note).index(type_el) + 1
        for offset in range(dots):
            note.insert(type_idx + offset, ElementTree.Element("dot"))


__all__ = [
    "CORRECTION_KINDS",
    "apply_corrections",
    "load_corrections",
    "save_corrections",
    "validate_corrections",
    "verify_corrections",
]
