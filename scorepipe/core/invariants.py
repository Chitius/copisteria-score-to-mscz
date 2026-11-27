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


def _prefix(doc: Document, part_id: str, detail: str) -> str:
    return f"{part_id} {detail}" if len(doc.parts()) > 1 else detail


def duplicate_ties(doc: Document, ctx: Context) -> list[Violation]:
    out: list[Violation] = []
    for part_id, _part, number, measure in doc.iter_part_measures():
        for note in measure.iter("note"):
            kinds = [tie.get("type") for tie in note.findall("tie")]
            for kind in ("start", "stop"):
                if kinds.count(kind) > 1:
                    out.append(
                        Violation(
                            "duplicate-tie",
                            number,
                            _prefix(doc, part_id, f"{kinds.count(kind)}x tie {kind}"),
                        )
                    )
        for note in measure.iter("note"):
            kinds = [tied.get("type") for tied in note.findall("notations/tied")]
            for kind in ("start", "stop"):
                if kinds.count(kind) > 1:
                    out.append(
                        Violation(
                            "duplicate-tied",
                            number,
                            _prefix(doc, part_id, f"{kinds.count(kind)}x tied {kind}"),
                        )
                    )
    return out


def redundant_time_signatures(doc: Document, ctx: Context) -> list[Violation]:
    out: list[Violation] = []
    for part_id, part in doc.iter_parts():
        current = None
        for number, measure in enumerate(doc.part_measures(part), start=1):
            signature = doc.time_signature(measure)
            if signature is None:
                continue
            if signature == current:
                out.append(
                    Violation(
                        "redundant-time",
                        number,
                        _prefix(doc, part_id, f"repeats {signature[0]}/{signature[1]}"),
                    )
                )
            current = signature
    return out


def hidden_rests(doc: Document, ctx: Context) -> list[Violation]:
    out: list[Violation] = []
    for part_id, _part, number, measure in doc.iter_part_measures():
        for note in measure.iter("note"):
            if note.find("rest") is not None and note.get("print-object") == "no":
                out.append(
                    Violation(
                        "hidden-rest",
                        number,
                        _prefix(doc, part_id, note.findtext("duration") or ""),
                    )
                )
    return out


def chord_semantics(doc: Document, ctx: Context) -> list[Violation]:
    """The cursor/chord rules an importer needs but an XSD will not catch."""
    out: list[Violation] = []
    for part_id, _part, number, measure in doc.iter_part_measures():
        cursor = 0
        previous = None
        for item in measure:
            if item.tag in ("backup", "forward"):
                text = item.findtext("duration")
                value = int(text) if text is not None else 0
                cursor += -value if item.tag == "backup" else value
                previous = None
                if cursor < 0:
                    out.append(
                        Violation("negative-cursor", number, _prefix(doc, part_id, f"cursor {cursor}"))
                    )
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
                out.append(
                    Violation("orphan-chord", number, _prefix(doc, part_id, "chord without a base note"))
                )
            elif (
                (item.findtext("voice") or "1") != (previous.findtext("voice") or "1")
                or (item.findtext("staff") or "1") != (previous.findtext("staff") or "1")
                or previous.find("rest") is not None
            ):
                out.append(
                    Violation(
                        "chord-context",
                        number,
                        _prefix(doc, part_id, "chord after a different voice/staff/rest"),
                    )
                )
            previous = item
    return out


def measure_lengths(doc: Document, ctx: Context) -> list[Violation]:
    out: list[Violation] = []
    for part_id, part in doc.iter_parts():
        meter = (4.0, 4.0)
        for number, measure in enumerate(doc.part_measures(part), start=1):
            declared = doc.time_signature(measure)
            if declared is not None:
                meter = declared
            bar = meter[0] * 4.0 / meter[1]
            implicit = measure.get("implicit") == "yes"
            ends: dict[tuple[str, str], float] = {}
            for event in doc.events(measure):
                key = (event.staff, event.voice)
                ends[key] = max(ends.get(key, 0.0), event.end)
            if not ends:
                out.append(
                    Violation("measure-length", number, _prefix(doc, part_id, "empty measure"))
                )
                continue
            for (staff, voice), end in ends.items():
                # An anacrusis is allowed to be short, but never overfull.
                if implicit and end <= bar + 1e-6:
                    continue
                if abs(end - bar) > 1e-6:
                    out.append(
                        Violation(
                            "measure-length",
                            number,
                            _prefix(
                                doc,
                                part_id,
                                f"staff {staff} voice {voice}: {end:g} beats, metre {bar:g}",
                            ),
                        )
                    )
    return out


def part_measure_alignment(doc: Document, ctx: Context) -> list[Violation]:
    parts = list(doc.iter_parts())
    if len(parts) <= 1:
        return []
    counts = {part_id: len(doc.part_measures(part)) for part_id, part in parts}
    if len(set(counts.values())) <= 1:
        return []
    summary = ", ".join(f"{part_id}={count}" for part_id, count in counts.items())
    return [Violation("part-measure-mismatch", None, f"parts disagree on measure count: {summary}")]


VERIFIERS = (
    duplicate_ties,
    redundant_time_signatures,
    hidden_rests,
    chord_semantics,
    measure_lengths,
    part_measure_alignment,
)
