"""Bind unpitched drumset notes lacking MIDI percussion mappings to standard GM drumkit entries.

Upstream OMR emits percussion notes as ``<unpitched><display-step>/<display-octave>`` without
``<score-instrument>``, ``<midi-instrument><midi-unpitched>``, or cymbal ``<notehead>x</notehead>``.
Without explicit GM channel-10 bindings, MuseScore converts display positions literally into raw
MIDI note numbers (e.g. C5 -> 72 Long Whistle, G5 -> 79 Open Cuica, F4 -> 65 High Timbale).
"""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.document import Document
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase
from ..instruments import STANDARD_DRUMSET, DrumSpec

# Child tags in MusicXML 4.0 <note> that must precede <instrument>.
_BEFORE_INSTRUMENT = {"grace", "cue", "chord", "pitch", "unpitched", "rest", "duration", "tie"}
# Child tags in MusicXML 4.0 <note> that must precede <notehead>.
_BEFORE_NOTEHEAD = {
    "grace",
    "cue",
    "chord",
    "pitch",
    "unpitched",
    "rest",
    "duration",
    "tie",
    "instrument",
    "footnote",
    "level",
    "voice",
    "type",
    "dot",
    "accidental",
    "time-modification",
    "stem",
}
# Child tags in MusicXML 4.0 <score-part> that must precede <score-instrument>.
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


class NormalizePercussion:
    spec = PassSpec(
        name="normalize_percussion",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("percussion-bindings",),
        description="bind unpitched drumset notes to standard GM drumset MIDI instruments and cymbal noteheads",
        measure="unpitched drum notes missing <instrument> or <midi-unpitched> binding",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        del ctx
        part_list = doc.root.find("part-list")
        if part_list is None:
            return PassResult(changed=0)

        score_parts = {
            score_part.get("id"): score_part
            for score_part in part_list.findall("score-part")
            if score_part.get("id")
        }
        changed = 0
        for part_id, part in doc.iter_parts():
            if not _is_percussion_part(doc, part):
                continue
            score_part = score_parts.get(part_id)
            if score_part is None:
                continue
            changed += _normalize_part(part_id, part, score_part)
        return PassResult(changed=changed)


def _is_percussion_part(doc: Document, part: ElementTree.Element) -> bool:
    if doc.staff_count(part) > 1:
        return False
    unpitched_count = 0
    pitched_count = 0
    for note in part.iter("note"):
        if note.find("unpitched") is not None:
            unpitched_count += 1
        elif note.find("pitch") is not None:
            pitched_count += 1
    if unpitched_count == 0:
        return False
    if pitched_count == 0:
        return True
    # Only tolerate occasional spurious pitched notes if measure 1 declares percussion clef
    # and the part is predominantly unpitched.
    measures = doc.part_measures(part)
    first_is_perc = bool(
        measures
        and any(
            (clef.findtext("sign") or "").strip().lower() == "percussion"
            for clef in measures[0].findall("attributes/clef")
        )
    )
    return first_is_perc and unpitched_count > pitched_count


def _normalize_part(
    part_id: str,
    part: ElementTree.Element,
    score_part: ElementTree.Element,
) -> int:
    # Map existing midi-unpitched (1-based) -> instrument id so we never duplicate definitions.
    existing_unpitched: dict[int, str] = {}
    existing_score_ids: set[str] = {
        elem.get("id") for elem in score_part.findall("score-instrument") if elem.get("id")
    }
    existing_midi_ids: set[str] = set()
    for midi in score_part.findall("midi-instrument"):
        midi_id = midi.get("id")
        if midi_id:
            existing_midi_ids.add(midi_id)
        unpitched_text = midi.findtext("midi-unpitched")
        if midi_id and unpitched_text:
            try:
                existing_unpitched[int(unpitched_text.strip())] = midi_id
            except ValueError:
                pass

    # Discover which standard drum positions appear on unbound unpitched notes.
    needed: dict[tuple[str, str], DrumSpec] = {}
    unbound_notes: list[tuple[ElementTree.Element, DrumSpec]] = []
    for note in part.iter("note"):
        unpitched = note.find("unpitched")
        if unpitched is None or note.find("instrument") is not None:
            continue
        step = (unpitched.findtext("display-step") or "").strip().upper()
        octave = (unpitched.findtext("display-octave") or "").strip()
        spec = STANDARD_DRUMSET.get((step, octave))
        if spec is None:
            continue
        needed[(step, octave)] = spec
        unbound_notes.append((note, spec))

    if not unbound_notes:
        return 0

    changed = 0
    # Ensure <score-instrument> and <midi-instrument> exist for each needed drum sound.
    inst_id_for_unpitched: dict[int, str] = dict(existing_unpitched)
    for spec in sorted(needed.values(), key=lambda item: item.midi_unpitched):
        code = spec.midi_unpitched
        inst_id = inst_id_for_unpitched.get(code) or f"{part_id}-I{code}"
        if inst_id not in existing_score_ids:
            _insert_score_instrument(score_part, inst_id, spec)
            existing_score_ids.add(inst_id)
            changed += 1
        if inst_id not in existing_midi_ids:
            _append_midi_unpitched(score_part, inst_id, code)
            existing_midi_ids.add(inst_id)
            changed += 1
        inst_id_for_unpitched[code] = inst_id

    # Bind each unbound unpitched note to its GM drum instrument (and add cymbal notehead if absent).
    for note, spec in unbound_notes:
        inst_id = inst_id_for_unpitched[spec.midi_unpitched]
        _insert_note_instrument(note, inst_id)
        changed += 1
        if spec.notehead and note.find("notehead") is None:
            _insert_notehead(note, spec.notehead)
            changed += 1

    return changed


def _insert_score_instrument(
    score_part: ElementTree.Element,
    inst_id: str,
    spec: DrumSpec,
) -> None:
    elem = ElementTree.Element("score-instrument", {"id": inst_id})
    ElementTree.SubElement(elem, "instrument-name").text = spec.name
    ElementTree.SubElement(elem, "instrument-sound").text = spec.sound
    insert_at = 0
    for index, child in enumerate(list(score_part)):
        if child.tag in _BEFORE_SCORE_INSTRUMENT:
            insert_at = index + 1
    score_part.insert(insert_at, elem)


def _append_midi_unpitched(
    score_part: ElementTree.Element,
    inst_id: str,
    midi_unpitched: int,
) -> None:
    midi = ElementTree.SubElement(score_part, "midi-instrument", {"id": inst_id})
    ElementTree.SubElement(midi, "midi-channel").text = "10"
    ElementTree.SubElement(midi, "midi-program").text = "1"
    ElementTree.SubElement(midi, "midi-unpitched").text = str(midi_unpitched)


def _insert_note_instrument(note: ElementTree.Element, inst_id: str) -> None:
    elem = ElementTree.Element("instrument", {"id": inst_id})
    insert_at = 0
    for index, child in enumerate(list(note)):
        if child.tag in _BEFORE_INSTRUMENT:
            insert_at = index + 1
    note.insert(insert_at, elem)


def _insert_notehead(note: ElementTree.Element, shape: str) -> None:
    elem = ElementTree.Element("notehead")
    elem.text = shape
    insert_at = 0
    for index, child in enumerate(list(note)):
        if child.tag in _BEFORE_NOTEHEAD:
            insert_at = index + 1
    note.insert(insert_at, elem)


NORMALIZE_PERCUSSION = NormalizePercussion()
