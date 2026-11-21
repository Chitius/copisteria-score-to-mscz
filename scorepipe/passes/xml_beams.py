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
        description="group consecutive eighth-or-shorter notes into beams and complete partial groups",
        measure="unbeamed or partially beamed runs of eighth notes",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        divisions = doc.divisions()
        changed = 0
        for _number, measure in doc.iter_measures():
            changed += _restore_measure(measure, divisions)
        return PassResult(changed=changed)


def _restore_measure(measure, divisions: float) -> int:
    by_voice: dict[tuple, list[dict]] = defaultdict(list)
    cursor = 0
    previous_start = None
    for item in measure:
        if item.tag in ("backup", "forward"):
            text = item.findtext("duration")
            if text is None:
                continue
            value = int(text)
            cursor += -value if item.tag == "backup" else value
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
            by_voice[(item.findtext("staff") or "1", item.findtext("voice") or "1")].append(
                {
                    "element": item,
                    "start": start,
                    "end": start + duration,
                    "rest": item.find("rest") is not None,
                    "level": _LEVELS.get(item.findtext("type")),
                }
            )
            cursor += int(text)
        previous_start = start

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
                continue
            chunks = _split_isolated_eighths(run)
            for chunk in chunks:
                if len(chunk) >= 2:
                    changed += _complete_run(chunk, divisions)
    return changed


def _split_isolated_eighths(run: list[dict]) -> list[list[dict]]:
    """Keep an explicit un-beamed eighth out of surrounding sixteenth groups.

    OMR often leaves an eighth with no beam between two beamed sixteenth runs (Sincerely m3's
    low B3). Rebuilding the whole contiguous run would beam across it. Only an un-beamed level-1
    note next to a shorter-value note is split out; fully beamed eighth runs (laputa m50) still
    go through the normal rebuild.
    """
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


def _complete_run(run: list[dict], divisions: float) -> int:
    # Rebuild the whole contiguous run. Keeping the old partial groups is what left the first
    # eighth of laputa m51 on a separate `begin` while the next note also started a group.
    targets = [(0, len(run))]
    changed = 0
    for start, end in targets:
        target = run[start:end]
        if len(target) < 2:
            continue
        desired = _beam_values(target, divisions)
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


def _beam_values(target: list[dict], divisions: float) -> dict[int, dict[int, str]]:
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
                next_within_beat = (
                    index + 1 < len(target)
                    and target[index + 1]["start"] // (1.0) == target[index]["start"] // 1.0
                )
                values[index][level] = "forward hook" if next_within_beat else "backward hook"
    return values


RESTORE_BEAMS = RestoreBeams()
