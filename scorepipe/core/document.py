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
    @property
    def part(self) -> ElementTree.Element:
        part = self.root.find("part")
        if part is None:
            raise ValueError("MusicXML has no <part>")
        return part

    def measures(self) -> list[ElementTree.Element]:
        return self.part.findall("measure")

    def divisions(self) -> float:
        text = self.root.findtext(".//divisions")
        return float(text) if text else 10080.0

    def state_hash(self) -> str:
        return hashlib.sha1(ElementTree.tostring(self.root)).hexdigest()

    # -- measure helpers --------------------------------------------------
    def events(self, measure: ElementTree.Element) -> list[Event]:
        """Walk one measure with cursor semantics (backup/forward/chord aware)."""
        divisions = self.divisions()
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
                    onset=onset / divisions,
                    duration=duration / divisions,
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

    def iter_measures(self) -> Iterator[tuple[int, ElementTree.Element]]:
        for index, measure in enumerate(self.measures(), start=1):
            yield index, measure
