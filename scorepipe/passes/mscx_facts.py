"""Display-layer fact injection: make a recognised tempo word a real Tempo object."""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.mscx import MsxcDocument
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase

METRONOME_SYMBOLS = {
    "whole": "metNoteWhole",
    "half": "metNoteHalfUp",
    "quarter": "metNoteQuarterUp",
    "eighth": "metNote8thUp",
    "16th": "metNote16thUp",
    "32nd": "metNote32ndUp",
}


class UpgradeTempoTexts:
    spec = PassSpec(
        name="upgrade_tempo_texts",
        phase=Phase.DISPLAY,
        kind=Kind.MECHANICAL,
        owns=("tempo-objects",),
        description="a StaffText matching a tempo fact becomes a <Tempo> with a metronome glyph",
        measure="tempo words still stored as plain staff text",
    )

    def run(self, doc: MsxcDocument, ctx: Context) -> PassResult:
        facts = (ctx.facts or {}).get("marks") or []
        changed = 0
        staves = doc.staves()
        if not staves:
            return PassResult()
        for fact in facts:
            tempo = fact.get("tempo")
            text = (fact.get("text") or "").strip()
            if not tempo or not text:
                continue
            number = int(fact.get("measure") or 0)
            measures = staves[0].findall("Measure")
            if not 0 < number <= len(measures):
                continue
            measure = measures[number - 1]
            if any(_tempo_text(node).strip() == text for node in measure.iter("Tempo")):
                continue
            for voice in measure.findall("voice"):
                replaced = False
                for node in list(voice):
                    if node.tag != "StaffText":
                        continue
                    if (node.findtext("text") or "").strip() != text:
                        continue
                    element = ElementTree.Element("Tempo")
                    ElementTree.SubElement(element, "tempo").text = (
                        f"{float(tempo) / 60:.6f}".rstrip("0").rstrip(".")
                    )
                    text_element = ElementTree.SubElement(element, "text")
                    text_element.text = text + " "
                    symbol = ElementTree.SubElement(text_element, "sym")
                    symbol.text = METRONOME_SYMBOLS.get(
                        fact.get("beat_unit") or "quarter", "metNoteQuarterUp"
                    )
                    symbol.tail = f" = {int(float(tempo))}"
                    voice.insert(list(voice).index(node), element)
                    voice.remove(node)
                    replaced = True
                    changed += 1
                    break
                if replaced:
                    break
        return PassResult(changed=changed)


def _tempo_text(tempo_element) -> str:
    text = tempo_element.find("text")
    if text is None:
        return ""
    return "".join(text.itertext())


_LENGTHS = {
    "whole": 4.0,
    "half": 2.0,
    "quarter": 1.0,
    "eighth": 0.5,
    "16th": 0.25,
    "32nd": 0.125,
}


def _duration_quarters(element) -> float:
    kind = element.findtext("durationType") or ""
    if kind == "measure":
        return 4.0
    length = _LENGTHS.get(kind, 0.0)
    dots = element.findtext("dots")
    if dots and dots.isdigit():
        length *= 1 + (1 - 0.5 ** int(dots))
    return length


def _insert_index_at(voice, target_quarters: float) -> int:
    """Index right after the chord/rest covering the target beat."""
    ticks = 0.0
    for index, child in enumerate(voice):
        if child.tag in ("Chord", "Rest"):
            length = _duration_quarters(child)
            if ticks + length > target_quarters + 1e-6:
                return index + 1
            ticks += length
        elif child.tag == "location":
            fraction = child.findtext("fractions") or ""
            if "/" in fraction:
                numerator, denominator = fraction.split("/", 1)
                try:
                    ticks += float(numerator) / float(denominator) * 4.0
                except (ValueError, ZeroDivisionError):
                    pass
    return len(voice)


class UpgradeGradualTexts:
    spec = PassSpec(
        name="upgrade_gradual_texts",
        phase=Phase.DISPLAY,
        kind=Kind.MECHANICAL,
        owns=("gradual-spanners",),
        description="a recognised rit./rall./accel. word becomes a paired GradualTempoChange spanner",
        measure="gradual tempo words still stored as plain staff text",
    )

    def run(self, doc: MsxcDocument, ctx: Context) -> PassResult:
        facts = (ctx.facts or {}).get("marks") or []
        staves = doc.staves()
        if not staves:
            return PassResult()
        changed = 0
        for fact in facts:
            gradual = fact.get("gradual")
            text = (fact.get("text") or "").strip()
            if not gradual or not text:
                continue
            number = int(fact.get("measure") or 0)
            measures = staves[0].findall("Measure")
            if not 0 < number <= len(measures):
                continue
            measure = measures[number - 1]
            if any(_spanner_text(spanner) == text for spanner in measure.iter("Spanner")):
                continue
            start_voice = next(
                (voice for voice in measure.findall("voice") if voice.findall("Chord")), None
            )
            staff_text = next(
                (
                    node
                    for voice in measure.findall("voice")
                    for node in voice
                    if node.tag == "StaffText" and (node.findtext("text") or "").strip() == text
                ),
                None,
            )
            if start_voice is None or staff_text is None:
                continue
            for voice in measure.findall("voice"):
                if staff_text in list(voice):
                    voice.remove(staff_text)
                    break
            beat = float(fact.get("beat") or 0)
            start = _gradual_start(text, gradual)
            start_voice.insert(_insert_index_at(start_voice, beat), start)
            changed += 1

            span_measures = int(fact.get("length_measures") or 1)
            span_fractions = str(fact.get("length_fractions") or "-1/8")
            end_index = number - 1 + span_measures
            if 0 <= end_index < len(measures):
                end_measure = measures[end_index]
                end_voice = next(
                    (voice for voice in end_measure.findall("voice") if voice.findall("Chord")), None
                )
                if end_voice is not None:
                    end_voice.insert(
                        _insert_index_at(end_voice, _fraction_quarters(span_fractions)),
                        _gradual_end(span_measures, span_fractions),
                    )
        return PassResult(changed=changed)


def _gradual_start(text: str, gradual: str) -> ElementTree.Element:
    spanner = ElementTree.Element("Spanner", {"type": "GradualTempoChange"})
    change = ElementTree.SubElement(spanner, "GradualTempoChange")
    ElementTree.SubElement(change, "tempoChangeType").text = gradual
    ElementTree.SubElement(change, "beginHookHeight").text = "1.9"
    ElementTree.SubElement(change, "endHookType").text = "0"
    ElementTree.SubElement(change, "endHookHeight").text = "1.9"
    ElementTree.SubElement(change, "beginText").text = text
    ElementTree.SubElement(change, "beginTextOffset", {"x": "0", "y": "0"})
    ElementTree.SubElement(change, "continueText").text = f"({text})"
    next_element = ElementTree.SubElement(spanner, "next")
    location = ElementTree.SubElement(next_element, "location")
    ElementTree.SubElement(location, "measures").text = "1"
    ElementTree.SubElement(location, "fractions").text = "-1/8"
    return spanner


def _gradual_end(span_measures: int, span_fractions: str) -> ElementTree.Element:
    spanner = ElementTree.Element("Spanner", {"type": "GradualTempoChange"})
    previous = ElementTree.SubElement(spanner, "prev")
    location = ElementTree.SubElement(previous, "location")
    ElementTree.SubElement(location, "measures").text = str(-span_measures)
    if span_fractions:
        ElementTree.SubElement(location, "fractions").text = span_fractions.lstrip("-")
    return spanner


def _spanner_text(spanner) -> str:
    return (spanner.findtext("GradualTempoChange/beginText") or "").strip()


def _fraction_quarters(fraction: str) -> float:
    if "/" in fraction:
        numerator, denominator = fraction.lstrip("-").split("/", 1)
        try:
            return float(numerator) / float(denominator) * 4.0
        except (ValueError, ZeroDivisionError):
            return 0.0
    return 0.0


DISPLAY_FACT_PASSES = [UpgradeTempoTexts(), UpgradeGradualTexts()]
