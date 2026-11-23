"""Force overfull primary voices back to the measure length.

This is deliberately an *editable-repair* pass, not a musical reconstruction.  OMR sometimes
produces a voice whose copied note/rest durations exceed the bar; MuseScore cannot make that
measure editable until the total is valid.  The pass trims from the tail, preferring rests, and
records every removal/shortening so the forced copy is auditable.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from xml.etree import ElementTree

from ..core.document import Document, Event
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase

_TYPE_BY_BEATS = {
    Fraction(4): "whole",
    Fraction(2): "half",
    Fraction(1): "quarter",
    Fraction(1, 2): "eighth",
    Fraction(1, 4): "16th",
    Fraction(1, 8): "32nd",
    Fraction(1, 16): "64th",
}


@dataclass
class _Group:
    events: list[Event]

    @property
    def element(self):
        return self.events[0].element

    @property
    def rest(self) -> bool:
        return all(event.rest for event in self.events)

    @property
    def tuplet(self) -> bool:
        return any(event.element.find("time-modification") is not None for event in self.events)

    def duration(self, divisions: int) -> int:
        text = self.element.findtext("duration")
        return int(text) if text and text.strip().isdigit() else 0


class TruncateOverfullVoices:
    spec = PassSpec(
        name="truncate_overfull_voices",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("overfull-voice-durations",),
        description="trim overfull voices to the bar line for an editable MuseScore copy",
        measure="voice durations that exceed the active time signature",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        divisions = int(round(doc.divisions()))
        changed = 0
        notes: list[str] = []
        meter = (4.0, 4.0)
        for index, measure in enumerate(doc.measures(), start=1):
            declared = doc.time_signature(measure)
            if declared is not None:
                meter = declared
            if measure.get("implicit") == "yes":
                continue
            bar = Fraction(str(meter[0])) * 4 / Fraction(str(meter[1]))
            target = int(bar * divisions)
            for (staff, voice), groups in _groups(doc, measure).items():
                total = sum(group.duration(divisions) for group in groups)
                excess = total - target
                if excess <= 0:
                    continue
                remaining = excess
                actions: list[str] = []
                for group in reversed([group for group in groups if group.rest and not group.tuplet]):
                    if remaining <= 0:
                        break
                    duration = group.duration(divisions)
                    if duration <= 0:
                        continue
                    if duration <= remaining:
                        _remove_group(measure, group)
                        remaining -= duration
                        actions.append(f"removed rest {duration} ticks")
                    else:
                        _shorten_group(measure, group, remaining, divisions)
                        actions.append(f"shortened rest by {remaining} ticks")
                        remaining = 0
                while remaining > 0:
                    candidates = [group for group in groups if not group.rest and not group.tuplet]
                    candidates = [
                        group for group in candidates if group.element in list(measure)
                    ]
                    if not candidates:
                        break
                    group = max(candidates, key=lambda item: list(measure).index(item.element))
                    duration = group.duration(divisions)
                    if duration <= 0:
                        break
                    if duration <= remaining:
                        _remove_group(measure, group)
                        remaining -= duration
                        actions.append(f"removed note/chord {duration} ticks")
                    else:
                        _shorten_group(measure, group, remaining, divisions)
                        actions.append(f"shortened note/chord by {remaining} ticks")
                        remaining = 0
                if remaining > 0:
                    notes.append(
                        f"m{index} staff {staff} voice {voice}: could not trim {remaining} ticks"
                    )
                    continue
                changed += 1
                notes.append(
                    f"m{index} staff {staff} voice {voice}: {total}->{target} ticks; "
                    + "; ".join(actions)
                )
        return PassResult(changed=changed, notes=notes)


def _groups(doc: Document, measure) -> dict[tuple[str, str], list[_Group]]:
    grouped: dict[tuple[str, str], list[_Group]] = {}
    for event in doc.events(measure):
        key = (event.staff, event.voice)
        groups = grouped.setdefault(key, [])
        if event.chord and groups and abs(groups[-1].events[0].onset - event.onset) < 1e-6:
            groups[-1].events.append(event)
        else:
            groups.append(_Group([event]))
    return grouped


def _remove_group(measure, group: _Group) -> None:
    elements = {id(event.element): event.element for event in group.events}
    children = list(measure)
    indexes = [index for index, child in enumerate(children) if id(child) in elements]
    if not indexes:
        return
    text = group.element.findtext("duration")
    delta = int(text) if text and text.strip().isdigit() else 0
    _adjust_following_backup(measure, max(indexes), delta)
    for child in group.events:
        if child.element in list(measure):
            measure.remove(child.element)


def _shorten_group(measure, group: _Group, delta: int, divisions: int) -> None:
    old = group.duration(divisions)
    new = max(0, old - delta)
    for event in group.events:
        duration = event.element.find("duration")
        if duration is not None:
            duration.text = str(new)
    _set_type(group.element, new, divisions)
    _adjust_following_backup(measure, list(measure).index(group.element), old - new)


def _set_type(note, ticks: int, divisions: int) -> None:
    beats = Fraction(ticks, divisions)
    name = _TYPE_BY_BEATS.get(beats)
    current = note.find("type")
    if name is None:
        return
    if current is None:
        current = ElementTree.SubElement(note, "type")
    current.text = name


def _adjust_following_backup(measure, index: int, delta: int) -> None:
    if delta <= 0:
        return
    for child in list(measure)[index + 1 :]:
        if child.tag == "backup":
            text = child.findtext("duration")
            if text is not None and text.strip().isdigit():
                child.find("duration").text = str(max(0, int(text) - delta))
            return


TRUNCATE_OVERFULL = TruncateOverfullVoices()
