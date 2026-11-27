"""Shared helpers and page-event indexing for page-level restoration passes."""

from __future__ import annotations

from xml.etree import ElementTree

from ...core.document import Document
from ...core.pass_base import Context


def _offsets(pages) -> list[int]:
    offsets = []
    running = 0
    for count in pages.measure_counts:
        offsets.append(running)
        running += count
    return offsets


def _page_events(root) -> list[tuple]:
    """(measure_index, staff, voice, onset, duration, pitch, element) for one page."""
    part = root.find("part")
    if part is None:
        return []
    divisions = float(root.findtext(".//divisions") or 10080)
    events = []
    for measure_index, measure in enumerate(part.findall("measure"), start=1):
        cursor = 0
        previous = None
        for item in measure:
            if item.tag in ("backup", "forward"):
                text = item.findtext("duration")
                if text is None:
                    continue
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
            pitch = item.find("pitch")
            events.append(
                (
                    measure_index,
                    item.findtext("staff") or "1",
                    item.findtext("voice") or "1",
                    round(onset / divisions, 4),
                    duration / divisions,
                    _pitch_name(pitch),
                    item,
                )
            )
    return events


def _pitch_name(pitch) -> str | None:
    if pitch is None:
        return None
    return (
        (pitch.findtext("step") or "")
        + (pitch.findtext("alter") or "0")
        + (pitch.findtext("octave") or "")
    )


def _merged_index(doc: Document) -> dict[tuple, ElementTree.Element]:
    index = {}
    for number, measure in doc.iter_measures():
        for event in doc.events(measure):
            if event.rest:
                continue
            pitch = event.element.find("pitch")
            name = _pitch_name(pitch)
            if name is None:
                continue
            index[(number, event.staff, round(event.onset, 4), name)] = event.element
    return index


def _merged_onset_index(doc: Document) -> dict[tuple, ElementTree.Element]:
    index = {}
    for number, measure in doc.iter_measures():
        for event in doc.events(measure):
            if event.rest:
                continue
            index.setdefault((number, event.staff, round(event.onset, 4)), event.element)
    return index


class PageRestoreMixin:
    def _model(self, ctx: Context):
        model = getattr(ctx, "pages", None)
        if model is None or not getattr(model, "pages", None):
            return None
        return model
