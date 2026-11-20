"""Display-layer duplicates: identical pedal spanners and identical text objects."""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.mscx import MsxcDocument
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase


class DedupePedalSpanners:
    spec = PassSpec(
        name="dedupe_pedal_spanners",
        phase=Phase.DISPLAY,
        kind=Kind.MECHANICAL,
        owns=("pedal-spanners",),
        description="remove byte-identical pedal spanners inside one voice",
        measure="duplicate pedal spanners",
    )

    def run(self, doc: MsxcDocument, ctx: Context) -> PassResult:
        removed = 0
        for _staff, _index, measure in doc.iter_measures():
            for voice in doc.voices(measure):
                seen: set[str] = set()
                for child in list(voice):
                    if child.tag != "Spanner" or child.get("type") != "Pedal":
                        continue
                    signature = _signature(child)
                    if signature in seen:
                        voice.remove(child)
                        removed += 1
                    else:
                        seen.add(signature)
        return PassResult(changed=removed)


class DedupeTextObjects:
    spec = PassSpec(
        name="dedupe_text_objects",
        phase=Phase.DISPLAY,
        kind=Kind.MECHANICAL,
        owns=("display-text-duplicates",),
        description="remove a second text object with the same words in the same measure",
        measure="duplicate text objects in a measure",
    )

    def run(self, doc: MsxcDocument, ctx: Context) -> PassResult:
        text_tags = {"StaffText", "SystemText", "Expression", "Tempo"}
        removed = 0
        for _staff, _index, measure in doc.iter_measures():
            seen: set[str] = set()
            for voice in doc.voices(measure):
                for child in list(voice):
                    if child.tag not in text_tags:
                        continue
                    text = (child.findtext("text") or "").strip()
                    if not text:
                        continue
                    signature = (child.tag, text)
                    if signature in seen:
                        voice.remove(child)
                        removed += 1
                    else:
                        seen.add(signature)
        return PassResult(changed=removed)


class DropEmptyVoices:
    spec = PassSpec(
        name="drop_empty_voices",
        phase=Phase.DISPLAY,
        kind=Kind.MECHANICAL,
        owns=("empty-voices",),
        description="remove voice slots that contain no chord, rest or spanner",
        measure="empty voice slots",
    )

    def run(self, doc: MsxcDocument, ctx: Context) -> PassResult:
        removed = 0
        for _staff, _index, measure in doc.iter_measures():
            for voice in list(measure.findall("voice")):
                if any(child.tag not in ("BarLine", "location") for child in voice):
                    continue
                barlines = list(voice.findall("BarLine"))
                if barlines:
                    owner = _barline_owner(measure, voice)
                    if owner is None:
                        # no other voice can carry the barline; keeping the slot is the
                        # only way not to delete notation
                        continue
                    for barline in barlines:
                        voice.remove(barline)
                        owner.append(barline)
                measure.remove(voice)
                removed += 1
        return PassResult(changed=removed)


def _barline_owner(measure, voice):
    """The voice that should adopt a BarLine from an otherwise empty slot.

    Prefer the immediately preceding voice (MuseScore's canonical order puts chord voices
    first), otherwise the next one.  ``None`` means the measure has no other voice at all.
    """
    before: list = []
    after: list = []
    seen = False
    for other in measure.findall("voice"):
        if other is voice:
            seen = True
            continue
        (after if seen else before).append(other)
    if before:
        return before[-1]
    return after[0] if after else None


TEXT_TAGS = {
    "Tempo",
    "StaffText",
    "SystemText",
    "RehearsalMark",
    "Expression",
    "Dynamic",
    "Harmony",
    "Fingering",
}


class MergeTextVoices:
    spec = PassSpec(
        name="merge_text_voices",
        phase=Phase.DISPLAY,
        kind=Kind.MECHANICAL,
        owns=("text-voice-slots",),
        description="move text objects out of their own zero-length voice into the first chord voice",
        measure="text-only voice slots",
    )

    def run(self, doc: MsxcDocument, ctx: Context) -> PassResult:
        removed = 0
        for _staff, _index, measure in doc.iter_measures():
            voices = list(measure.findall("voice"))
            chords = [voice for voice in voices if voice.findall("Chord")]
            if not chords:
                continue
            target = chords[0]
            for voice in voices:
                if voice is target or voice.findall("Chord") or voice.findall("Rest"):
                    continue
                # every child that is not a barline or cursor positioning is content:
                # move it into the owning voice instead of deleting it with the slot
                movable = [
                    child for child in voice if child.tag not in ("BarLine", "location")
                ]
                if not movable:
                    continue
                position = _content_index(target)
                for child in movable:
                    voice.remove(child)
                    target.insert(position, child)
                    position += 1
                if any(child.tag not in ("BarLine", "location") for child in voice):
                    continue  # safety: never drop a slot that still holds content
                for barline in list(voice.findall("BarLine")):
                    voice.remove(barline)
                    if target.find("BarLine") is None:
                        target.append(barline)
                measure.remove(voice)
                removed += 1
        return PassResult(changed=removed)


def _content_index(voice) -> int:
    """Where MuseScore keeps text objects: after clef/key/time metadata, before chords."""
    for position, child in enumerate(voice):
        if child.tag not in ("Clef", "KeySig", "TimeSig", "eid"):
            return position
    return len(voice)


DISPLAY_DEDUPE_PASSES = [
    DedupePedalSpanners(),
    DedupeTextObjects(),
    MergeTextVoices(),
    DropEmptyVoices(),
]


def _signature(element) -> tuple:
    """Structure + attributes + text, ignoring tail whitespace."""
    return (
        element.tag,
        tuple(sorted(element.attrib.items())),
        (element.text or "").strip(),
        tuple(_signature(child) for child in element),
    )
