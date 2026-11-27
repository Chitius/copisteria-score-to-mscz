"""Constrained notation patches: agent proposes symbols, the compiler writes MusicXML.

``ottava`` (8va/8vb) is emitted as standard MusicXML ``<octave-shift>`` directions. ``tuplet``
rewrites an explicitly evidenced, continuous note segment with one duration ratio and bracket.
``clef`` places a staff clef at a musical anchor (and can retire the clef the OMR put elsewhere).
The agent never has to serialize mscx ids or location fractions.
"""

from __future__ import annotations

import json
import math
from fractions import Fraction
from pathlib import Path
from xml.etree import ElementTree

from .core.document import Document

OTTAAVA_SUBTYPES = {"8va": "up", "8vb": "down"}
CLEF_SIGNS = {"G", "F", "C"}
NOTE_TYPE_BEATS = {
    "maxima": Fraction(32),
    "long": Fraction(16),
    "breve": Fraction(8),
    "whole": Fraction(4),
    "half": Fraction(2),
    "quarter": Fraction(1),
    "eighth": Fraction(1, 2),
    "16th": Fraction(1, 4),
    "32nd": Fraction(1, 8),
    "64th": Fraction(1, 16),
    "128th": Fraction(1, 32),
    "256th": Fraction(1, 64),
    "512th": Fraction(1, 128),
    "1024th": Fraction(1, 256),
}


def _part_score_map(doc: Document, part: ElementTree.Element) -> list[dict]:
    measures = []
    for number, measure in enumerate(doc.part_measures(part), start=1):
        staves: dict[str, list[dict]] = {}
        for event in doc.events(measure, doc.effective_divisions(measure, part)):
            if event.rest:
                continue
            note = event.element
            pitch = _pitch_name(note)
            if pitch is None:
                continue
            modification = note.find("time-modification")
            staves.setdefault(event.staff, []).append(
                {
                    "voice": event.voice,
                    "onset": round(event.onset, 4),
                    "duration": round(event.duration, 4),
                    "pitch": pitch,
                    "alter": _alter(note),
                    "chord": event.chord,
                    "type": note.findtext("type"),
                    "dots": len(note.findall("dot")),
                    "actual": _integer_text(modification, "actual-notes"),
                    "normal": _integer_text(modification, "normal-notes"),
                }
            )
        measures.append({"number": number, "staves": staves})
    return measures


def score_map(doc: Document) -> dict:
    """Stable note anchors for an agent choosing patch start/end positions."""
    parts = list(doc.iter_parts())
    if len(parts) <= 1:
        return {"measures": _part_score_map(doc, parts[0][1]) if parts else []}
    by_part = {part_id: {"measures": _part_score_map(doc, part)} for part_id, part in parts}
    return {"measures": by_part[parts[0][0]]["measures"], "parts": by_part}


def _resolve_patch_part(
    patch: dict, doc: Document | None, prefix: str
) -> tuple[str | None, ElementTree.Element | None, list[str]]:
    part_id = patch.get("part")
    if part_id is not None and (not isinstance(part_id, str) or not part_id.strip()):
        return None, None, [f"{prefix}: part must be a non-empty string"]
    if doc is None:
        return part_id, None, []
    try:
        part = doc.part_by_id(part_id)
    except ValueError:
        return part_id, None, [f"{prefix}: unknown part {part_id!r}"]
    resolved_id = part.get("id") or "P1"
    return resolved_id, part, []


def load_patches(path: str | Path | None) -> dict:
    if not path:
        return {"patches": []}
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def validate_patches(
    payload: dict, doc: Document | None = None, *, require_acceptance: bool = False
) -> list[str]:
    problems: list[str] = []
    patches = payload.get("patches")
    if not isinstance(patches, list):
        return ["patches must be an array"]
    tuplet_plans: list[tuple[int, dict]] = []
    for index, patch in enumerate(patches):
        prefix = f"patches[{index}]"
        if not isinstance(patch, dict):
            problems.append(f"{prefix}: must be an object")
            continue
        op = patch.get("op")
        if op == "ottava":
            problems.extend(_validate_ottava(patch, doc, prefix, require_acceptance))
            continue
        if op == "clef":
            problems.extend(_validate_clef(patch, doc, prefix))
            continue
        if op != "tuplet":
            problems.append(f"{prefix}: unsupported op {op!r}")
            continue
        plan, patch_problems = _validate_tuplet(patch, doc, prefix)
        problems.extend(patch_problems)
        if plan is None:
            continue
        for other_index, other in tuplet_plans:
            if plan["measure"] is other["measure"] and not (
                plan["end_index"] < other["start_index"]
                or plan["start_index"] > other["end_index"]
            ):
                problems.append(f"{prefix}: overlaps patches[{other_index}]")
                break
        else:
            tuplet_plans.append((index, plan))
    return problems


def apply_patches(doc: Document, payload: dict) -> int:
    """Apply validated patches; return directions written plus tuplet spans rewritten."""
    next_number_by_part: dict[str, int] = {}
    patches = payload.get("patches") or []
    # Select every range before deleting forwards or changing durations shifts later onsets.
    tuplet_plans = {
        index: _select_tuplet(patch, doc, f"patches[{index}]")[0]
        for index, patch in enumerate(patches)
        if patch.get("op") == "tuplet"
    }
    changed = 0
    for index, patch in enumerate(patches):
        if patch.get("op") == "tuplet":
            _apply_tuplet(tuplet_plans[index])
            changed += 1
            continue
        if patch.get("op") == "clef":
            changed += _apply_clef(doc, patch)
            continue
        part_id, part, _problems = _resolve_patch_part(patch, doc, f"patches[{index}]")
        assert part is not None and part_id is not None
        measures = doc.part_measures(part)
        start = patch["start"]
        end = patch["end"]
        subtype = patch["subtype"]
        staff = str(patch["staff"])
        mode = patch.get("mode") or "add"
        if mode in ("replace", "remove"):
            changed += remove_octave_shifts(doc, staff, part_id=part_id)
        if mode == "remove":
            continue
        next_number = next_number_by_part.setdefault(part_id, _next_octave_number(doc, part_id))
        number = str(patch.get("number") or next_number)
        next_number_by_part[part_id] = next_number + 1
        start_measure = measures[start["measure"] - 1]
        end_measure = measures[end["measure"] - 1]
        _insert_octave(
            start_measure,
            float(start.get("beat") or 0),
            staff,
            "start",
            OTTAAVA_SUBTYPES[subtype],
            number,
            doc.effective_divisions(start_measure, part),
        )
        _insert_octave(
            end_measure,
            float(end.get("beat") or 0),
            staff,
            "stop",
            OTTAAVA_SUBTYPES[subtype],
            number,
            doc.effective_divisions(end_measure, part),
        )
        changed += 2
    return changed


def _validate_ottava(
    patch: dict, doc: Document | None, prefix: str, require_acceptance: bool = False
) -> list[str]:
    problems: list[str] = []
    if require_acceptance:
        status = patch.get("status")
        if status not in (None, "accepted"):
            problems.append(f"{prefix}: ottava patch must be accepted before apply")
    _part_id, part, part_problems = _resolve_patch_part(patch, doc, prefix)
    problems.extend(part_problems)
    measure_count = len(doc.part_measures(part)) if doc is not None and part is not None else None
    if patch.get("mode") not in (None, "add", "replace", "remove"):
        problems.append(f"{prefix}: mode must be add/replace/remove")
    if patch.get("subtype") not in OTTAAVA_SUBTYPES:
        problems.append(f"{prefix}: subtype must be 8va or 8vb")
    if not isinstance(patch.get("staff"), int) or patch["staff"] < 1:
        problems.append(f"{prefix}: staff must be a positive integer")
    start = patch.get("start") or {}
    end = patch.get("end") or {}
    for label, anchor in (("start", start), ("end", end)):
        if not isinstance(anchor, dict):
            problems.append(f"{prefix}: {label} must be an object")
            continue
        if not isinstance(anchor.get("measure"), int) or anchor["measure"] < 1:
            problems.append(f"{prefix}: {label}.measure must be positive")
        if measure_count is not None and anchor.get("measure", 0) > measure_count:
            problems.append(f"{prefix}: {label}.measure exceeds {measure_count}")
        if not isinstance(anchor.get("beat"), (int, float)) or anchor["beat"] < 0:
            problems.append(f"{prefix}: {label}.beat must be non-negative")
    if (
        isinstance(start.get("measure"), int)
        and isinstance(end.get("measure"), int)
        and (end["measure"], float(end.get("beat") or 0))
        <= (start["measure"], float(start.get("beat") or 0))
    ):
        problems.append(f"{prefix}: end must be after start")
    if not (patch.get("page") or patch.get("bbox") or patch.get("crop")):
        problems.append(f"{prefix}: page/bbox evidence is required")
    return problems


def _validate_tuplet(
    patch: dict, doc: Document | None, prefix: str
) -> tuple[dict | None, list[str]]:
    problems: list[str] = []
    for field in ("measure", "staff", "actual_notes", "normal_notes", "note_count"):
        if not _positive_integer(patch.get(field)):
            problems.append(f"{prefix}: {field} must be a positive integer")
    if not isinstance(patch.get("voice"), str) or not patch["voice"]:
        problems.append(f"{prefix}: voice must be a non-empty string")
    span = patch.get("span_beats")
    if (
        isinstance(span, bool)
        or not isinstance(span, (int, float))
        or not math.isfinite(span)
        or span <= 0
    ):
        problems.append(f"{prefix}: span_beats must be a positive number")
    if patch.get("status") != "accepted":
        problems.append(f"{prefix}: status must be accepted")
    start = patch.get("start") or {}
    end = patch.get("end") or {}
    for label, anchor in (("start", start), ("end", end)):
        if not isinstance(anchor, dict):
            problems.append(f"{prefix}: {label} must be an object")
            continue
        if not _positive_integer(anchor.get("measure")):
            problems.append(f"{prefix}: {label}.measure must be a positive integer")
        beat = anchor.get("beat")
        if (
            isinstance(beat, bool)
            or not isinstance(beat, (int, float))
            or not math.isfinite(beat)
            or beat < 0
        ):
            problems.append(f"{prefix}: {label}.beat must be non-negative")
        if not isinstance(anchor.get("pitch"), str) or not anchor["pitch"]:
            problems.append(f"{prefix}: {label}.pitch is required")
    if isinstance(start, dict) and isinstance(end, dict):
        for label, anchor in (("start", start), ("end", end)):
            if anchor.get("measure") != patch.get("measure"):
                problems.append(f"{prefix}: {label}.measure must match measure")
        if (
            isinstance(start.get("beat"), (int, float))
            and isinstance(end.get("beat"), (int, float))
            and end["beat"] <= start["beat"]
        ):
            problems.append(f"{prefix}: end onset must be after start onset")
    if not _positive_integer(patch.get("page")):
        problems.append(f"{prefix}: page must be a positive integer")
    if not (patch.get("bbox") or patch.get("crop")):
        problems.append(f"{prefix}: bbox or crop evidence is required")
    if not isinstance(patch.get("evidence"), str) or not patch["evidence"]:
        problems.append(f"{prefix}: evidence is required")
    _part_id, part, part_problems = _resolve_patch_part(patch, doc, prefix)
    problems.extend(part_problems)
    if doc is None:
        problems.append(f"{prefix}: tuplet validation requires a document")
        return None, problems
    if part is not None and _positive_integer(patch.get("measure")) and patch["measure"] > len(doc.part_measures(part)):
        problems.append(f"{prefix}: measure exceeds {len(doc.part_measures(part))}")
    if problems:
        return None, problems
    return _select_tuplet(patch, doc, prefix)


def _select_tuplet(patch: dict, doc: Document, prefix: str) -> tuple[dict | None, list[str]]:
    """Resolve a complete segment and check its new durations without changing the tree."""
    problems: list[str] = []
    _part_id, part, part_problems = _resolve_patch_part(patch, doc, prefix)
    if part_problems or part is None:
        return None, part_problems
    measure = doc.part_measures(part)[patch["measure"] - 1]
    staff = str(patch["staff"])
    voice = patch["voice"]
    active_divisions = doc.effective_divisions(measure, part)
    events = doc.events(measure, active_divisions)
    voice_events = [event for event in events if event.staff == staff and event.voice == voice]
    groups: list[list] = []
    for event in voice_events:
        if event.chord and groups and abs(groups[-1][0].onset - event.onset) < 1e-6:
            groups[-1].append(event)
        else:
            groups.append([event])

    anchored = []
    for label in ("start", "end"):
        anchor = patch[label]
        matches = [
            event
            for event in voice_events
            if abs(event.onset - anchor["beat"]) < 1e-6 and _pitch_name(event.element) == anchor["pitch"]
        ]
        if len(matches) != 1:
            problems.append(f"{prefix}: {label} anchor must match exactly one pitched note")
            anchored.append(None)
        else:
            anchored.append(matches[0])
    if any(event is None for event in anchored):
        return None, problems

    group_indices = []
    for event in anchored:
        group_indices.append(next(index for index, group in enumerate(groups) if event in group))
    start_group, end_group = group_indices
    if end_group <= start_group:
        problems.append(f"{prefix}: end onset must be after start onset")
        return None, problems
    selected_groups = groups[start_group : end_group + 1]
    for previous, current in zip(selected_groups, selected_groups[1:]):
        if current[0].onset <= previous[0].onset:
            problems.append(f"{prefix}: onsets must be strictly increasing")
            break
    if len(selected_groups) != patch["note_count"]:
        problems.append(f"{prefix}: note_count does not match the number of onsets")

    children = list(measure)
    start_index = children.index(selected_groups[0][0].element)
    end_index = children.index(selected_groups[-1][-1].element)
    segment = children[start_index : end_index + 1]
    if any(child.tag == "backup" for child in segment):
        problems.append(f"{prefix}: backup inside a tuplet segment is not supported")
    selected_notes = [child for child in segment if child.tag == "note"]
    for note in selected_notes:
        if (note.findtext("staff") or "1") != staff or (note.findtext("voice") or "1") != voice:
            problems.append(f"{prefix}: another staff/voice intersects the segment")
        elif note.find("rest") is not None or _pitch_name(note) is None:
            problems.append(f"{prefix}: segment must contain only pitched notes")
        if note.find("duration") is None:
            problems.append(f"{prefix}: every note must have a duration")
        if note.find("type") is None:
            problems.append(f"{prefix}: every note must have a type")

    _check_existing_tuplets(voice_events, selected_groups, prefix, problems)
    divisions = Fraction(str(active_divisions))
    actual = patch["actual_notes"]
    normal = patch["normal_notes"]
    durations = []
    total = Fraction(0)
    for group in selected_groups:
        group_durations = []
        for event in group:
            note = event.element
            note_type = note.findtext("type")
            if note_type not in NOTE_TYPE_BEATS:
                if note_type is not None:
                    problems.append(f"{prefix}: unsupported note type {note_type!r}")
                continue
            nominal = NOTE_TYPE_BEATS[note_type] * (2 - Fraction(1, 2 ** len(note.findall("dot"))))
            duration = divisions * nominal * normal / actual
            group_durations.append(duration)
            if duration.denominator != 1:
                problems.append(f"{prefix}: new duration is not an integer tick")
        if not group_durations:
            durations.append(0)
            continue
        if any(duration != group_durations[0] for duration in group_durations[1:]):
            problems.append(f"{prefix}: chord members must have the same nominal duration")
        durations.append(int(group_durations[0]))
        total += group_durations[0] / divisions
    if total != Fraction(str(patch["span_beats"])):
        problems.append(f"{prefix}: recomputed duration does not equal span_beats")
    plan = {
        "measure": measure,
        "groups": [[event.element for event in group] for group in selected_groups],
        "forwards": [child for child in segment if child.tag == "forward"],
        "durations": durations,
        "actual": actual,
        "normal": normal,
        "start_index": start_index,
        "end_index": end_index,
    }
    return plan, problems


def _check_existing_tuplets(voice_events, selected_groups, prefix: str, problems: list[str]) -> None:
    start_onset = selected_groups[0][0].onset
    end_onset = selected_groups[-1][0].onset
    starts: list[float] = []
    pairs: list[tuple[float | None, float | None]] = []
    nested = False
    for event in voice_events:
        for tuplet in event.element.findall("notations/tuplet"):
            if tuplet.get("type") == "start":
                if starts:
                    nested = True
                starts.append(event.onset)
            elif tuplet.get("type") == "stop":
                pairs.append((starts.pop() if starts else None, event.onset))
    if nested:
        problems.append(f"{prefix}: existing tuplet crosses or is nested in the segment")
    pairs.extend((start, None) for start in starts)
    for old_start, old_stop in pairs:
        overlaps = (old_start is None or old_start <= end_onset + 1e-6) and (
            old_stop is None or old_stop >= start_onset - 1e-6
        )
        contained = (
            old_start is not None
            and old_stop is not None
            and old_start >= start_onset - 1e-6
            and old_stop <= end_onset + 1e-6
        )
        if overlaps and not contained:
            problems.append(f"{prefix}: existing tuplet crosses or is nested in the segment")


def _apply_tuplet(plan: dict) -> None:
    measure = plan["measure"]
    for forward in plan["forwards"]:
        measure.remove(forward)
    for group in plan["groups"]:
        for note in group:
            notations = note.find("notations")
            if notations is not None:
                for tuplet in list(notations.findall("tuplet")):
                    notations.remove(tuplet)
    for group, duration in zip(plan["groups"], plan["durations"]):
        for note in group:
            note.find("duration").text = str(duration)
            _set_time_modification(note, plan["actual"], plan["normal"])
    _append_tuplet(plan["groups"][0][0], "start")
    _append_tuplet(plan["groups"][-1][0], "stop")


def _set_time_modification(note, actual: int, normal: int) -> None:
    for existing in list(note.findall("time-modification")):
        note.remove(existing)
    modification = ElementTree.Element("time-modification")
    ElementTree.SubElement(modification, "actual-notes").text = str(actual)
    ElementTree.SubElement(modification, "normal-notes").text = str(normal)
    children = list(note)
    index = 0
    for candidate, child in enumerate(children):
        if child.tag in ("type", "dot", "accidental"):
            index = candidate + 1
    note.insert(index, modification)


def _append_tuplet(note, kind: str) -> None:
    notations = note.find("notations")
    if notations is None:
        notations = ElementTree.Element("notations")
        children = list(note)
        index = next(
            (candidate for candidate, child in enumerate(children) if child.tag in ("lyric", "play", "listen")),
            len(children),
        )
        note.insert(index, notations)
    ElementTree.SubElement(notations, "tuplet", {"type": kind})


def _positive_integer(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _alter(note) -> int | float:
    text = note.findtext("pitch/alter")
    try:
        value = float(text or 0)
    except ValueError:
        return 0
    return int(value) if value.is_integer() else value


def _pitch_name(note) -> str | None:
    step = note.findtext("pitch/step")
    octave = note.findtext("pitch/octave")
    if not step or not octave:
        return None
    alter = _alter(note)
    if isinstance(alter, int) and alter > 0:
        accidental = "#" * alter
    elif isinstance(alter, int) and alter < 0:
        accidental = "b" * -alter
    else:
        accidental = ""
    return f"{step}{accidental}{octave}"


def _integer_text(element, path: str) -> int | None:
    if element is None:
        return None
    text = element.findtext(path)
    try:
        return int(text) if text is not None else None
    except ValueError:
        return None


def _validate_clef(patch: dict, doc: Document | None, prefix: str) -> list[str]:
    problems: list[str] = []
    _part_id, part, part_problems = _resolve_patch_part(patch, doc, prefix)
    problems.extend(part_problems)
    measure_count = len(doc.part_measures(part)) if doc is not None and part is not None else None
    if not _positive_integer(patch.get("measure")):
        problems.append(f"{prefix}: measure must be a positive integer")
    elif measure_count is not None and patch["measure"] > measure_count:
        problems.append(f"{prefix}: measure exceeds {measure_count}")
    if not _positive_integer(patch.get("staff")):
        problems.append(f"{prefix}: staff must be a positive integer")
    if patch.get("clef") not in CLEF_SIGNS:
        problems.append(f"{prefix}: clef must be one of G/F/C")
    if not _positive_integer(patch.get("line")) or patch["line"] > 5:
        problems.append(f"{prefix}: line must be 1..5")
    if patch.get("status") != "accepted":
        problems.append(f"{prefix}: status must be accepted")
    from_measure = patch.get("from_measure")
    if from_measure is not None:
        if not _positive_integer(from_measure):
            problems.append(f"{prefix}: from_measure must be a positive integer")
        elif measure_count is not None and from_measure > measure_count:
            problems.append(f"{prefix}: from_measure exceeds {measure_count}")
        elif from_measure == patch.get("measure"):
            problems.append(f"{prefix}: from_measure must differ from measure")
    if not _positive_integer(patch.get("page")):
        problems.append(f"{prefix}: page must be a positive integer")
    if not (patch.get("bbox") or patch.get("crop")):
        problems.append(f"{prefix}: bbox or crop evidence is required")
    if not isinstance(patch.get("evidence"), str) or not patch["evidence"]:
        problems.append(f"{prefix}: evidence is required")
    return problems


def _apply_clef(doc: Document, patch: dict) -> int:
    _part_id, part, _problems = _resolve_patch_part(patch, doc, "clef")
    assert part is not None
    measures = doc.part_measures(part)
    staff = str(patch["staff"])
    changed = 0
    from_measure = patch.get("from_measure")
    if from_measure and 1 <= from_measure <= len(measures):
        # the source put the clef change on another measure; retire that copy first so the
        # redundant-clef pass does not have to guess which one is the real one
        changed += _remove_staff_clefs(measures[from_measure - 1], staff, sign=patch["clef"])
    target = measures[patch["measure"] - 1]
    sign = patch["clef"]
    line = str(patch["line"])
    existing = [clef for clef in target.iter("clef") if (clef.get("number") or "1") == staff]
    if existing:
        for clef in existing:
            if (clef.findtext("sign"), clef.findtext("line")) == (sign, line):
                continue
            for tag, value in (("sign", sign), ("line", line)):
                element = clef.find(tag)
                if element is None:
                    element = ElementTree.SubElement(clef, tag)
                element.text = value
            changed += 1
        return changed
    attributes = target.find("attributes")
    if attributes is None:
        attributes = ElementTree.Element("attributes")
        target.insert(0, attributes)
    clef = ElementTree.SubElement(attributes, "clef")
    if staff != "1":
        clef.set("number", staff)
    ElementTree.SubElement(clef, "sign").text = sign
    ElementTree.SubElement(clef, "line").text = line
    return changed + 1


def _remove_staff_clefs(measure, staff: str, sign: str | None = None) -> int:
    removed = 0
    for attributes in list(measure.findall("attributes")):
        for clef in list(attributes.findall("clef")):
            if (clef.get("number") or "1") != staff:
                continue
            if sign is not None and clef.findtext("sign") != sign:
                continue
            attributes.remove(clef)
            removed += 1
        if len(attributes) == 0:
            measure.remove(attributes)
    return removed


def list_clefs(doc: Document, part_id: str | None = None) -> list[dict]:
    """Read back the clefs so a review can compare them with the page."""
    result = []
    for current_part, _part, number, measure in doc.iter_part_measures():
        if part_id is not None and current_part != part_id:
            continue
        for clef in measure.iter("clef"):
            result.append(
                {
                    "part": current_part,
                    "measure": number,
                    "staff": clef.get("number") or "1",
                    "sign": clef.findtext("sign"),
                    "line": clef.findtext("line"),
                }
            )
    return result


def remove_octave_shifts(doc: Document, staff: str, part_id: str | None = None) -> int:
    """Remove all octave-shift directions on one staff; returns directions removed."""
    removed = 0
    for measure in doc.measures(part_id):
        for direction in list(measure.findall("direction")):
            if direction.find("direction-type/octave-shift") is None:
                continue
            if (direction.findtext("staff") or "1") != staff:
                continue
            measure.remove(direction)
            removed += 1
    return removed


def list_octave_shifts(doc: Document, part_id: str | None = None) -> list[dict]:
    """Read back the octave shifts so a review can compare them with the page."""
    result = []
    for current_part, _part, number, measure in doc.iter_part_measures():
        if part_id is not None and current_part != part_id:
            continue
        for direction in measure.findall("direction"):
            shift = direction.find("direction-type/octave-shift")
            if shift is None:
                continue
            result.append(
                {
                    "part": current_part,
                    "measure": number,
                    "staff": direction.findtext("staff") or "1",
                    "type": shift.get("type"),
                    "size": shift.get("size"),
                    "number": shift.get("number"),
                }
            )
    return result


def verify_patches(doc: Document, payload: dict) -> list[str]:
    """Check that applied patches still have their target notes/shifts after the pipeline."""
    problems: list[str] = []
    for index, patch in enumerate(payload.get("patches") or []):
        prefix = f"patches[{index}]"
        op = patch.get("op")
        part_id, part, part_problems = _resolve_patch_part(patch, doc, prefix)
        if part_problems or part is None:
            problems.extend(part_problems)
            continue
        if op == "ottava":
            if patch.get("mode") == "remove":
                continue
            shifts = list_octave_shifts(doc, part_id=part_id)
            staff = str(patch.get("staff"))
            expected_type = OTTAAVA_SUBTYPES.get(patch.get("subtype"))
            start_measure = (patch.get("start") or {}).get("measure")
            end_measure = (patch.get("end") or {}).get("measure")
            starts = [
                shift
                for shift in shifts
                if shift["staff"] == staff
                and shift["type"] == expected_type
                and shift["size"] == "8"
                and shift["measure"] == start_measure
            ]
            if not starts:
                problems.append(f"{prefix}: ottava start missing or has the wrong type/size/measure")
                continue
            if not any(
                any(
                    stop["staff"] == staff
                    and stop["type"] == "stop"
                    and stop["number"] == start["number"]
                    and stop["measure"] == end_measure
                    for stop in shifts
                )
                for start in starts
            ):
                problems.append(f"{prefix}: ottava stop missing or does not match its start")
            continue
        if op == "clef":
            clefs = list_clefs(doc, part_id=part_id)
            staff = str(patch.get("staff"))
            sign = patch.get("clef")
            line = str(patch.get("line"))
            if not any(
                clef["measure"] == patch.get("measure")
                and clef["staff"] == staff
                and clef["sign"] == sign
                and clef["line"] == line
                for clef in clefs
            ):
                problems.append(
                    f"{prefix}: clef {sign}/{line} missing at measure {patch.get('measure')} staff {staff}"
                )
            from_measure = patch.get("from_measure")
            if from_measure and any(
                clef["measure"] == from_measure and clef["staff"] == staff and clef["sign"] == sign
                for clef in clefs
            ):
                problems.append(f"{prefix}: the superseded clef at measure {from_measure} is still present")
            continue
        if op != "tuplet":
            problems.append(f"{prefix}: unsupported op {op!r}")
            continue
        measure_index = patch.get("measure")
        part_measures = doc.part_measures(part)
        if not isinstance(measure_index, int) or not 1 <= measure_index <= len(part_measures):
            problems.append(f"{prefix}: measure missing after pipeline")
            continue
        measure = part_measures[measure_index - 1]
        events = [
            event
            for event in doc.events(measure, doc.effective_divisions(measure, part))
            if event.staff == str(patch.get("staff")) and event.voice == patch.get("voice")
        ]
        for label in ("start", "end"):
            anchor = patch.get(label) or {}
            found = [
                event
                for event in events
                if _pitch_name(event.element) == anchor.get("pitch")
            ]
            if not found:
                problems.append(f"{prefix}: {label} anchor note missing after pipeline")
        start_events = [
            event
            for event in events
            if _pitch_name(event.element) == (patch.get("start") or {}).get("pitch")
        ]
        end_events = [
            event
            for event in events
            if _pitch_name(event.element) == (patch.get("end") or {}).get("pitch")
        ]
        if not start_events or not end_events:
            continue
        start = min(start_events, key=lambda event: event.onset)
        end = max(end_events, key=lambda event: event.onset)
        if end.onset <= start.onset - 1e-6:
            problems.append(f"{prefix}: end anchor is not after start after pipeline")
            continue
        selected = [
            event
            for event in events
            if start.onset - 1e-6 <= event.onset <= end.onset + 1e-6
        ]
        actual = patch.get("actual_notes")
        normal = patch.get("normal_notes")
        modified = [
            event
            for event in selected
            if (mod := event.element.find("time-modification")) is not None
            and mod.findtext("actual-notes") == str(actual)
            and mod.findtext("normal-notes") == str(normal)
        ]
        expected_count = int(patch.get("note_count") or 0)
        if len(modified) < expected_count:
            problems.append(
                f"{prefix}: tuplet notes lost after pipeline "
                f"({len(modified)}/{expected_count} remain)"
            )
        notations = [
            tuplet.get("type")
            for event in selected
            if (tuplet := event.element.find("notations/tuplet")) is not None
        ]
        if "start" not in notations or "stop" not in notations:
            problems.append(f"{prefix}: tuplet start/stop bracket missing after pipeline")
        span = float(patch.get("span_beats") or 0)
        selected_duration = sum(
            event.duration for event in selected if not event.chord and not event.rest
        )
        if span and abs(selected_duration - span) > 0.05:
            problems.append(
                f"{prefix}: tuplet span changed after pipeline "
                f"({selected_duration:g} vs {span:g} beats)"
            )
    return problems


def _insert_octave(measure, beat: float, staff: str, kind: str, direction: str, number: str, divisions: float) -> None:
    # 8vb is printed under the staff it lowers; keeping it "above" drew the bracket between the
    # staves (measured on the First Step delivery).
    placement = "below" if direction == "down" else "above"
    direction_element = ElementTree.Element("direction", {"placement": placement})
    direction_type = ElementTree.SubElement(direction_element, "direction-type")
    attributes = {"type": direction if kind == "start" else "stop", "number": number}
    if kind == "start":
        attributes["size"] = "8"
    ElementTree.SubElement(direction_type, "octave-shift", attributes)
    ElementTree.SubElement(direction_element, "staff").text = staff
    index = _insertion_index(measure, beat, staff, divisions)
    measure.insert(index, direction_element)


def _insertion_index(measure, beat: float, staff: str, divisions: float) -> int:
    target = beat * divisions
    cursor = 0.0
    previous = None
    children = list(measure)
    for index, child in enumerate(children):
        if child.tag in ("backup", "forward"):
            value = int(child.findtext("duration") or 0)
            cursor += -value if child.tag == "backup" else value
            previous = None
            continue
        if child.tag != "note":
            continue
        text = child.findtext("duration")
        if text is None:
            continue
        duration = int(text)
        chord = child.find("chord") is not None
        onset = previous if chord and previous is not None else cursor
        if not chord:
            cursor += duration
        previous = onset
        note_staff = child.findtext("staff") or "1"
        if note_staff == staff and onset >= target - 1e-6:
            return index
    return len(children)


def _next_octave_number(doc: Document, part_id: str | None = None) -> int:
    used = []
    scope = doc.part_by_id(part_id) if part_id is not None else doc.root
    for element in scope.iter("octave-shift"):
        value = element.get("number")
        if value and value.isdigit():
            used.append(int(value))
    return max(used, default=0) + 1
