"""Merge the voices of one staff into a single line, as the old skill's aggressive pass did.

OMR splits one printed line across voices whose durations drift. When the voices do not disagree on
notehead fill (a whole note is not the same line as a quarter-note run), the measure is rebuilt as
one line: notes sharing an onset become a chord, each chord lasts until the next onset, and gaps
become rests. Ties and slurs are restored afterwards by the page passes.
"""

from __future__ import annotations

from fractions import Fraction
from xml.etree import ElementTree

from ..core.directions import direction_onsets, set_direction_offset
from ..core.document import Document
from ..core.musescore_ticks import TICKS_PER_WHOLE, duration_parts, legal_ticks_parts
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase


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
        done = ctx.options.setdefault("merge_staff_done", set())
        for part_id, part, number, measure in doc.iter_part_measures():
            key = (part_id, number)
            if key in done:
                continue
            if _merge(doc, measure, allow_sustained=True, part=part):
                changed += 1
                done.add(key)
        return PassResult(changed=changed)


def _merge(doc: Document, measure, allow_sustained: bool = True, part=None) -> bool:
    divisions = doc.effective_divisions(measure, part)
    events = doc.events(measure, divisions)
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

    meter = doc.effective_time_signature(measure, part)
    bar = meter[0] * 4.0 / meter[1]
    rebuilt = False
    for staff, staff_events in targets.items():
        if any(not event.rest and event.element.find("pitch") is None for event in staff_events):
            continue
        notes = [event for event in staff_events if not event.rest and event.element.find("pitch") is not None]
        if not notes:
            continue
        if _has_tuplets(staff_events):
            # Rebuilding a tuplet line with plain durations loses <time-modification> and turns
            # 16th-triplets into quarters (Lindenbaum m1). Leave the source voices alone until the
            # merge can preserve tuplet ratios.
            continue
        all_onsets = sorted({round(event.onset, 4) for event in staff_events})
        if all_onsets[0] < -1e-6 or all_onsets[-1] >= bar - 1e-6:
            continue
        protected = _protected_notes(notes, all_onsets, bar, allow_sustained)
        active = [event for event in notes if id(event.element) not in protected]
        if not active:
            continue
        active_onsets = sorted({round(event.onset, 4) for event in active})
        sequence: list[ElementTree.Element] = []
        cursor = 0.0
        try:
            for onset in active_onsets:
                if onset > cursor + 1e-6:
                    sequence.extend(_rests(onset - cursor, divisions, staff))
                boundary = next((value for value in all_onsets if value > onset + 1e-6), bar)
                duration = boundary - onset
                pitches = []
                for event in active:
                    if abs(event.onset - onset) > 1e-6:
                        continue
                    pitch = _pitch(event.element)
                    if pitch and pitch not in [item[0] for item in pitches]:
                        pitches.append((pitch, event))
                for position, (pitch, event) in enumerate(pitches):
                    source = event.element if abs(event.duration - duration) < 1e-6 else None
                    sequence.append(
                        _note(pitch, duration, divisions, staff, chord=position > 0, source=source)
                    )
                cursor = onset + duration
            if cursor < bar - 1e-6:
                sequence.extend(_rests(bar - cursor, divisions, staff))
            extras = _protected_blocks(
                [event for event in notes if id(event.element) in protected], bar, divisions, staff
            )
        except ValueError:
            # A proposed slot/gap cannot be represented as a plain binary MusicXML duration
            # (e.g. a cross-voice triplet subdivision); leave the source voices intact.
            continue
        _replace_staff(doc, measure, staff, sequence, extras)
        rebuilt = True
    return rebuilt


def _protected_notes(notes, all_onsets: list[float], bar: float, allow_sustained: bool = True) -> set[int]:
    """Notes whose proposed duration would cross the filled/hollow boundary.

    The proposal is measured against **all** original onsets, including notes that are themselves
    protected. A protected note keeps its slot as a gap, so it cannot stretch its neighbours (m29:
    protecting the A2 halves used to turn the beat-2 quarter into a half and protect that too).

    A second, directional guard protects a genuinely notated sustained note when merging would
    shorten it into a run in another voice. OMR durations alone are not trusted: the note's
    ``<type>`` must agree with its duration (m5: the voice-2 D4 quarter was being compressed to a
    sixteenth because voice 1 has a run there). This is not applied to notes without a matching
    type, so ordinary OMR duration drift can still be normalised.
    """
    protected: set[int] = set()
    for index, onset in enumerate(all_onsets):
        following = all_onsets[index + 1] if index + 1 < len(all_onsets) else bar
        duration = following - onset
        for event in notes:
            if abs(event.onset - onset) > 1e-6:
                continue
            if (event.duration >= 2.0 - 1e-6) != (duration >= 2.0 - 1e-6):
                protected.add(id(event.element))
            elif allow_sustained and _would_shrink_notated_note(event, duration):
                protected.add(id(event.element))
    return protected


def _has_tuplets(events) -> bool:
    for event in events:
        if event.element.find("time-modification") is not None:
            return True
        if event.element.find("notations/tuplet") is not None:
            return True
    return False


def _would_shrink_notated_note(event, proposed: float) -> bool:
    if proposed >= event.duration - 1e-6:
        return False
    notated = _notated_duration(event.element)
    if notated is None or abs(notated - event.duration) > 1e-6:
        return False
    return True


def _notated_duration(note_element) -> float | None:
    note_type = (note_element.findtext("type") or "").strip()
    base = {
        "whole": 4.0,
        "half": 2.0,
        "quarter": 1.0,
        "eighth": 0.5,
        "16th": 0.25,
        "32nd": 0.125,
        "64th": 0.0625,
    }.get(note_type)
    if base is None:
        return None
    dots = len(note_element.findall("dot"))
    if dots:
        base *= 2.0 - 0.5**dots
    return base


def _forward(duration: float, divisions: float, staff: str) -> ElementTree.Element:
    element = ElementTree.Element("forward")
    ElementTree.SubElement(element, "duration").text = str(int(round(duration * divisions)))
    ElementTree.SubElement(element, "voice").text = "1"
    ElementTree.SubElement(element, "staff").text = staff
    return element


def _protected_blocks(events: list, bar: float, divisions: float, staff: str) -> list[list]:
    """One block per original voice, keeping each protected note at its own onset and duration."""
    if not events:
        return []
    by_voice: dict[str, list] = {}
    for event in events:
        by_voice.setdefault(event.voice, []).append(event)
    blocks: list[list] = []
    for position, voice in enumerate(
        sorted(by_voice, key=lambda value: (-len(by_voice[value]), value)), start=2
    ):
        layer = sorted(by_voice[voice], key=lambda event: event.onset)
        block: list[ElementTree.Element] = []
        cursor = 0.0
        index = 0
        while index < len(layer):
            onset = layer[index].onset
            group = []
            while index < len(layer) and abs(layer[index].onset - onset) < 1e-6:
                group.append(layer[index])
                index += 1
            if onset > cursor + 1e-6:
                forward = ElementTree.Element("forward")
                ElementTree.SubElement(forward, "duration").text = str(
                    int(round((onset - cursor) * divisions))
                )
                block.append(forward)
            length = 0.0
            for chord_position, event in enumerate(group):
                pitch = _pitch(event.element)
                if pitch is None:
                    continue
                element = _note(
                    pitch,
                    event.duration,
                    divisions,
                    staff,
                    chord=chord_position > 0,
                    source=event.element,
                    voice=str(position),
                )
                block.append(element)
                length = max(length, event.duration)
            cursor = onset + length
        if cursor < bar - 1e-6:
            block.extend(_rests(bar - cursor, divisions, staff, voice=str(position)))
        blocks.append(block)
    return blocks


def _replace_staff(
    doc: Document, measure, staff: str, sequence: list, extras: list[list] | None = None
) -> None:
    onsets = direction_onsets(measure)
    children = list(measure)
    segments: list[tuple[list, ElementTree.Element | None]] = []
    current: list = []
    for child in children:
        if child.tag == "backup":
            segments.append((current, child))
            current = []
        else:
            current.append(child)
    segments.append((current, None))

    leading_tags = ("attributes", "print", "sound", "barline")
    leading = [child for child in children if child.tag in leading_tags]
    rescued_directions: list[ElementTree.Element] = []
    other_blocks: list[list] = []
    for position, (segment, _following_backup) in enumerate(segments):
        staffs = {child.findtext("staff") or "1" for child in segment if child.tag == "note"}
        if not staffs or staffs == {staff}:
            for child in segment:
                if child.tag == "direction":
                    set_direction_offset(child, onsets.get(id(child), 0))
                    rescued_directions.append(child)
            continue
        # keep the whole block (forwards, gaps, directions), not only its notes, otherwise the
        # other staff's onsets move (laputa m31: bass D3 from beat 3 to beat 1)
        block = [child for child in segment if child.tag not in leading_tags]
        if not block:
            continue
        preceding_backup = segments[position - 1][1] if position else None
        if (
            other_blocks
            and preceding_backup is not None
            and _block_staffs(other_blocks[-1]) == staffs
        ):
            # The source split one staff's stream on a backup of its own (an overlapping rest).
            # Re-inserting the halves as separate blocks moves that rest to the barline; keep the
            # backup so the rest stays where the OMR put it (Suzume m16).
            other_blocks[-1].append(ElementTree.fromstring(ElementTree.tostring(preceding_backup)))
            other_blocks[-1].extend(block)
            continue
        other_blocks.append(block)

    for child in children:
        measure.remove(child)
    for child in leading:
        measure.append(child)
    for child in rescued_directions:
        measure.append(child)
    meter = doc.effective_time_signature(measure)
    bar = meter[0] * 4.0 / meter[1]
    divisions = doc.divisions()
    blocks = [sequence] + list(extras or []) + other_blocks
    for index, block in enumerate(blocks):
        if index:
            backup = ElementTree.Element("backup")
            ElementTree.SubElement(backup, "duration").text = str(_block_ticks(blocks[index - 1]))
            measure.append(backup)
        for child in block:
            measure.append(child)


def _block_ticks(block: list) -> int:
    """Net advance of a block over the block's own stream.

    A kept block may contain a source backup (a staff whose stream was split on an overlapping
    rest), so backups subtract; constructed blocks never contain one.
    """
    total = 0
    for child in block:
        if child.tag == "backup":
            text = child.findtext("duration")
            if text:
                total -= int(text)
            continue
        if child.tag == "note" and child.find("chord") is not None:
            continue
        if child.tag in ("note", "forward"):
            text = child.findtext("duration")
            if text:
                total += int(text)
    return total


def _block_staffs(block: list) -> set[str]:
    return {child.findtext("staff") or "1" for child in block if child.tag == "note"}


def _pitch(note_element) -> tuple[str, str, str] | None:
    step = note_element.findtext("pitch/step")
    octave = note_element.findtext("pitch/octave")
    if step is None or octave is None:
        return None
    return (step, note_element.findtext("pitch/alter") or "", octave)


def _note(
    pitch,
    duration: float,
    divisions: float,
    staff: str,
    *,
    chord: bool,
    source=None,
    voice: str = "1",
) -> ElementTree.Element:
    if source is not None:
        # keep tie/slur/articulation/accidental/beam children when the duration did not change;
        # a retimed note must drop them (the old skill restored ties separately)
        element = ElementTree.fromstring(ElementTree.tostring(source))
        chord_tag = element.find("chord")
        if chord and chord_tag is None:
            element.insert(0, ElementTree.Element("chord"))
        elif not chord and chord_tag is not None:
            element.remove(chord_tag)
        duration_element = element.find("duration")
        if duration_element is not None:
            duration_element.text = str(int(round(duration * divisions)))
        voice_element = element.find("voice")
        if voice_element is None:
            voice_element = ElementTree.SubElement(element, "voice")
        voice_element.text = voice
        staff_element = element.find("staff")
        if staff_element is None:
            staff_element = ElementTree.SubElement(element, "staff")
        staff_element.text = staff
        return element
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
    ElementTree.SubElement(element, "voice").text = voice
    note_type, dots = _type_for(duration)
    ElementTree.SubElement(element, "type").text = note_type
    for _ in range(dots):
        ElementTree.SubElement(element, "dot")
    ElementTree.SubElement(element, "staff").text = staff
    return element


def _rests(
    duration: float, divisions: float, staff: str, *, voice: str = "1"
) -> list[ElementTree.Element]:
    """Split a gap into exact legal rest values instead of mislabelling its type."""
    whole = Fraction(duration).limit_denominator(256) / 4
    ticks = whole * TICKS_PER_WHOLE
    if ticks.denominator != 1:
        raise ValueError(f"cannot represent generated MusicXML rest exactly: {duration}")
    parts = legal_ticks_parts(int(ticks))
    if sum(part[2] for part in parts) != ticks:
        raise ValueError(f"cannot represent generated MusicXML rest exactly: {duration}")
    return [
        _rest(float(Fraction(part_ticks, TICKS_PER_WHOLE) * 4), divisions, staff, voice=voice)
        for _name, _dots, part_ticks in parts
    ]


def _rest(duration: float, divisions: float, staff: str, *, voice: str = "1") -> ElementTree.Element:
    element = ElementTree.Element("note")
    ElementTree.SubElement(element, "rest")
    ElementTree.SubElement(element, "duration").text = str(int(round(duration * divisions)))
    ElementTree.SubElement(element, "voice").text = voice
    note_type, dots = _type_for(duration)
    ElementTree.SubElement(element, "type").text = note_type
    for _ in range(dots):
        ElementTree.SubElement(element, "dot")
    ElementTree.SubElement(element, "staff").text = staff
    return element


def _type_for(duration: float) -> tuple[str, int]:
    values = duration_parts(Fraction(duration).limit_denominator(256) / 4)
    if values is None:
        # MuseScore's MusicXML reader follows <type> when it disagrees with
        # <duration>; never emit a plausible-looking but rhythmically wrong note.
        raise ValueError(f"cannot represent generated MusicXML duration exactly: {duration}")
    return values


MERGE_STAFF_VOICES = MergeStaffVoices()
