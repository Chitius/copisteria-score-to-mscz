"""FactSet: what a producer returns. Data only, never a document edit."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FactSet:
    marks: list[dict] = field(default_factory=list)
    words: list[dict] = field(default_factory=list)
    source: str = ""
