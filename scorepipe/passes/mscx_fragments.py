"""Move chord notes with a conflicting duration into their own voice in the mscx.

MusicXML allows a chord member to carry a different duration than the chord base, but MuseScore
coerces it to the base duration (a quarter becomes a whole note). The conflicting members are
recorded on the MusicXML side and split into a separate voice here.
"""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.mscx import MsxcDocument
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase

TYPE_FOR_BEATS = [
    (4.0, "whole", 0),
    (3.0, "half", 1),
    (2.0, "half", 0),
    (1.5, "quarter", 1),
    (1.0, "quarter", 0),
    (0.75, "eighth", 1),
    (0.5, "eighth", 0),
    (0.375, "16th", 1),
    (0.25, "16th", 0),
]


class SplitChordFragments:
    spec = PassSpec(
        name="split_chord_fragments",
        phase=Phase.DISPLAY,
        kind=Kind.MECHANICAL,
        owns=("mscx-chord-fragments",),
        description="give a chord member with a conflicting duration its own voice",
        measure="chord members whose duration the importer coerced",
    )

    def run(self, doc: MsxcDocument, ctx: Context) -> PassResult:
        fragments = (ctx.options or {}).get("chord_fragments") or []
        if not fragments:
            return PassResult()
        added = 0
        for fragment in fragments:
            staff = _staff(doc, str(fragment["staff"]))
            if staff is None:
                continue
            measures = staff.findall("Measure")
            number = int(fragment["measure"])
            if not 0 < number <= len(measures):
                continue
            measure = measures[number - 1]
            chord, note = _find_note(measure, int(fragment["pitch"]), float(fragment["onset"]))
            if chord is None or note is None:
                continue
            if abs(_beats(chord) - float(fragment["duration"])) < 1e-6:
                continue  # already in its own voice
            chord.remove(note)
            if not chord.findall("Note"):
                for voice in measure.findall("voice"):
                    if chord in list(voice):
                        voice.remove(chord)
            _new_voice(measure, fragment, note)
            added += 1
        return PassResult(changed=added)


def _staff(doc: MsxcDocument, staff_id: str):
    for staff in doc.root.iter("Staff"):
        if staff.get("id") == staff_id:
            return staff
    return None


def _find_note(measure, pitch: int, onset: float):
    cursor = 0.0
    for voice in measure.findall("voice"):
        cursor = 0.0
        for child in voice:
            if child.tag == "Chord":
                duration = _beats(child)
                if abs(cursor - onset) < 1e-4:
                    for note in child.findall("Note"):
                        if int(note.findtext("pitch") or 0) == pitch:
                            return child, note
                cursor += duration
            elif child.tag == "Rest":
                cursor += _beats(child)
    return None, None


def _new_voice(measure, fragment, note) -> None:
    voice = ElementTree.SubElement(measure, "voice")
    onset = float(fragment["onset"])
    duration = float(fragment["duration"])
    if onset > 1e-6:
        rest = ElementTree.SubElement(voice, "Rest")
        _set_type(rest, onset)
    chord = ElementTree.SubElement(voice, "Chord")
    _set_type(chord, duration)
    copy = ElementTree.SubElement(chord, "Note")
    for child in note:
        if child.tag in ("pitch", "tpc"):
            copy.append(ElementTree.fromstring(ElementTree.tostring(child)))
    remaining = 4.0 - onset - duration
    if remaining > 1e-6:
        rest = ElementTree.SubElement(voice, "Rest")
        _set_type(rest, remaining)


def _set_type(element, beats: float) -> None:
    for value, name, dots in TYPE_FOR_BEATS:
        if abs(value - beats) < 1e-6:
            ElementTree.SubElement(element, "durationType").text = name
            if dots:
                ElementTree.SubElement(element, "dots").text = str(dots)
            return
    ElementTree.SubElement(element, "durationType").text = "quarter"


def _beats(element) -> float:
    name = element.findtext("durationType") or "quarter"
    base = {
        "breve": 8.0,
        "whole": 4.0,
        "half": 2.0,
        "quarter": 1.0,
        "eighth": 0.5,
        "16th": 0.25,
        "32nd": 0.125,
    }.get(name, 1.0)
    dots = int(element.findtext("dots") or 0)
    return base * sum(0.5**index for index in range(dots + 1))


FRAGMENTS = SplitChordFragments()
