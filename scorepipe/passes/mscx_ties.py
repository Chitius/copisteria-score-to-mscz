"""Restore ties in the mscx from tie pairs recorded on the MusicXML side.

MuseScore's importer drops ties on chord members, so the pairs are carried across the conversion
as data (`Context.options["ties"]`) and attached to the matching Note elements here, in MuseScore's
own Spanner/Tie form.
"""

from __future__ import annotations

import uuid
from xml.etree import ElementTree

from ..core.mscx import MsxcDocument
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase

DURATIONS = {
    "breve": 8.0,
    "whole": 4.0,
    "half": 2.0,
    "quarter": 1.0,
    "eighth": 0.5,
    "16th": 0.25,
    "32nd": 0.125,
    "64th": 0.0625,
    "128th": 0.03125,
}


class RestoreMscxTies:
    spec = PassSpec(
        name="restore_mscx_ties",
        phase=Phase.DISPLAY,
        kind=Kind.MECHANICAL,
        owns=("mscx-ties",),
        description="attach tie spanners that the MuseScore importer dropped",
        measure="ties missing from the mscx",
    )

    def run(self, doc: MsxcDocument, ctx: Context) -> PassResult:
        pairs = (ctx.options or {}).get("ties") or []
        if not pairs:
            return PassResult()
        index = _note_index(doc)
        added = 0
        for pair in pairs:
            start_entry = index.get(
                _key(pair["start_measure"], pair["staff"], pair["pitch"], pair["start_onset"])
            )
            stop_entry = index.get(
                _key(pair["stop_measure"], pair["staff"], pair["pitch"], pair["stop_onset"])
            )
            if start_entry is None or stop_entry is None:
                continue
            start, start_index = start_entry
            stop, stop_index = stop_entry
            if _has_tie(start, "next") or _has_tie(stop, "prev"):
                continue
            distance = pair["stop_measure"] - pair["start_measure"]
            offset = stop_index - start_index
            _add_spanner(start, "next", distance, offset)
            _add_spanner(stop, "prev", -distance, -offset)
            added += 1
        return PassResult(changed=added)


def _key(measure: int, staff: str, pitch: int, onset: float) -> tuple:
    return (measure, staff, pitch, round(onset, 4))


def _has_tie(note, side: str) -> bool:
    return any(spanner.find(side) is not None for spanner in note.findall("Spanner"))


def _add_spanner(note, side: str, measures: int, notes: int = 0) -> None:
    spanner = ElementTree.Element("Spanner", {"type": "Tie"})
    tie = ElementTree.SubElement(spanner, "Tie")
    ElementTree.SubElement(tie, "eid").text = uuid.uuid4().hex[:20]
    location = ElementTree.Element(side)
    location_measures = ElementTree.SubElement(location, "location")
    ElementTree.SubElement(location_measures, "measures").text = str(measures)
    ElementTree.SubElement(location_measures, "notes").text = str(notes)
    spanner.append(location)
    children = list(note)
    position = 1 if children and children[0].tag == "eid" else 0
    note.insert(position, spanner)


def _note_index(doc: MsxcDocument) -> dict[tuple, tuple]:
    index = {}
    for staff in doc.root.iter("Staff"):
        staff_id = staff.get("id") or "1"
        for measure_number, measure in enumerate(staff.findall("Measure"), start=1):
            for voice in measure.findall("voice"):
                cursor = 0.0
                for child in voice:
                    if child.tag == "Chord":
                        duration = _beats(child)
                        onset = cursor
                        cursor += duration
                        for position, note in enumerate(child.findall("Note")):
                            pitch = int(note.findtext("pitch") or 0)
                            index[_key(measure_number, staff_id, pitch, onset)] = (note, position)
                    elif child.tag == "Rest":
                        cursor += _beats(child)
    return index


def _beats(element) -> float:
    name = element.findtext("durationType") or "quarter"
    if name == "measure":
        return 4.0
    base = DURATIONS.get(name, 1.0)
    dots = int(element.findtext("dots") or 0)
    multiplier = 0.0
    for index in range(dots + 1):
        multiplier += 0.5**index
    return base * multiplier


def _pitch_midi(step: str, alter: str, octave: str) -> int:
    semitones = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    return (int(octave) + 1) * 12 + semitones[step] + int(float(alter or 0))


MSXC_TIES = RestoreMscxTies()
