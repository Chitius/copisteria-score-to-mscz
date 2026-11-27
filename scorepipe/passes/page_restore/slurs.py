"""Page-level slur restoration pass."""

from __future__ import annotations

from xml.etree import ElementTree

from ...core.document import Document
from ...core.pairing import Endpoint, pair_endpoints
from ...core.pass_base import Context, Kind, PassResult, PassSpec, Phase
from .common import PageRestoreMixin, _merged_index, _offsets, _page_events, _pitch_name
from .ties import _has_tie

MAX_SLUR_BARS = 6


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
            # a page often records the same arc as both tie and slur; only when both endpoints
            # already carry a tie is the slur a duplicate. A slur may legitimately end on a tied note.
            if _has_tie(start_note, "start") and _has_tie(stop_note, "stop"):
                continue
            if _tied_span_covers(
                index,
                start_measure,
                staff,
                start_onset,
                start_pitch,
                stop_measure,
                stop_onset,
                stop_pitch,
                start_note,
                stop_note,
            ):
                continue
            pairs.append(
                {
                    "start": start_note,
                    "stop": stop_note,
                    "start_key": (start_measure, round(start_onset, 4)),
                    "stop_key": (stop_measure, round(stop_onset, 4)),
                    "staff": staff,
                    "start_pitch": start_pitch,
                    "stop_pitch": stop_pitch,
                    "stop_measure": stop_measure,
                }
            )
        # MuseScore resolves slur numbers document-wide, not per staff. Page numbers are only
        # unique within a staff, so they must be reassigned globally; otherwise the treble slur 1
        # pairs with the bass stop 1 and jumps staves (laputa m29-m30).
        # Page OMR often splits one long phrase at a shared note; join those before numbering.
        pairs = _merge_adjacent_pairs(pairs)
        desired = _assign_slur_numbers(pairs)
        current = _slur_signature(doc)
        if current == desired["signature"]:
            return PassResult()
        removed = len(current)
        _clear_slurs(doc)
        changed = removed
        for note, kind, number in desired["entries"]:
            _add_slur(note, kind, number)
            changed += 1
        return PassResult(changed=changed)


def _tied_span_covers(
    index,
    start_measure,
    staff,
    start_onset,
    start_pitch,
    stop_measure,
    stop_onset,
    stop_pitch,
    start_note,
    stop_note,
) -> bool:
    """If one slur endpoint is a tie note and the other lands at the tie's other end, the slur
    describes the same span as the tie (its other endpoint may be another chord member)."""
    if _has_tie(start_note, "start"):
        same_pitch_stop = index.get((stop_measure, staff, stop_onset, start_pitch))
        if same_pitch_stop is not None and _has_tie(same_pitch_stop, "stop"):
            return True
    if _has_tie(stop_note, "stop"):
        same_pitch_start = index.get((start_measure, staff, start_onset, stop_pitch))
        if same_pitch_start is not None and _has_tie(same_pitch_start, "start"):
            return True
    return False


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


def _merge_adjacent_pairs(pairs: list[dict]) -> list[dict]:
    """Join slur pairs whose stop note is the next pair's start note."""
    if len(pairs) < 2:
        return pairs
    starts: dict[int, list[int]] = {}
    stops: dict[int, list[int]] = {}
    for index, pair in enumerate(pairs):
        starts.setdefault(id(pair["start"]), []).append(index)
        stops.setdefault(id(pair["stop"]), []).append(index)
    links: dict[int, int] = {}
    for index, pair in enumerate(pairs):
        note = id(pair["stop"])
        if len(starts.get(note, [])) != 1 or len(stops.get(note, [])) != 1:
            continue
        following = starts[note][0]
        if following != index and following not in links:
            links[index] = following
    incoming = set(links.values())
    merged: list[dict] = []
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
        first = pairs[chain[0]]
        last = pairs[chain[-1]]
        merged.append(
            {
                "start": first["start"],
                "stop": last["stop"],
                "start_key": first["start_key"],
                "stop_key": last["stop_key"],
                "staff": first["staff"],
                "start_pitch": first["start_pitch"],
                "stop_pitch": last["stop_pitch"],
                "stop_measure": last["stop_measure"],
            }
        )
    return merged


def _assign_slur_numbers(pairs: list[dict]) -> dict:
    """Global 1..16 numbering, reused as soon as a slur has ended (the old skill's scheme)."""
    ordered = sorted(pairs, key=lambda pair: (pair["start_key"], pair["stop_measure"]))
    active: dict[int, int] = {}
    entries: list[tuple] = []
    signature: set[tuple] = set()
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
        number = str(free)
        active[free] = pair["stop_measure"]
        entries.append((pair["start"], "start", number))
        entries.append((pair["stop"], "stop", number))
        start_measure, start_onset = pair["start_key"]
        stop_measure, stop_onset = pair["stop_key"]
        signature.add((start_measure, pair["staff"], start_onset, pair["start_pitch"], "start", number))
        signature.add((stop_measure, pair["staff"], stop_onset, pair["stop_pitch"], "stop", number))
    return {"entries": entries, "signature": frozenset(signature)}


def _slur_signature(doc: Document) -> frozenset[tuple]:
    """Slurs keyed by musical position, not by XML element identity.

    Merge/rebuild passes replace note elements even when the music is unchanged.  An id(note)-based
    signature would then look different on every round and force the page pass to clear and re-add
    every slur (laputa's page slurs oscillated).  Position + pitch lets a slur follow a note when its
    voice changes.
    """
    signature: set[tuple] = set()
    for number, measure in doc.iter_measures():
        for event in doc.events(measure):
            if event.rest:
                continue
            pitch = _pitch_name(event.element.find("pitch"))
            if pitch is None:
                continue
            for slur in event.element.findall("notations/slur"):
                signature.add(
                    (
                        number,
                        event.staff,
                        round(event.onset, 4),
                        pitch,
                        slur.get("type") or "",
                        slur.get("number") or "1",
                    )
                )
    return frozenset(signature)


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
