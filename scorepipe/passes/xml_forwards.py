"""Normalize MuseScore-hostile forward and tuplet-rest durations.

MuseScore 4 can abort while importing a ``<forward>`` that consumes the rest of a bar and is
immediately followed by ``<backup>`` when its duration is not on a quarter-beat grid.  It can also
abort on a tuplet rest whose duration is not representable as a plain rest (e.g. 1680 ticks at
10080 divisions).  Both are OMR/merge artifacts, not musical tuplets.
"""

from __future__ import annotations

from ..core.document import Document
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase


class NormalizeForwardDurations:
    spec = PassSpec(
        name="normalize_forward_durations",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("forward-durations",),
        description="round a bar-filling forward before backup to a MuseScore-safe grid",
        measure="forward durations not on a quarter-beat grid",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        divisions = doc.divisions()
        quantum = max(1, int(round(divisions / 4.0)))
        changed = 0
        for measure in doc.measures():
            children = list(measure)
            for index, child in enumerate(children[:-1]):
                if child.tag != "forward" or children[index + 1].tag != "backup":
                    continue
                duration = child.find("duration")
                if duration is None or not (duration.text or "").strip().isdigit():
                    continue
                value = int(duration.text)
                if value <= 0 or value % quantum == 0:
                    continue
                new_value = (value // quantum) * quantum
                duration.text = str(new_value)
                backup = children[index + 1].find("duration")
                if backup is not None and (backup.text or "").strip().isdigit():
                    backup.text = str(int(backup.text) - (value - new_value))
                changed += 1
        return PassResult(changed=changed)


class NormalizeTupletRests:
    spec = PassSpec(
        name="normalize_tuplet_rests",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("tuplet-rest-durations",),
        description="make a merge-created tuplet rest a plain grid rest",
        measure="tuplet-rest durations not representable as a plain rest",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        divisions = doc.divisions()
        quantum = max(1, int(round(divisions / 4.0)))
        changed = 0
        for measure in doc.measures():
            for note in measure.findall("note"):
                if note.find("rest") is None or note.find("time-modification") is None:
                    continue
                duration = note.find("duration")
                if duration is None or not (duration.text or "").strip().isdigit():
                    continue
                value = int(duration.text)
                new_value = max(quantum, (value // quantum) * quantum)
                duration.text = str(new_value)
                note.remove(note.find("time-modification"))
                changed += 1
        return PassResult(changed=changed)


NORMALIZE_FORWARDS = NormalizeForwardDurations()
NORMALIZE_TUPLET_RESTS = NormalizeTupletRests()
