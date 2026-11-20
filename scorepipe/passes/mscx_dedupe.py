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
            voices = list(measure.findall("voice"))
            for position, voice in enumerate(voices):
                if any(child.tag not in ("BarLine", "location") for child in voice):
                    continue
                barline = voice.find("BarLine")
                if barline is not None and position > 0:
                    voices[position - 1].append(barline)
                measure.remove(voice)
                removed += 1
        return PassResult(changed=removed)


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
                texts = [child for child in voice if child.tag in TEXT_TAGS]
                if not texts:
                    continue
                for text in texts:
                    voice.remove(text)
                    target.insert(0, text)
                measure.remove(voice)
                removed += 1
        return PassResult(changed=removed)


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
