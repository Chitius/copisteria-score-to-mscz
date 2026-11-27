"""Measure-length repair: pad a voice that stops short of the barline."""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.document import Document
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase

_TYPE_BY_DURATION = {
    4.0: "whole",
    2.0: "half",
    1.0: "quarter",
    0.5: "eighth",
    0.25: "16th",
    0.125: "32nd",
}


class FillShortMeasures:
    spec = PassSpec(
        name="fill_short_measures",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("rest-padding",),
        description=(
            "append a rest when a voice stops before the barline (pickup/last bar excluded) and "
            "trim a padding rest that starts before the note it follows in the same voice"
        ),
        measure="voices ending before the barline; padding rests overlapping their own voice",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        pad_last = bool(ctx.options.get("pad_last_measure", False))
        changed = 0
        for _part_id, part in doc.iter_parts():
            meter = (4.0, 4.0)
            measures = doc.part_measures(part)
            for index, measure in enumerate(measures):
                divisions = doc.effective_divisions(measure, part)
                declared = doc.time_signature(measure)
                if declared is not None:
                    meter = declared
                bar = meter[0] * 4.0 / meter[1]
                changed += _trim_overlapping_padding_rests(doc, measure, divisions)
                if measure.get("implicit") == "yes":
                    continue  # an anacrusis is short by design
                if not pad_last and index == len(measures) - 1:
                    continue
                ends: dict[tuple[str, str], float] = {}
                for event in doc.events(measure, divisions):
                    key = (event.staff, event.voice)
                    ends[key] = max(ends.get(key, 0.0), event.end)
                for (staff, voice), end in sorted(ends.items()):
                    if end >= bar - 1e-6:
                        continue
                    missing = bar - end
                    insert_at = _insert_index(measure, staff, voice)
                    if insert_at is None:
                        continue
                    rest = ElementTree.Element("note")
                    ElementTree.SubElement(rest, "rest")
                    ElementTree.SubElement(rest, "duration").text = str(int(round(missing * divisions)))
                    ElementTree.SubElement(rest, "voice").text = voice
                    note_type = _TYPE_BY_DURATION.get(round(missing, 3))
                    if note_type:
                        ElementTree.SubElement(rest, "type").text = note_type
                    ElementTree.SubElement(rest, "staff").text = staff
                    measure.insert(insert_at, rest)
                    _extend_following_backup(measure, insert_at + 1, int(round(missing * divisions)))
                    changed += 1
        return PassResult(changed=changed)


def _trim_overlapping_padding_rests(
    doc: Document, measure, divisions: float | None = None
) -> int:
    """Trim a padding rest that starts before the note it follows in the same voice.

    OMR sometimes writes a bar-filling rest one grid step early, so it overlaps the end of the
    note before it in the same voice (Suzume m16: rest 3.0-4.0 under a note ending at 3.5). The
    rest's end is authoritative for a padding rest; move only its start to the note's end.
    """
    active_divisions = divisions if divisions is not None else doc.effective_divisions(measure)
    streams: dict[tuple[str, str], list] = {}
    for event in doc.events(measure, active_divisions):
        streams.setdefault((event.staff, event.voice), []).append(event)
    changed = 0
    for stream in streams.values():
        stream.sort(key=lambda event: (event.onset, event.chord))
        end = 0.0
        for event in stream:
            if not event.rest or event.onset >= end - 1e-6:
                end = max(end, event.end)
                continue
            old_ticks = int(round(event.duration * active_divisions))
            shift = int(round((end - event.onset) * active_divisions))
            new_ticks = old_ticks - shift
            position = _element_index(measure, event.element)
            if position is None:
                continue
            if new_ticks <= 0:
                measure.remove(event.element)
                _shift_following_backup(measure, position, -old_ticks)
            else:
                forward = ElementTree.Element("forward")
                ElementTree.SubElement(forward, "duration").text = str(shift)
                ElementTree.SubElement(forward, "voice").text = event.voice
                ElementTree.SubElement(forward, "staff").text = event.staff
                event.element.find("duration").text = str(new_ticks)
                _retag(event.element, new_ticks / active_divisions)
                measure.insert(position, forward)
            changed += 1
            end = max(end, event.end)
    return changed


def _element_index(measure, element) -> int | None:
    for index, child in enumerate(measure):
        if child is element:
            return index
    return None


def _shift_following_backup(measure, index: int, ticks: int) -> None:
    """After a rest inside a voice block is removed, its closing backup is that much shorter."""
    for child in list(measure)[index:]:
        if child.tag == "backup":
            text = child.findtext("duration")
            if text is not None:
                child.find("duration").text = str(max(0, int(text) + ticks))
            return


def _retag(note, duration: float) -> None:
    note_type = _TYPE_BY_DURATION.get(round(duration, 3))
    if note_type is None:
        return
    element = note.find("type")
    if element is None:
        element = ElementTree.SubElement(note, "type")
    element.text = note_type
    for dot in list(note.findall("dot")):
        note.remove(dot)


def _extend_following_backup(measure, index: int, ticks: int) -> None:
    """A longer voice needs a longer backup to put the next voice back at the barline."""
    for child in list(measure)[index:]:
        if child.tag == "backup":
            text = child.findtext("duration")
            if text is not None:
                child.find("duration").text = str(int(text) + ticks)
            return


def _insert_index(measure, staff: str, voice: str):
    """Index right after the last element of that voice's stream."""
    cursor = 0
    previous = None
    last = None
    for index, item in enumerate(measure):
        if item.tag in ("backup", "forward"):
            text = item.findtext("duration")
            if text is not None:
                value = int(text)
                cursor += -value if item.tag == "backup" else value
            previous = None
            continue
        if item.tag != "note":
            previous = None
            continue
        text = item.findtext("duration")
        if text is None:
            previous = None
            continue
        duration = int(text)
        chord = item.find("chord") is not None
        onset = previous if chord and previous is not None else cursor
        if not chord:
            cursor += duration
        previous = onset
        if (item.findtext("staff") or "1") == staff and (item.findtext("voice") or "1") == voice:
            last = index
    return None if last is None else last + 1


FILL_PASS = FillShortMeasures()
