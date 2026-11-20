"""Rebuild fragmented measures into clean voices.

copisteria sometimes writes one chord as several consecutive blocks with backups, and sometimes
puts a short note at the same onset as a long chord. Both are fine as XML but MuseScore resolves
them by merging the blocks into one chord, which loses durations and ties.

For such a measure this pass rebuilds the staff as non-overlapping layers: notes that share an
onset and duration form one chord, each layer goes into the first voice that is free at that onset,
and gaps become rests. Durations, ties and notations are preserved.
"""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.document import Document
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase


class RebuildVoiceLayers:
    spec = PassSpec(
        name="rebuild_voice_layers",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("voice-layers",),
        description="rebuild a fragmented measure as non-overlapping voices, keeping durations and ties",
        measure="fragmented measures MuseScore would coerce",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        changed = 0
        for _number, measure in doc.iter_measures():
            if _needs_rebuild(doc, measure):
                if _rebuild(doc, measure):
                    changed += 1
        return PassResult(changed=changed)


def _needs_rebuild(doc: Document, measure) -> bool:
    seen: set[tuple] = set()
    durations: dict[tuple, set] = {}
    for event in doc.events(measure):
        if event.rest:
            continue
        key = (event.staff, event.voice, round(event.onset, 4))
        if key in seen:
            # same voice, same onset: copisteria fragments or a conflicting duration
            durations.setdefault(key, set()).add(round(event.duration, 4))
        seen.add(key)
        durations.setdefault(key, set()).add(round(event.duration, 4))
    return any(len(values) > 1 for values in durations.values())


def _rebuild(doc: Document, measure) -> bool:
    events = doc.events(measure)
    if not events:
        return False
    meter = doc.time_signature(measure) or (4.0, 4.0)
    bar = meter[0] * 4.0 / meter[1]
    divisions = doc.divisions()
    leading = [
        child
        for child in list(measure)
        if child.tag in ("attributes", "print", "direction", "sound", "barline")
    ]
    by_staff: dict[str, list] = {}
    for event in events:
        if event.rest:
            continue
        by_staff.setdefault(event.staff, []).append(event)

    blocks: list[list[ElementTree.Element]] = []
    for staff in sorted(by_staff):
        layers: dict[tuple, list] = {}
        for event in by_staff[staff]:
            layers.setdefault((round(event.onset, 4), round(event.duration, 4)), []).append(event)
        voices: list[dict] = []
        for (onset, duration), group in sorted(layers.items()):
            slot = next(
                (voice for voice in voices if voice["end"] <= onset + 1e-6),
                None,
            )
            if slot is None:
                slot = {"end": 0.0, "elements": []}
                voices.append(slot)
            elements = slot["elements"]
            if onset > slot["end"] + 1e-6:
                forward = ElementTree.Element("forward")
                ElementTree.SubElement(forward, "duration").text = str(
                    int(round((onset - slot["end"]) * divisions))
                )
                elements.append(forward)
            first = group[0].element
            for position, event in enumerate(group):
                element = event.element
                chord = element.find("chord")
                if position == 0 and chord is not None:
                    element.remove(chord)
                elif position > 0 and chord is None:
                    element.insert(0, ElementTree.Element("chord"))
                elements.append(element)
            slot["end"] = onset + duration
        for number, voice in enumerate(voices, start=1):
            for element in voice["elements"]:
                if element.tag != "note":
                    continue
                voice_element = element.find("voice")
                if voice_element is None:
                    voice_element = ElementTree.SubElement(element, "voice")
                voice_element.text = str(number)
        for index, voice in enumerate(voices):
            if blocks:
                backup = ElementTree.Element("backup")
                ElementTree.SubElement(backup, "duration").text = str(int(round(bar * divisions)))
                blocks.append([backup])
            if voice["end"] < bar - 1e-6:
                rest = ElementTree.Element("note")
                ElementTree.SubElement(rest, "rest")
                ElementTree.SubElement(rest, "duration").text = str(
                    int(round((bar - voice["end"]) * divisions))
                )
                voice["elements"].append(rest)
            blocks.append(voice["elements"])

    for event in events:
        element = event.element
        if element in list(measure):
            measure.remove(element)
    for child in list(measure):
        if child.tag in ("backup", "forward"):
            measure.remove(child)
    children = list(leading)
    for block in blocks:
        children.extend(block)
    measure[:] = children
    return True


REBUILD_VOICE_LAYERS = RebuildVoiceLayers()
