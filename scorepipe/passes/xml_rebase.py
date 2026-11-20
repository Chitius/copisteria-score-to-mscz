"""Move notes that start past the barline into the next measure as a new voice.

The moved notes keep their relative rhythm: the block starts with a forward for the offset, notes
follow in onset order, and a backup of the block's length lets the original voices start at 0 again.
This is conservative: if the overflow would land past the *next* barline too, the measure is left
alone and the verifier keeps reporting it.
"""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.document import Document
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase


class RebaseMeasures:
    spec = PassSpec(
        name="rebase_measures",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("measure-content",),
        description="move notes starting past the barline into the next measure as a new voice",
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
            overflow: dict[tuple[str, str], list] = {}
            for event in doc.events(measure):
                if event.onset < bar - 1e-6:
                    continue
                overflow.setdefault((event.staff, event.voice), []).append(event)
            if not overflow:
                continue
            fragments: list[list[ElementTree.Element]] = []
            for (staff, _voice), events in overflow.items():
                offset = min(event.onset for event in events) - bar
                if offset >= next_bar - 1e-6:
                    continue
                fragment = _block(events, offset, bar, staff, divisions, next_measure, next_bar)
                fragments.append(fragment)
                for event in events:
                    measure.remove(event.element)
                    moved += 1
            if not fragments:
                continue
            insertion = _insertion_index(next_measure)
            payload: list[ElementTree.Element] = []
            for fragment in fragments:
                payload.extend(fragment)
            next_measure[insertion:insertion] = payload
        return PassResult(changed=moved)


def _block(
    events, offset: float, bar: float, staff: str, divisions: float, measure, next_bar: float
) -> list[ElementTree.Element]:
    ordered = sorted(events, key=lambda event: (event.onset, event.chord))
    new_voice = _next_voice(measure, staff)
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
        ElementTree.SubElement(rest, "duration").text = str(int(round((next_bar - cursor) * divisions)))
        ElementTree.SubElement(rest, "voice").text = new_voice
        ElementTree.SubElement(rest, "staff").text = staff
        fragment.append(rest)
        cursor = next_bar
    # the block fills the bar exactly, so the backup returns the cursor to 0 for the original voices
    backup = ElementTree.Element("backup")
    ElementTree.SubElement(backup, "duration").text = str(int(round(cursor * divisions)))
    fragment.append(backup)
    return fragment


def _next_voice(measure, staff: str) -> str:
    used = set()
    for note in measure.iter("note"):
        if (note.findtext("staff") or "1") != staff:
            continue
        text = note.findtext("voice") or "1"
        if text.isdigit():
            used.add(int(text))
    return str(max(used) + 1 if used else 1)


def _insertion_index(measure) -> int:
    index = 0
    for position, child in enumerate(measure):
        if child.tag in ("attributes", "print", "sound"):
            index = position + 1
        else:
            break
    return index


REBASE_MEASURES = RebaseMeasures()
