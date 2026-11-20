"""Inject pass: turn already-recognised facts into MusicXML directions.

Mechanical and idempotent: a fact whose words already exist in that measure is skipped, so the
fixed-point loop can run it repeatedly. It never looks at the PDF itself.
"""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.document import Document
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase


class ApplyMarksFacts:
    spec = PassSpec(
        name="apply_marks_facts",
        phase=Phase.INJECT,
        kind=Kind.MECHANICAL,
        owns=("text-directions",),
        description="insert words/rehearsal/metronome directions from a facts file",
        measure="facts not yet present in the score",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        marks = (ctx.facts or {}).get("marks") or []
        divisions = doc.divisions()
        changed = 0
        for mark in marks:
            number = int(mark.get("measure") or 0)
            measures = doc.measures()
            if not 0 < number <= len(measures):
                continue
            measure = measures[number - 1]
            text = (mark.get("text") or "").strip()
            if text and _has_words(measure, text):
                continue
            beat_ticks = float(mark.get("beat") or 0) * divisions
            placement = mark.get("placement") or "above"
            rehearsal = (mark.get("rehearsal") or "").strip()
            metronome = mark.get("tempo") or mark.get("metronome")
            if rehearsal:
                direction = _direction(placement)
                direction_type = ElementTree.SubElement(direction, "direction-type")
                ElementTree.SubElement(direction_type, "rehearsal").text = rehearsal
                _stamp(direction, beat_ticks)
                _insert(measure, direction)
                changed += 1
            if text:
                direction = _direction(placement)
                direction_type = ElementTree.SubElement(direction, "direction-type")
                ElementTree.SubElement(direction_type, "words").text = text
                _stamp(direction, beat_ticks)
                _insert(measure, direction)
                changed += 1
            if metronome:
                direction = _direction(placement)
                direction_type = ElementTree.SubElement(direction, "direction-type")
                metronome_element = ElementTree.SubElement(direction_type, "metronome")
                ElementTree.SubElement(metronome_element, "beat-unit").text = (
                    mark.get("beat_unit") or "quarter"
                )
                ElementTree.SubElement(metronome_element, "per-minute").text = str(metronome)
                _stamp(direction, beat_ticks)
                ElementTree.SubElement(direction, "sound", {"tempo": str(metronome)})
                _insert(measure, direction)
                changed += 1
        return PassResult(changed=changed)


def _has_words(measure: ElementTree.Element, text: str) -> bool:
    return any((words.text or "").strip() == text for words in measure.iter("words"))


def _direction(placement: str) -> ElementTree.Element:
    return ElementTree.Element("direction", {"placement": placement})


def _stamp(direction: ElementTree.Element, offset_ticks: float) -> None:
    """Offset goes after the direction-type(s) and before <sound>."""
    if offset_ticks:
        ElementTree.SubElement(direction, "offset").text = str(int(round(offset_ticks)))


def _insert(measure: ElementTree.Element, direction: ElementTree.Element) -> None:
    index = next(
        (position for position, child in enumerate(measure) if child.tag in ("note", "forward")),
        len(measure),
    )
    measure.insert(index, direction)


INJECT_PASSES = [ApplyMarksFacts()]
