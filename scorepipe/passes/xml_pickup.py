"""Anacrusis: place the opening short bar at the end of its printed bar.

copisteria writes a pickup as beat 1 of a full bar and pads the remainder with rests.  The old
skill moved the sounding events to the end of the bar (``paddingLeft``), which is also how the
printed source often shows a short upbeat at the end of the first bar.  Do the same in MusicXML and
leave the measure non-implicit, so no courtesy time signature is introduced.
"""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.document import Document
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase


class MarkPickup:
    spec = PassSpec(
        name="mark_pickup",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("pickup-marking",),
        description="move a short opening pickup to the end of its printed bar",
        measure="opening bars whose sounding music stops before the barline",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        first_measures: list[tuple[ElementTree.Element, ElementTree.Element]] = []
        for _part_id, part in doc.iter_parts():
            measures = doc.part_measures(part)
            if not measures:
                return PassResult()
            first_measures.append((part, measures[0]))
        if not first_measures:
            return PassResult()
        if all(first.get("implicit") == "yes" for _part, first in first_measures):
            return PassResult()

        meter = next(
            (doc.time_signature(first) for _part, first in first_measures if doc.time_signature(first)),
            (4.0, 4.0),
        )
        bar = meter[0] * 4.0 / meter[1]
        part_events = [
            (part, first, doc.events(first, doc.effective_divisions(first, part)))
            for part, first in first_measures
        ]
        all_events = [event for _part, _first, events in part_events for event in events]
        if not all_events:
            return PassResult()
        all_sounding = [event for event in all_events if not event.rest]
        if not all_sounding:
            return PassResult()
        if min(event.onset for event in all_sounding) > 1e-6:
            return PassResult()  # starts with a rest: not a pickup
        end = max(event.end for event in all_sounding)
        if end >= bar - 1e-6:
            return PassResult()
        total_end = max(event.end for event in all_events)
        if total_end < bar - 1e-6:
            # A genuinely short pickup bar: keep it implicit across every part.
            changed = 0
            for _part, first, _events in part_events:
                if first.get("implicit") != "yes":
                    first.set("implicit", "yes")
                    changed += 1
            return PassResult(changed=changed)
        if any(first.get("implicit") == "yes" for _part, first in first_measures):
            return PassResult()
        shift = bar - end
        if shift <= 1e-6:
            return PassResult()
        changed = 0
        for part, first, events in part_events:
            if any(not event.rest for event in events):
                _move_to_bar_end(first, shift, doc.effective_divisions(first, part))
                changed += 1
        return PassResult(changed=changed)


def _move_to_bar_end(measure, shift: float, divisions: float) -> None:
    measure[:] = _blocks(measure, shift, divisions)


def _is_sounding_note(child: ElementTree.Element) -> bool:
    return child.tag == "note" and child.find("rest") is None


def _is_rest_note(child: ElementTree.Element) -> bool:
    return child.tag == "note" and child.find("rest") is not None


def _blocks(measure, shift: float, divisions: float) -> list:
    """Rebuild each voice block with a leading forward of ``shift`` and no padding rests."""
    result: list = []
    segment: list = []
    segments: list[list] = []
    for child in list(measure):
        if child.tag == "backup":
            segments.append(segment)
            segment = []
        else:
            segment.append(child)
    segments.append(segment)

    first = True
    for segment in segments:
        if not any(_is_sounding_note(child) for child in segment):
            continue
        segment = [child for child in segment if not _is_rest_note(child)]
        first_note = next(index for index, child in enumerate(segment) if child.tag == "note")
        forward = ElementTree.Element("forward")
        ElementTree.SubElement(forward, "duration").text = str(int(round(shift * divisions)))
        segment.insert(first_note, forward)
        if not first:
            backup = ElementTree.Element("backup")
            ElementTree.SubElement(backup, "duration").text = str(
                int(round(_segment_end(previous, divisions) * divisions))
            )
            result.append(backup)
        result.extend(segment)
        first = False
        previous = segment
    return result


def _segment_end(segment: list, divisions: float) -> float:
    total = 0
    for child in segment:
        if child.tag in ("note", "forward"):
            text = child.findtext("duration")
            if text and (child.tag != "note" or child.find("chord") is None):
                total += int(text)
    return total / divisions


MARK_PICKUP = MarkPickup()
