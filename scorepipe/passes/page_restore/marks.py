"""Page-level pedal, wedge, arpeggio, and articulation restoration passes."""

from __future__ import annotations

from xml.etree import ElementTree

from ...core.document import Document
from ...core.pass_base import Context, Kind, PassResult, PassSpec, Phase
from .common import (
    PageRestoreMixin,
    _merged_index,
    _merged_onset_index,
    _offsets,
    _page_events,
    _pitch_name,
)


def _restore_page_directions(doc: Document, model, direction_tag: str) -> PassResult:
    """Replace ``direction-type/<direction_tag>`` elements with the page-accurate ones."""
    offsets = _offsets(model)
    measures = doc.measures()
    desired: list[dict] = []
    xpath = f"direction-type/{direction_tag}"
    for page_index, path in enumerate(model.pages):
        root = ElementTree.parse(str(path)).getroot()
        divisions = float(root.findtext(".//divisions") or 10080)
        part = root.find("part")
        if part is None:
            continue
        for measure_index, measure in enumerate(part.findall("measure"), start=1):
            cursor = 0
            for item in measure:
                if item.tag in ("backup", "forward"):
                    text = item.findtext("duration")
                    if text is None:
                        continue
                    value = int(text)
                    cursor += -value if item.tag == "backup" else value
                    continue
                if item.tag == "note":
                    text = item.findtext("duration")
                    if text is not None and item.find("chord") is None:
                        cursor += int(text)
                    continue
                if item.tag != "direction":
                    continue
                target = item.find(xpath)
                if target is None:
                    continue
                offset = item.findtext("offset")
                onset = cursor + (int(offset) if offset else 0)
                desired.append(
                    {
                        "measure": offsets[page_index] + measure_index,
                        "staff": item.findtext("staff") or "1",
                        "onset": onset / divisions,
                        "type": target.get("type"),
                        "number": target.get("number") or "1",
                        "placement": item.get("placement") or "below",
                    }
                )
    changed = 0
    by_measure: dict[int, list[dict]] = {}
    for entry in desired:
        by_measure.setdefault(entry["measure"], []).append(entry)
    for measure_number, entries in by_measure.items():
        if not 0 < measure_number <= len(measures):
            continue
        measure = measures[measure_number - 1]
        wanted = sorted(
            (entry["type"], entry["staff"], round(entry["onset"], 4), entry["number"])
            for entry in entries
        )
        existing = sorted(
            (
                direction.find(xpath).get("type"),
                direction.findtext("staff") or "1",
                round(float(direction.findtext("offset") or 0) / doc.divisions(), 4),
                direction.find(xpath).get("number") or "1",
            )
            for direction in measure.findall("direction")
            if direction.find(xpath) is not None
        )
        if wanted == existing:
            continue
        for direction in list(measure.findall("direction")):
            if direction.find(xpath) is not None:
                measure.remove(direction)
                changed += 1
        for entry in entries:
            direction = ElementTree.Element("direction", {"placement": entry["placement"]})
            direction_type = ElementTree.SubElement(direction, "direction-type")
            ElementTree.SubElement(
                direction_type, direction_tag, {"type": entry["type"], "number": entry["number"]}
            )
            if entry["onset"]:
                ElementTree.SubElement(direction, "offset").text = str(
                    int(round(entry["onset"] * doc.divisions()))
                )
            ElementTree.SubElement(direction, "staff").text = entry["staff"]
            index = next(
                (position for position, child in enumerate(measure) if child.tag == "note"),
                len(measure),
            )
            measure.insert(index, direction)
            changed += 1
    return PassResult(changed=changed)


class RestorePagePedals(PageRestoreMixin):
    spec = PassSpec(
        name="restore_page_pedals",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("page-pedals",),
        description="replace pedal directions with the page-accurate ones",
        measure="pedal directions that differ from the page",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        model = self._model(ctx)
        if model is None:
            return PassResult()
        return _restore_page_directions(doc, model, "pedal")


class RestorePageWedges(PageRestoreMixin):
    spec = PassSpec(
        name="restore_page_wedges",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("page-wedges",),
        description="replace wedge (crescendo/diminuendo) directions with the page-accurate ones",
        measure="wedge directions that differ from the page",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        model = self._model(ctx)
        if model is None:
            return PassResult()
        return _restore_page_directions(doc, model, "wedge")


class RestorePageArpeggios(PageRestoreMixin):
    spec = PassSpec(
        name="restore_page_arpeggios",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("page-arpeggios",),
        description="re-attach arpeggiate / non-arpeggiate marks written on the pages",
        measure="page arpeggio marks missing from the merged score",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        model = self._model(ctx)
        if model is None:
            return PassResult()
        offsets = _offsets(model)
        # An arpeggio belongs to a chord, not to one note. Page marks are collapsed per position,
        # then written once on the merged chord's base note; a single-note fragment that inherited
        # the mark (laputa m1 F6 after voice protection) loses it.
        page_marks: dict[tuple, tuple[ElementTree.Element, set[str]]] = {}
        for page_index, path in enumerate(model.pages):
            root = ElementTree.parse(str(path)).getroot()
            for measure_index, staff, _voice, onset, _duration, pitch, element in _page_events(root):
                marks = element.findall("notations/arpeggiate") + element.findall(
                    "notations/non-arpeggiate"
                )
                if not marks:
                    continue
                key = (offsets[page_index] + measure_index, staff, round(onset, 4))
                entry = page_marks.get(key)
                if entry is None:
                    page_marks[key] = (marks[0], {pitch} if pitch else set())
                elif pitch:
                    entry[1].add(pitch)

        notes_at: dict[tuple, list] = {}
        for number, measure in doc.iter_measures():
            for event in doc.events(measure):
                if event.rest:
                    continue
                notes_at.setdefault((number, event.staff, round(event.onset, 4)), []).append(event)

        restored = 0
        for key, (mark, marked_pitches) in page_marks.items():
            events = notes_at.get(key)
            if not events:
                continue
            groups: dict[str, list] = {}
            for event in events:
                groups.setdefault(event.voice, []).append(event)
            chord_groups = [group for group in groups.values() if len(group) >= 2]
            target = None
            if chord_groups:
                target = max(
                    chord_groups,
                    key=lambda group: (
                        len(group),
                        len({_pitch_name(event.element.find("pitch")) for event in group} & marked_pitches),
                    ),
                )
            if target is None:
                affected = events
                desired: list[tuple] = []
            else:
                base = next((event for event in target if event.element.find("chord") is None), target[0])
                # single-note voices at this onset are split chord fragments, not independent chords
                affected = list(target) + [
                    event for event in events if event.voice not in groups or len(groups[event.voice]) < 2
                ]
                desired = [(id(base.element), mark.tag, _mark_attributes(mark))]

            current = [
                (id(event.element), child.tag, tuple(sorted(child.attrib.items())))
                for event in affected
                for notations in event.element.findall("notations")
                for child in notations
                if child.tag in ("arpeggiate", "non-arpeggiate")
            ]
            if sorted(current) == sorted(desired):
                continue
            for event in affected:
                _remove_arpeggio_marks(event.element)
            if target is not None:
                _add_notation(base.element, mark)
            restored += 1
        return PassResult(changed=restored)


class RestorePageArticulations(PageRestoreMixin):
    spec = PassSpec(
        name="restore_page_articulations",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("page-articulations",),
        description="re-attach staccato/accent/tenuto and other page articulations",
        measure="page articulations missing from the merged score",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        model = self._model(ctx)
        if model is None:
            return PassResult()
        index = _merged_index(doc)
        onset_index = _merged_onset_index(doc)
        offsets = _offsets(model)
        restored = 0
        for page_index, path in enumerate(model.pages):
            root = ElementTree.parse(str(path)).getroot()
            for measure_index, staff, _voice, onset, _duration, pitch, element in _page_events(root):
                global_measure = offsets[page_index] + measure_index
                for mark in element.findall("notations/articulations/*"):
                    note = index.get((global_measure, staff, onset, pitch)) if pitch else None
                    if note is None:
                        note = onset_index.get((global_measure, staff, onset))
                    if note is None:
                        continue
                    if _add_articulation(note, mark):
                        restored += 1
        return PassResult(changed=restored)


def _mark_attributes(mark) -> tuple:
    return tuple(sorted(mark.attrib.items()))


def _remove_arpeggio_marks(note) -> None:
    notations = note.find("notations")
    if notations is None:
        return
    for child in list(notations):
        if child.tag in ("arpeggiate", "non-arpeggiate"):
            notations.remove(child)
    if len(notations) == 0:
        note.remove(notations)


def _add_notation(note, mark) -> bool:
    notations = note.find("notations")
    if notations is None:
        notations = ElementTree.SubElement(note, "notations")
    for existing in notations:
        if existing.tag == mark.tag and dict(existing.attrib) == dict(mark.attrib):
            return False
    notations.append(ElementTree.fromstring(ElementTree.tostring(mark)))
    return True


def _add_articulation(note, mark) -> bool:
    notations = note.find("notations")
    if notations is None:
        notations = ElementTree.SubElement(note, "notations")
    articulations = notations.find("articulations")
    if articulations is None:
        articulations = ElementTree.SubElement(notations, "articulations")
    for existing in articulations:
        if existing.tag == mark.tag and dict(existing.attrib) == dict(mark.attrib):
            return False
    articulations.append(ElementTree.fromstring(ElementTree.tostring(mark)))
    return True
