"""Overflow notes that only repeat the next bar's opening are OMR bleed, not music."""

from __future__ import annotations

from ..core.document import Document
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase


class DropOverflowDuplicates:
    spec = PassSpec(
        name="drop_overflow_duplicates",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("overflow-notes",),
        description="drop a note past the barline when the next bar starts with the same pitch there",
        measure="overflow notes duplicated at the next barline",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        changed = 0
        for _part_id, part in doc.iter_parts():
            measures = doc.part_measures(part)
            meter = (4.0, 4.0)
            for index, measure in enumerate(measures):
                declared = doc.time_signature(measure)
                if declared is not None:
                    meter = declared
                bar = meter[0] * 4.0 / meter[1]
                if index + 1 >= len(measures):
                    continue
                next_measure = measures[index + 1]
                following = _index_by_key(doc, next_measure)
                for event in doc.events(measure):
                    if event.rest or event.onset < bar - 1e-6:
                        continue
                    pitch = _pitch(event.element)
                    if pitch is None:
                        continue
                    target_onset = round(event.onset - bar, 4)
                    key = (event.staff, event.voice, target_onset, pitch)
                    if key in following:
                        elements = [event.element]
                        if event.element.find("chord") is None:
                            children = list(measure)
                            position = children.index(event.element) + 1
                            while (
                                position < len(children)
                                and children[position].tag == "note"
                                and children[position].find("chord") is not None
                            ):
                                elements.append(children[position])
                                position += 1
                        for element in elements:
                            if element in list(measure):
                                measure.remove(element)
                                changed += 1
        return PassResult(changed=changed)


def _index_by_key(doc: Document, measure) -> set[tuple[str, str, float, str]]:
    keys: set[tuple[str, str, float, str]] = set()
    for event in doc.events(measure):
        if event.rest:
            continue
        pitch = _pitch(event.element)
        if pitch is None:
            continue
        keys.add((event.staff, event.voice, round(event.onset, 4), pitch))
    return keys


def _pitch(note) -> str | None:
    pitch = note.find("pitch")
    if pitch is None:
        return None
    return (
        (pitch.findtext("step") or "")
        + (pitch.findtext("alter") or "0")
        + (pitch.findtext("octave") or "")
    )


DROP_OVERFLOW_DUPLICATES = DropOverflowDuplicates()
