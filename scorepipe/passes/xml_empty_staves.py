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
        added = 0
        for _part_id, part in doc.iter_parts():
            measures = doc.part_measures(part)
            staves = {
                event.staff
                for measure in measures
                for event in doc.events(measure, doc.effective_divisions(measure, part))
            }
            if not staves:
                continue
            meter = (4.0, 4.0)
            for measure in measures:
                if measure.get("implicit") == "yes":
                    continue  # an anacrusis is intentionally short; do not fill it with a measure rest
                declared = doc.time_signature(measure)
                if declared is not None:
                    meter = declared
                bar = meter[0] * 4.0 / meter[1]
                divisions = doc.effective_divisions(measure, part)
                events = doc.events(measure, divisions)
                present = {event.staff for event in events}
                missing = sorted(staves - present)
                if not missing:
                    continue
                if not events:
                    # copisteria writes an empty bar as a bare <forward>; replace it cleanly
                    # with a measure rest so the rest starts at beat 0 instead of past the barline.
                    for forward in list(measure.findall("forward")):
                        measure.remove(forward)
                for staff in missing:
                    cursor_ticks = _measure_cursor_ticks(measure)
                    if cursor_ticks > 0:
                        backup = ElementTree.Element("backup")
                        ElementTree.SubElement(backup, "duration").text = str(cursor_ticks)
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


def _measure_cursor_ticks(measure: ElementTree.Element) -> int:
    cursor = 0
    for item in measure:
        if item.tag == "backup":
            text = item.findtext("duration")
            if text:
                cursor -= int(text)
        elif item.tag == "forward":
            text = item.findtext("duration")
            if text:
                cursor += int(text)
        elif item.tag == "note" and item.find("chord") is None:
            text = item.findtext("duration")
            if text:
                cursor += int(text)
    return cursor


PAD_EMPTY_STAVES = PadEmptyStaves()
