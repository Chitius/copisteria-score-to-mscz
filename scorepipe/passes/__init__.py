"""Pass registry: the order here is only within a phase; phases are ordered by the runner."""

from .xml_basic import (
    STRUCTURAL_PASSES,
    DedupeTies,
    DropRedundantTimeSignatures,
    UnhideRests,
)

__all__ = [
    "STRUCTURAL_PASSES",
    "DedupeTies",
    "DropRedundantTimeSignatures",
    "UnhideRests",
]
