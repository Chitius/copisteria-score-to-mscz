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
    for staff, index, measure in doc.iter_measures():
        if only is not None and index not in only:
            continue
        expected = measure_expected_ticks(measure)
        for voice in measure.findall("voice"):
            if not voice.findall("Chord"):
                continue
            if any(rest.findtext("durationType") == "measure" or rest.find("padding") is not None
                   for rest in voice.findall("Rest")):
                continue
            start = location_ticks(voice)
            duration = voice_ticks(voice)
            end = start + duration
            if start <= 0:
                continue
            if end > expected:
                if duration <= expected:
                    _set_location(voice, expected - duration)
                    changed += 1
            elif end < expected:
                changed += _fill(voice, expected - end)
        for voice in measure.findall("voice"):
            if location_ticks(voice) + voice_ticks(voice) > expected:
                raise ValueError(f"canonicalization left m{index} voice beyond the bar")
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
    remaining = ticks
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
    return changed
