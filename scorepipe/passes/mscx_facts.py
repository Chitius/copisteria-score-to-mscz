"""Display-layer fact injection: make a recognised tempo word a real Tempo object."""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.mscx import MsxcDocument
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase
from .tempo_text import looks_like_tempo_text, normalize_tempo_text

METRONOME_SYMBOLS = {
    "whole": "metNoteWhole",
    "half": "metNoteHalfUp",
    "quarter": "metNoteQuarterUp",
    "eighth": "metNote8thUp",
    "16th": "metNote16thUp",
    "32nd": "metNote32ndUp",
}


class ApplyTextFactsStyle:
    spec = PassSpec(
        name="apply_text_facts_style",
        phase=Phase.DISPLAY,
        kind=Kind.MECHANICAL,
        owns=("text-display-style",),
        description="apply facts justification to imported StaffText objects",
        measure="fact text objects without their alignment",
    )

    def run(self, doc: MsxcDocument, ctx: Context) -> PassResult:
        facts = (ctx.facts or {}).get("marks") or []
        changed = 0
        staves = doc.staves()
        for fact in facts:
            text = (fact.get("text") or "").strip()
            justify = (fact.get("justify") or "").strip().lower()
            if not text or justify not in ("center", "left", "right"):
                continue
            number = int(fact.get("measure") or 0)
            for staff in staves:
                measures = staff.findall("Measure")
                if not 0 < number <= len(measures):
                    continue
                for node in measures[number - 1].iter():
                    if node.tag not in ("StaffText", "SystemText"):
                        continue
                    if _node_text(node).strip() != text:
                        continue
                    align = f"{justify},top"
                    if (node.findtext("align") or "") == align:
                        continue
                    existing = node.find("align")
                    if existing is None:
                        ElementTree.SubElement(node, "align").text = align
                    else:
                        existing.text = align
                    changed += 1
        return PassResult(changed=changed)


def _node_text(node) -> str:
    text = node.find("text")
    if text is None:
        return ""
    return "".join(text.itertext())


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
            raw_text = (fact.get("text") or "").strip()
            text = normalize_tempo_text(raw_text)
            if not tempo or not text:
                continue
            # either spelling matches: the shorthand ("q = 72") or the printed glyph ("♩ = 72")
            accepted = {text, raw_text}
            number = int(fact.get("measure") or 0)
            measures = staves[0].findall("Measure")
            if not 0 < number <= len(measures):
                continue
            measure = measures[number - 1]
            if any(_tempo_text(node).strip() in accepted for node in measure.iter("Tempo")):
                continue
            # the metronome direction imported from MusicXML becomes its own Tempo with just the
            # glyph and a number; drop it, the real Tempo below carries the words and the glyph.
            # Deleting a node is a change even when no StaffText replacement follows.
            for voice in measure.findall("voice"):
                for node in list(voice.findall("Tempo")):
                    plain = _plain_text(node).strip()
                    if plain and not any(character.isalpha() for character in plain):
                        voice.remove(node)
                        changed += 1
            for voice in measure.findall("voice"):
                replaced = False
                for node in list(voice):
                    if node.tag != "StaffText":
                        continue
                    if (node.findtext("text") or "").strip() not in accepted:
                        continue
                    element = ElementTree.Element("Tempo")
                    ElementTree.SubElement(element, "tempo").text = (
                        f"{float(tempo) / 60:.6f}".rstrip("0").rstrip(".")
                    )
                    text_element = ElementTree.SubElement(element, "text")
                    if looks_like_tempo_text(text):
                        text_element.text = text
                    else:
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


class ApplyCreditsDisplay:
    spec = PassSpec(
        name="apply_credits_display",
        phase=Phase.DISPLAY,
        kind=Kind.MECHANICAL,
        owns=("display-credits",),
        description="put title/subtitle/composer facts into the MuseScore title frame",
        measure="credits missing from the mscx title frame",
    )

    STYLES = {
        "title": "title",
        "subtitle": "subtitle",
        "composer": "composer",
        "arranger": "composer",
        "transcriber": "composer",
        "lyricist": "lyricist",
    }

    def run(self, doc: MsxcDocument, ctx: Context) -> PassResult:
        credits = (ctx.facts or {}).get("credits") or []
        score = doc.root.find("Score")
        if score is None:
            return PassResult()
        added = 0
        target = next((child for child in score if child.tag == "Staff"), score)
        position = 0
        created: set[int] = set()
        credit_texts = [(credit.get("text") or "").strip() for credit in credits]
        for credit in credits:
            text = (credit.get("text") or "").strip()
            if not text:
                continue
            style_name = self.STYLES.get((credit.get("type") or "title").strip(), "title")
            existing = [
                node
                for node in doc.root.iter("Text")
                if (node.findtext("text") or "").strip() == text
            ]
            if style_name == "composer":
                composer_texts = [
                    node for node in doc.root.iter("Text") if node.findtext("style") == "composer"
                ]
                if composer_texts:
                    composer_target = composer_texts[0]
                    target_text = composer_target.find("text")
                    if target_text is not None and text not in "".join(target_text.itertext()):
                        target_text.text = (target_text.text or "") + "\n" + text
                        added += 1
                    # Drop the separate imported credit Text that duplicated this line.
                    for node in existing:
                        if node is composer_target:
                            continue
                        parent = _parent_of(doc.root, node)
                        if parent is not None:
                            parent.remove(node)
                    continue
            if existing:
                # MuseScore already imported the MusicXML credit as a Text; give it the style
                for node in existing:
                    style = node.find("style")
                    if style is None:
                        style = ElementTree.Element("style")
                        text_element = node.find("text")
                        index = list(node).index(text_element) if text_element is not None else 0
                        node.insert(index, style)
                    if (style.text or "") != style_name:
                        style.text = style_name
                        added += 1
                continue
            vbox = ElementTree.Element("VBox")
            ElementTree.SubElement(vbox, "height").text = "10"
            text_element = ElementTree.SubElement(vbox, "Text")
            ElementTree.SubElement(text_element, "style").text = style_name
            ElementTree.SubElement(text_element, "text").text = text
            target.insert(position, vbox)
            created.add(id(vbox))
            position += 1
            added += 1
        # MuseScore imports MusicXML credits as a VBox at the *end* of the first staff; only a
        # frame before the measures is drawn as a title.  The credit order must not decide where
        # the frame goes: a facts file may list the arranger first (convert.py --arranger) or a
        # user facts file may already carry the title, and the old rank lookup then inserted the
        # frame after measure 1.  Every imported credit frame belongs before the first Measure.
        measure_index = next(
            (index for index, child in enumerate(list(target)) if child.tag == "Measure"),
            len(target),
        )
        for vbox in list(doc.root.iter("VBox")):
            if id(vbox) in created:
                continue
            texts = [(node.findtext("text") or "").strip() for node in vbox.iter("Text")]
            if not any(text in credit_texts for text in texts):
                continue
            parent = _parent_of(doc.root, vbox)
            if parent is target and list(target).index(vbox) < measure_index:
                continue
            if parent is not None:
                parent.remove(vbox)
            target.insert(measure_index, vbox)
            measure_index += 1
            added += 1
        return PassResult(changed=added)


def _before_first_staff(score) -> int:
    for index, child in enumerate(list(score)):
        if child.tag == "Staff":
            return index
    return len(score)


def _parent_of(root, target):
    for parent in root.iter():
        if target in list(parent):
            return parent
    return None


def _tempo_text(tempo_element) -> str:
    text = tempo_element.find("text")
    if text is None:
        return ""
    return "".join(text.itertext())


def _plain_text(tempo_element) -> str:
    """The words of a Tempo, ignoring <sym> glyph names (which are not visible text)."""
    text = tempo_element.find("text")
    if text is None:
        return ""
    parts = [text.text or ""]
    for child in text:
        if child.tag != "sym":
            parts.append(child.text or "")
        parts.append(child.tail or "")
    return "".join(parts)


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
                    if node.tag == "StaffText" and _node_text(node).strip() == text
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
            span_measures = int(fact.get("length_measures") or 1)
            span_fractions = str(fact.get("length_fractions") or "").strip()
            start = _gradual_start(text, gradual, span_measures, span_fractions)
            start_voice.insert(_insert_index_at(start_voice, beat), start)
            changed += 1

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


def _gradual_start(
    text: str, gradual: str, span_measures: int, span_fractions: str
) -> ElementTree.Element:
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
    ElementTree.SubElement(location, "measures").text = str(span_measures)
    if span_fractions:
        ElementTree.SubElement(location, "fractions").text = span_fractions
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


DISPLAY_FACT_PASSES = [UpgradeTempoTexts(), UpgradeGradualTexts(), ApplyTextFactsStyle(), ApplyCreditsDisplay()]
