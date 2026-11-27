"""Constrained tuplet notation patch validation, application, and verification."""

from __future__ import annotations

import math
from fractions import Fraction
from xml.etree import ElementTree

from ..core.document import Document
from .common import NOTE_TYPE_BEATS, _pitch_name, _positive_integer, _resolve_patch_part


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


def _verify_tuplet(doc: Document, patch: dict, prefix: str) -> list[str]:
    _part_id, part, part_problems = _resolve_patch_part(patch, doc, prefix)
    if part_problems or part is None:
        return part_problems
    problems: list[str] = []
    measure_index = patch.get("measure")
    part_measures = doc.part_measures(part)
    if not isinstance(measure_index, int) or not 1 <= measure_index <= len(part_measures):
        return [f"{prefix}: measure missing after pipeline"]
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
        return problems
    start = min(start_events, key=lambda event: event.onset)
    end = max(end_events, key=lambda event: event.onset)
    if end.onset <= start.onset - 1e-6:
        problems.append(f"{prefix}: end anchor is not after start after pipeline")
        return problems
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
