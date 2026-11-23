"""Read-only invariants for the MuseScore display IR."""

from __future__ import annotations

from fractions import Fraction

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
                visible = rest.find("visible")
                if visible is None:
                    continue
                if (visible.text or "").strip().lower() not in ("0", "false"):
                    continue
                out.append(Violation("hidden-rest", index, rest.findtext("durationType") or ""))
    return out


def text_voice_rests(doc: MsxcDocument, ctx: Context) -> list[Violation]:
    out: list[Violation] = []
    for _staff, index, measure in doc.iter_measures():
        for voice in doc.voices(measure):
            if voice.findall("Chord") or not has_text(voice):
                continue
            rests = [
                rest
                for rest in voice.findall("Rest")
                if not (
                    rest.findtext("durationType") == "measure"
                    and (rest.findtext("visible") or "").strip().lower() in ("0", "false")
                )
            ]
            if rests:
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
    "breve": Fraction(8),
    "whole": Fraction(4),
    "half": Fraction(2),
    "quarter": Fraction(1),
    "eighth": Fraction(1, 2),
    "16th": Fraction(1, 4),
    "32nd": Fraction(1, 8),
    "64th": Fraction(1, 16),
    "128th": Fraction(1, 32),
    "256th": Fraction(1, 64),
}


def _beats(element, meter: Fraction = Fraction(4), tuplet: Fraction = Fraction(1)) -> Fraction:
    name = element.findtext("durationType") or "quarter"
    if name == "measure":
        return meter
    explicit = element.findtext("duration")
    if explicit:
        try:
            # MuseScore's optional duration is an actual fraction of a whole note.
            return Fraction(explicit) * 4
        except (ValueError, ZeroDivisionError):
            pass
    base = DURATIONS.get(name, Fraction(1))
    dots = int(element.findtext("dots") or 0)
    multiplier = sum((Fraction(1, 2) ** index for index in range(dots + 1)), Fraction(0))
    return base * multiplier * tuplet


def _tuplet_ratio(tuplet) -> Fraction:
    try:
        normal = Fraction(tuplet.findtext("normalNotes") or "")
        actual = Fraction(tuplet.findtext("actualNotes") or "")
        if normal <= 0 or actual <= 0:
            return Fraction(1)
        return normal / actual
    except (ValueError, ZeroDivisionError):
        return Fraction(1)


def measure_lengths(doc: MsxcDocument, ctx: Context) -> list[Violation]:
    """What MuseScore flags as an incomplete measure: a voice whose ticks miss the time signature."""
    out: list[Violation] = []
    for staff in doc.root.iter("Staff"):
        meter = Fraction(4)
        for index, measure in enumerate(staff.findall("Measure"), start=1):
            for time in measure.iter("TimeSig"):
                try:
                    meter = Fraction(time.findtext("sigN") or 4) * 4 / Fraction(
                        time.findtext("sigD") or 4
                    )
                except (ValueError, ZeroDivisionError):
                    pass
            target = _measure_target(measure, meter)
            primary = _primary_voice(measure)
            primary_voice = primary[0] if primary else None
            for voice in measure.findall("voice"):
                total = Fraction(0)
                tuplets: list[Fraction] = []
                for child in voice:
                    if child.tag == "Tuplet":
                        tuplets.append(_tuplet_ratio(child))
                    elif child.tag == "endTuplet":
                        if tuplets:
                            tuplets.pop()
                    elif child.tag in ("Chord", "Rest"):
                        ratio = Fraction(1)
                        for tuplet in tuplets:
                            ratio *= tuplet
                        total += _beats(child, target, ratio)
                if total <= 0:
                    continue
                # The primary voice must fill the bar. Secondary voices may intentionally stop
                # early, but they must never be overfull: that is what the editable repair edits.
                if abs(total - target) <= Fraction(1, 1_000_000):
                    continue
                if voice is primary_voice or total > target:
                    out.append(
                        Violation(
                            "mscx-measure-length",
                            index,
                            f"voice {float(total):g} beats, metre {float(target):g}",
                        )
                    )
    return out


def _measure_target(measure, meter: Fraction) -> Fraction:
    raw = measure.get("len")
    if not raw:
        return meter
    try:
        target = Fraction(raw) * 4
        return target if target <= meter else meter
    except (ValueError, ZeroDivisionError):
        return meter


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
