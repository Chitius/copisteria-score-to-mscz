"""Reusable sanity checks and behaviour contracts for single passes.

A pass has a declared contract (what it may change) and an implicit one (it must be
idempotent).  This module makes both testable without touching the pipeline:

* :func:`snapshot` freezes the note-level view of a document.
* :func:`diff_snapshots` reports note/measure effects in a structured form.
* :class:`PassContract` turns "this pass may not add notes" into a list of messages.
* the ``check_*`` functions report plain strings, so pytest assertions stay simple.
* :func:`run_contract` wires everything together on *fresh* copies of a document,
  which keeps one test from contaminating the next.

Only the standard library is used.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Callable, Sequence

from .core.document import Document
from .core.invariants import VERIFIERS, chord_semantics, measure_lengths
from .core.pass_base import Context

_EPS = 1e-6

# NoteChange kinds.  They are plain strings so a failing test reads well.
ADDED = "added"
REMOVED = "removed"
MOVED = "moved"
RETIMED = "retimed"
CHANGED_PITCH = "changed-pitch"
CHANGED_IDENTITY = "changed-identity"

Verifier = Callable[[Document, Context], list]
DocFactory = Callable[[], Document]


# ---------------------------------------------------------------------------
# value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NoteSnapshot:
    """One note/rest occurrence, normalised to beats and measure number."""

    measure: int
    staff: str
    voice: str
    rest: bool
    step: str | None
    alter: float | None
    octave: int | None
    onset: float
    duration: float
    chord: bool
    type: str | None
    tie_start: bool
    tie_stop: bool

    @property
    def pitched(self) -> bool:
        return not self.rest and self.step is not None

    @property
    def pitch(self) -> str | None:
        """``C#4``-style name, or ``None`` for a rest/unpitched note."""
        if not self.pitched:
            return None
        return _pitch_name(self.step, self.alter, self.octave)

    def describe(self) -> str:
        label = self.pitch or ("rest" if self.rest else "unpitched")
        return (
            f"m{self.measure} staff {self.staff} voice {self.voice} {label} "
            f"at {_fmt(self.onset)} (duration {_fmt(self.duration)})"
        )


@dataclass(frozen=True)
class MeasureSnapshot:
    """The notes of one measure plus the time signature declared in that measure."""

    number: int
    time_signature: tuple[float, float] | None
    notes: tuple[NoteSnapshot, ...] = ()

    @property
    def voice_count(self) -> int:
        return len({(note.staff, note.voice) for note in self.notes})


@dataclass(frozen=True)
class Snapshot:
    """An ordered score snapshot keyed by integer measure number."""

    measures: tuple[MeasureSnapshot, ...] = ()
    measure_numbers: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if not self.measure_numbers:
            object.__setattr__(
                self, "measure_numbers", tuple(measure.number for measure in self.measures)
            )

    @property
    def notes(self) -> tuple[NoteSnapshot, ...]:
        return tuple(note for measure in self.measures for note in measure.notes)

    def measure(self, number: int) -> MeasureSnapshot:
        for measure in self.measures:
            if measure.number == number:
                return measure
        raise KeyError(number)

    def by_number(self) -> dict[int, MeasureSnapshot]:
        return {measure.number: measure for measure in self.measures}


@dataclass(frozen=True)
class NoteChange:
    """One diffed note occurrence.  ``before``/``after`` is ``None`` for add/remove."""

    kind: str
    measure: int
    before: NoteSnapshot | None = None
    after: NoteSnapshot | None = None

    @property
    def staff(self) -> str:
        reference = self.before or self.after
        assert reference is not None
        return reference.staff

    @property
    def voice(self) -> str:
        reference = self.before or self.after
        assert reference is not None
        return reference.voice

    @property
    def pitch(self) -> str | None:
        after = self.after
        before = self.before
        if after is not None and after.pitch is not None:
            return after.pitch
        return before.pitch if before is not None else None

    @property
    def pitched(self) -> bool:
        return bool(
            (self.before is not None and self.before.pitched)
            or (self.after is not None and self.after.pitched)
        )

    def describe(self) -> str:
        prefix = f"m{self.measure} staff {self.staff} voice {self.voice}"
        if self.kind == ADDED:
            note = self.after
            assert note is not None
            return (
                f"{prefix}: added {_note_label(note)} at {_fmt(note.onset)} "
                f"(duration {_fmt(note.duration)})"
            )
        if self.kind == REMOVED:
            note = self.before
            assert note is not None
            return (
                f"{prefix}: removed {_note_label(note)} at {_fmt(note.onset)} "
                f"(duration {_fmt(note.duration)})"
            )
        before = self.before
        after = self.after
        assert before is not None and after is not None
        if self.kind == MOVED:
            return (
                f"{prefix} {_note_label(before)}: "
                f"onset {_fmt(before.onset)} -> {_fmt(after.onset)}"
            )
        if self.kind == RETIMED:
            return (
                f"{prefix} {_note_label(before)}: "
                f"duration {_fmt(before.duration)} -> {_fmt(after.duration)}"
            )
        if self.kind == CHANGED_PITCH:
            return (
                f"{prefix}: pitch {_note_label(before)} -> {_note_label(after)} "
                f"at {_fmt(after.onset)}"
            )
        if self.kind == CHANGED_IDENTITY:
            return (
                f"{prefix} {_note_label(before)}: staff/voice "
                f"{before.staff}/{before.voice} -> {after.staff}/{after.voice} "
                f"at onset {_fmt(after.onset)}"
            )
        return f"{prefix}: {self.kind}"


@dataclass(frozen=True)
class VoiceCountChange:
    """A change in the number of distinct voices on one staff of one measure."""

    measure: int
    staff: str
    old: int
    new: int

    def describe(self) -> str:
        return f"m{self.measure} staff {self.staff}: voice count {self.old} -> {self.new}"


@dataclass
class SanityDiff:
    """Every observable note/measure effect between two snapshots."""

    added_notes: list[NoteChange] = field(default_factory=list)
    removed_notes: list[NoteChange] = field(default_factory=list)
    moved_onsets: list[NoteChange] = field(default_factory=list)
    retimed_notes: list[NoteChange] = field(default_factory=list)
    changed_pitches: list[NoteChange] = field(default_factory=list)
    identity_changes: list[NoteChange] = field(default_factory=list)
    added_measures: list[int] = field(default_factory=list)
    removed_measures: list[int] = field(default_factory=list)
    voice_count_changes: list[VoiceCountChange] = field(default_factory=list)
    same_note_identity: bool = True

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.added_notes,
                self.removed_notes,
                self.moved_onsets,
                self.retimed_notes,
                self.changed_pitches,
                self.identity_changes,
                self.added_measures,
                self.removed_measures,
                self.voice_count_changes,
            )
        )

    @property
    def total_changes(self) -> int:
        return sum(
            len(items)
            for items in (
                self.added_notes,
                self.removed_notes,
                self.moved_onsets,
                self.retimed_notes,
                self.changed_pitches,
                self.identity_changes,
                self.added_measures,
                self.removed_measures,
                self.voice_count_changes,
            )
        )


# ---------------------------------------------------------------------------
# snapshotting and diffing
# ---------------------------------------------------------------------------


def snapshot(doc: Document) -> Snapshot:
    """Freeze the note-level state of ``doc`` into hashable/immutable dataclasses."""
    measures: list[MeasureSnapshot] = []
    for fallback, measure in doc.iter_measures():
        number = _measure_number(measure, fallback)
        notes: list[NoteSnapshot] = []
        for event in doc.events(measure):
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
                )
            )
        measures.append(
            MeasureSnapshot(
                number=number,
                time_signature=doc.time_signature(measure),
                notes=tuple(notes),
            )
        )
    return Snapshot(tuple(measures), tuple(measure.number for measure in measures))


def diff_snapshots(before: Snapshot, after: Snapshot) -> SanityDiff:
    """Match note occurrences in the two snapshots and describe the differences.

    Matching is deliberately staged so a single edit is named, not counted as a
    remove+add: same slot first, then same pitch (onset moved), then same onset
    (pitch changed).  Whatever remains is a genuine addition or removal.
    """
    diff = SanityDiff()
    before_by = before.by_number()
    after_by = after.by_number()
    before_numbers = set(before_by)
    after_numbers = set(after_by)

    diff.added_measures = sorted(after_numbers - before_numbers)
    diff.removed_measures = sorted(before_numbers - after_numbers)

    for number in sorted(before_numbers & after_numbers):
        _diff_measure(number, before_by[number].notes, after_by[number].notes, diff)
        _diff_voice_counts(before_by[number], after_by[number], diff)

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


# ---------------------------------------------------------------------------
# contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PassContract:
    """What a pass is allowed to change.  ``violations`` reports everything else."""

    name: str
    allows_add_notes: bool = False
    allows_remove_notes: bool = False
    allows_move_onsets: bool = False
    allows_retime: bool = False
    allows_change_pitch: bool = False
    allows_add_or_remove_measures: bool = False
    allows_voice_changes: bool = False

    def violations(self, before: Snapshot | Document, after: Snapshot | Document) -> list[str]:
        before_snapshot = _as_snapshot(before)
        after_snapshot = _as_snapshot(after)
        diff = diff_snapshots(before_snapshot, after_snapshot)
        messages: list[str] = []

        if not self.allows_add_notes:
            messages.extend(f"{self.name}: {change.describe()}" for change in diff.added_notes)
        if not self.allows_remove_notes:
            messages.extend(
                f"{self.name}: {change.describe()}" for change in diff.removed_notes
            )
        if not self.allows_move_onsets:
            messages.extend(
                f"{self.name}: {change.describe()}" for change in diff.moved_onsets
            )
        if not self.allows_retime:
            messages.extend(
                f"{self.name}: {change.describe()}" for change in diff.retimed_notes
            )
        if not self.allows_change_pitch:
            messages.extend(
                f"{self.name}: {change.describe()}" for change in diff.changed_pitches
            )
        if not self.allows_add_or_remove_measures:
            messages.extend(
                f"{self.name}: m{number} added" for number in diff.added_measures
            )
            messages.extend(
                f"{self.name}: m{number} removed" for number in diff.removed_measures
            )
        if not self.allows_voice_changes:
            messages.extend(
                f"{self.name}: {change.describe()}" for change in diff.identity_changes
            )
            messages.extend(
                f"{self.name}: {change.describe()}"
                for change in diff.voice_count_changes
            )
        return messages


# ---------------------------------------------------------------------------
# checkers (plain strings, never Violation objects)
# ---------------------------------------------------------------------------


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
    """Fail on a ``(code, measure)`` verifier violation that is new after the pass."""
    functions = tuple(VERIFIERS) if verifiers is None else tuple(verifiers)
    before_keys = {
        (violation.code, violation.measure)
        for verifier in functions
        for violation in verifier(before_doc, ctx)
    }
    messages: list[str] = []
    for verifier in functions:
        name = getattr(verifier, "__name__", type(verifier).__name__)
        for violation in verifier(after_doc, ctx):
            if (violation.code, violation.measure) in before_keys:
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


def check_idempotent(pass_obj, doc: Document, ctx: Context) -> list[str]:
    """Run a pass twice on the same document; the second run must be a no-op."""
    name = _pass_name(pass_obj)
    first = pass_obj.run(doc, ctx)
    second = pass_obj.run(doc, ctx)
    if second.changed != 0:
        return [
            f"pass {name} is not idempotent: second run changed {second.changed} "
            f"(first run changed {first.changed})"
        ]
    return []


# ---------------------------------------------------------------------------
# contract runner
# ---------------------------------------------------------------------------


@dataclass
class SanityReport:
    """The result of :func:`run_contract`."""

    pass_name: str
    contract_violations: list[str] = field(default_factory=list)
    checker_violations: list[str] = field(default_factory=list)
    idempotent: bool = True
    changed: int = 0

    @property
    def ok(self) -> bool:
        return not self.contract_violations and not self.checker_violations and self.idempotent

    def messages(self) -> list[str]:
        return [*self.contract_violations, *self.checker_violations]


def run_contract(
    pass_obj,
    doc_factory: DocFactory,
    contract: PassContract,
    ctx: Context | None = None,
) -> SanityReport:
    """Exercise one pass against one contract on isolated document copies.

    ``doc_factory`` must return a fresh :class:`Document` on every call.  Three
    copies are used: before, after (the pass runs here) and idempotence.  The
    inventory/onset checkers are intentionally not part of ``checker_violations``;
    they are contract dimensions, so a contract that allows adding notes stays
    usable.
    """
    context = Context() if ctx is None else ctx
    name = _pass_name(pass_obj)

    before_doc = doc_factory()
    after_doc = doc_factory()
    before_snapshot = snapshot(before_doc)

    result = pass_obj.run(after_doc, context)
    after_snapshot = snapshot(after_doc)

    contract_violations = contract.violations(before_snapshot, after_snapshot)

    checker_violations: list[str] = []
    checker_violations.extend(check_structure(after_doc, context))
    checker_violations.extend(check_measure_health_preserved(before_doc, after_doc, context))
    checker_violations.extend(
        check_no_new_verifier_violations(before_doc, after_doc, context)
    )

    idempotence_doc = doc_factory()
    idempotence_violations = check_idempotent(pass_obj, idempotence_doc, context)
    checker_violations.extend(idempotence_violations)

    return SanityReport(
        pass_name=name,
        contract_violations=contract_violations,
        checker_violations=checker_violations,
        idempotent=not idempotence_violations,
        changed=result.changed,
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _as_snapshot(value: Snapshot | Document) -> Snapshot:
    return value if isinstance(value, Snapshot) else snapshot(value)


def _pass_name(pass_obj) -> str:
    spec = getattr(pass_obj, "spec", None)
    name = getattr(spec, "name", None)
    return name or type(pass_obj).__name__


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


def _pitch_key(note: NoteSnapshot) -> tuple[str, float, int | None] | None:
    if not note.pitched:
        return None
    return (note.step or "", round(float(note.alter or 0.0), 6), note.octave)


def _pitch_name(step: str | None, alter: float | None, octave: int | None) -> str | None:
    if step is None:
        return None
    suffix = ""
    if alter:
        accidental = {
            1.0: "#",
            2.0: "##",
            -1.0: "b",
            -2.0: "bb",
        }.get(float(alter))
        suffix = accidental if accidental is not None else f"{float(alter):+g}"
    octave_text = "" if octave is None else str(octave)
    return f"{step}{suffix}{octave_text}"


def _note_label(note: NoteSnapshot) -> str:
    return note.pitch or ("rest" if note.rest else "unpitched")


def _fmt(value: float) -> str:
    return f"{value:g}"


def _close(left: float, right: float) -> bool:
    return abs(left - right) <= _EPS


def _where(measure: int | None) -> str:
    return "score" if measure is None else f"m{measure}"


def _violation_sort_key(key: tuple[str, int | None, str]) -> tuple:
    code, measure, detail = key
    return (measure is None, measure if measure is not None else 0, code, detail)


__all__ = [
    "ADDED",
    "REMOVED",
    "MOVED",
    "RETIMED",
    "CHANGED_PITCH",
    "CHANGED_IDENTITY",
    "NoteSnapshot",
    "MeasureSnapshot",
    "Snapshot",
    "NoteChange",
    "VoiceCountChange",
    "SanityDiff",
    "PassContract",
    "SanityReport",
    "snapshot",
    "diff_snapshots",
    "check_structure",
    "check_measure_health_preserved",
    "check_no_new_verifier_violations",
    "check_note_inventory_preserved",
    "check_onsets_preserved",
    "check_idempotent",
    "run_contract",
]
