"""Reconcile ties and slurs when OMR confuses the two.

Rules:

1. if a slur and a tie have the same start/end notes, the tie wins and the slur is removed;
2. a tie that has another pitch between its endpoints in the same voice cannot be a tie
   (a tie is contiguous on one pitch), so it becomes a slur;
3. a slur whose endpoints are the same pitch and contiguous, with no note between them in the
   same voice, is a tie.
"""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.document import Document
from ..core.pairing import Endpoint, pair_endpoints
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase


class ReconcileTieSlurs:
    spec = PassSpec(
        name="reconcile_tie_slurs",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("tie-slur-reconciliation",),
        description="remove a slur duplicated by a tie; turn non-contiguous ties into slurs and "
        "contiguous same-pitch slurs into ties",
        measure="slurs duplicated by ties, ties that span other pitches, tie-shaped slurs",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        changed = 0
        changed += _drop_slurs_under_ties(doc)
        changed += _ties_with_other_pitches_to_slurs(doc, ctx)
        changed += _tie_shaped_slurs_to_ties(doc)
        changed += _drop_orphan_slurs(doc)
        return PassResult(changed=changed)


def _drop_orphan_slurs(doc: Document) -> int:
    _events, _ties, slurs = _collect(doc)
    removed = 0
    for endpoint in pair_endpoints(slurs).orphans:
        note = endpoint.payload[1].element
        _remove_slur(note, endpoint.payload[2])
        removed += 1
    return removed


def _pitch(note) -> tuple | None:
    pitch = note.find("pitch")
    if pitch is None:
        return None
    return (
        pitch.findtext("step") or "",
        pitch.findtext("alter") or "0",
        pitch.findtext("octave") or "",
    )


def _collect(doc: Document):
    ties: list[Endpoint] = []
    slurs: list[Endpoint] = []
    events = []
    for number, measure in doc.iter_measures():
        for event in doc.events(measure):
            if event.rest:
                continue
            events.append((number, event))
            pitch = _pitch(event.element)
            for tie in event.element.findall("tie"):
                kind = tie.get("type")
                if kind in ("start", "stop") and pitch is not None:
                    ties.append(
                        Endpoint(
                            key=(event.staff, event.voice, pitch),
                            position=(number, round(event.onset, 4)),
                            kind=kind,
                            payload=(number, event, tie),
                        )
                    )
            notations = event.element.find("notations")
            if notations is None:
                continue
            for slur in notations.findall("slur"):
                kind = slur.get("type")
                if kind not in ("start", "stop"):
                    continue
                number_text = slur.get("number") or "1"
                slurs.append(
                    Endpoint(
                        key=(event.staff, number_text),
                        position=(number, round(event.onset, 4)),
                        kind=kind,
                        payload=(number, event, slur),
                    )
                )
    ties.sort(key=lambda endpoint: (endpoint.position, 0 if endpoint.kind == "stop" else 1))
    slurs.sort(key=lambda endpoint: (endpoint.position, 0 if endpoint.kind == "stop" else 1))
    return events, ties, slurs


def _drop_slurs_under_ties(doc: Document) -> int:
    _events, ties, slurs = _collect(doc)
    tie_pairs = pair_endpoints(ties).pairs
    slur_pairs = pair_endpoints(slurs).pairs
    removed = 0
    for slur_start, slur_stop in slur_pairs:
        start_note = slur_start.payload[1].element
        stop_note = slur_stop.payload[1].element
        if not any(
            tie_start.payload[1].element is start_note
            and tie_stop.payload[1].element is stop_note
            for tie_start, tie_stop in tie_pairs
        ):
            continue
        _remove_slur(start_note, slur_start.payload[2])
        _remove_slur(stop_note, slur_stop.payload[2])
        removed += 1
    return removed


def _ties_with_other_pitches_to_slurs(doc: Document, ctx: Context) -> int:
    events, ties, _slurs = _collect(doc)
    marker = ctx.options.setdefault("tie_to_slur", set())
    changed = 0
    for start, stop in pair_endpoints(ties).pairs:
        start_event = start.payload[1]
        stop_event = stop.payload[1]
        pitch = _pitch(start_event.element)
        if pitch is None or pitch != _pitch(stop_event.element):
            continue
        if start_event.voice != stop_event.voice:
            continue
        between = [
            event
            for _number, event in events
            if event.staff == start_event.staff
            and event.voice == start_event.voice
            and start_event.onset + 1e-6 < event.onset < stop_event.onset - 1e-6
            and _pitch(event.element) != pitch
        ]
        if not between:
            continue
        number = _free_slur_number(doc, start_event.staff)
        if number is None:
            continue
        _remove_tie(start_event.element, "start")
        _remove_tie(stop_event.element, "stop")
        _add_slur(start_event.element, "start", number)
        _add_slur(stop_event.element, "stop", number)
        marker.add(_marker_key(start, start_event, pitch))
        marker.add(_marker_key(stop, stop_event, pitch))
        changed += 1
    return changed


def _marker_key(endpoint, event, pitch) -> tuple:
    number = endpoint.payload[0]
    return (number, event.staff, round(event.onset, 4), "".join(pitch))


def _tie_shaped_slurs_to_ties(doc: Document) -> int:
    events, _ties, slurs = _collect(doc)
    changed = 0
    for start, stop in pair_endpoints(slurs).pairs:
        start_event = start.payload[1]
        stop_event = stop.payload[1]
        pitch = _pitch(start_event.element)
        if pitch is None or pitch != _pitch(stop_event.element):
            continue
        if start_event.voice != stop_event.voice:
            continue
        if abs(start_event.end - stop_event.onset) > 1e-6:
            continue
        between = [
            event
            for _number, event in events
            if event.staff == start_event.staff
            and event.voice == start_event.voice
            and start_event.onset + 1e-6 < event.onset < stop_event.onset - 1e-6
        ]
        if between:
            continue
        _remove_slur(start_event.element, start.payload[2])
        _remove_slur(stop_event.element, stop.payload[2])
        _add_tie(start_event.element, "start")
        _add_tie(stop_event.element, "stop")
        changed += 1
    return changed


def _remove_slur(note, slur) -> None:
    notations = note.find("notations")
    if notations is None:
        return
    if slur in list(notations):
        notations.remove(slur)
    if len(notations) == 0:
        note.remove(notations)


def _add_slur(note, kind: str, number: str) -> None:
    notations = note.find("notations")
    if notations is None:
        notations = ElementTree.SubElement(note, "notations")
    if any(
        slur.get("type") == kind and (slur.get("number") or "1") == number
        for slur in notations.findall("slur")
    ):
        return
    ElementTree.SubElement(notations, "slur", {"type": kind, "number": number})


def _remove_tie(note, kind: str) -> None:
    for tie in list(note.findall("tie")):
        if tie.get("type") == kind:
            note.remove(tie)
    notations = note.find("notations")
    if notations is None:
        return
    for tied in list(notations.findall("tied")):
        if tied.get("type") == kind:
            notations.remove(tied)
    if len(notations) == 0:
        note.remove(notations)


def _add_tie(note, kind: str) -> None:
    if not any(tie.get("type") == kind for tie in note.findall("tie")):
        duration = note.find("duration")
        position = list(note).index(duration) + 1 if duration is not None else 0
        note.insert(position, ElementTree.Element("tie", {"type": kind}))
    notations = note.find("notations")
    if notations is None:
        notations = ElementTree.SubElement(note, "notations")
    if not any(tied.get("type") == kind for tied in notations.findall("tied")):
        ElementTree.SubElement(notations, "tied", {"type": kind})


def _free_slur_number(doc: Document, staff: str) -> str | None:
    used = {
        slur.get("number") or "1"
        for _number, measure in doc.iter_measures()
        for note in measure.iter("note")
        if (note.findtext("staff") or "1") == staff
        for slur in note.findall("notations/slur")
    }
    return next((str(number) for number in range(1, 17) if str(number) not in used), None)


RECONCILE_TIE_SLURS = ReconcileTieSlurs()
