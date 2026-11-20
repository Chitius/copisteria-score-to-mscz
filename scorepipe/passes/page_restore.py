"""Page-level notation restoration: ties, slurs and pedals that OMR only wrote per page.

The page MusicXML files keep their own local measure numbering; `Context.pages` is the
`MergedPages` model from the loader, which maps every local measure to the merged score.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

from ..core.document import Document
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase

MAX_SLUR_BARS = 6


def _offsets(pages) -> list[int]:
    offsets = []
    running = 0
    for count in pages.measure_counts:
        offsets.append(running)
        running += count
    return offsets


def _page_events(root) -> list[tuple]:
    """(measure_index, staff, voice, onset, duration, pitch, element) for one page."""
    part = root.find("part")
    if part is None:
        return []
    divisions = float(root.findtext(".//divisions") or 10080)
    events = []
    for measure_index, measure in enumerate(part.findall("measure"), start=1):
        cursor = 0
        previous = None
        for item in measure:
            if item.tag in ("backup", "forward"):
                text = item.findtext("duration")
                if text is None:
                    continue
                value = int(text)
                cursor += -value if item.tag == "backup" else value
                previous = None
                continue
            if item.tag != "note":
                previous = None
                continue
            text = item.findtext("duration")
            if text is None:
                previous = None
                continue
            duration = int(text)
            chord = item.find("chord") is not None
            onset = previous if chord and previous is not None else cursor
            if not chord:
                cursor += duration
            previous = onset
            pitch = item.find("pitch")
            events.append(
                (
                    measure_index,
                    item.findtext("staff") or "1",
                    item.findtext("voice") or "1",
                    round(onset / divisions, 4),
                    duration / divisions,
                    _pitch_name(pitch),
                    item,
                )
            )
    return events


def _pitch_name(pitch) -> str | None:
    if pitch is None:
        return None
    return (
        (pitch.findtext("step") or "")
        + (pitch.findtext("alter") or "0")
        + (pitch.findtext("octave") or "")
    )


def _merged_index(doc: Document) -> dict[tuple, ElementTree.Element]:
    index = {}
    for number, measure in doc.iter_measures():
        for event in doc.events(measure):
            if event.rest:
                continue
            pitch = event.element.find("pitch")
            name = _pitch_name(pitch)
            if name is None:
                continue
            index[(number, event.staff, round(event.onset, 4), name)] = event.element
    return index


class PageRestoreMixin:
    def _model(self, ctx: Context):
        model = getattr(ctx, "pages", None)
        if model is None or not getattr(model, "pages", None):
            return None
        return model


class RestorePageTies(PageRestoreMixin):
    spec = PassSpec(
        name="restore_page_ties",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("page-ties",),
        description="re-attach ties that were written per page to the merged score",
        measure="page ties missing from the merged score",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        model = self._model(ctx)
        if model is None:
            return PassResult()
        index = _merged_index(doc)
        offsets = _offsets(model)
        restored = 0
        for page_index, path in enumerate(model.pages):
            root = ElementTree.parse(str(path)).getroot()
            open_ties: dict[tuple, list] = {}
            for measure_index, staff, voice, onset, _duration, pitch, _element in _page_events(root):
                for tie in _note_ties(_element):
                    if pitch is None:
                        continue
                    key = (staff, voice, pitch)
                    global_measure = offsets[page_index] + measure_index
                    if tie == "start":
                        open_ties.setdefault(key, []).append((global_measure, onset))
                    elif open_ties.get(key):
                        start = open_ties[key].pop(0)
                        start_note = index.get((start[0], staff, start[1], pitch))
                        stop_note = index.get((global_measure, staff, onset, pitch))
                        if start_note is None or stop_note is None:
                            continue
                        if _add_tie(start_note, "start") | _add_tie(stop_note, "stop"):
                            restored += 1
        return PassResult(changed=restored)


class RestorePageSlurs(PageRestoreMixin):
    spec = PassSpec(
        name="restore_page_slurs",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("page-slurs",),
        description="re-attach slurs per page, pairing by staff and number (not by voice)",
        measure="page slurs missing from the merged score",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        model = self._model(ctx)
        if model is None:
            return PassResult()
        index = _merged_index(doc)
        offsets = _offsets(model)
        restored = 0
        for page_index, path in enumerate(model.pages):
            root = ElementTree.parse(str(path)).getroot()
            open_slurs: dict[tuple, list] = {}
            for measure_index, staff, _voice, onset, _duration, pitch, element in _page_events(root):
                key = (staff,)
                global_measure = offsets[page_index] + measure_index
                for slur in element.findall("notations/slur"):
                    number = slur.get("number") or "1"
                    kind = slur.get("type")
                    pair_key = (staff, number)
                    if kind == "start":
                        open_slurs.setdefault(pair_key, []).append((global_measure, onset, pitch))
                    elif kind == "stop":
                        stack = open_slurs.get(pair_key) or []
                        if not stack:
                            continue
                        start = stack.pop()
                        if start[2] is None or pitch is None:
                            continue
                        if global_measure - start[0] > MAX_SLUR_BARS:
                            continue
                        start_note = index.get((start[0], staff, start[1], start[2]))
                        stop_note = index.get((global_measure, staff, onset, pitch))
                        if start_note is None or stop_note is None:
                            continue
                        if _add_slur(start_note, "start", number) | _add_slur(stop_note, "stop", number):
                            restored += 1
        return PassResult(changed=restored)


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
        offsets = _offsets(model)
        measures = doc.measures()
        desired = []
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
                    if item.tag != "direction":
                        continue
                    pedal = item.find("direction-type/pedal")
                    if pedal is None:
                        continue
                    offset = item.findtext("offset")
                    onset = cursor + (int(offset) if offset else 0)
                    desired.append(
                        {
                            "measure": offsets[page_index] + measure_index,
                            "staff": item.findtext("staff") or "1",
                            "onset": onset / divisions,
                            "type": pedal.get("type"),
                            "number": pedal.get("number") or "1",
                            "placement": item.get("placement") or "below",
                        }
                    )
        changed = 0
        desired_by_measure: dict[int, list[dict]] = {}
        for entry in desired:
            desired_by_measure.setdefault(entry["measure"], []).append(entry)
        for measure_number, entries in desired_by_measure.items():
            if not 0 < measure_number <= len(measures):
                continue
            measure = measures[measure_number - 1]
            wanted = sorted(
                (entry["type"], entry["staff"], round(entry["onset"], 4), entry["number"])
                for entry in entries
            )
            existing = sorted(
                (
                    direction.find("direction-type/pedal").get("type"),
                    direction.findtext("staff") or "1",
                    round(float(direction.findtext("offset") or 0) / doc.divisions(), 4),
                    direction.find("direction-type/pedal").get("number") or "1",
                )
                for direction in measure.findall("direction")
                if direction.find("direction-type/pedal") is not None
            )
            if wanted == existing:
                continue
            for direction in list(measure.findall("direction")):
                if direction.find("direction-type/pedal") is not None:
                    measure.remove(direction)
                    changed += 1
            for entry in entries:
                direction = ElementTree.Element("direction", {"placement": entry["placement"]})
                direction_type = ElementTree.SubElement(direction, "direction-type")
                ElementTree.SubElement(
                    direction_type, "pedal", {"type": entry["type"], "number": entry["number"]}
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
        index = _merged_index(doc)
        onset_index = _merged_onset_index(doc)
        offsets = _offsets(model)
        restored = 0
        for page_index, path in enumerate(model.pages):
            root = ElementTree.parse(str(path)).getroot()
            for measure_index, staff, _voice, onset, _duration, pitch, element in _page_events(root):
                global_measure = offsets[page_index] + measure_index
                marks = element.findall("notations/arpeggiate") + element.findall("notations/non-arpeggiate")
                for mark in marks:
                    note = index.get((global_measure, staff, onset, pitch)) if pitch else None
                    if note is None:
                        note = onset_index.get((global_measure, staff, onset))
                    if note is None:
                        continue
                    if _add_notation(note, mark):
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
        offsets = _offsets(model)
        measures = doc.measures()
        desired: list[dict] = []
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
                    if item.tag != "direction":
                        continue
                    wedge = item.find("direction-type/wedge")
                    if wedge is None:
                        continue
                    offset = item.findtext("offset")
                    onset = cursor + (int(offset) if offset else 0)
                    desired.append(
                        {
                            "measure": offsets[page_index] + measure_index,
                            "staff": item.findtext("staff") or "1",
                            "onset": onset / divisions,
                            "type": wedge.get("type"),
                            "number": wedge.get("number") or "1",
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
                    direction.find("direction-type/wedge").get("type"),
                    direction.findtext("staff") or "1",
                    round(float(direction.findtext("offset") or 0) / doc.divisions(), 4),
                    direction.find("direction-type/wedge").get("number") or "1",
                )
                for direction in measure.findall("direction")
                if direction.find("direction-type/wedge") is not None
            )
            if wanted == existing:
                continue
            for direction in list(measure.findall("direction")):
                if direction.find("direction-type/wedge") is not None:
                    measure.remove(direction)
                    changed += 1
            for entry in entries:
                direction = ElementTree.Element("direction", {"placement": entry["placement"]})
                direction_type = ElementTree.SubElement(direction, "direction-type")
                ElementTree.SubElement(
                    direction_type, "wedge", {"type": entry["type"], "number": entry["number"]}
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


def _merged_onset_index(doc: Document) -> dict[tuple, ElementTree.Element]:
    index = {}
    for number, measure in doc.iter_measures():
        for event in doc.events(measure):
            if event.rest:
                continue
            index.setdefault((number, event.staff, round(event.onset, 4)), event.element)
    return index


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


def _note_ties(note) -> list[str]:
    kinds = [tie.get("type") for tie in note.findall("tie") if tie.get("type")]
    if kinds:
        return kinds
    return [tied.get("type") for tied in note.findall("notations/tied") if tied.get("type")]


def _add_tie(note, kind: str) -> bool:
    if any(tie.get("type") == kind for tie in note.findall("tie")):
        return False
    duration = note.find("duration")
    position = list(note).index(duration) + 1 if duration is not None else 0
    note.insert(position, ElementTree.Element("tie", {"type": kind}))
    notations = note.find("notations")
    if notations is None:
        notations = ElementTree.SubElement(note, "notations")
    if not any(tied.get("type") == kind for tied in notations.findall("tied")):
        ElementTree.SubElement(notations, "tied", {"type": kind})
    return True


def _add_slur(note, kind: str, number: str) -> bool:
    notations = note.find("notations")
    if notations is None:
        notations = ElementTree.SubElement(note, "notations")
    for slur in notations.findall("slur"):
        if slur.get("type") == kind and (slur.get("number") or "1") == number:
            return False
    ElementTree.SubElement(notations, "slur", {"type": kind, "number": number})
    return True


RESTORE_PAGE_TIES = RestorePageTies()
RESTORE_PAGE_SLURS = RestorePageSlurs()
RESTORE_PAGE_PEDALS = RestorePagePedals()
RESTORE_PAGE_ARPEGGIOS = RestorePageArpeggios()
RESTORE_PAGE_ARTICULATIONS = RestorePageArticulations()
RESTORE_PAGE_WEDGES = RestorePageWedges()
