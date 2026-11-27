"""Inject part instrument metadata (name, abbreviation, sound, MIDI program) from facts.

Idempotent and mechanical: updates ``<score-part>`` elements inside ``<part-list>`` without
touching pitched note data, and preserves per-drum ``<midi-unpitched>`` definitions on
percussion parts.
"""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.document import Document
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase
from ..instruments import InstrumentPreset, resolve_instrument

_BEFORE_ABBR = {"identification", "part-link", "part-name", "part-name-display"}
_BEFORE_SCORE_INSTRUMENT = {
    "identification",
    "part-link",
    "part-name",
    "part-name-display",
    "part-abbreviation",
    "part-abbreviation-display",
    "group",
    "score-instrument",
}


class ApplyPartsFacts:
    spec = PassSpec(
        name="apply_parts_facts",
        phase=Phase.INJECT,
        kind=Kind.MECHANICAL,
        owns=("part-instruments",),
        description="apply part names, abbreviations, instrument sounds, and MIDI programs from facts",
        measure="part instrument facts not yet reflected in <part-list>",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        part_facts = (ctx.facts or {}).get("parts") or []
        if not part_facts:
            return PassResult(changed=0)
        part_list = doc.root.find("part-list")
        if part_list is None:
            return PassResult(changed=0)

        score_parts = {
            score_part.get("id"): score_part
            for score_part in part_list.findall("score-part")
            if score_part.get("id")
        }
        used_channels = _collect_used_channels(score_parts.values())

        changed = 0
        for entry in part_facts:
            if not isinstance(entry, dict):
                continue
            part_id = (entry.get("part") or "").strip()
            if not part_id or part_id not in score_parts:
                continue
            score_part = score_parts[part_id]
            preset = resolve_instrument(entry.get("instrument"))
            changed += _apply_part_entry(part_id, score_part, entry, preset, used_channels)
        return PassResult(changed=changed)


def _apply_part_entry(
    part_id: str,
    score_part: ElementTree.Element,
    entry: dict,
    preset: InstrumentPreset | None,
    used_channels: set[int],
) -> int:
    changed = 0

    name = (entry.get("name") or "").strip() or (preset.name if preset else "")
    abbr = (entry.get("abbreviation") or "").strip() or (preset.abbreviation if preset else "")
    sound = (entry.get("sound") or "").strip() or (preset.sound if preset else "")
    midi_program = entry.get("midi_program")
    if midi_program is None and preset is not None and not preset.percussion:
        midi_program = preset.midi_program
    midi_channel = entry.get("midi_channel")
    is_percussion = bool(
        (preset is not None and preset.percussion)
        or _has_unpitched_midi(score_part)
        or midi_channel == 10
    )

    if name:
        part_name = score_part.find("part-name")
        if part_name is None:
            part_name = ElementTree.Element("part-name")
            score_part.insert(0, part_name)
            part_name.text = name
            changed += 1
        elif (part_name.text or "").strip() != name:
            part_name.text = name
            changed += 1

    if abbr:
        part_abbr = score_part.find("part-abbreviation")
        if part_abbr is None:
            part_abbr = ElementTree.Element("part-abbreviation")
            part_abbr.text = abbr
            insert_at = 0
            for index, child in enumerate(list(score_part)):
                if child.tag in _BEFORE_ABBR:
                    insert_at = index + 1
            score_part.insert(insert_at, part_abbr)
            changed += 1
        elif (part_abbr.text or "").strip() != abbr:
            part_abbr.text = abbr
            changed += 1

    # Percussion parts carry per-drum <score-instrument>/<midi-instrument><midi-unpitched> entries;
    # keep those intact instead of overwriting them with a single pitched instrument.
    if is_percussion:
        return changed

    if sound or midi_program is not None or midi_channel is not None:
        inst_id = f"{part_id}-I1"
        score_inst = _find_by_id(score_part, "score-instrument", inst_id)
        if score_inst is None:
            existing = score_part.find("score-instrument")
            if existing is not None and existing.get("id"):
                score_inst = existing
                inst_id = existing.get("id")
        inst_name = name or (preset.name if preset else part_id)

        if score_inst is None:
            score_inst = ElementTree.Element("score-instrument", {"id": inst_id})
            ElementTree.SubElement(score_inst, "instrument-name").text = inst_name
            if sound:
                ElementTree.SubElement(score_inst, "instrument-sound").text = sound
            insert_at = 0
            for index, child in enumerate(list(score_part)):
                if child.tag in _BEFORE_SCORE_INSTRUMENT:
                    insert_at = index + 1
            score_part.insert(insert_at, score_inst)
            changed += 1
        else:
            name_elem = score_inst.find("instrument-name")
            if name_elem is None:
                name_elem = ElementTree.Element("instrument-name")
                name_elem.text = inst_name
                score_inst.insert(0, name_elem)
                changed += 1
            elif (name_elem.text or "").strip() != inst_name:
                name_elem.text = inst_name
                changed += 1
            if sound:
                sound_elem = score_inst.find("instrument-sound")
                if sound_elem is None:
                    sound_elem = ElementTree.SubElement(score_inst, "instrument-sound")
                    sound_elem.text = sound
                    changed += 1
                elif (sound_elem.text or "").strip() != sound:
                    sound_elem.text = sound
                    changed += 1

        if midi_program is not None or midi_channel is not None:
            midi_inst = _find_by_id(score_part, "midi-instrument", inst_id)
            if midi_inst is None:
                channel = _pick_channel(midi_channel, used_channels)
                midi_inst = ElementTree.SubElement(score_part, "midi-instrument", {"id": inst_id})
                ElementTree.SubElement(midi_inst, "midi-channel").text = str(channel)
                if midi_program is not None:
                    ElementTree.SubElement(midi_inst, "midi-program").text = str(int(midi_program))
                used_channels.add(channel)
                changed += 1
            else:
                if midi_channel is not None:
                    ch_elem = midi_inst.find("midi-channel")
                    if ch_elem is None:
                        ch_elem = ElementTree.Element("midi-channel")
                        ch_elem.text = str(int(midi_channel))
                        midi_inst.insert(0, ch_elem)
                        used_channels.add(int(midi_channel))
                        changed += 1
                    elif (ch_elem.text or "").strip() != str(int(midi_channel)):
                        ch_elem.text = str(int(midi_channel))
                        used_channels.add(int(midi_channel))
                        changed += 1
                if midi_program is not None:
                    prog_elem = midi_inst.find("midi-program")
                    if prog_elem is None:
                        prog_elem = ElementTree.SubElement(midi_inst, "midi-program")
                        prog_elem.text = str(int(midi_program))
                        changed += 1
                    elif (prog_elem.text or "").strip() != str(int(midi_program)):
                        prog_elem.text = str(int(midi_program))
                        changed += 1

    return changed


def _has_unpitched_midi(score_part: ElementTree.Element) -> bool:
    return any(midi.find("midi-unpitched") is not None for midi in score_part.findall("midi-instrument"))


def _find_by_id(
    parent: ElementTree.Element, tag: str, element_id: str
) -> ElementTree.Element | None:
    for child in parent.findall(tag):
        if child.get("id") == element_id:
            return child
    return None


def _collect_used_channels(score_parts) -> set[int]:
    used: set[int] = {10}  # reserve channel 10 for GM percussion
    for score_part in score_parts:
        for midi in score_part.findall("midi-instrument"):
            text = (midi.findtext("midi-channel") or "").strip()
            if text:
                try:
                    used.add(int(text))
                except ValueError:
                    pass
    return used


def _pick_channel(requested: int | None, used_channels: set[int]) -> int:
    if requested is not None:
        return int(requested)
    for candidate in range(1, 17):
        if candidate not in used_channels:
            return candidate
    return 1


INJECT_PARTS = ApplyPartsFacts()
