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
            beat_ticks = float(mark.get("beat") or 0) * divisions
            placement = mark.get("placement") or "above"
            rehearsal = (mark.get("rehearsal") or "").strip()
            metronome = mark.get("tempo") or mark.get("metronome")
            if rehearsal and not _has_rehearsal(measure, rehearsal):
                direction = _direction(placement)
                direction_type = ElementTree.SubElement(direction, "direction-type")
                ElementTree.SubElement(direction_type, "rehearsal").text = rehearsal
                _stamp(direction, beat_ticks)
                _insert(measure, direction)
                changed += 1
            if text and not _has_words(measure, text):
                direction = _direction(placement)
                direction_type = ElementTree.SubElement(direction, "direction-type")
                words = ElementTree.SubElement(direction_type, "words", _style_attributes(mark))
                words.text = text
                _stamp(direction, beat_ticks)
                _insert(measure, direction)
                changed += 1
            if metronome and not _has_metronome(measure, metronome):
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


def _style_attributes(mark: dict) -> dict:
    attrs = {}
    if mark.get("font_family"):
        attrs["font-family"] = str(mark["font_family"])
    if mark.get("font_size"):
        attrs["font-size"] = str(mark["font_size"])
    if mark.get("font_weight"):
        attrs["font-weight"] = str(mark["font_weight"])
    if mark.get("italic"):
        attrs["font-style"] = "italic"
    if mark.get("justify"):
        attrs["justify"] = str(mark["justify"])
    return attrs


def _has_words(measure: ElementTree.Element, text: str) -> bool:
    return any((words.text or "").strip() == text for words in measure.iter("words"))


def _has_rehearsal(measure: ElementTree.Element, text: str) -> bool:
    return any((rehearsal.text or "").strip() == text for rehearsal in measure.iter("rehearsal"))


def _has_metronome(measure: ElementTree.Element, per_minute) -> bool:
    for metronome in measure.iter("metronome"):
        if (metronome.findtext("per-minute") or "").strip() == str(per_minute):
            return True
    for sound in measure.iter("sound"):
        if (sound.get("tempo") or "").strip() == str(per_minute):
            return True
    return False


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
