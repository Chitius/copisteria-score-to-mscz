"""The display IR: a MuseScore .mscx tree.

MuseScore's import is not idempotent with respect to our invariants, so the display form has its
own document type, its own pass set and its own fixed-point loop.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from xml.etree import ElementTree

TEXT_TAGS = (
    "StaffText",
    "SystemText",
    "RehearsalMark",
    "Tempo",
    "Dynamic",
    "Expression",
    "Harmony",
    "Marker",
    "Jump",
)


class MsxcDocument:
    def __init__(self, root: ElementTree.Element):
        self.root = root

    @classmethod
    def load(cls, path: str | Path) -> "MsxcDocument":
        return cls(ElementTree.parse(str(path)).getroot())

    def save(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        ElementTree.ElementTree(self.root).write(
            str(destination), encoding="UTF-8", xml_declaration=True
        )

    def state_hash(self) -> str:
        return hashlib.sha1(ElementTree.tostring(self.root)).hexdigest()

    def staves(self) -> list[ElementTree.Element]:
        return [staff for staff in self.root.iter("Staff") if staff.findall("Measure")]

    def iter_measures(self):
        for staff in self.staves():
            for index, measure in enumerate(staff.findall("Measure"), start=1):
                yield staff, index, measure

    def voices(self, measure: ElementTree.Element) -> list[ElementTree.Element]:
        return measure.findall("voice")


def note_count(voice: ElementTree.Element) -> int:
    return sum(len(chord.findall("Note")) for chord in voice.findall("Chord"))


def has_text(voice: ElementTree.Element) -> bool:
    return any(voice.findall(tag) for tag in TEXT_TAGS)
