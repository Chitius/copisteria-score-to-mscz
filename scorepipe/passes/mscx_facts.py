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


DISPLAY_FACT_PASSES = [UpgradeTempoTexts()]
