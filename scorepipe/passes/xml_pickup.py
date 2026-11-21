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
        measures = doc.measures()
        if not measures:
            return PassResult()
        first = measures[0]
        if first.get("implicit") == "yes":
            return PassResult()
        meter = doc.time_signature(first) or (4.0, 4.0)
        bar = meter[0] * 4.0 / meter[1]
        events = doc.events(first)
        if not events:
            return PassResult()
        sounding = [event for event in events if not event.rest]
        if not sounding:
            return PassResult()
        if min(event.onset for event in sounding) > 1e-6:
            return PassResult()  # starts with a rest: not a pickup
        end = max(event.end for event in sounding)
        if end >= bar - 1e-6:
            return PassResult()
        total_end = max(event.end for event in events)
        if total_end < bar - 1e-6:
            # A genuinely short pickup bar: keep it implicit and let the next bar start the metre.
            first.set("implicit", "yes")
            return PassResult(changed=1)
        shift = bar - end
        if shift <= 1e-6:
            return PassResult()
        _move_to_bar_end(first, shift, doc.divisions())
        return PassResult(changed=1)


def _move_to_bar_end(measure, shift: float, divisions: float) -> None:
    measure[:] = _blocks(measure, shift, divisions)


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
        if not any(child.tag == "note" and child.find("pitch") is not None for child in segment):
            continue
        segment = [child for child in segment if not (child.tag == "note" and child.find("pitch") is None)]
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
