"""Value objects, diff types, and formatting helpers for pass sanity checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..core.document import Document
from ..core.pass_base import Context

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
    part: str = "P1"

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
    part: str = "P1"

    @property
    def voice_count(self) -> int:
        return len({(note.staff, note.voice) for note in self.notes})


@dataclass(frozen=True)
class Snapshot:
    """An ordered score snapshot keyed by integer measure number (and part for multi-part)."""

    measures: tuple[MeasureSnapshot, ...] = ()
    measure_numbers: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if not self.measure_numbers:
            object.__setattr__(
                self,
                "measure_numbers",
                tuple(dict.fromkeys(measure.number for measure in self.measures)),
            )

    @property
    def notes(self) -> tuple[NoteSnapshot, ...]:
        return tuple(note for measure in self.measures for note in measure.notes)

    def measure(self, number: int, part: str | None = None) -> MeasureSnapshot:
        for measure in self.measures:
            if measure.number == number and (part is None or measure.part == part):
                return measure
        raise KeyError(number)

    def by_number(self) -> dict[int, MeasureSnapshot]:
        return {measure.number: measure for measure in self.measures}

    def by_part_number(self) -> dict[tuple[str, int], MeasureSnapshot]:
        return {(measure.part, measure.number): measure for measure in self.measures}


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
