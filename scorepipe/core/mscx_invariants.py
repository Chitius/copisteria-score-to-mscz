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
                if rest.find("pickupPadding") is not None:
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
            if voice.findall("Chord") or has_text(voice):
                continue
            if not voice.findall("Rest"):
                continue
            if any(
                child.tag not in ("Rest", "location", "Clef", "KeySig", "TimeSig")
                for child in voice
            ):
                continue
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


def empty_voices(doc: MsxcDocument, ctx: Context) -> list[Violation]:
    out: list[Violation] = []
    for _staff, index, measure in doc.iter_measures():
        for voice in measure.findall("voice"):
            if any(child.tag not in ("BarLine", "location") for child in voice):
                continue
            out.append(Violation("empty-voice", index, "voice slot without notes, rests or spanners"))
    return out


DURATIONS = {
    "breve": 8.0,
    "whole": 4.0,
    "half": 2.0,
    "quarter": 1.0,
    "eighth": 0.5,
    "16th": 0.25,
    "32nd": 0.125,
    "64th": 0.0625,
}


def _beats(element, meter: float = 4.0) -> float:
    name = element.findtext("durationType") or "quarter"
    if name == "measure":
        return meter
    base = DURATIONS.get(name, 1.0)
    dots = int(element.findtext("dots") or 0)
    return base * sum(0.5**index for index in range(dots + 1))


def measure_lengths(doc: MsxcDocument, ctx: Context) -> list[Violation]:
    """What MuseScore flags as an incomplete measure: a voice whose ticks miss the time signature."""
    signatures: dict[int, float] = {}
    for staff in doc.root.iter("Staff"):
        for index, measure in enumerate(staff.findall("Measure"), start=1):
            for time in measure.iter("TimeSig"):
                try:
                    signatures[index] = float(time.findtext("sigN") or 4) * 4.0 / float(
                        time.findtext("sigD") or 4
                    )
                except ValueError:
                    pass
    out: list[Violation] = []
    meter = 4.0
    for staff in doc.root.iter("Staff"):
        for index, measure in enumerate(staff.findall("Measure"), start=1):
            meter = signatures.get(index, meter)
            for voice in _primary_voice(measure):
                total = 0.0
                for child in voice:
                    if child.tag in ("Chord", "Rest"):
                        total += _beats(child, meter)
                if total <= 0:
                    continue
                if abs(total - meter) > 1e-6:
                    out.append(
                        Violation(
                            "mscx-measure-length", index, f"voice {total:g} beats, metre {meter:g}"
                        )
                    )
    return out


def _primary_voice(measure):
    """Only voice 1 must fill the measure; later voices may start or end early by design."""
    voices = measure.findall("voice")
    for voice in voices:
        if voice.findall("Chord"):
            return [voice]
    return voices[:1]


MSCX_VERIFIERS = (
    hidden_non_measure_rests,
    text_voice_rests,
    padding_voices,
    voice_order,
    empty_voices,
    measure_lengths,
)
