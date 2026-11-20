"""Fold an exactly-aligned secondary voice into the primary voice as chord members.

Only voices whose every note starts on a primary chord of exactly the same length are merged; a
secondary voice with a rest, a different onset or a different duration is left alone. The merged
notes are copied into the primary chord, then the emptied voice block is removed.
"""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.document import Document
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase


class MergeAlignedVoices:
    spec = PassSpec(
        name="merge_aligned_voices",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("voice-merge",),
        description="fold a secondary voice into the primary chords when every note aligns exactly",
        measure="mergeable secondary voices",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        merged = 0
        for _number, measure in doc.iter_measures():
            events = doc.events(measure)
            if len({event.staff for event in events}) > 1:
                # the block/backup structure mixes staves; removing a block can shift the other
                # staff's notes, so leave multi-staff measures to their own alignment
                continue
            merged += _merge_measure(doc, measure)
        return PassResult(changed=merged)


def _merge_measure(doc: Document, measure) -> int:
    by_staff: dict[str, dict[str, list]] = {}
    for event in doc.events(measure):
        by_staff.setdefault(event.staff, {}).setdefault(event.voice, []).append(event)
    merged = 0
    for staff, voices in by_staff.items():
        note_voices = {voice: events for voice, events in voices.items() if any(not e.rest for e in events)}
        if len(note_voices) < 2:
            continue
        primary_voice = max(note_voices, key=lambda voice: (sum(1 for e in note_voices[voice] if not e.rest), voice))
        primary_notes = [event for event in note_voices[primary_voice] if not event.rest]
        primary_onsets = {}
        for event in primary_notes:
            if not event.chord:
                primary_onsets.setdefault(round(event.onset, 4), event)
        for voice, events in note_voices.items():
            if voice == primary_voice:
                continue
            notes = [event for event in events if not event.rest]
            if not notes or any(event.rest for event in events):
                continue
            if not _aligned(notes, primary_onsets):
                continue
            if not _clean_block(measure, staff, voice):
                continue
            clones = [(event, _clone(event, primary_onsets[round(event.onset, 4)])) for event in notes]
            if not _remove_block(measure, staff, voice):
                continue
            for event, clone in clones:
                _insert_chord(measure, primary_onsets[round(event.onset, 4)].element, clone)
            merged += 1
    return merged


def _aligned(notes, primary_onsets) -> bool:
    for event in notes:
        primary = primary_onsets.get(round(event.onset, 4))
        if primary is None:
            return False
        if abs(primary.duration - event.duration) > 1e-6:
            return False
    return True


def _clean_block(measure, staff: str, voice: str) -> bool:
    for segment in _segments(measure):
        keys = {
            (note.findtext("staff") or "1", note.findtext("voice") or "1")
            for note in segment
            if note.tag == "note"
        }
        if keys != {(staff, voice)}:
            continue
        allowed = {"note", "backup", "forward", "location", "direction", "attributes", "print", "sound"}
        return all(child.tag in allowed for child in segment)
    return False


def _segments(measure) -> list[list]:
    children = list(measure)
    starts = [0] + [index + 1 for index, child in enumerate(children) if child.tag == "backup"]
    ends = [index for index, child in enumerate(children) if child.tag == "backup"] + [len(children)]
    return [children[start:end] for start, end in zip(starts, ends) if start < end]


def _remove_block(measure, staff: str, voice: str) -> bool:
    children = list(measure)
    starts = [0] + [index + 1 for index, child in enumerate(children) if child.tag == "backup"]
    ends = [index for index, child in enumerate(children) if child.tag == "backup"] + [len(children)]
    for start, end in zip(starts, ends):
        if start >= end:
            continue
        segment = children[start:end]
        keys = {
            (note.findtext("staff") or "1", note.findtext("voice") or "1")
            for note in segment
            if note.tag == "note"
        }
        if keys != {(staff, voice)}:
            continue
        for child in segment:
            if child.tag in ("note", "forward", "location", "direction"):
                measure.remove(child)
        if start > 0 and children[start - 1] in list(measure):
            measure.remove(children[start - 1])
        elif end < len(children) and children[end] in list(measure):
            measure.remove(children[end])
        return True
    return False


def _clone(event, primary) -> ElementTree.Element:
    clone = ElementTree.fromstring(ElementTree.tostring(event.element))
    if clone.find("chord") is None:
        clone.insert(0, ElementTree.Element("chord"))
    voice = clone.find("voice")
    if voice is None:
        voice = ElementTree.SubElement(clone, "voice")
    voice.text = primary.voice
    # the duration is already equal to the primary's by _aligned()
    return clone


def _insert_chord(measure, base_note, clone) -> None:
    children = list(measure)
    index = children.index(base_note)
    existing = [_pitch_key(base_note)]
    while index + 1 < len(children) and children[index + 1].tag == "note" and children[index + 1].find("chord") is not None:
        index += 1
        existing.append(_pitch_key(children[index]))
    if _pitch_key(clone) in existing:
        return  # the primary chord already sounds this pitch; do not double it
    measure.insert(index + 1, clone)


def _pitch_key(note) -> str | None:
    pitch = note.find("pitch")
    if pitch is None:
        return None
    return (
        (pitch.findtext("step") or "")
        + (pitch.findtext("alter") or "0")
        + (pitch.findtext("octave") or "")
    )


MERGE_ALIGNED_VOICES = MergeAlignedVoices()
