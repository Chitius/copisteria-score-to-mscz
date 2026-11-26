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
                if rest.find("padding") is not None:
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
        voices = doc.voices(measure)
        for voice in voices:
            if voice.findall("Chord") or not has_text(voice):
                continue
            if not any(other.findall("Chord") for other in voices if other is not voice):
                # the text voice is the staff's only content; its rest is the measure itself
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


def signature_timeline(doc: MsxcDocument) -> list[tuple[int, Fraction]]:
    """The first staff that declares time signatures, as `(measure_index, metre)` events.

    MuseScore prints the signature on the top staff of a system; the others inherit it.  This is
    the timeline a staff without its own signature has to follow.
    """
    for staff in doc.staves():
        events: list[tuple[int, Fraction]] = []
        for index, measure in enumerate(staff.findall("Measure"), start=1):
            for time in measure.iter("TimeSig"):
                try:
                    events.append(
                        (index, Fraction(int(time.findtext("sigN") or 4), int(time.findtext("sigD") or 4)))
                    )
                except (ValueError, ZeroDivisionError):
                    continue
        if events:
            return events
    return []


def meter_at(events: list[tuple[int, Fraction]], index: int) -> Fraction:
    """The metre in force at `index`; 4/4 before the first declared signature."""
    meter = Fraction(4, 4)
    for at, value in events:
        if at <= index:
            meter = value
        else:
            break
    return meter


def iter_measures_with_meter(doc: MsxcDocument):
    """Yield ``(staff, index, measure, meter)`` with shared-timeline fallback.

    MuseScore writes the time signature on the top staff only; a staff without its own
    ``<TimeSig>`` inherits the first staff's signature timeline.  Once a staff declares a
    signature of its own, it tracks its own metre from that measure onward.
    """
    fallback = signature_timeline(doc)
    meters: dict[int, Fraction] = {}
    for staff, index, measure in doc.iter_measures():
        meter = meters[id(staff)] if id(staff) in meters else meter_at(fallback, index)
        for time in measure.iter("TimeSig"):
            try:
                meter = Fraction(int(time.findtext("sigN") or 4), int(time.findtext("sigD") or 4))
                meters[id(staff)] = meter
            except (ValueError, ZeroDivisionError):
                pass
        yield staff, index, measure, meter


def measure_lengths(doc: MsxcDocument, ctx: Context) -> list[Violation]:
    """MuseScore's tick model, not a local beat approximation.

    A secondary voice may end early (MuseScore fills gap rests itself), but an
    overlong voice is always reported.  Overlapping Chord/Rest events - the old
    negative-location bug - are reported even when the final tick happens to
    match.
    """
    from .musescore_ticks import measure_expected_fraction, voice_timeline

    out: list[Violation] = []
    for _staff, index, measure, meter in iter_measures_with_meter(doc):
        expected = measure_expected_fraction(measure, meter)
        if expected > meter:
            # MuseScore writes ``len`` from the imported content, so a ``len`` longer than the
            # metre is the import of an overfull bar, not an independent expectation.  The
            # truncation pass already treats it as stale (mscx_truncate.py); comparing the
            # content against that len made this check circular -- First Step m82 shipped a
            # 3.25-beat bar as ``len=13/16`` and the verifier stayed clean.
            expected = meter
        # MuseScore writes ``len`` when it had to make a measure irregular on import.  The
        # value is derived from the imported content, so the message has to say so: otherwise
        # "expected 4.0625 beats" in a plain 4/4 score reads like a verifier bug.
        import_len = measure.get("len")
        len_note = (
            f"; the importer set irregular length len={import_len} "
            f"(metre {float(meter) * 4:g} beats)"
            if import_len
            else ""
        )
        primary = _primary_voice(measure)
        primary_voice = primary[0] if primary else None
        for voice in measure.findall("voice"):
            timeline = voice_timeline(voice, expected)
            actual = timeline.end
            if actual <= 0:
                if voice is primary_voice and expected > 0 and not voice.findall("Chord"):
                    # A measure with no written time at all is an incomplete bar, not a short
                    # secondary voice: MuseScore shows it as 0/1 (Suzume m1 before the fix).
                    out.append(
                        Violation(
                            "mscx-measure-length",
                            index,
                            "measure has no written time "
                            f"(expected {float(expected) * 4:g} beats)",
                        )
                    )
                continue
            if timeline.overlaps:
                out.append(
                    Violation(
                        "mscx-measure-length",
                        index,
                        "overlapping Chord/Rest "
                        f"at {float(timeline.overlaps[0][0]) * 4:g} beats",
                    )
                )
                continue
            if actual == expected:
                continue
            if voice is primary_voice or actual > expected:
                out.append(
                    Violation(
                        "mscx-measure-length",
                        index,
                        f"voice {float(actual) * 4:g} beats "
                        f"({float(actual) * 1920:g} ticks), "
                        f"expected {float(expected) * 4:g} beats "
                        f"({float(expected) * 1920:g} ticks)" + len_note,
                    )
                )
    return out


def tuplet_lengths(doc: MsxcDocument, ctx: Context) -> list[Violation]:
    """Every tuplet must contain exactly ``baseNote * actualNotes`` written."""
    from .musescore_ticks import measure_expected_fraction, voice_timeline

    out: list[Violation] = []
    for _staff, index, measure, meter in iter_measures_with_meter(doc):
        expected = measure_expected_fraction(measure, meter)
        for voice in measure.findall("voice"):
            for span in voice_timeline(voice, expected).invalid_tuplets:
                out.append(
                    Violation(
                        "mscx-tuplet-length",
                        index,
                        f"tuplet at {float(span.start) * 4:g} beats has "
                        f"{float(span.written) * 4:g} written beats, "
                        f"expected {float(span.target_written) * 4:g}",
                    )
                )
    return out


def _primary_voice(measure):
    """The verifier reports a short measure for the first chord voice only.

    MuseScore itself fills gaps in secondary voices; the canonicalizer still
    tries to make every note-bearing voice exact, but a short secondary voice
    is not a measure-length error.
    """
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
    tuplet_lengths,
)
