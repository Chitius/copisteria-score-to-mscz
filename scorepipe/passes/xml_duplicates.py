"""Duplicate notes at the same staff/voice/onset/pitch are OMR noise."""

from __future__ import annotations

from ..core.document import Document
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase


class DropDuplicateNotes:
    spec = PassSpec(
        name="drop_duplicate_notes",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("duplicate-notes",),
        description="remove repeated notes with the same staff, voice, onset and pitch",
        measure="duplicate notes at one position",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        changed = 0
        for _number, measure in doc.iter_measures():
            children = list(measure)
            groups: dict[tuple[str, str, float, str], list] = {}
            for event in doc.events(measure):
                if event.rest:
                    continue
                pitch = event.element.find("pitch")
                if pitch is None:
                    continue
                name = (
                    (pitch.findtext("step") or "")
                    + (pitch.findtext("alter") or "0")
                    + (pitch.findtext("octave") or "")
                )
                key = (event.staff, event.voice, round(event.onset, 4), name)
                groups.setdefault(key, []).append(event)
            for events in groups.values():
                if len(events) < 2:
                    continue
                keeper = max(events, key=lambda event: event.duration)
                for event in events:
                    if event is keeper:
                        continue
                    if not _removable(children, event.element):
                        continue
                    if event.element in list(measure):
                        measure.remove(event.element)
                        changed += 1
        return PassResult(changed=changed)


def _removable(children: list, element) -> bool:
    """A base note followed by chord members cannot be removed without orphaning them."""
    if element.find("chord") is not None:
        return True
    try:
        index = children.index(element)
    except ValueError:
        return False
    if index + 1 < len(children):
        following = children[index + 1]
        if following.tag == "note" and following.find("chord") is not None:
            return False
    return True


DROP_DUPLICATE_NOTES = DropDuplicateNotes()
