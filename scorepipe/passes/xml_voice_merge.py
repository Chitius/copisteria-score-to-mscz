"""Merge the voices of one staff into a single line, as the old skill's aggressive pass did.

OMR splits one printed line across voices whose durations drift. When the voices do not disagree on
notehead fill (a whole note is not the same line as a quarter-note run), the measure is rebuilt as
one line: notes sharing an onset become a chord, each chord lasts until the next onset, and gaps
become rests. Ties and slurs are restored afterwards by the page passes.
"""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.document import Document
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase

_TYPES = [
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


class MergeStaffVoices:
    spec = PassSpec(
        name="merge_staff_voices",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("staff-line",),
        description="rebuild a multi-voice staff as one retimed line (skips fill conflicts)",
        measure="multi-voice staves whose durations drift",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        changed = 0
        for _number, measure in doc.iter_measures():
            if _merge(doc, measure):
                changed += 1
        return PassResult(changed=changed)


def _merge(doc: Document, measure) -> bool:
    events = doc.events(measure)
    if not events:
        return False
    by_staff: dict[str, list] = {}
    for event in events:
        by_staff.setdefault(event.staff, []).append(event)
    targets = {
        staff: staff_events
        for staff, staff_events in by_staff.items()
        if len({event.voice for event in staff_events}) > 1
    }
    if not targets:
        return False

    meter = doc.time_signature(measure) or (4.0, 4.0)
    bar = meter[0] * 4.0 / meter[1]
    divisions = doc.divisions()
    rebuilt = False
    for staff, staff_events in targets.items():
        if _fill_conflict(staff_events, bar):
            continue
        notes = [event for event in staff_events if not event.rest and event.element.find("pitch") is not None]
        if not notes:
            continue
        onsets = sorted({round(event.onset, 4) for event in notes})
        if onsets[0] < -1e-6 or onsets[-1] >= bar - 1e-6:
            continue
        sequence: list[ElementTree.Element] = []
        if onsets[0] > 1e-6:
            sequence.append(_rest(onsets[0], divisions, staff))
        for index, onset in enumerate(onsets):
            following = onsets[index + 1] if index + 1 < len(onsets) else bar
            duration = following - onset
            pitches = []
            for event in notes:
                if abs(event.onset - onset) > 1e-6:
                    continue
                pitch = _pitch(event.element)
                if pitch and pitch not in pitches:
                    pitches.append(pitch)
            for position, pitch in enumerate(pitches):
                sequence.append(
                    _note(pitch, duration, divisions, staff, chord=position > 0)
                )
        _replace_staff(doc, measure, staff, sequence)
        rebuilt = True
    return rebuilt


def _fill_conflict(staff_events, bar: float) -> bool:
    voices = {}
    for event in staff_events:
        voices.setdefault(event.voice, []).append(event)
    if len(voices) < 2:
        return False
    primary = max(voices, key=lambda voice: len(voices[voice]))
    primary_notes = [event for event in voices[primary] if not event.rest]
    if not primary_notes:
        return False
    for voice, events in voices.items():
        if voice == primary:
            continue
        for event in events:
            if event.rest:
                continue
            hollow = event.duration >= 2.0
            matches = [
                other
                for other in primary_notes
                if other.onset <= event.onset < other.end
            ]
            if any((other.duration >= 2.0) != hollow for other in matches):
                return True
    return False


def _replace_staff(doc: Document, measure, staff: str, sequence: list) -> None:
    children = list(measure)
    segments: list[list] = []
    current: list = []
    for child in children:
        if child.tag == "backup":
            segments.append(current)
            current = []
        else:
            current.append(child)
    segments.append(current)

    leading_tags = ("attributes", "print", "sound", "barline")
    leading = [child for child in children if child.tag in leading_tags]
    other_blocks: list[list] = []
    for segment in segments:
        staffs = {child.findtext("staff") or "1" for child in segment if child.tag == "note"}
        if not staffs or staffs == {staff}:
            continue
        # keep the whole block (forwards, gaps, directions), not only its notes, otherwise the
        # other staff's onsets move (laputa m31: bass D3 from beat 3 to beat 1)
        other_blocks.append([child for child in segment if child.tag not in leading_tags])

    for child in children:
        measure.remove(child)
    for child in leading:
        measure.append(child)
    meter = doc.time_signature(measure) or (4.0, 4.0)
    bar = meter[0] * 4.0 / meter[1]
    divisions = doc.divisions()
    blocks = [sequence] + other_blocks
    for index, block in enumerate(blocks):
        if index:
            backup = ElementTree.Element("backup")
            ElementTree.SubElement(backup, "duration").text = str(int(round(bar * divisions)))
            measure.append(backup)
        for child in block:
            measure.append(child)


def _pitch(note_element) -> tuple[str, str, str] | None:
    step = note_element.findtext("pitch/step")
    octave = note_element.findtext("pitch/octave")
    if step is None or octave is None:
        return None
    return (step, note_element.findtext("pitch/alter") or "", octave)


def _note(pitch, duration: float, divisions: float, staff: str, *, chord: bool) -> ElementTree.Element:
    element = ElementTree.Element("note")
    if chord:
        ElementTree.SubElement(element, "chord")
    pitch_element = ElementTree.SubElement(element, "pitch")
    step, alter, octave = pitch
    ElementTree.SubElement(pitch_element, "step").text = step
    if alter and float(alter) != 0:
        ElementTree.SubElement(pitch_element, "alter").text = alter
    ElementTree.SubElement(pitch_element, "octave").text = octave
    ElementTree.SubElement(element, "duration").text = str(int(round(duration * divisions)))
    ElementTree.SubElement(element, "voice").text = "1"
    note_type, dots = _type_for(duration)
    ElementTree.SubElement(element, "type").text = note_type
    for _ in range(dots):
        ElementTree.SubElement(element, "dot")
    ElementTree.SubElement(element, "staff").text = staff
    return element


def _rest(duration: float, divisions: float, staff: str) -> ElementTree.Element:
    element = ElementTree.Element("note")
    ElementTree.SubElement(element, "rest")
    ElementTree.SubElement(element, "duration").text = str(int(round(duration * divisions)))
    ElementTree.SubElement(element, "voice").text = "1"
    note_type, dots = _type_for(duration)
    ElementTree.SubElement(element, "type").text = note_type
    for _ in range(dots):
        ElementTree.SubElement(element, "dot")
    ElementTree.SubElement(element, "staff").text = staff
    return element


def _type_for(duration: float) -> tuple[str, int]:
    for value, name, dots in _TYPES:
        if abs(value - duration) < 1e-6:
            return name, dots
    return "quarter", 0


MERGE_STAFF_VOICES = MergeStaffVoices()
