"""Page-level tie restoration pass."""

from __future__ import annotations

from xml.etree import ElementTree

from ...core.document import Document
from ...core.pairing import Endpoint, pair_endpoints
from ...core.pass_base import Context, Kind, PassResult, PassSpec, Phase
from .common import PageRestoreMixin, _merged_index, _offsets, _page_events


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
        page_chords: dict[tuple, dict[str, set[float]]] = {}
        endpoints: list[Endpoint] = []
        for page_index, path in enumerate(model.pages):
            root = ElementTree.parse(str(path)).getroot()
            events = _page_events(root)
            for part_id, measure_index, staff, _voice, onset, duration, pitch, _element in events:
                if pitch is not None:
                    global_measure = offsets[page_index] + measure_index
                    page_chords.setdefault(
                        (part_id, global_measure, staff, round(onset, 4)), {}
                    ).setdefault(pitch, set()).add(round(duration, 4))
            for part_id, measure_index, staff, voice, onset, duration, pitch, element in events:
                if pitch is None:
                    continue
                global_measure = offsets[page_index] + measure_index
                for tie in _note_ties(element):
                    if tie not in ("start", "stop"):
                        continue
                    endpoints.append(
                        Endpoint(
                            key=(part_id, staff, voice, pitch),
                            position=(global_measure, round(onset, 4)),
                            kind=tie,
                            payload=(part_id, staff, global_measure, onset, round(duration, 4), pitch),
                        )
                    )
        pairing = pair_endpoints(endpoints)
        restored = 0
        tie_to_slur = ctx.options.get("tie_to_slur") or set()
        for start_endpoint, stop_endpoint in pairing.pairs:
            part_id, staff, start_measure, start_onset, start_duration, start_pitch = (
                start_endpoint.payload
            )
            _stop_part, _staff, stop_measure, stop_onset, stop_duration, stop_pitch = (
                stop_endpoint.payload
            )
            start_key = (part_id, start_measure, staff, round(start_onset, 4), start_pitch)
            stop_key = (part_id, stop_measure, staff, round(stop_onset, 4), stop_pitch)
            if start_key in tie_to_slur and stop_key in tie_to_slur:
                # this tie was deliberately converted to a slur by reconcile_tie_slurs
                continue
            start_note = index.get((part_id, start_measure, staff, start_onset, start_pitch))
            stop_note = index.get((part_id, stop_measure, staff, stop_onset, stop_pitch))
            if start_note is None or stop_note is None:
                continue
            # a tie between two printed chords applies to every member that has the same duration
            # at both ends; a different-duration voice at the same onset is not a chord member
            start_set = page_chords.get((part_id, start_measure, staff, round(start_onset, 4))) or {}
            stop_set = page_chords.get((part_id, stop_measure, staff, round(stop_onset, 4))) or {}
            start_members = {
                member for member, durations in start_set.items() if start_duration in durations
            }
            stop_members = {
                member for member, durations in stop_set.items() if stop_duration in durations
            }
            common = start_members & stop_members or {start_pitch}
            applied = 0
            for member in sorted(common):
                member_start = index.get((part_id, start_measure, staff, start_onset, member))
                member_stop = index.get((part_id, stop_measure, staff, stop_onset, member))
                if member_start is None or member_stop is None:
                    continue
                added_start = _add_tie(member_start, "start")
                added_stop = _add_tie(member_stop, "stop")
                if added_start or added_stop:
                    applied += 1
            if applied:
                restored += applied
        return PassResult(changed=restored)


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
