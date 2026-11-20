"""Read-only invariants for the MuseScore display IR."""

from __future__ import annotations

from .invariants import Violation
from .mscx import MsxcDocument, has_text, note_count
from .pass_base import Context


def hidden_non_measure_rests(doc: MsxcDocument, ctx: Context) -> list[Violation]:
    out: list[Violation] = []
    for _staff, index, measure in doc.iter_measures():
        for voice in doc.voices(measure):
            for rest in voice.findall("Rest"):
                if rest.findtext("durationType") == "measure":
                    continue
                if rest.find("visible") is not None:
                    out.append(Violation("hidden-rest", index, rest.findtext("durationType") or ""))
    return out


def text_voice_rests(doc: MsxcDocument, ctx: Context) -> list[Violation]:
    out: list[Violation] = []
    for _staff, index, measure in doc.iter_measures():
        for voice in doc.voices(measure):
            if voice.findall("Chord") or not has_text(voice):
                continue
            if voice.findall("Rest"):
                out.append(Violation("text-voice-rest", index, "text voice carries a rest"))
    return out


def padding_voices(doc: MsxcDocument, ctx: Context) -> list[Violation]:
    out: list[Violation] = []
    for _staff, index, measure in doc.iter_measures():
        voices = doc.voices(measure)
        if not any(voice.findall("Chord") for voice in voices):
            continue
        for voice in voices:
            if not voice.findall("Chord") and not has_text(voice):
                out.append(Violation("padding-voice", index, "rest-only voice next to chords"))
    return out


def voice_order(doc: MsxcDocument, ctx: Context) -> list[Violation]:
    out: list[Violation] = []
    for _staff, index, measure in doc.iter_measures():
        voices = doc.voices(measure)
        chord_voices = [voice for voice in voices if voice.findall("Chord")]
        counts = [note_count(voice) for voice in chord_voices]
        if counts != sorted(counts, reverse=True):
            out.append(Violation("voice-order", index, f"chord voice note counts {counts}"))
        first_chord = next((i for i, voice in enumerate(voices) if voice.findall("Chord")), None)
        if first_chord is not None and any(
            not voice.findall("Chord") for voice in voices[:first_chord]
        ):
            out.append(Violation("voice-order", index, "a text/rest voice precedes a chord voice"))
    return out


MSCX_VERIFIERS = (
    hidden_non_measure_rests,
    text_voice_rests,
    padding_voices,
    voice_order,
)
