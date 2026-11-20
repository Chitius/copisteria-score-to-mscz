"""Pass registry: the order here is only within a phase; phases are ordered by the runner."""

from .mscx_display import (
    DISPLAY_PASSES,
    CanonicalVoiceOrder,
    DropPaddingVoices,
    DropTextVoiceRests,
    UnhideRealRests,
)
from .xml_basic import (
    STRUCTURAL_PASSES,
    DedupeTies,
    DropRedundantTimeSignatures,
    UnhideRests,
)
from .xml_measures import FILL_PASS, FillShortMeasures
from .xml_slurs import SLUR_PASS, SanitizeSlurs

# order matters only inside a phase; keep the cheap, local rewrites first
STRUCTURAL_PASSES = STRUCTURAL_PASSES + [SLUR_PASS, FILL_PASS]

__all__ = [
    "STRUCTURAL_PASSES",
    "DISPLAY_PASSES",
    "DedupeTies",
    "DropRedundantTimeSignatures",
    "UnhideRests",
    "SanitizeSlurs",
    "FillShortMeasures",
    "DropTextVoiceRests",
    "UnhideRealRests",
    "DropPaddingVoices",
    "CanonicalVoiceOrder",
    "SLUR_PASS",
    "FILL_PASS",
]
