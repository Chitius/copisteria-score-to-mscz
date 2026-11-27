"""The working document: a MusicXML tree plus the queries passes need."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from xml.etree import ElementTree


@dataclass(frozen=True)
class Event:
    element: ElementTree.Element
    staff: str
    voice: str
    onset: float
    duration: float
    rest: bool
    chord: bool

    @property
    def end(self) -> float:
        return self.onset + self.duration


class Document:
    """A parsed score. The root element is the single source of truth."""

    def __init__(self, root: ElementTree.Element):
        self.root = root

    # -- loading / saving -------------------------------------------------
    @classmethod
    def load(cls, path: str | Path) -> "Document":
        return cls(ElementTree.parse(str(path)).getroot())

    def save(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        ElementTree.ElementTree(self.root).write(
            str(destination), encoding="UTF-8", xml_declaration=True
        )

    # -- structure --------------------------------------------------------
    def parts(self) -> list[ElementTree.Element]:
        return self.root.findall("part")

    def iter_parts(self) -> Iterator[tuple[str, ElementTree.Element]]:
        for index, part in enumerate(self.parts(), start=1):
            yield part.get("id") or f"P{index}", part

    def part_by_id(self, part_id: str | None = None) -> ElementTree.Element:
        if part_id is None:
            return self.part
        for current_id, part in self.iter_parts():
            if current_id == part_id:
                return part
        raise ValueError(f"MusicXML has no <part id={part_id!r}>")

    @property
    def part(self) -> ElementTree.Element:
        part = self.root.find("part")
        if part is None:
            raise ValueError("MusicXML has no <part>")
        return part

    def part_measures(self, part: ElementTree.Element) -> list[ElementTree.Element]:
        return part.findall("measure")

    def measures(self, part_id: str | None = None) -> list[ElementTree.Element]:
        return self.part_by_id(part_id).findall("measure")

    def _owning_part(self, measure: ElementTree.Element) -> ElementTree.Element | None:
        for part in self.parts():
            for candidate in part.findall("measure"):
                if candidate is measure:
                    return part
        return None

    def divisions(self, part: ElementTree.Element | None = None) -> float:
        if part is not None:
            text = part.findtext(".//divisions")
            if text:
                return float(text)
        text = self.root.findtext(".//divisions")
        return float(text) if text else 10080.0

    def effective_divisions(
        self,
        measure: ElementTree.Element,
        part: ElementTree.Element | None = None,
    ) -> float:
        """The active ``<divisions>`` at ``measure`` within its owning part."""
        declared = measure.findtext("attributes/divisions")
        if declared:
            try:
                value = float(declared)
            except ValueError:
                value = 0.0
            if value > 0:
                return value
        owner = part if part is not None else self._owning_part(measure)
        if owner is None:
            return self.divisions()
        current = self.divisions(owner)
        for candidate in owner.findall("measure"):
            declared = candidate.findtext("attributes/divisions")
            if declared:
                try:
                    value = float(declared)
                except ValueError:
                    value = 0.0
                if value > 0:
                    current = value
            if candidate is measure:
                return current
        return current

    def staff_count(self, part: ElementTree.Element) -> int:
        count = 1
        for attributes in part.iter("attributes"):
            text = attributes.findtext("staves")
            if text and text.strip().isdigit():
                count = max(count, int(text.strip()))
        for staff in part.iter("staff"):
            text = (staff.text or "").strip()
            if text.isdigit():
                count = max(count, int(text))
        return count

    def part_staff_offsets(self) -> dict[str, int]:
        """0-based global staff offset for each part (matching MuseScore's global Staff ids)."""
        offsets: dict[str, int] = {}
        running = 0
        for part_id, part in self.iter_parts():
            offsets[part_id] = running
            running += self.staff_count(part)
        return offsets

    def global_staff_id(self, part_id: str, local_staff: str) -> str:
        offsets = self.part_staff_offsets()
        offset = offsets.get(part_id, 0)
        staff_num = int(local_staff) if str(local_staff).isdigit() else 1
        return str(offset + staff_num)

    def state_hash(self) -> str:
        return hashlib.sha1(ElementTree.tostring(self.root)).hexdigest()

    # -- measure helpers --------------------------------------------------
    def events(
        self,
        measure: ElementTree.Element,
        divisions: float | None = None,
    ) -> list[Event]:
        """Walk one measure with cursor semantics (backup/forward/chord aware)."""
        active_divisions = divisions if divisions is not None else self.effective_divisions(measure)
        cursor = 0
        previous_onset: float | None = None
        events: list[Event] = []
        for item in measure:
            if item.tag in ("backup", "forward"):
                text = item.findtext("duration")
                if text is None:
                    continue
                value = int(text)
                cursor += -value if item.tag == "backup" else value
                previous_onset = None
                continue
            if item.tag != "note":
                previous_onset = None
                continue
            text = item.findtext("duration")
            if text is None:
                previous_onset = None
                continue
            duration = int(text)
            chord = item.find("chord") is not None
            onset = previous_onset if chord and previous_onset is not None else cursor
            if not chord:
                cursor += duration
            previous_onset = onset
            events.append(
                Event(
                    element=item,
                    staff=item.findtext("staff") or "1",
                    voice=item.findtext("voice") or "1",
                    onset=onset / active_divisions,
                    duration=duration / active_divisions,
                    rest=item.find("rest") is not None,
                    chord=chord,
                )
            )
        return events

    def time_signature(self, measure: ElementTree.Element) -> tuple[float, float] | None:
        time = measure.find("attributes/time")
        if time is None or not time.findtext("beats") or not time.findtext("beat-type"):
            return None
        return float(time.findtext("beats")), float(time.findtext("beat-type"))

    def effective_time_signature(
        self,
        measure: ElementTree.Element,
        part: ElementTree.Element | None = None,
    ) -> tuple[float, float]:
        """The active meter at ``measure``; MusicXML only prints the declaration when it changes."""
        owner = part if part is not None else self._owning_part(measure)
        measures = owner.findall("measure") if owner is not None else self.measures()
        current = (4.0, 4.0)
        for candidate in measures:
            declared = self.time_signature(candidate)
            if declared is not None:
                current = declared
            if candidate is measure:
                return current
        return current

    def iter_measures(
        self, part_id: str | None = None
    ) -> Iterator[tuple[int, ElementTree.Element]]:
        for index, measure in enumerate(self.measures(part_id), start=1):
            yield index, measure

    def iter_part_measures(
        self,
    ) -> Iterator[tuple[str, ElementTree.Element, int, ElementTree.Element]]:
        for part_id, part in self.iter_parts():
            for index, measure in enumerate(part.findall("measure"), start=1):
                yield part_id, part, index, measure
