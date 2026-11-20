"""Read-only invariant checks. A verifier never mutates the document."""

from __future__ import annotations

from dataclasses import dataclass

from .document import Document
from .pass_base import Context


@dataclass(frozen=True)
class Violation:
    code: str
    measure: int | None
    detail: str


def duplicate_ties(doc: Document, ctx: Context) -> list[Violation]:
    out: list[Violation] = []
    for number, measure in doc.iter_measures():
        for note in measure.iter("note"):
            kinds = [tie.get("type") for tie in note.findall("tie")]
            for kind in ("start", "stop"):
                if kinds.count(kind) > 1:
                    out.append(Violation("duplicate-tie", number, f"{kinds.count(kind)}x tie {kind}"))
        for note in measure.iter("note"):
            kinds = [tied.get("type") for tied in note.findall("notations/tied")]
            for kind in ("start", "stop"):
                if kinds.count(kind) > 1:
                    out.append(Violation("duplicate-tied", number, f"{kinds.count(kind)}x tied {kind}"))
    return out


def redundant_time_signatures(doc: Document, ctx: Context) -> list[Violation]:
    out: list[Violation] = []
    current = None
    for number, measure in doc.iter_measures():
        signature = doc.time_signature(measure)
        if signature is None:
            continue
        if signature == current:
            out.append(Violation("redundant-time", number, f"repeats {signature[0]}/{signature[1]}"))
        current = signature
    return out


def hidden_rests(doc: Document, ctx: Context) -> list[Violation]:
    out: list[Violation] = []
    for number, measure in doc.iter_measures():
        for note in measure.iter("note"):
            if note.find("rest") is not None and note.get("print-object") == "no":
                out.append(Violation("hidden-rest", number, note.findtext("duration") or ""))
    return out


def chord_semantics(doc: Document, ctx: Context) -> list[Violation]:
    """The cursor/chord rules an importer needs but an XSD will not catch."""
    out: list[Violation] = []
    for number, measure in doc.iter_measures():
        cursor = 0
        previous = None
        for item in measure:
            if item.tag in ("backup", "forward"):
                text = item.findtext("duration")
                value = int(text) if text is not None else 0
                cursor += -value if item.tag == "backup" else value
                previous = None
                if cursor < 0:
                    out.append(Violation("negative-cursor", number, f"cursor {cursor}"))
                continue
            if item.tag != "note":
                previous = None
                continue
            text = item.findtext("duration")
            if text is None:
                previous = None
                continue
            duration = int(text)
            if item.find("chord") is None:
                cursor += duration
            elif previous is None:
                out.append(Violation("orphan-chord", number, "chord without a base note"))
            elif (
                (item.findtext("voice") or "1") != (previous.findtext("voice") or "1")
                or (item.findtext("staff") or "1") != (previous.findtext("staff") or "1")
                or previous.find("rest") is not None
            ):
                out.append(Violation("chord-context", number, "chord after a different voice/staff/rest"))
            previous = item
    return out


def measure_lengths(doc: Document, ctx: Context) -> list[Violation]:
    out: list[Violation] = []
    meter = (4.0, 4.0)
    for number, measure in doc.iter_measures():
        declared = doc.time_signature(measure)
        if declared is not None:
            meter = declared
        bar = meter[0] * 4.0 / meter[1]
        if measure.get("implicit") == "yes":
            continue  # anacrusis: short by design
        ends: dict[tuple[str, str], float] = {}
        for event in doc.events(measure):
            key = (event.staff, event.voice)
            ends[key] = max(ends.get(key, 0.0), event.end)
        for (staff, voice), end in ends.items():
            if abs(end - bar) > 1e-6:
                out.append(
                    Violation(
                        "measure-length",
                        number,
                        f"staff {staff} voice {voice}: {end:g} beats, metre {bar:g}",
                    )
                )
    return out


VERIFIERS = (
    duplicate_ties,
    redundant_time_signatures,
    hidden_rests,
    chord_semantics,
    measure_lengths,
)
