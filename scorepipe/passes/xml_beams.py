"""Rebuild beam groups after voice merging.

OMR often leaves beams only on some of the notes it recognised (laputa m50: only the G3 eighths
carry ``begin``/``end``, while the C3/E4/D4 notes in the same run have none). Merging voices makes
that visible as disconnected stems. This pass groups consecutive eighth-or-shorter notes per
staff/voice, extends existing edge groups and fills internal gaps, then writes the whole beam level
structure (1 = eighth, 2 = sixteenth, ...).
"""

from __future__ import annotations

from collections import defaultdict
from xml.etree import ElementTree

from ..core.document import Document
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase

_LEVELS = {"eighth": 1, "16th": 2, "32nd": 3, "64th": 4}


class RestoreBeams:
    spec = PassSpec(
        name="restore_beams",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("beams",),
        description="group consecutive eighth-or-shorter notes by source beam/beat boundaries",
        measure="unbeamed or partially beamed runs of eighth notes",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        changed = 0
        for _part_id, part, _number, measure in doc.iter_part_measures():
            changed += _restore_measure(
                measure,
                doc.effective_divisions(measure, part),
                doc.effective_time_signature(measure, part),
            )
        return PassResult(changed=changed)


def _restore_measure(measure, divisions: float, meter: tuple[float, float]) -> int:
    by_voice: dict[tuple, list[dict]] = defaultdict(list)
    cursor = 0
    previous_start = None
    measure_end = 0.0
    for item in measure:
        if item.tag in ("backup", "forward"):
            text = item.findtext("duration")
            if text is None:
                continue
            value = int(text)
            cursor += -value if item.tag == "backup" else value
            measure_end = max(measure_end, cursor / divisions)
            previous_start = None
            continue
        if item.tag != "note":
            previous_start = None
            continue
        text = item.findtext("duration")
        if text is None:
            previous_start = None
            continue
        duration = float(text) / divisions
        is_chord = item.find("chord") is not None
        start = previous_start if is_chord and previous_start is not None else cursor / divisions
        if not is_chord:
            modification = item.find("time-modification")
            actual = _int_text(modification, "actual-notes")
            normal = _int_text(modification, "normal-notes")
            tuplet_scale = (normal / actual) if actual and normal and actual > 0 else 1.0
            by_voice[(item.findtext("staff") or "1", item.findtext("voice") or "1")].append(
                {
                    "element": item,
                    "start": start,
                    "end": start + duration,
                    "rest": item.find("rest") is not None,
                    "level": _LEVELS.get(item.findtext("type")),
                    "tuplet_scale": tuplet_scale,
                }
            )
            cursor += int(text)
            measure_end = max(measure_end, cursor / divisions)
        previous_start = start

    bar_length = meter[0] * 4.0 / meter[1]
    phase_offset = 0.0
    if measure.get("implicit") == "yes" and 0.0 < measure_end < bar_length - 1e-6:
        phase_offset = bar_length - measure_end

    changed = 0
    for records in by_voice.values():
        runs = []
        run = []
        for record in records:
            if record["level"] is not None and not record["rest"]:
                if run and abs(record["start"] - run[-1]["end"]) > 1e-6:
                    runs.append(run)
                    run = []
                run.append(record)
            else:
                if run:
                    runs.append(run)
                    run = []
        if run:
            runs.append(run)

        for run in runs:
            if len(run) < 2:
                if len(run) == 1:
                    changed += _clear_beams(run[0]["element"])
                continue
            grouper = BeamGrouper(
                meter,
                phase_offset=phase_offset,
                source_splits=_source_boundary_onsets(run, phase_offset),
            )
            for source_chunk, explicit_pair in _split_source_groups(run):
                if explicit_pair and grouper.preserve_explicit_group(source_chunk):
                    beat_chunks = [(source_chunk, source_chunk[0]["start"])]
                else:
                    beat_chunks = grouper.split_by_beat(source_chunk)
                for chunk, beat_origin in beat_chunks:
                    for target in _split_isolated_eighths(chunk):
                        if len(target) >= 2:
                            changed += _complete_run(target, divisions, beat_origin)
                        elif len(target) == 1:
                            changed += _clear_beams(target[0]["element"])
    return changed


def _int_text(element, path: str) -> int | None:
    if element is None:
        return None
    text = element.findtext(path)
    try:
        return int(text) if text is not None else None
    except ValueError:
        return None


def _source_boundary_onsets(run: list[dict], phase_offset: float) -> set[float]:
    """Return shifted start onsets of clean level-1 source beam pairs (for asymmetric meters)."""
    pairs_by_level = _source_pairs(run)
    boundaries: set[float] = set()
    for start, end in pairs_by_level.get(1) or []:
        if end - start + 1 >= 2:
            boundaries.add(round(run[start]["start"] + phase_offset, 4))
            boundaries.add(round(run[end]["end"] + phase_offset, 4))
    return boundaries


def _split_source_groups(run: list[dict]) -> list[tuple[list[dict], bool]]:
    """Treat complete source begin/end groups as boundaries for uniform eighth runs.

    Runs containing sixteenths instead follow the beat grid as a whole. Their source
    pairs often cover only two or three notes, and treating those fragments as hard
    boundaries leaves an isolated note inside an otherwise ordinary beat.
    """
    if any(record["level"] > 1 for record in run):
        return [(run, False)]
    pairs_by_level = _source_pairs(run)
    pair_ranges = [
        (start, end)
        for start, end in (pairs_by_level.get(1) or [])
        if end - start + 1 >= 2
    ]
    if not pair_ranges:
        return [(run, False)]
    pair_by_start = {start: end for start, end in pair_ranges}
    chunks: list[tuple[list[dict], bool]] = []
    index = 0
    plain: list[dict] = []
    while index < len(run):
        end = pair_by_start.get(index)
        if end is not None:
            if plain:
                chunks.append((plain, False))
                plain = []
            chunks.append((run[index : end + 1], True))
            index = end + 1
        else:
            plain.append(run[index])
            index += 1
    if plain:
        chunks.append((plain, False))
    return chunks


def _source_pairs(run: list[dict]) -> dict[int, list[tuple[int, int]]]:
    """begin/end pairs per beam level; a level with a broken sequence contributes nothing.

    A level is "broken" when a begin opens while another group is open, or when continue/end
    arrives without one.  That level cannot be trusted as a boundary, but a well-formed level
    beside it (Suzume m31: level 1 groups the beats, level 2 has a stray end) still can.
    """
    levels: dict[int, dict[int, str]] = {}
    for index, record in enumerate(run):
        for beam in record["element"].findall("beam"):
            try:
                level = int(beam.get("number") or 1)
            except ValueError:
                level = 1
            levels.setdefault(level, {})[index] = (beam.text or "").strip()
    pairs: dict[int, list[tuple[int, int]]] = {}
    for level, values in levels.items():
        start: int | None = None
        level_pairs: list[tuple[int, int]] = []
        broken = False
        for index in sorted(values):
            value = values[index]
            if value == "begin":
                if start is not None:
                    broken = True
                    break
                start = index
            elif value in ("forward hook", "backward hook"):
                continue  # a single-note hook is not a group boundary
            elif value == "continue":
                if start is None:
                    broken = True
                    break
            elif value == "end":
                if start is None:
                    broken = True
                    break
                level_pairs.append((start, index))
                start = None
            else:
                broken = True
                break
        if start is not None:
            broken = True
        if not broken and level_pairs:
            pairs[level] = level_pairs
    return pairs


def _meter_beat_spans(
    meter: tuple[float, float], source_splits: set[float] | None = None
) -> list[tuple[float, float]]:
    """Return ``(start, end)`` beat spans in quarter-note beats for one bar of ``meter``."""
    beats, beat_type = meter
    unit = 4.0 / beat_type
    bar = beats * unit
    if beat_type in (8, 16) and beats % 3 == 0:
        beat = unit * 3.0
        count = max(1, int(round(beats / 3)))
        return [(index * beat, (index + 1) * beat) for index in range(count)]
    if beat_type in (8, 16) and beats >= 5:
        patterns = _asymmetric_patterns(int(round(beats)))
        chosen = patterns[0]
        if source_splits:
            for candidate in patterns:
                edges = []
                acc = 0.0
                for group in candidate[:-1]:
                    acc += group * unit
                    edges.append(round(acc, 4))
                if any(edge in source_splits for edge in edges):
                    chosen = candidate
                    break
        spans: list[tuple[float, float]] = []
        cursor = 0.0
        for group in chosen:
            width = group * unit
            spans.append((cursor, cursor + width))
            cursor += width
        return spans
    if beat_type in (8, 16) and beats == 2:
        return [(0.0, bar)]
    if beat_type in (8, 16) and beats == 4:
        return [(0.0, 2.0 * unit), (2.0 * unit, 4.0 * unit)]
    count = max(1, int(round(beats)))
    return [(index * unit, (index + 1) * unit) for index in range(count)]


def _asymmetric_patterns(beats: int) -> list[list[int]]:
    known = {
        5: [[3, 2], [2, 3]],
        7: [[2, 2, 3], [3, 2, 2], [2, 3, 2]],
        8: [[3, 3, 2], [3, 2, 3], [2, 3, 3]],
        10: [[3, 3, 2, 2], [2, 2, 3, 3]],
        11: [[3, 3, 3, 2], [2, 3, 3, 3]],
    }
    if beats in known:
        return known[beats]
    pattern: list[int] = []
    remaining = beats
    while remaining > 4:
        pattern.append(3)
        remaining -= 3
    if remaining == 4:
        pattern.extend([2, 2])
    elif remaining > 0:
        pattern.append(remaining)
    return [pattern]


class BeamGrouper:
    """Group beam runs against compound/asymmetric beat spans and explicit syncopated pairs."""

    def __init__(
        self,
        meter: tuple[float, float],
        *,
        phase_offset: float = 0.0,
        source_splits: set[float] | None = None,
    ) -> None:
        self.meter = meter
        self.phase_offset = phase_offset
        self.spans = _meter_beat_spans(meter, source_splits)
        self.bar = self.spans[-1][1]
        self.step_fallback = self.spans[-1][1] - self.spans[-1][0]

    def beat_slot(self, onset: float) -> tuple[int, float]:
        """Return ``(slot_index, unshifted_slot_origin)`` for ``onset``."""
        shifted = onset + self.phase_offset
        for index, (start, end) in enumerate(self.spans):
            if shifted + 1e-6 < end:
                return index, start - self.phase_offset
        extra_index = int((shifted - self.bar + 1e-6) // self.step_fallback)
        origin = self.bar + extra_index * self.step_fallback - self.phase_offset
        return len(self.spans) + extra_index, origin

    def preserve_explicit_group(self, chunk: list[dict]) -> bool:
        """True when a clean level-1 source group should stay intact across beat boundaries."""
        if len(chunk) < 2:
            return False
        span = chunk[-1]["end"] - chunk[0]["start"]
        beats, beat_type = self.meter
        if beat_type in (8, 16):
            # Compound / asymmetric meters: preserve only if inside one beat (not across 3+3).
            first_slot, _ = self.beat_slot(chunk[0]["start"])
            last_slot, _ = self.beat_slot(chunk[-1]["start"])
            return first_slot == last_slot
        # Simple meters: preserve explicit 2..4-eighth groups (<= 2 quarter beats, e.g. syncopated
        # across-beat phrasing or half-bar 4-eighth beaming) while splitting full-bar runs.
        return len(chunk) <= 4 and span <= 2.0 + 1e-6 and span < beats * (4.0 / beat_type) - 1e-6

    def split_by_beat(self, run: list[dict]) -> list[tuple[list[dict], float]]:
        """Split a beam run at the active metre's notated beat boundaries."""
        if not run:
            return []
        chunks: list[tuple[list[dict], float]] = []
        chunk: list[dict] = []
        current_slot = None
        current_origin = 0.0
        for record in run:
            slot, origin = self.beat_slot(record["start"])
            if chunk and slot != current_slot:
                chunks.append((chunk, current_origin))
                chunk = []
            chunk.append(record)
            current_slot = slot
            current_origin = origin
        if chunk:
            chunks.append((chunk, current_origin))
        return chunks


def _beat_length(meter: tuple[float, float]) -> float:
    beats, beat_type = meter
    unit = 4.0 / beat_type
    if beat_type in (8, 16) and beats % 3 == 0:
        return unit * 3.0
    return unit


def _split_by_beat(run: list[dict], beat_length: float) -> list[list[dict]]:
    """Split every beam run at the active metre's notated beat boundaries."""
    if not run:
        return [run]
    chunks: list[list[dict]] = []
    chunk: list[dict] = []
    current_beat = None
    for record in run:
        beat = int((record["start"] + 1e-6) // beat_length)
        if chunk and beat != current_beat:
            chunks.append(chunk)
            chunk = []
        chunk.append(record)
        current_beat = beat
    if chunk:
        chunks.append(chunk)
    return chunks


def _split_isolated_eighths(run: list[dict]) -> list[list[dict]]:
    """Keep an explicit un-beamed eighth out of surrounding sixteenth groups.

    OMR often leaves an eighth with no beam between two beamed sixteenth runs (Sincerely m3's
    low B3). Rebuilding the whole contiguous run would beam across it. Only an un-beamed level-1
    note next to a shorter-value note is split out; fully beamed eighth runs (laputa m50) still
    go through the normal rebuild.
    """
    if not any(record["element"].findall("beam") for record in run):
        return [run]
    isolated: set[int] = set()
    for index, record in enumerate(run):
        if record["level"] != 1 or record["element"].findall("beam"):
            continue
        left = run[index - 1]["level"] if index > 0 else None
        right = run[index + 1]["level"] if index + 1 < len(run) else None
        if (left is not None and left > 1) or (right is not None and right > 1):
            isolated.add(index)
    if not isolated:
        return [run]
    chunks: list[list[dict]] = []
    chunk: list[dict] = []
    for index, record in enumerate(run):
        if index in isolated:
            if chunk:
                chunks.append(chunk)
                chunk = []
            chunks.append([record])
        else:
            chunk.append(record)
    if chunk:
        chunks.append(chunk)
    return chunks


def _clear_beams(element) -> int:
    beams = list(element.findall("beam"))
    if not beams:
        return 0
    for beam in beams:
        element.remove(beam)
    return 1


def _complete_run(run: list[dict], divisions: float, beat_origin: float = 0.0) -> int:
    # Rebuild the whole contiguous run. Keeping the old partial groups is what left the first
    # eighth of laputa m51 on a separate `begin` while the next note also started a group.
    targets = [(0, len(run))]
    changed = 0
    for start, end in targets:
        target = run[start:end]
        if len(target) < 2:
            continue
        desired = _beam_values(target, divisions, beat_origin)
        for index, record in enumerate(target):
            current = sorted(
                (beam.get("number") or "1", (beam.text or "").strip())
                for beam in record["element"].findall("beam")
            )
            wanted = sorted((str(level), value) for level, value in desired[index].items())
            if current == wanted:
                continue
            element = record["element"]
            for beam in list(element.findall("beam")):
                element.remove(beam)
            children = list(element)
            staff = element.find("staff")
            notations = element.find("notations")
            if staff is not None:
                insert_at = children.index(staff) + 1
            elif notations is not None:
                insert_at = children.index(notations)
            else:
                insert_at = len(children)
            for level, value in sorted(desired[index].items()):
                beam = ElementTree.Element("beam", {"number": str(level)})
                beam.text = value
                element.insert(insert_at, beam)
                insert_at += 1
            changed += 1
    return changed


def _has_beam(note, value: str) -> bool:
    return any(
        beam.get("number") in (None, "1") and (beam.text or "").strip() == value
        for beam in note.findall("beam")
    )


def _last_begin(run: list[dict], limit: int) -> int:
    starts = [index for index in range(limit + 1) if _has_beam(run[index]["element"], "begin")]
    return starts[-1] if starts else limit


def _beam_values(
    target: list[dict], divisions: float, beat_origin: float = 0.0
) -> dict[int, dict[int, str]]:
    values: dict[int, dict[int, str]] = defaultdict(dict)
    max_level = max(record["level"] for record in target)
    for level in range(1, max_level + 1):
        indices = [index for index, record in enumerate(target) if record["level"] >= level]
        subgroups: list[list[int]] = []
        subgroup: list[int] = []
        for index in indices:
            if subgroup and index != subgroup[-1] + 1:
                subgroups.append(subgroup)
                subgroup = []
            subgroup.append(index)
        if subgroup:
            subgroups.append(subgroup)
        for subgroup in subgroups:
            if len(subgroup) > 1:
                values[subgroup[0]][level] = "begin"
                for index in subgroup[1:-1]:
                    values[index][level] = "continue"
                values[subgroup[-1]][level] = "end"
            elif level > 1:
                index = subgroup[0]
                if index == 0:
                    values[index][level] = "forward hook"
                elif index == len(target) - 1:
                    values[index][level] = "backward hook"
                else:
                    scale = target[index].get("tuplet_scale", 1.0)
                    step = (2.0 / (2**level)) * scale
                    curr_slot = int(((target[index]["start"] - beat_origin) + 1e-6) // step)
                    next_slot = int(((target[index + 1]["start"] - beat_origin) + 1e-6) // step)
                    values[index][level] = (
                        "forward hook" if curr_slot == next_slot else "backward hook"
                    )
    return values


RESTORE_BEAMS = RestoreBeams()
