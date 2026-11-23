"""Force overfull mscx voices to the bar line for an editable copy.

The display IR has no backup syntax: each ``<voice>`` is a self-contained event stream.  Prefer
removing/shortening rests, then shorten the final Chord, and never touch a Tuplet block.  Every
change is reported so a forced copy cannot be mistaken for a semantic repair.
"""

from __future__ import annotations

from fractions import Fraction

from ..core.mscx import MsxcDocument
from ..core.mscx_invariants import _beats, _tuplet_ratio
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase


class TruncateOverfullMscx:
    spec = PassSpec(
        name="truncate_overfull_mscx",
        phase=Phase.DISPLAY,
        kind=Kind.MECHANICAL,
        owns=("overfull-mscx-voice-durations",),
        description="trim overfull mscx voices to the bar line for manual repair",
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
        for staff_id, index, measure in doc.iter_measures():
            meter = signatures.get(index, meter)
            for voice in doc.voices(measure):
                total = _voice_total(voice, meter)
                excess = total - meter
                if excess <= 0:
                    continue
                remaining = excess
                actions: list[str] = []
                for child in reversed(list(voice)):
                    if remaining <= 0:
                        break
                    if child.tag != "Rest":
                        continue
                    duration = _beats(child, meter)
                    if duration <= 0 or child.findtext("durationType") == "measure":
                        continue
                    if duration <= remaining:
                        voice.remove(child)
                        remaining -= duration
                        actions.append(f"removed rest {float(duration):g} beats")
                    else:
                        _shorten(child, duration - remaining)
                        actions.append(f"shortened rest {float(duration):g}->{float(duration - remaining):g}")
                        remaining = 0
                while remaining > 0:
                    chords = [child for child in voice if child.tag == "Chord"]
                    if not chords:
                        break
                    child = chords[-1]
                    duration = _beats(child, meter)
                    if duration <= 0:
                        break
                    if duration <= remaining:
                        voice.remove(child)
                        remaining -= duration
                        actions.append(f"removed chord {float(duration):g} beats")
                    else:
                        _shorten(child, duration - remaining)
                        actions.append(f"shortened chord {float(duration):g}->{float(duration - remaining):g}")
                        remaining = 0
                if remaining > 0:
                    notes.append(f"m{index} staff {staff_id} voice: unresolved {float(remaining):g} beats")
                    continue
                changed += 1
                notes.append(f"m{index} staff {staff_id}: {float(total):g}->{float(meter):g}; " + "; ".join(actions))
        return PassResult(changed=changed, notes=notes)


def _voice_total(voice, meter: Fraction) -> Fraction:
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


def _shorten(element, beats: Fraction) -> None:
    """MuseScore accepts an optional whole-note fraction; keep the original durationType."""
    text = Fraction(beats) / 4
    node = element.find("duration")
    if node is None:
        from xml.etree import ElementTree

        node = ElementTree.SubElement(element, "duration")
    node.text = f"{text.numerator}/{text.denominator}"


TRUNCATE_OVERFULL_MSCX = TruncateOverfullMscx()
