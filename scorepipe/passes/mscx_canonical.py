"""Canonicalize mscx voices against MuseScore's 480-tick model.

The model in ``musescore_ticks`` mirrors ``Constants::DIVISION`` and
``Fraction::ticks()``.  A forced voice is allowed to be short only when it is a
secondary voice; here we fill such a voice with hidden rests, and clamp a
cross-staff ``location`` that starts late enough to leave the bar.  The result
is checked by exact tick totals, not beat totals.
"""

from __future__ import annotations

from fractions import Fraction
from xml.etree import ElementTree

from ..core.mscx import MsxcDocument
from ..core.musescore_ticks import (
    TICKS_PER_WHOLE,
    location_ticks,
    measure_expected_ticks,
    voice_ticks,
)

# name, dots, ticks
_LEGAL_TICKS = (
    ("whole", 0, 1920),
    ("half", 1, 1440),
    ("half", 0, 960),
    ("quarter", 1, 720),
    ("quarter", 0, 480),
    ("eighth", 1, 360),
    ("eighth", 0, 240),
    ("16th", 1, 180),
    ("16th", 0, 120),
    ("32nd", 1, 90),
    ("32nd", 0, 60),
    ("64th", 1, 45),
    ("64th", 0, 30),
    ("128th", 0, 15),
)


def canonicalize(doc: MsxcDocument, only=None) -> int:
    changed = 0
    meters = {}
    for staff, index, measure in doc.iter_measures():
        if only is not None and index not in only:
            continue
        meter = Fraction(TICKS_PER_WHOLE, TICKS_PER_WHOLE)
        meter = meters.get(id(staff), Fraction(1))
        for time in measure.iter("TimeSig"):
            try:
                meter = Fraction(int(time.findtext("sigN") or 4), int(time.findtext("sigD") or 4))
            except (ValueError, ZeroDivisionError):
                pass
        meters[id(staff)] = meter
        expected = measure_expected_ticks(measure, Fraction(round(meter * TICKS_PER_WHOLE), 1))
        for voice in measure.findall("voice"):
            if not voice.findall("Chord"):
                continue
            if any(rest.findtext("durationType") == "measure" or rest.find("padding") is not None
                   for rest in voice.findall("Rest")):
                continue
            start = location_ticks(voice)
            duration = voice_ticks(voice)
            end = start + duration
            if end > expected:
                if start > 0 and duration <= expected:
                    _set_location(voice, expected - duration)
                    changed += 1
            elif 0 < expected - end <= 15 or start > 0:
                changed += _fill(voice, expected - end)
    return changed


def _set_location(voice, ticks: int) -> None:
    location = voice.find("location")
    if location is None:
        location = ElementTree.SubElement(voice, "location")
    fractions = location.find("fractions")
    if fractions is None:
        fractions = ElementTree.SubElement(location, "fractions")
    value = Fraction(ticks, TICKS_PER_WHOLE)
    fractions.text = f"{value.numerator}/{value.denominator}"


def _fill(voice, ticks: int) -> int:
    changed = 0
    remaining = int(ticks)
    for name, dots, value in _LEGAL_TICKS:
        while remaining >= value:
            rest = ElementTree.SubElement(voice, "Rest")
            ElementTree.SubElement(rest, "padding").text = "1"
            ElementTree.SubElement(rest, "durationType").text = name
            if dots:
                ElementTree.SubElement(rest, "dots").text = str(dots)
            ElementTree.SubElement(rest, "visible").text = "0"
            remaining -= value
            changed += 1
    if remaining:
        # A few ticks cannot be written as a single legal note value.
        # Use a hidden 128th triplet so the tick total remains exact.
        normal, actual = _reduce(remaining, 15)
        tuplet = ElementTree.SubElement(voice, "Tuplet")
        ElementTree.SubElement(tuplet, "normalNotes").text = str(normal)
        ElementTree.SubElement(tuplet, "actualNotes").text = str(actual)
        ElementTree.SubElement(tuplet, "baseNote").text = "128th"
        rest = ElementTree.SubElement(voice, "Rest")
        ElementTree.SubElement(rest, "padding").text = "1"
        ElementTree.SubElement(rest, "durationType").text = "128th"
        ElementTree.SubElement(rest, "visible").text = "0"
        ElementTree.SubElement(voice, "endTuplet")
        changed += 1
    return changed


def _reduce(numerator: int, denominator: int) -> tuple[int, int]:
    import math

    divisor = math.gcd(numerator, denominator)
    return numerator // divisor, denominator // divisor
