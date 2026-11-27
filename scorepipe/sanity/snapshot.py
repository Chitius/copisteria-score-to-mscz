"""Score snapshotting and staged note-level diffing."""

from __future__ import annotations

from collections import defaultdict
from typing import Callable, Sequence

from ..core.document import Document
from .models import (
    ADDED,
    CHANGED_IDENTITY,
    CHANGED_PITCH,
    MOVED,
    REMOVED,
    RETIMED,
    MeasureSnapshot,
    NoteChange,
    NoteSnapshot,
    SanityDiff,
    Snapshot,
    VoiceCountChange,
    _close,
    _pitch_key,
)


def snapshot(doc: Document) -> Snapshot:
    """Freeze the note-level state of ``doc`` into hashable/immutable dataclasses."""
    measures: list[MeasureSnapshot] = []
    for part_id, part, fallback, measure in doc.iter_part_measures():
        number = _measure_number(measure, fallback)
        notes: list[NoteSnapshot] = []
        for event in doc.events(measure, doc.effective_divisions(measure, part)):
            element = event.element
            rest = event.rest
            step = None if rest else element.findtext("pitch/step")
            alter = None if rest else _parse_alter(element.findtext("pitch/alter"))
            octave = None if rest else _parse_octave(element.findtext("pitch/octave"))
            tie_types = {tie.get("type") for tie in element.findall("tie")}
            tied_types = {tied.get("type") for tied in element.findall("notations/tied")}
            tie_types.update(tied_types)
            notes.append(
                NoteSnapshot(
                    measure=number,
                    staff=event.staff,
                    voice=event.voice,
                    rest=rest,
                    step=step,
                    alter=alter,
                    octave=octave,
                    onset=event.onset,
                    duration=event.duration,
                    chord=event.chord,
                    type=element.findtext("type"),
                    tie_start="start" in tie_types,
                    tie_stop="stop" in tie_types,
                    part=part_id,
                )
            )
        measures.append(
            MeasureSnapshot(
                number=number,
                time_signature=doc.time_signature(measure),
                notes=tuple(notes),
                part=part_id,
            )
        )
    return Snapshot(
        tuple(measures),
        tuple(dict.fromkeys(measure.number for measure in measures)),
    )


def diff_snapshots(before: Snapshot, after: Snapshot) -> SanityDiff:
    """Match note occurrences in the two snapshots and describe the differences.

    Matching is deliberately staged so a single edit is named, not counted as a
    remove+add: same slot first, then same pitch (onset moved), then same onset
    (pitch changed).  Whatever remains is a genuine addition or removal.
    """
    diff = SanityDiff()
    before_by = before.by_part_number()
    after_by = after.by_part_number()
    before_keys = set(before_by)
    after_keys = set(after_by)

    diff.added_measures = sorted({number for _part, number in (after_keys - before_keys)})
    diff.removed_measures = sorted({number for _part, number in (before_keys - after_keys)})

    for key in sorted(before_keys & after_keys):
        _part, number = key
        _diff_measure(number, before_by[key].notes, after_by[key].notes, diff)
        _diff_voice_counts(before_by[key], after_by[key], diff)

    return diff


def _diff_measure(
    number: int,
    before_notes: Sequence[NoteSnapshot],
    after_notes: Sequence[NoteSnapshot],
    diff: SanityDiff,
) -> None:
    matched_before = [False] * len(before_notes)
    matched_after = [False] * len(after_notes)

    stages = (
        # Same staff/voice/pitch/onset: only duration can differ.
        (
            lambda note: (
                note.staff,
                note.voice,
                note.rest,
                _pitch_key(note),
                round(note.onset, 6),
            ),
            lambda before, after: abs(before.duration - after.duration),
            None,
        ),
        # Same staff/voice/pitch but another onset.
        (
            lambda note: (note.staff, note.voice, note.rest, _pitch_key(note)),
            lambda before, after: (
                abs(before.onset - after.onset),
                abs(before.duration - after.duration),
            ),
            None,
        ),
        # Same pitch and onset, but moved to another staff/voice.
        (
            lambda note: (note.rest, _pitch_key(note), round(note.onset, 6)),
            lambda before, after: 0.0,
            None,
        ),
        # Same pitch, moved to another staff/voice and/or onset.
        (
            lambda note: (note.rest, _pitch_key(note)),
            lambda before, after: (
                abs(before.onset - after.onset),
                abs(before.duration - after.duration),
            ),
            None,
        ),
        # Same slot but a different pitch.
        (
            lambda note: (note.staff, note.voice, round(note.onset, 6)),
            lambda before, after: 0.0,
            lambda before, after: before.pitched and after.pitched,
        ),
    )

    for key, score, accept in stages:
        for before_index, after_index in _pair_stage(
            before_notes, after_notes, matched_before, matched_after, key, score, accept
        ):
            _record_pair(diff, number, before_notes[before_index], after_notes[after_index])

    for index, note in enumerate(before_notes):
        if not matched_before[index]:
            diff.removed_notes.append(NoteChange(REMOVED, number, before=note))
    for index, note in enumerate(after_notes):
        if not matched_after[index]:
            diff.added_notes.append(NoteChange(ADDED, number, after=note))


def _pair_stage(
    before_notes: Sequence[NoteSnapshot],
    after_notes: Sequence[NoteSnapshot],
    matched_before: list[bool],
    matched_after: list[bool],
    key: Callable[[NoteSnapshot], object],
    score: Callable[[NoteSnapshot, NoteSnapshot], object],
    accept: Callable[[NoteSnapshot, NoteSnapshot], bool] | None,
) -> list[tuple[int, int]]:
    """Greedily pair open notes that share ``key``, preferring the closest score."""
    groups: dict[object, list[int]] = defaultdict(list)
    for index, note in enumerate(after_notes):
        if not matched_after[index]:
            groups[key(note)].append(index)

    pairs: list[tuple[int, int]] = []
    for before_index, note in enumerate(before_notes):
        if matched_before[before_index]:
            continue
        candidates = groups.get(key(note))
        if not candidates:
            continue
        open_candidates = [
            after_index
            for after_index in candidates
            if not matched_after[after_index]
            and (accept is None or accept(note, after_notes[after_index]))
        ]
        if not open_candidates:
            continue
        best = min(open_candidates, key=lambda index: score(note, after_notes[index]))
        matched_before[before_index] = True
        matched_after[best] = True
        pairs.append((before_index, best))
    return pairs


def _record_pair(
    diff: SanityDiff, number: int, before: NoteSnapshot, after: NoteSnapshot
) -> None:
    same_slot = (
        before.staff == after.staff
        and before.voice == after.voice
        and _close(before.onset, after.onset)
    )
    if (before.pitched or after.pitched) and not same_slot:
        diff.same_note_identity = False
    if before.staff != after.staff or before.voice != after.voice:
        diff.identity_changes.append(NoteChange(CHANGED_IDENTITY, number, before, after))
    if not _close(before.onset, after.onset):
        diff.moved_onsets.append(NoteChange(MOVED, number, before, after))
    if not _close(before.duration, after.duration):
        diff.retimed_notes.append(NoteChange(RETIMED, number, before, after))
    if _pitch_key(before) != _pitch_key(after):
        diff.changed_pitches.append(NoteChange(CHANGED_PITCH, number, before, after))


def _diff_voice_counts(
    before: MeasureSnapshot, after: MeasureSnapshot, diff: SanityDiff
) -> None:
    before_counts: dict[str, set[str]] = defaultdict(set)
    after_counts: dict[str, set[str]] = defaultdict(set)
    for note in before.notes:
        before_counts[note.staff].add(note.voice)
    for note in after.notes:
        after_counts[note.staff].add(note.voice)
    for staff in sorted(set(before_counts) | set(after_counts)):
        old = len(before_counts.get(staff, ()))
        new = len(after_counts.get(staff, ()))
        if old != new:
            diff.voice_count_changes.append(VoiceCountChange(before.number, staff, old, new))


def _as_snapshot(value: Snapshot | Document) -> Snapshot:
    return value if isinstance(value, Snapshot) else snapshot(value)


def _measure_number(measure, fallback: int) -> int:
    raw = measure.get("number")
    if raw is not None:
        text = raw.strip()
        try:
            return int(text)
        except ValueError:
            digits = "".join(character for character in text if character.isdigit())
            if digits:
                try:
                    return int(digits)
                except ValueError:
                    pass
    return fallback


def _parse_alter(text: str | None) -> float | None:
    if text is None or not text.strip():
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_octave(text: str | None) -> int | None:
    if text is None or not text.strip():
        return None
    try:
        return int(text)
    except ValueError:
        return None
