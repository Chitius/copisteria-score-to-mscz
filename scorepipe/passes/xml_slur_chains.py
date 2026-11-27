"""Merge slurs that meet on the same note.

OMR sometimes splits one long phrase into two slurs that share a boundary note (laputa m53 G4 →
m54 A4, m54 A4 → m55 E5). When exactly one slur stops and one starts on the same note/voice, the
two are almost certainly one phrase; join the chain into a single slur.
"""

from __future__ import annotations

from collections import defaultdict
from xml.etree import ElementTree

from ..core.document import Document
from ..core.pairing import Endpoint, pair_endpoints
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase


class MergeAdjacentSlurs:
    spec = PassSpec(
        name="merge_adjacent_slurs",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("slur-chains",),
        description="join two slurs that stop and start on the same note",
        measure="slurs split at a shared boundary note",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        changed = 0
        for _part_id, part in doc.iter_parts():
            changed += _merge_part_slurs(doc, part)
        return PassResult(changed=changed)


def _merge_part_slurs(doc: Document, part: ElementTree.Element) -> int:
    endpoints = _collect_slurs(doc, part)
    pairs = pair_endpoints(endpoints).pairs
    if len(pairs) < 2:
        return 0

    all_starts: dict[int, list[int]] = defaultdict(list)
    all_stops: dict[int, list[int]] = defaultdict(list)
    for endpoint in endpoints:
        note = id(endpoint.payload[1].element)
        if endpoint.kind == "start":
            all_starts[note].append(id(endpoint))
        else:
            all_stops[note].append(id(endpoint))

    starts: dict[int, list[int]] = defaultdict(list)
    stops: dict[int, list[int]] = defaultdict(list)
    for index, (start, stop) in enumerate(pairs):
        starts[id(start.payload[1].element)].append(index)
        stops[id(stop.payload[1].element)].append(index)

    links: dict[int, int] = {}
    for index, (_start, stop) in enumerate(pairs):
        note = id(stop.payload[1].element)
        if len(starts[note]) != 1 or len(stops[note]) != 1:
            continue
        if len(all_starts[note]) != 1 or len(all_stops[note]) != 1:
            continue
        following = starts[note][0]
        if following == index or following in links:
            continue
        next_start = pairs[following][0].payload[1]
        if next_start.staff != stop.payload[1].staff or next_start.voice != stop.payload[1].voice:
            continue
        links[index] = following

    incoming = {target for target in links.values()}
    chains: list[list[int]] = []
    visited: set[int] = set()
    for index in range(len(pairs)):
        if index in incoming or index in visited:
            continue
        chain = []
        current = index
        while current not in visited:
            visited.add(current)
            chain.append(current)
            current = links.get(current, -1)
            if current == -1:
                break
        if len(chain) > 1:
            chains.append(chain)

    changed = 0
    for chain in chains:
        first_start = pairs[chain[0]][0]
        last_stop = pairs[chain[-1]][1]
        number = _free_slur_number(doc, part, first_start.payload[1].staff)
        if number is None:
            continue
        for index in chain:
            start, stop = pairs[index]
            _remove_slur(start.payload[1].element, start.payload[2])
            _remove_slur(stop.payload[1].element, stop.payload[2])
        _add_slur(first_start.payload[1].element, "start", number)
        _add_slur(last_stop.payload[1].element, "stop", number)
        changed += 1
    return changed


def _collect_slurs(doc: Document, part: ElementTree.Element) -> list[Endpoint]:
    endpoints: list[Endpoint] = []
    for number, measure in enumerate(doc.part_measures(part), start=1):
        for event in doc.events(measure):
            if event.rest:
                continue
            notations = event.element.find("notations")
            if notations is None:
                continue
            for slur in notations.findall("slur"):
                kind = slur.get("type")
                if kind not in ("start", "stop"):
                    continue
                endpoints.append(
                    Endpoint(
                        key=(event.staff, slur.get("number") or "1"),
                        position=(number, round(event.onset, 4)),
                        kind=kind,
                        payload=(number, event, slur),
                    )
                )
    endpoints.sort(key=lambda endpoint: (endpoint.position, 0 if endpoint.kind == "stop" else 1))
    return endpoints


def _remove_slur(note, slur) -> None:
    for notations in list(note.findall("notations")):
        if slur in list(notations):
            notations.remove(slur)
            if len(notations) == 0:
                note.remove(notations)
            return


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


def _free_slur_number(doc: Document, part: ElementTree.Element, staff: str) -> str | None:
    used = {
        slur.get("number") or "1"
        for measure in doc.part_measures(part)
        for note in measure.iter("note")
        if (note.findtext("staff") or "1") == staff
        for slur in note.findall("notations/slur")
    }
    return next((str(number) for number in range(1, 17) if str(number) not in used), None)


MERGE_ADJACENT_SLURS = MergeAdjacentSlurs()
