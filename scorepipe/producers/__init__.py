"""Fact producers: they read the outside world, they never touch the score.

A producer returns a FactSet; the inject pass is the only thing that writes facts into the
document, and it is mechanical and idempotent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ..facts import load_facts


@dataclass
class FactSet:
    marks: list[dict] = field(default_factory=list)
    source: str = ""


class Producer(Protocol):
    name: str

    def produce(self, input_path: Path) -> FactSet: ...


class JsonProducer:
    """A marks JSON written by the text layer or by the agent."""

    name = "json"

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def produce(self, input_path: Path) -> FactSet:
        data = load_facts(self.path)
        return FactSet(marks=data.get("marks") or [], source=str(self.path))


class TextLayerProducer:
    """A line-oriented sidecar: `measure<TAB>beat<TAB>placement<TAB>text`.

    This is the shape a text-layer or OCR step can emit without understanding MusicXML; the
    producer only parses it, the inject pass decides how it lands in the score.
    """

    name = "text-layer"

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def produce(self, input_path: Path) -> FactSet:
        marks: list[dict] = []
        for line in self.path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            measure, beat = parts[0], parts[1]
            placement = parts[2] if len(parts) > 2 and parts[2] else "above"
            text = parts[3] if len(parts) > 3 else ""
            if not text:
                continue
            marks.append(
                {
                    "measure": int(measure),
                    "beat": float(beat),
                    "placement": placement,
                    "text": text,
                }
            )
        return FactSet(marks=marks, source=str(self.path))


class CompositeProducer:
    """Merge several producers; later marks do not overwrite, they append."""

    name = "composite"

    def __init__(self, producers: list[Producer]):
        self.producers = producers

    def produce(self, input_path: Path) -> FactSet:
        marks: list[dict] = []
        sources: list[str] = []
        for producer in self.producers:
            result = producer.produce(input_path)
            marks.extend(result.marks)
            sources.append(result.source)
        return FactSet(marks=marks, source=", ".join(sources))


def resolve(path: str | Path | None) -> Producer | None:
    if not path:
        return None
    candidate = Path(path)
    if candidate.suffix.lower() in (".txt", ".tsv"):
        return TextLayerProducer(candidate)
    return JsonProducer(candidate)
