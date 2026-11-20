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
        description="append a rest when a voice stops before the barline (pickup/last bar excluded)",
        measure="voices ending before the barline",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        divisions = doc.divisions()
        pad_last = bool(ctx.options.get("pad_last_measure", False))
        changed = 0
        meter = (4.0, 4.0)
        measures = doc.measures()
        for index, measure in enumerate(measures):
            declared = doc.time_signature(measure)
            if declared is not None:
                meter = declared
            bar = meter[0] * 4.0 / meter[1]
            if measure.get("implicit") == "yes":
                continue  # an anacrusis is short by design
            if not pad_last and index == len(measures) - 1:
                continue
            ends: dict[tuple[str, str], float] = {}
            for event in doc.events(measure):
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
                changed += 1
        return PassResult(changed=changed)


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
