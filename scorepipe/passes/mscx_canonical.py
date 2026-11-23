"""Turn the remaining raw mscx fractions into legal MuseScore values.

Forced truncation can leave OMR fractions such as 16/384 or 5/12 whole-note
values.  MuseScore can display them but reports tick-level measure errors.  This
module wraps the small fractions in the smallest tuplet that represents them and
clamps cross-staff voice locations that start too late in the bar.
"""

from __future__ import annotations

import copy
from fractions import Fraction
from xml.etree import ElementTree

from ..core.mscx import MsxcDocument
from ..core.mscx_invariants import _beats, _tuplet_ratio

# beats -> (base durationType, normalNotes, actualNotes)
_TUPLET_FOR_BEATS = {
    Fraction(1, 12): ("32nd", 2, 3),
    Fraction(1, 6): ("16th", 2, 3),
    Fraction(1, 24): ("64th", 2, 3),
}


def canonicalize(doc: MsxcDocument, only=None) -> int:
    changed = 0
    for staff, index, measure in doc.iter_measures():
        if only is not None and index not in only:
            continue
        meter = Fraction(4)
        for time in measure.iter("TimeSig"):
            try:
                meter = Fraction(time.findtext("sigN") or 4) * 4 / Fraction(
                    time.findtext("sigD") or 4
                )
            except (ValueError, ZeroDivisionError):
                pass
        for voice in measure.findall("voice"):
            changed += _clamp_location(voice, meter)
            changed += _wrap_fractions(voice)
    return changed


def _voice_beats(voice, meter: Fraction) -> Fraction:
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
            total += _beats(child, meter, ratio)
    return total


def _clamp_location(voice, meter: Fraction) -> int:
    location = voice.find("location")
    if location is None:
        return 0
    fractions = location.find("fractions")
    if fractions is None:
        return 0
    try:
        start = Fraction(fractions.text or "0") * 4
    except (ValueError, ZeroDivisionError):
        return 0
    duration = _voice_beats(voice, meter)
    if start + duration <= meter:
        return 0
    new_start = max(Fraction(0), meter - duration)
    value = new_start / 4
    fractions.text = f"{value.numerator}/{value.denominator}"
    return 1


def _wrap_fractions(voice) -> int:
    changed = 0
    tuplets: list[Fraction] = []
    for element in list(voice):
        if element.tag == "Tuplet":
            tuplets.append(_tuplet_ratio(element))
            continue
        if element.tag == "endTuplet":
            if tuplets:
                tuplets.pop()
            continue
        if tuplets:
            continue
        if element.tag not in ("Chord", "Rest") or element.find("duration") is None:
            continue
        try:
            beats = Fraction(element.findtext("duration") or "0") * 4
        except (ValueError, ZeroDivisionError):
            continue
        if beats == Fraction(5, 3) and element.tag == "Rest":
            changed += _split_rest(voice, element)
            continue
        mapping = _TUPLET_FOR_BEATS.get(beats)
        if mapping is None:
            continue
        base, normal, actual = mapping
        _wrap(voice, element, base, normal, actual)
        changed += 1
    return changed


def _wrap(voice, element, base: str, normal: int, actual: int) -> None:
    index = list(voice).index(element)
    tuplet = ElementTree.Element("Tuplet")
    ElementTree.SubElement(tuplet, "normalNotes").text = str(normal)
    ElementTree.SubElement(tuplet, "actualNotes").text = str(actual)
    ElementTree.SubElement(tuplet, "baseNote").text = base
    end = ElementTree.Element("endTuplet")
    voice.remove(element)
    _set_type(element, base)
    voice.insert(index, tuplet)
    voice.insert(index + 1, element)
    voice.insert(index + 2, end)


def _split_rest(voice, element) -> int:
    """5/3 beats = dotted quarter (3/2) plus one 16th triplet (1/6)."""
    index = list(voice).index(element)
    first = copy.deepcopy(element)
    _set_type(first, "quarter")
    ElementTree.SubElement(first, "dots").text = "1"
    voice.remove(element)
    voice.insert(index, first)
    rest = copy.deepcopy(element)
    _set_type(rest, "16th")
    tuplet = ElementTree.Element("Tuplet")
    ElementTree.SubElement(tuplet, "normalNotes").text = "2"
    ElementTree.SubElement(tuplet, "actualNotes").text = "3"
    ElementTree.SubElement(tuplet, "baseNote").text = "16th"
    end = ElementTree.Element("endTuplet")
    voice.insert(index + 1, tuplet)
    voice.insert(index + 2, rest)
    voice.insert(index + 3, end)
    return 1


def _set_type(element, name: str) -> None:
    for tag in ("duration", "durationType", "dots"):
        for node in element.findall(tag):
            element.remove(node)
    for node in element.findall("NoteDot"):
        element.remove(node)
    ElementTree.SubElement(element, "durationType").text = name
