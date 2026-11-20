"""Give a staff that is silent for a whole measure a proper measure rest.

An empty staff in the MusicXML makes MuseScore show nothing at all, and a hand-built rest made of
quarter notes looks like a placeholder. A measure rest (`<rest measure="yes"/>`) is what a printed
score uses, and it keeps the staff visible in the system.
"""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.document import Document
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase


class PadEmptyStaves:
    spec = PassSpec(
        name="pad_empty_staves",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("empty-staff-rests",),
        description="insert a measure rest for a staff that has no note in the measure",
        measure="staves missing a whole-measure rest",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        staves = {event.staff for _number, measure in doc.iter_measures() for event in doc.events(measure)}
        if not staves:
            return PassResult()
        divisions = doc.divisions()
        meter = (4.0, 4.0)
        added = 0
        for _number, measure in doc.iter_measures():
            declared = doc.time_signature(measure)
            if declared is not None:
                meter = declared
            bar = meter[0] * 4.0 / meter[1]
            present = {event.staff for event in doc.events(measure)}
            for staff in sorted(staves - present):
                if any(
                    child.tag == "note" for child in measure
                ):
                    backup = ElementTree.Element("backup")
                    ElementTree.SubElement(backup, "duration").text = str(int(round(bar * divisions)))
                    measure.append(backup)
                rest = ElementTree.Element("note")
                ElementTree.SubElement(rest, "rest", {"measure": "yes"})
                ElementTree.SubElement(rest, "duration").text = str(int(round(bar * divisions)))
                ElementTree.SubElement(rest, "voice").text = "1"
                ElementTree.SubElement(rest, "type").text = "whole"
                ElementTree.SubElement(rest, "staff").text = staff
                measure.append(rest)
                added += 1
        return PassResult(changed=added)


PAD_EMPTY_STAVES = PadEmptyStaves()
