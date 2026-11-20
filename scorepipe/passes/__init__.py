"""Pass registry: the order here is only within a phase; phases are ordered by the runner."""

from .analysis import ANALYSIS_PASSES, MeasureLengthReport
from .mscx_facts import DISPLAY_FACT_PASSES, UpgradeGradualTexts, UpgradeTempoTexts
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
from .xml_facts import ApplyMarksFacts, INJECT_PASSES
from .xml_measures import FILL_PASS, FillShortMeasures
from .xml_slurs import SLUR_PASS, SanitizeSlurs
from .xml_tail import DROP_DUPLICATE_TAIL, DropTrailingDuplicateMeasure
from .xml_voices import NORMALIZE_VOICES_PASS, NormalizeVoiceNumbers

# order matters only inside a phase; keep the cheap, local rewrites first
STRUCTURAL_PASSES = (
    STRUCTURAL_PASSES
    + [DROP_DUPLICATE_TAIL, NORMALIZE_VOICES_PASS, SLUR_PASS, FILL_PASS]
    + ANALYSIS_PASSES
)
DISPLAY_PASSES = DISPLAY_PASSES + DISPLAY_FACT_PASSES

__all__ = [
    "STRUCTURAL_PASSES",
    "DISPLAY_PASSES",
    "INJECT_PASSES",
    "ANALYSIS_PASSES",
    "MeasureLengthReport",
    "DedupeTies",
    "DropRedundantTimeSignatures",
    "UnhideRests",
    "SanitizeSlurs",
    "FillShortMeasures",
    "NormalizeVoiceNumbers",
    "DropTrailingDuplicateMeasure",
    "UpgradeTempoTexts",
    "UpgradeGradualTexts",
    "ApplyMarksFacts",
    "DropTextVoiceRests",
    "UnhideRealRests",
    "DropPaddingVoices",
    "CanonicalVoiceOrder",
    "SLUR_PASS",
    "FILL_PASS",
]
