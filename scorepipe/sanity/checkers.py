"""Reusable invariant checkers (returning plain strings) for single-pass sanity."""

from __future__ import annotations

from collections import Counter
from typing import Sequence

from ..core.document import Document
from ..core.invariants import VERIFIERS, chord_semantics, measure_lengths
from ..core.pass_base import Context
from .models import MeasureSnapshot, Snapshot, Verifier, _fmt
from .snapshot import _as_snapshot, diff_snapshots


def check_structure(doc: Document, ctx: Context) -> list[str]:
    """Chord/cursor sanity.

    ``invariants.chord_semantics`` already reports ``orphan-chord`` and
    ``negative-cursor``, so reusing it keeps this check identical to the
    pipeline verifier.
    """
    return [
        f"{violation.code} at {_where(violation.measure)}: {violation.detail}"
        for violation in chord_semantics(doc, ctx)
    ]


def check_measure_health_preserved(
    before_doc: Document, after_doc: Document, ctx: Context
) -> list[str]:
    """Fail on measure-length violations that did not exist before the pass."""
    before = Counter(
        (violation.code, violation.measure, violation.detail)
        for violation in measure_lengths(before_doc, ctx)
    )
    after = Counter(
        (violation.code, violation.measure, violation.detail)
        for violation in measure_lengths(after_doc, ctx)
    )
    new = after - before
    messages: list[str] = []
    for (code, measure, detail), count in sorted(
        new.items(), key=lambda item: _violation_sort_key(item[0])
    ):
        for _ in range(count):
            messages.append(f"new {code} at {_where(measure)}: {detail}")
    return messages


def check_no_new_verifier_violations(
    before_doc: Document,
    after_doc: Document,
    ctx: Context,
    verifiers: Sequence[Verifier] | None = None,
) -> list[str]:
    """Fail on a new or worsened verifier violation after the pass."""
    functions = tuple(VERIFIERS) if verifiers is None else tuple(verifiers)
    before_counts = Counter(
        (violation.code, violation.measure, violation.detail, getattr(verifier, "__name__", ""))
        for verifier in functions
        for violation in verifier(before_doc, ctx)
    )
    messages: list[str] = []
    for verifier in functions:
        name = getattr(verifier, "__name__", type(verifier).__name__)
        for violation in verifier(after_doc, ctx):
            key = (violation.code, violation.measure, violation.detail, name)
            if before_counts[key] > 0:
                before_counts[key] -= 1
                continue
            messages.append(
                f"{name}: new {violation.code} at {_where(violation.measure)}: "
                f"{violation.detail}"
            )
    return messages


def check_note_inventory_preserved(
    before: Snapshot | Document, after: Snapshot | Document
) -> list[str]:
    """Compare the pitched-note multiset per measure (staff/voice/onset ignored)."""
    before_snapshot = _as_snapshot(before)
    after_snapshot = _as_snapshot(after)
    before_counts = Counter(
        (note.measure, note.pitch)
        for note in before_snapshot.notes
        if note.pitched and note.pitch is not None
    )
    after_counts = Counter(
        (note.measure, note.pitch)
        for note in after_snapshot.notes
        if note.pitched and note.pitch is not None
    )
    messages: list[str] = []
    for (measure, pitch), count in sorted((after_counts - before_counts).items()):
        messages.append(f"m{measure} {pitch}: {count} pitched note(s) added")
    for (measure, pitch), count in sorted((before_counts - after_counts).items()):
        messages.append(f"m{measure} {pitch}: {count} pitched note(s) removed")
    return messages


def check_onsets_preserved(before: Snapshot | Document, after: Snapshot | Document) -> list[str]:
    """Report every surviving pitched occurrence whose onset changed."""
    diff = diff_snapshots(_as_snapshot(before), _as_snapshot(after))
    return [change.describe() for change in diff.moved_onsets if change.pitched]


def check_pitch_set_preserved(before: Snapshot | Document, after: Snapshot | Document) -> list[str]:
    """No unique (measure, staff, pitch) may disappear, whatever the note-level contract says.

    Removing a duplicated pitch is fine; deleting the only occurrence of a sounding pitch is not.
    This catches a rebuild that drops a sustained chord while a permissive "may remove notes"
    contract would otherwise let it pass.
    """
    before_snapshot = _as_snapshot(before)
    after_snapshot = _as_snapshot(after)
    before_pitches = {
        (note.measure, note.staff, note.pitch) for note in before_snapshot.notes if note.pitched
    }
    after_pitches = {
        (note.measure, note.staff, note.pitch) for note in after_snapshot.notes if note.pitched
    }
    return [
        f"pitch disappeared: m{measure} staff {staff} {pitch}"
        for measure, staff, pitch in sorted(before_pitches - after_pitches)
    ]


def check_sounding_notes_preserved(
    before: Snapshot | Document,
    after: Snapshot | Document,
    *,
    allow_measure_removal: bool = False,
) -> list[str]:
    """Every pitched note that sounds in a measure must still sound in that measure.

    This is the global invariant of the sanity flow: no pass may make music disappear.  The
    comparison is a *set* per ``(measure, staff, pitch)`` so that removing one of two identical
    occurrences (a duplicate that sounds at the same time and pitch) is not a loss, and retiming
    or re-voicing a surviving note is still allowed.

    ``allow_measure_removal`` skips measures that the pass deleted outright; a measure removal is
    a declared contract dimension, and its notes go with it.  A pass that moves a note *into
    another measure* must declare ``allows_relocate_notes`` and is checked by
    :func:`check_piece_pitch_set_preserved` instead.
    """
    before_snapshot = _as_snapshot(before)
    after_snapshot = _as_snapshot(after)
    after_numbers = {measure.number for measure in after_snapshot.measures}
    messages: list[str] = []

    for measure in before_snapshot.measures:
        if allow_measure_removal and measure.number not in after_numbers:
            continue
        before_index = _sounding_index(measure)
        after_measure = next(
            (candidate for candidate in after_snapshot.measures if candidate.number == measure.number),
            None,
        )
        after_index = {} if after_measure is None else _sounding_index(after_measure)
        for (staff, pitch), (onset, duration) in sorted(before_index.items()):
            if (staff, pitch) in after_index:
                continue
            messages.append(
                f"m{measure.number} staff {staff} {pitch} at {_fmt(onset)} "
                f"(duration {_fmt(duration)}): sounding note lost"
            )
    return messages


def check_piece_pitch_set_preserved(
    before: Snapshot | Document, after: Snapshot | Document
) -> list[str]:
    """Whole-piece version of :func:`check_sounding_notes_preserved` for relocating passes.

    A pass that may move a note between measures (``rebase_measures``, overflow dedupe) cannot
    be held to the per-measure set, but a pitch that disappears from the entire piece is still
    a loss.
    """
    before_snapshot = _as_snapshot(before)
    after_snapshot = _as_snapshot(after)
    before_pitches = {
        (note.staff, note.pitch)
        for measure in before_snapshot.measures
        for note in measure.notes
        if note.pitched and note.pitch is not None
    }
    after_pitches = {
        (note.staff, note.pitch)
        for measure in after_snapshot.measures
        for note in measure.notes
        if note.pitched and note.pitch is not None
    }
    return [
        f"staff {staff} {pitch}: sounding note lost from the whole piece"
        for staff, pitch in sorted(before_pitches - after_pitches)
    ]


def check_mscx_pitched_notes_preserved(before, after) -> list[str]:
    """The display-phase twin: no ``<Chord><Note><pitch>`` may disappear from a measure.

    Display passes drop rests, text objects and empty voices; they may never take a chord with
    them.  Rests are not counted, so "remove a padding rest" stays legal.
    """
    before_keys = _mscx_pitch_keys(before)
    after_keys = _mscx_pitch_keys(after)
    return [
        f"staff {staff} m{number} pitch {pitch}: chord note lost"
        for staff, number, pitch in sorted(before_keys - after_keys)
    ]


def _mscx_pitch_keys(doc) -> set[tuple[str, int, str]]:
    keys: set[tuple[str, int, str]] = set()
    for staff, number, measure in doc.iter_measures():
        staff_id = staff.get("id") or "?"
        for note in measure.iter("Note"):
            pitch = note.findtext("pitch")
            if pitch:
                keys.add((staff_id, number, pitch.strip()))
    return keys


def _sounding_index(measure: MeasureSnapshot) -> dict[tuple[str, str], tuple[float, float]]:
    """``(staff, pitch) -> (onset, duration)`` for the pitched notes of one measure.

    The identity is the pitch on the staff, so a note that keeps sounding but moves within the
    measure is not a loss; onset/duration are recorded only to name the note in a message (the
    earliest onset wins when a pitch sounds more than once).
    """
    index: dict[tuple[str, str], tuple[float, float]] = {}
    for note in measure.notes:
        if not note.pitched or note.pitch is None:
            continue
        identity = (note.staff, note.pitch)
        geometry = (round(note.onset, 6), round(note.duration, 6))
        current = index.get(identity)
        if current is None or geometry[0] < current[0]:
            index[identity] = geometry
    return index


def check_idempotent(pass_obj, doc: Document, ctx: Context) -> list[str]:
    """Run a pass twice; the second run must change neither the counter nor the state hash."""
    name = _pass_name(pass_obj)
    first = pass_obj.run(doc, ctx)
    after_first = doc.state_hash()
    second = pass_obj.run(doc, ctx)
    after_second = doc.state_hash()
    if second.changed != 0 or after_second != after_first:
        return [
            f"pass {name} is not idempotent: second run changed {second.changed}, "
            f"state moved={after_second != after_first} (first run changed {first.changed})"
        ]
    return []


def _pass_name(pass_obj) -> str:
    spec = getattr(pass_obj, "spec", None)
    name = getattr(spec, "name", None)
    return name or type(pass_obj).__name__


def _where(measure: int | None) -> str:
    return "score" if measure is None else f"m{measure}"


def _violation_sort_key(key: tuple[str, int | None, str]) -> tuple:
    code, measure, detail = key
    return (measure is None, measure if measure is not None else 0, code, detail)
