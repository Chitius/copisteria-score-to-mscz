"""MuseScore's tick model, mirrored for local validation.

The constants and rounding follow MuseScore's open-source engraving code:
``Constants::DIVISION`` is 480 ticks per quarter in
``src/engraving/types/constants.h`` and ``Fraction::ticks()`` rounds a
whole-note fraction to ``DIVISION * 4`` ticks in
``src/engraving/types/fraction.h``.

This is intentionally a *validator*, not a second notation engine.
"""

from __future__ import annotations

from fractions import Fraction
from xml.etree import ElementTree

TICKS_PER_QUARTER = 480
TICKS_PER_WHOLE = TICKS_PER_QUARTER * 4

# MuseScore's DurationType values, in whole notes.
BASE_WHOLE = {
    "breve": Fraction(2),
    "whole": Fraction(1),
    "half": Fraction(1, 2),
    "quarter": Fraction(1, 4),
    "eighth": Fraction(1, 8),
    "16th": Fraction(1, 16),
    "32nd": Fraction(1, 32),
    "64th": Fraction(1, 64),
    "128th": Fraction(1, 128),
    "256th": Fraction(1, 256),
}


def fraction_ticks(value: Fraction) -> int:
    """Mirror ``Fraction::ticks()``: round(value * 1920)."""
    return round(value * TICKS_PER_WHOLE)


def element_ticks(element: ElementTree.Element) -> int:
    """Ticks for one Chord/Rest, including durationType+dots."""
    explicit = element.findtext("duration")
    if explicit:
        return fraction_ticks(Fraction(explicit))
    name = element.findtext("durationType") or "quarter"
    if name == "measure":
        return -1
    dots = int(element.findtext("dots") or 0)
    multiplier = sum((Fraction(1, 2) ** index for index in range(dots + 1)), Fraction(0))
    return fraction_ticks(BASE_WHOLE.get(name, Fraction(1)) * multiplier)


def tuplet_ratio(tuplet: ElementTree.Element) -> Fraction:
    try:
        normal = Fraction(tuplet.findtext("normalNotes") or "1")
        actual = Fraction(tuplet.findtext("actualNotes") or "1")
        if normal <= 0 or actual <= 0:
            return Fraction(1)
        return normal / actual
    except (ValueError, ZeroDivisionError):
        return Fraction(1)


def voice_ticks(voice: ElementTree.Element) -> int:
    total = Fraction(0)
    tuplets: list[Fraction] = []
    for child in voice:
        if child.tag == "Tuplet":
            tuplets.append(tuplet_ratio(child))
        elif child.tag == "endTuplet":
            if tuplets:
                tuplets.pop()
        elif child.tag in ("Chord", "Rest"):
            ratio = Fraction(1)
            for tuplet in tuplets:
                ratio *= tuplet
            ticks = element_ticks(child)
            if ticks >= 0:
                if child.find("duration") is not None:
                    total += ticks
                else:
                    total += Fraction(ticks) * ratio
    return round(total)


def location_ticks(voice: ElementTree.Element) -> int:
    fraction = voice.findtext("location/fractions")
    return fraction_ticks(Fraction(fraction)) if fraction else 0


def measure_expected_ticks(measure: ElementTree.Element, inherited=None) -> int:
    length = measure.get("len")
    if length:
        return fraction_ticks(Fraction(length))
    signature = measure.find(".//TimeSig")
    if signature is not None:
        beats = int(signature.findtext("sigN") or 4)
        unit = int(signature.findtext("sigD") or 4)
        return fraction_ticks(Fraction(beats, unit))
    if inherited is not None:
        return inherited
    return TICKS_PER_WHOLE


def measure_report(measure: ElementTree.Element, inherited=None) -> list[dict]:
    expected = measure_expected_ticks(measure, inherited)
    rows = []
    for voice in measure.findall("voice"):
        actual = location_ticks(voice) + voice_ticks(voice)
        rows.append(
            {
                "actual": actual,
                "expected": expected,
                "delta": actual - expected,
            }
        )
    return rows
