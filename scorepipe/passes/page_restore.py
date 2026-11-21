"""Page-level notation restoration: ties, slurs and pedals that OMR only wrote per page.

The page MusicXML files keep their own local measure numbering; `Context.pages` is the
`MergedPages` model from the loader, which maps every local measure to the merged score.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

from ..core.document import Document
from ..core.pairing import Endpoint, pair_endpoints
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
        page_chords: dict[tuple, set] = {}
        endpoints: list[Endpoint] = []
        for page_index, path in enumerate(model.pages):
            root = ElementTree.parse(str(path)).getroot()
            for measure_index, staff, _voice, onset, _duration, pitch, _element in _page_events(root):
                if pitch is not None:
                    global_measure = offsets[page_index] + measure_index
                    page_chords.setdefault((global_measure, staff, round(onset, 4)), set()).add(pitch)
            for measure_index, staff, voice, onset, _duration, pitch, element in _page_events(root):
                if pitch is None:
                    continue
                global_measure = offsets[page_index] + measure_index
                for tie in _note_ties(element):
                    if tie not in ("start", "stop"):
                        continue
                    endpoints.append(
                        Endpoint(
                            key=(staff, voice, pitch),
                            position=(global_measure, round(onset, 4)),
                            kind=tie,
                            payload=(staff, global_measure, onset, pitch),
                        )
                    )
        pairing = pair_endpoints(endpoints)
        restored = 0
        tie_to_slur = ctx.options.get("tie_to_slur") or set()
        for start_endpoint, stop_endpoint in pairing.pairs:
            staff, start_measure, start_onset, pitch = start_endpoint.payload
            _staff, stop_measure, stop_onset, stop_pitch = stop_endpoint.payload
            start_key = (start_measure, staff, round(start_onset, 4), pitch)
            stop_key = (stop_measure, staff, round(stop_onset, 4), stop_pitch)
            if start_key in tie_to_slur and stop_key in tie_to_slur:
                # this tie was deliberately converted to a slur by reconcile_tie_slurs
                continue
            start_note = index.get((start_measure, staff, start_onset, pitch))
            stop_note = index.get((stop_measure, staff, stop_onset, stop_pitch))
            if start_note is None or stop_note is None:
                continue
            # a tie between two printed chords applies to every pitch they share
            start_set = page_chords.get((start_measure, staff, round(start_onset, 4)))
            stop_set = page_chords.get((stop_measure, staff, round(stop_onset, 4)))
            common = {pitch}
            if start_set and stop_set:
                common = start_set & stop_set or {pitch}
            applied = 0
            for member in sorted(common):
                member_start = index.get((start_measure, staff, start_onset, member))
                member_stop = index.get((stop_measure, staff, stop_onset, member))
                if member_start is None or member_stop is None:
                    continue
                added_start = _add_tie(member_start, "start")
                added_stop = _add_tie(member_stop, "stop")
                if added_start or added_stop:
                    applied += 1
            if applied:
                restored += applied
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
        endpoints: list[Endpoint] = []
        for page_index, path in enumerate(model.pages):
            root = ElementTree.parse(str(path)).getroot()
            for measure_index, staff, _voice, onset, _duration, pitch, element in _page_events(root):
                global_measure = offsets[page_index] + measure_index
                for slur in element.findall("notations/slur"):
                    number = slur.get("number") or "1"
                    kind = slur.get("type")
                    if kind not in ("start", "stop"):
                        continue
                    endpoints.append(
                        Endpoint(
                            key=(staff, number),
                            position=(global_measure, round(onset, 4)),
                            kind=kind,
                            payload=(staff, _voice, global_measure, onset, pitch),
                        )
                    )
        pairing = pair_endpoints(_musical_order(endpoints), max_span=MAX_SLUR_BARS, score=_slur_score)
        pairs: list[dict] = []
        for start, stop in pairing.pairs:
            staff, _voice, start_measure, start_onset, start_pitch = start.payload
            _staff, _stop_voice, stop_measure, stop_onset, stop_pitch = stop.payload
            if start_pitch is None or stop_pitch is None:
                continue
            start_note = index.get((start_measure, staff, start_onset, start_pitch))
            stop_note = index.get((stop_measure, staff, stop_onset, stop_pitch))
            if start_note is None or stop_note is None:
                continue
            # a page often records the same arc as both tie and slur; the tie is the specific one
            if _has_tie(start_note, "start") or _has_tie(stop_note, "stop"):
                continue
            pairs.append(
                {
                    "start": start_note,
                    "stop": stop_note,
                    "start_key": (start_measure, round(start_onset, 4)),
                    "stop_measure": stop_measure,
                }
            )
        # MuseScore resolves slur numbers document-wide, not per staff. Page numbers are only
        # unique within a staff, so they must be reassigned globally; otherwise the treble slur 1
        # pairs with the bass stop 1 and jumps staves (laputa m29-m30).
        desired = _assign_slur_numbers(pairs)
        current = _slur_signature(doc)
        if current == desired["signature"]:
            return PassResult()
        removed = sum(len(slurs) for slurs in current.values())
        _clear_slurs(doc)
        changed = removed
        for note, kind, number in desired["entries"]:
            _add_slur(note, kind, number)
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


def _has_tie(note, kind: str) -> bool:
    if any(tie.get("type") == kind for tie in note.findall("tie")):
        return True
    return any(tied.get("type") == kind for tied in note.findall("notations/tied"))


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


def _musical_order(endpoints: list[Endpoint]) -> list[Endpoint]:
    """Pair by when the marks sound, not by XML block order (laputa m35 stop appears first)."""
    return sorted(
        endpoints,
        key=lambda endpoint: (endpoint.position, 0 if endpoint.kind == "stop" else 1),
    )


def _slur_score(start, stop) -> float:
    """Prefer a start with the same pitch, then the same voice, for a reused slur number."""
    _staff, start_voice, _measure, _onset, start_pitch = start.payload
    _staff, stop_voice, _measure, _onset, stop_pitch = stop.payload
    score = 0.0
    if start_pitch is not None and start_pitch == stop_pitch:
        score += 100.0
    if start_voice == stop_voice:
        score += 10.0
    return score


def _assign_slur_numbers(pairs: list[dict]) -> dict:
    """Global 1..16 numbering, reused as soon as a slur has ended (the old skill's scheme)."""
    ordered = sorted(pairs, key=lambda pair: (pair["start_key"], pair["stop_measure"]))
    active: dict[int, int] = {}
    entries: list[tuple] = []
    seen: set[tuple] = set()
    for pair in ordered:
        identity = (id(pair["start"]), id(pair["stop"]))
        if identity in seen:
            continue  # the same page slur recorded twice must not become two arcs
        seen.add(identity)
        start_measure = pair["start_key"][0]
        for number in [key for key, end in active.items() if end < start_measure]:
            active.pop(number)
        free = next((number for number in range(1, 17) if number not in active), None)
        if free is None:
            continue
        active[free] = pair["stop_measure"]
        entries.append((pair["start"], "start", str(free)))
        entries.append((pair["stop"], "stop", str(free)))
    signature: dict[int, set] = {}
    for note, kind, number in entries:
        signature.setdefault(id(note), set()).add((kind, number))
    return {"entries": entries, "signature": {key: frozenset(value) for key, value in signature.items()}}


def _slur_signature(doc: Document) -> dict[int, frozenset]:
    signature: dict[int, set] = {}
    for _number, measure in doc.iter_measures():
        for note in measure.iter("note"):
            for slur in note.findall("notations/slur"):
                signature.setdefault(id(note), set()).add(
                    (slur.get("type") or "", slur.get("number") or "1")
                )
    return {key: frozenset(value) for key, value in signature.items()}


def _clear_slurs(doc: Document) -> None:
    for _number, measure in doc.iter_measures():
        for note in measure.iter("note"):
            notations = note.find("notations")
            if notations is None:
                continue
            for slur in list(notations.findall("slur")):
                notations.remove(slur)
            if not list(notations):
                note.remove(notations)


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
