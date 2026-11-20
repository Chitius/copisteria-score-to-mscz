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


def measure_lengths(doc: Document, ctx: Context) -> list[Violation]:
    out: list[Violation] = []
    meter = (4.0, 4.0)
    for number, measure in doc.iter_measures():
        declared = doc.time_signature(measure)
        if declared is not None:
            meter = declared
        bar = meter[0] * 4.0 / meter[1]
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
    measure_lengths,
)
