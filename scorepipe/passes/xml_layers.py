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

from ..core.directions import direction_onsets, set_direction_offset
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
        for _part_id, part, _number, measure in doc.iter_part_measures():
            if _needs_rebuild(doc, measure):
                if _rebuild(doc, measure, part):
                    changed += 1
        return PassResult(changed=changed)


def _needs_rebuild(doc: Document, measure) -> bool:
    seen: set[tuple] = set()
    events = doc.events(measure)
    for event in events:
        if event.rest or event.chord:
            continue
        key = (event.staff, event.voice, round(event.onset, 4))
        if key in seen:
            return True
        seen.add(key)
    by_voice: dict[tuple, list] = {}
    for event in events:
        # Rests occupy voice time too. A backup that rewinds into a rest creates
        # the same MuseScore-hostile overlap as two overlapping notes.
        if event.chord:
            continue
        by_voice.setdefault((event.staff, event.voice), []).append(event)
    for voice_events in by_voice.values():
        voice_events.sort(key=lambda event: event.onset)
        end = -1.0
        for event in voice_events:
            if event.onset < end - 1e-6:
                return True
            end = max(end, event.end)
    return False


def _rebuild(doc: Document, measure, part=None) -> bool:
    divisions = doc.effective_divisions(measure, part)
    events = doc.events(measure, divisions)
    if not events or not any(not event.rest for event in events):
        return False
    meter = doc.effective_time_signature(measure, part)
    bar = meter[0] * 4.0 / meter[1]
    onsets = direction_onsets(measure)
    leading = []
    for child in list(measure):
        if child.tag in ("attributes", "print", "direction", "sound", "barline"):
            if child.tag == "direction":
                set_direction_offset(child, onsets.get(id(child), 0))
            leading.append(child)
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
                # The rest belongs to this staff/voice block; MusicXML would inherit both from
                # the preceding note, but scorepipe's own readers default a missing <staff> to
                # "1", so an explicit staff/voice keeps the file self-describing (First Step
                # m82: the unattributed rest was read as staff 1 and later trimmed into a
                # stray <forward>, giving MuseScore a 3.25-beat bar).
                ElementTree.SubElement(rest, "voice").text = str(index + 1)
                ElementTree.SubElement(rest, "staff").text = staff
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
