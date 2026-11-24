"""Move or split notes that cross the barline.

Two cases are handled:

- a note that *starts* past the barline is moved into the next measure as a new voice;
- a note that starts before the barline but ends after it is split: the first part stays, the
  remainder becomes a tied note at the start of the next measure's new voice.
"""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.document import Document, Event
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase


class RebaseMeasures:
    spec = PassSpec(
        name="rebase_measures",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("measure-content",),
        description="move notes starting past the barline, split notes crossing it, into a new voice",
        measure="overflow beats beyond the barline",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        measures = doc.measures()
        divisions = doc.divisions()
        meter = (4.0, 4.0)
        moved = 0
        for index, measure in enumerate(measures):
            declared = doc.time_signature(measure)
            if declared is not None:
                meter = declared
            bar = meter[0] * 4.0 / meter[1]
            if index + 1 >= len(measures):
                continue
            next_measure = measures[index + 1]
            next_meter = doc.time_signature(next_measure)
            next_bar = next_meter[0] * 4.0 / next_meter[1] if next_meter is not None else bar
            next_voices = {
                staff: _max_voice(next_measure, staff) + 1
                for staff in {event.staff for event in doc.events(next_measure)}
            }

            groups: dict[tuple[str, str], list[Event]] = {}
            removals: list[ElementTree.Element] = []
            for event in doc.events(measure):
                if event.onset >= bar - 1e-6:
                    if event.rest:
                        # Stray padding rests after the barline are not musical overflow; moving
                        # them into the next measure corrupts that measure (Sincerely m24→m25).
                        removals.append(event.element)
                        continue
                    groups.setdefault((event.staff, event.voice), []).append(event)
                    removals.append(event.element)
                elif event.end > bar + 1e-6:
                    first = bar - event.onset
                    remainder = event.end - bar
                    continuation = ElementTree.fromstring(ElementTree.tostring(event.element))
                    _truncate(event.element, first, divisions)
                    _set_duration(continuation, remainder, divisions)
                    _remove_tie(continuation, "start")
                    _add_tie(continuation, "stop")
                    _drop_type(continuation)
                    groups.setdefault((event.staff, event.voice), []).append(
                        Event(continuation, event.staff, event.voice, bar, remainder, event.rest, False)
                    )
                    moved += 1
            if not groups:
                continue
            fragments: list[list[ElementTree.Element]] = []
            for (staff, _voice), events in groups.items():
                offset = min(event.onset for event in events) - bar
                if offset >= next_bar - 1e-6:
                    continue
                number = next_voices.get(staff, _max_voice(next_measure, staff) + 1)
                next_voices[staff] = number + 1
                fragments.append(
                    _block(events, offset, bar, staff, divisions, next_measure, next_bar, number)
                )
            if fragments:
                insertion = _insertion_index(next_measure)
                payload: list[ElementTree.Element] = []
                for fragment in fragments:
                    payload.extend(fragment)
                next_measure[insertion:insertion] = payload
            for element in removals:
                if element in list(measure):
                    measure.remove(element)
                    moved += 1
        for measure in measures:
            _shrink_backups(measure)
        return PassResult(changed=moved)


def _truncate(note, duration: float, divisions: float) -> None:
    _set_duration(note, duration, divisions)
    _add_tie(note, "start")
    _drop_type(note)


def _remove_tie(note, kind: str) -> None:
    for tie in list(note.findall("tie")):
        if tie.get("type") == kind:
            note.remove(tie)
    notations = note.find("notations")
    if notations is not None:
        for tied in list(notations.findall("tied")):
            if tied.get("type") == kind:
                notations.remove(tied)


def _set_duration(note, duration: float, divisions: float) -> None:
    element = note.find("duration")
    if element is None:
        element = ElementTree.SubElement(note, "duration")
    element.text = str(int(round(duration * divisions)))


def _drop_type(note) -> None:
    for note_type in note.findall("type"):
        note.remove(note_type)


def _add_tie(note, kind: str) -> None:
    if note.find("pitch") is None:
        return
    if any(tie.get("type") == kind for tie in note.findall("tie")):
        return
    duration = note.find("duration")
    position = list(note).index(duration) + 1 if duration is not None else 0
    note.insert(position, ElementTree.Element("tie", {"type": kind}))
    notations = note.find("notations")
    if notations is None:
        notations = ElementTree.SubElement(note, "notations")
    if not any(tied.get("type") == kind for tied in notations.findall("tied")):
        ElementTree.SubElement(notations, "tied", {"type": kind})


def _max_voice(measure, staff: str) -> int:
    used = [
        int(note.findtext("voice"))
        for note in measure.iter("note")
        if (note.findtext("staff") or "1") == staff and (note.findtext("voice") or "").isdigit()
    ]
    return max(used, default=0)


def _shrink_backups(measure) -> None:
    """After removing overflow notes, the block's closing backup must match what is left.

    Only shorten: a backup may legitimately be shorter than the block before it (the OMR writes
    a partial rewind for an overlapping rest, e.g. Suzume m16 backup 4 after 28 ticks). Rewriting
    such a backup to the block length moved that rest to the barline.
    """
    children = list(measure)
    start = 0
    for index, child in enumerate(children):
        if child.tag != "backup":
            continue
        end = 0
        for item in children[start:index]:
            if item.tag == "note" and item.find("chord") is not None:
                continue
            if item.tag in ("note", "forward", "rest"):
                text = item.findtext("duration")
                if text is not None:
                    end += int(text)
        duration = child.find("duration")
        if duration is not None:
            current = int(duration.text or 0)
            if end < current:
                duration.text = str(end)
        start = index + 1


def _block(
    events, offset: float, bar: float, staff: str, divisions: float, measure, next_bar: float, number: int
) -> list[ElementTree.Element]:
    ordered = sorted(events, key=lambda event: (event.onset, event.chord))
    new_voice = str(number)
    fragment: list[ElementTree.Element] = []
    if offset > 1e-6:
        forward = ElementTree.Element("forward")
        ElementTree.SubElement(forward, "duration").text = str(int(round(offset * divisions)))
        fragment.append(forward)
    cursor = offset
    position = 0
    while position < len(ordered):
        onset = ordered[position].onset - bar
        group = []
        while position < len(ordered) and abs(ordered[position].onset - bar - onset) < 1e-6:
            group.append(ordered[position])
            position += 1
        gap = onset - cursor
        if gap > 1e-6:
            forward = ElementTree.Element("forward")
            ElementTree.SubElement(forward, "duration").text = str(int(round(gap * divisions)))
            fragment.append(forward)
            cursor += gap
        length = 0.0
        for event in group:
            element = event.element
            voice = element.find("voice")
            if voice is None:
                voice = ElementTree.SubElement(element, "voice")
            voice.text = new_voice
            fragment.append(element)
            length = max(length, event.duration)
        cursor += length
    if cursor < next_bar - 1e-6:
        rest = ElementTree.Element("note")
        ElementTree.SubElement(rest, "rest")
        ElementTree.SubElement(rest, "duration").text = str(
            int(round((next_bar - cursor) * divisions))
        )
        ElementTree.SubElement(rest, "voice").text = new_voice
        ElementTree.SubElement(rest, "staff").text = staff
        fragment.append(rest)
        cursor = next_bar
    # the block fills the bar exactly, so the backup returns the cursor to 0 for the original voices
    backup = ElementTree.Element("backup")
    ElementTree.SubElement(backup, "duration").text = str(int(round(cursor * divisions)))
    fragment.append(backup)
    return fragment


def _insertion_index(measure) -> int:
    index = 0
    for position, child in enumerate(measure):
        if child.tag in ("attributes", "print", "sound"):
            index = position + 1
        else:
            break
    return index


class DropOverflowRests:
    spec = PassSpec(
        name="drop_overflow_rests",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("stray-rests",),
        description="drop rests that start at or beyond the barline",
        measure="rests beginning after the measure ends",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        meter = (4.0, 4.0)
        divisions = doc.divisions()
        changed = 0
        for measure in doc.measures():
            declared = doc.time_signature(measure)
            if declared is not None:
                meter = declared
            bar = meter[0] * 4.0 / meter[1]
            touched = False
            for event in list(doc.events(measure)):
                if not event.rest:
                    continue
                if event.onset >= bar - 1e-6:
                    if event.element in list(measure):
                        measure.remove(event.element)
                        changed += 1
                        touched = True
                elif event.end > bar + 1e-6:
                    duration = event.element.find("duration")
                    if duration is not None:
                        duration.text = str(int(round((bar - event.onset) * divisions)))
                        changed += 1
                        touched = True
            if touched:
                _shrink_backups(measure)
        return PassResult(changed=changed)


REBASE_MEASURES = RebaseMeasures()
DROP_OVERFLOW_RESTS = DropOverflowRests()
