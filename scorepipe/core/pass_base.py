"""Pass contract and context."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from .document import Document


class Phase(str, Enum):
    STRUCTURAL = "structural"
    INJECT = "inject"
    DISPLAY = "display"


class Kind(str, Enum):
    MECHANICAL = "mechanical"
    ANALYSIS = "analysis"
    FACT = "fact"


@dataclass(frozen=True)
class PassSpec:
    name: str
    phase: Phase
    kind: Kind = Kind.MECHANICAL
    owns: tuple[str, ...] = ()
    description: str = ""
    measure: str = ""


@dataclass
class PassResult:
    changed: int = 0
    notes: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.changed > 0


class Pass(Protocol):
    spec: PassSpec

    def run(self, doc: Document, ctx: "Context") -> PassResult: ...


@dataclass
class Context:
    """Everything a pass may read that is not in the document."""

    facts: dict = field(default_factory=dict)
    options: dict = field(default_factory=dict)
    pages: object | None = None
    log: list[str] = field(default_factory=list)
