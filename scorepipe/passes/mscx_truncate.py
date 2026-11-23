"""Trim overfull mscx voices from the tail so an editable copy can be opened.

Rules:
* only the tail is changed;
* a rest before a later chord is positional padding and is never removed;
* anything inside a flat ``<Tuplet>``/``<endTuplet>`` range is never edited;
* an operation that cannot be completed without touching a tuplet or a positional rest is
  reported as ``UNRESOLVED`` and no partial edit is applied.

The pass is intentionally a last-resort repair for MuseScore editability, not a musical
reconstruction.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from ..core.mscx import MsxcDocument
from ..core.mscx_invariants import _beats, _tuplet_ratio
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase


@dataclass
class _Item:
    element: object
    beats: Fraction
    rest: bool
    tuplet: bool


class TruncateOverfullMscx:
    spec = PassSpec(
        name="truncate_overfull_mscx",
        phase=Phase.DISPLAY,
        kind=Kind.MECHANICAL,
        owns=("overfull-mscx-voice-durations",),
        description="trim overfull mscx voices from the tail for manual repair",
        measure="mscx voices longer than the active time signature",
    )

    def run(self, doc: MsxcDocument, ctx: Context) -> PassResult:
        signatures: dict[int, Fraction] = {}
        for staff in doc.root.iter("Staff"):
            for index, measure in enumerate(staff.findall("Measure"), start=1):
                for time in measure.iter("TimeSig"):
                    try:
                        signatures[index] = Fraction(time.findtext("sigN") or 4) * 4 / Fraction(
                            time.findtext("sigD") or 4
                        )
                    except (ValueError, ZeroDivisionError):
                        pass
        meter = Fraction(4)
        changed = 0
        notes: list[str] = []
        staff_number = 0
        for staff, index, measure in doc.iter_measures():
            staff_number += 1
            staff_label = staff.get("id") or str(staff_number)
            meter = signatures.get(index, meter)
            target = _measure_target(measure, meter)
            for voice in doc.voices(measure):
                items = _items(voice, target)
                total = sum(item.beats for item in items)
                excess = total - target
                if excess <= 0:
                    continue
                actions, remaining = _plan_tail(items, excess, target)
                if remaining > 0:
                    notes.append(
                        f"UNRESOLVED m{index} staff {staff_label}: {float(total):g} beats, "
                        f"{float(remaining):g} left; tuplet/positional-rest tail is protected"
                    )
                    continue
                for element, new_beats in actions:
                    if new_beats is None:
                        voice.remove(element)
                    else:
                        _shorten(element, new_beats)
                changed += 1
                notes.append(
                    f"m{index} staff {staff_label}: {float(total):g}->{float(target):g}; "
                    + "; ".join(
                        f"{'remove' if new is None else 'shorten'} {float(old):g}"
                        + (f"->{float(new):g}" if new is not None else "")
                        + _describe_element(element)
                        for (element, old, new) in _describe(actions, items)
                    )
                )
        return PassResult(changed=changed, notes=notes)


def _measure_target(measure, meter: Fraction) -> Fraction:
    """MuseScore records irregular/pickup bar length as a fraction of a whole note."""
    raw = measure.get("len")
    if not raw:
        return meter
    try:
        target = Fraction(raw) * 4
        return target if target <= meter else meter
    except (ValueError, ZeroDivisionError):
        return meter


def _items(voice, meter: Fraction) -> list[_Item]:
    items: list[_Item] = []
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
            items.append(
                _Item(
                    element=child,
                    beats=_beats(child, meter, ratio),
                    rest=child.tag == "Rest",
                    tuplet=bool(tuplets),
                )
            )
    return items


def _plan_tail(items: list[_Item], excess: Fraction, meter: Fraction) -> tuple[list[tuple[object, Fraction | None]], Fraction]:
    """Plan edits from the end; return (edits, unhandled beats)."""
    remaining = excess
    edits: list[tuple[object, Fraction | None]] = []
    # Trailing rests, but stop at the last chord. A rest before a later chord is never touched.
    index = len(items) - 1
    last_chord = max((i for i, item in enumerate(items) if not item.rest), default=-1)
    while index > last_chord and remaining > 0:
        item = items[index]
        if item.tuplet or not item.rest:
            break
        if item.beats <= remaining:
            edits.append((item.element, None))
            remaining -= item.beats
            index -= 1
        else:
            edits.append((item.element, item.beats - remaining))
            remaining = Fraction(0)
            break
    # Then shorten/remove the final chord. Do not walk past a preceding rest.
    while remaining > 0 and index >= 0:
        item = items[index]
        if item.tuplet:
            break
        if item.rest:
            break
        if item.beats <= remaining:
            edits.append((item.element, None))
            remaining -= item.beats
            index -= 1
        else:
            edits.append((item.element, item.beats - remaining))
            remaining = Fraction(0)
            break
    return edits, remaining


def _describe(actions, items):
    by_element = {id(item.element): item for item in items}
    for element, new in actions:
        old = by_element[id(element)].beats
        yield element, old, new


def _describe_element(element) -> str:
    risky = [
        child.tag
        for child in element.iter()
        if child.tag in ("Tie", "Slur", "Spanner")
    ]
    suffix = f" [spanner-risk:{','.join(sorted(set(risky)))}]" if risky else ""
    if element.tag != "Chord":
        return suffix
    pitches = []
    for note in element.findall("Note"):
        pitch = note.find("pitch")
        if pitch is not None:
            pitches.append(str(pitch.text or ""))
    return (f" [{','.join(pitches)}]" if pitches else "") + suffix


def _shorten(element, beats: Fraction) -> None:
    """MuseScore accepts an optional whole-note fraction; keep the original durationType."""
    text = Fraction(beats) / 4
    node = element.find("duration")
    if node is None:
        from xml.etree import ElementTree

        node = ElementTree.SubElement(element, "duration")
    node.text = f"{text.numerator}/{text.denominator}"


TRUNCATE_OVERFULL_MSCX = TruncateOverfullMscx()
