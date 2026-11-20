"""Mechanical passes on the MuseScore display form (.mscx)."""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.mscx import MsxcDocument, has_text, note_count
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase


class DropTextVoiceRests:
    spec = PassSpec(
        name="drop_text_voice_rests",
        phase=Phase.DISPLAY,
        kind=Kind.MECHANICAL,
        owns=("text-voice-rests",),
        description="a text-only voice carries an imported whole-measure rest; remove it",
        measure="rests inside text-only voices",
    )

    def run(self, doc: MsxcDocument, ctx: Context) -> PassResult:
        changed = 0
        for _staff, _index, measure in doc.iter_measures():
            for voice in doc.voices(measure):
                if voice.findall("Chord") or not has_text(voice):
                    continue
                for rest in list(voice.findall("Rest")):
                    voice.remove(rest)
                    changed += 1
        return PassResult(changed=changed)


class UnhideRealRests:
    spec = PassSpec(
        name="unhide_real_rests",
        phase=Phase.DISPLAY,
        kind=Kind.MECHANICAL,
        owns=("rest-visibility",),
        description="mscx visibility is a child element; remove it from non-measure rests",
        measure="hidden non-measure rests",
    )

    def run(self, doc: MsxcDocument, ctx: Context) -> PassResult:
        changed = 0
        for _staff, _index, measure in doc.iter_measures():
            for voice in doc.voices(measure):
                for rest in voice.findall("Rest"):
                    if rest.findtext("durationType") == "measure":
                        continue
                    visible = rest.find("visible")
                    if visible is not None:
                        rest.remove(visible)
                        changed += 1
        return PassResult(changed=changed)


class DropPaddingVoices:
    spec = PassSpec(
        name="drop_padding_voices",
        phase=Phase.DISPLAY,
        kind=Kind.MECHANICAL,
        owns=("padding-voices",),
        description="a rest-only voice next to a chord voice is padding, not notation",
        measure="rest-only voices next to a chord voice",
    )

    def run(self, doc: MsxcDocument, ctx: Context) -> PassResult:
        changed = 0
        for _staff, _index, measure in doc.iter_measures():
            if not any(voice.findall("Chord") for voice in doc.voices(measure)):
                continue
            for voice in list(doc.voices(measure)):
                if voice.findall("Chord") or has_text(voice):
                    continue
                # a spanner or dynamic is real content. Clef/KeySig/TimeSig are measure metadata
                # that MuseScore sometimes parks in the padding voice (laputa m26 voice 2 was a
                # measure rest + Clef, so the whole voice looked non-empty and survived).
                metadata_tags = ("Clef", "KeySig", "TimeSig")
                if any(
                    child.tag not in ("Rest", "BarLine", "location", *metadata_tags)
                    for child in voice
                ):
                    continue
                owner = next(
                    (candidate for candidate in doc.voices(measure) if candidate.findall("Chord")),
                    None,
                )
                if owner is None:
                    continue
                for tag in reversed(metadata_tags):
                    item = voice.find(tag)
                    if item is None:
                        continue
                    if owner.find(tag) is None:
                        owner.insert(0, item)
                    else:
                        voice.remove(item)
                barline = voice.find("BarLine")
                if barline is not None:
                    owner.append(barline)
                measure.remove(voice)
                changed += 1
        return PassResult(changed=changed)


class CanonicalVoiceOrder:
    spec = PassSpec(
        name="canonical_voice_order",
        phase=Phase.DISPLAY,
        kind=Kind.MECHANICAL,
        owns=("voice-order",),
        description="densest chord voice first, text voices after; stable and idempotent",
        measure="voice slots out of canonical order",
    )

    def run(self, doc: MsxcDocument, ctx: Context) -> PassResult:
        changed = 0
        for _staff, _index, measure in doc.iter_measures():
            voices = doc.voices(measure)
            if not voices:
                continue
            ordered = sorted(
                voices,
                key=lambda voice: (
                    0 if voice.findall("Chord") else (1 if has_text(voice) else 2),
                    -note_count(voice),
                ),
            )
            if ordered == voices:
                continue
            for voice in list(voices):
                measure.remove(voice)
            for voice in ordered:
                measure.append(voice)
            changed += 1
        return PassResult(changed=changed)


DISPLAY_PASSES = [DropTextVoiceRests(), UnhideRealRests(), DropPaddingVoices(), CanonicalVoiceOrder()]
