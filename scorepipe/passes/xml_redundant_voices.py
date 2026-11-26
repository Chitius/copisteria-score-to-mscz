"""Remove a voice whose every note is already sounded by another voice on the same staff.

OMR sometimes leaves a second voice that merely repeats notes from the first one (laputa m27: the
bass line's second voice duplicated G3/E4 an octave below the melody). The duplicate voice is not
music; it makes MuseScore store cross-staff notes (``<staffMove>1</staffMove>``) that appear to
belong to the other staff.
"""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.directions import direction_insertion_index, direction_onsets, set_direction_offset
from ..core.document import Document
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase


class DropRedundantVoices:
    spec = PassSpec(
        name="drop_redundant_voices",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("redundant-voices",),
        description="drop a secondary voice whose notes are all duplicated by the primary voice",
        measure="voices that only repeat another voice",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        changed = 0
        for _number, measure in doc.iter_measures():
            by_staff: dict[str, dict[str, list]] = {}
            all_by_staff: dict[str, dict[str, list]] = {}
            for event in doc.events(measure):
                all_by_staff.setdefault(event.staff, {}).setdefault(event.voice, []).append(event)
                if event.rest:
                    continue
                by_staff.setdefault(event.staff, {}).setdefault(event.voice, []).append(event)
            for staff, all_voices in all_by_staff.items():
                sounding = by_staff.get(staff, {})
                if not sounding:
                    continue
                for voice, events in all_voices.items():
                    if voice in sounding:
                        continue
                    if not events or not all(event.rest for event in events):
                        continue
                    if _remove_voice(measure, events):
                        changed += 1
            for _staff, voices in by_staff.items():
                if len(voices) < 2:
                    continue
                primary_voice = max(
                    voices,
                    key=lambda voice: (
                        len(voices[voice]),
                        -int(voice) if voice.isdigit() else 0,
                    ),
                )
                primary = voices[primary_voice]
                for voice, events in voices.items():
                    if voice == primary_voice:
                        continue
                    if not _redundant(events, primary):
                        continue
                    if _remove_voice(measure, events):
                        changed += 1
        return PassResult(changed=changed)


def _redundant(events: list, primary: list) -> bool:
    for event in events:
        pitch = _pitch(event.element)
        if pitch is None:
            continue
        covered = any(
            _pitch(other.element) == pitch
            and other.onset <= event.onset + 1e-6
            and event.onset < other.end - 1e-6
            for other in primary
        )
        if not covered:
            return False
    return True


def _pitch(note) -> str | None:
    pitch = note.find("pitch")
    if pitch is None:
        return None
    return (
        (pitch.findtext("step") or "")
        + (pitch.findtext("alter") or "0")
        + (pitch.findtext("octave") or "")
    )


def _remove_voice(measure, events: list) -> bool:
    onsets = direction_onsets(measure)
    elements = {id(event.element) for event in events}
    children = list(measure)
    starts = [0] + [index + 1 for index, child in enumerate(children) if child.tag == "backup"]
    ends = [index for index, child in enumerate(children) if child.tag == "backup"] + [len(children)]
    for start, end in zip(starts, ends):
        segment = children[start:end]
        if not any(child.tag == "note" and id(child) in elements for child in segment):
            continue
        rescued_directions: list[ElementTree.Element] = []
        for child in segment:
            if child.tag in ("attributes", "print", "sound", "barline"):
                continue
            if child.tag == "direction":
                set_direction_offset(child, onsets.get(id(child), 0))
                rescued_directions.append(child)
            measure.remove(child)
        if start > 0:
            measure.remove(children[start - 1])
        elif end < len(children):
            measure.remove(children[end])
        if rescued_directions:
            insert_at = direction_insertion_index(measure)
            measure[insert_at:insert_at] = rescued_directions
        return True
    return False


DROP_REDUNDANT_VOICES = DropRedundantVoices()
