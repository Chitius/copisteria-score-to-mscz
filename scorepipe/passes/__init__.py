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
from .page_restore import (
    RESTORE_PAGE_ARPEGGIOS,
    RESTORE_PAGE_ARTICULATIONS,
    RESTORE_PAGE_PEDALS,
    RESTORE_PAGE_SLURS,
    RESTORE_PAGE_TIES,
    RESTORE_PAGE_WEDGES,
    RestorePageArpeggios,
    RestorePageArticulations,
    RestorePagePedals,
    RestorePageSlurs,
    RestorePageTies,
    RestorePageWedges,
)
from .xml_basic import (
    STRUCTURAL_PASSES,
    DedupeTies,
    DropRedundantTimeSignatures,
    UnhideRests,
)
from .xml_clefs import DROP_REDUNDANT_CLEFS, DROP_REDUNDANT_KEYS, DropRedundantClefs, DropRedundantKeySignatures
from .xml_duplicates import DROP_DUPLICATE_NOTES, DropDuplicateNotes
from .xml_facts import ApplyMarksFacts, INJECT_PASSES
from .xml_measures import FILL_PASS, FillShortMeasures
from .xml_merge import MERGE_ALIGNED_VOICES, MergeAlignedVoices
from .xml_overflow import DROP_OVERFLOW_DUPLICATES, DropOverflowDuplicates
from .xml_rebase import REBASE_MEASURES, RebaseMeasures
from .xml_slurs import SLUR_PASS, SanitizeSlurs
from .xml_tail import DROP_DUPLICATE_TAIL, DropTrailingDuplicateMeasure
from .xml_voices import NORMALIZE_VOICES_PASS, NormalizeVoiceNumbers

# order matters only inside a phase; keep the cheap, local rewrites first
STRUCTURAL_PASSES = (
    STRUCTURAL_PASSES
    + [
        DROP_REDUNDANT_CLEFS,
        DROP_REDUNDANT_KEYS,
        DROP_DUPLICATE_NOTES,
        DROP_DUPLICATE_TAIL,
        DROP_OVERFLOW_DUPLICATES,
        REBASE_MEASURES,
        MERGE_ALIGNED_VOICES,
        NORMALIZE_VOICES_PASS,
        SLUR_PASS,
        FILL_PASS,
        RESTORE_PAGE_TIES,
        RESTORE_PAGE_SLURS,
        RESTORE_PAGE_PEDALS,
        RESTORE_PAGE_ARPEGGIOS,
        RESTORE_PAGE_ARTICULATIONS,
        RESTORE_PAGE_WEDGES,
    ]
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
    "DropOverflowDuplicates",
    "RebaseMeasures",
    "MergeAlignedVoices",
    "RestorePageTies",
    "RestorePageSlurs",
    "RestorePagePedals",
    "RestorePageArpeggios",
    "RestorePageArticulations",
    "RestorePageWedges",
    "DropDuplicateNotes",
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
