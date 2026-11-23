"""Pass registry: the order here is only within a phase; phases are ordered by the runner."""

from .analysis import ANALYSIS_PASSES, MeasureLengthReport
from .mscx_dedupe import DISPLAY_DEDUPE_PASSES, DedupePedalSpanners, DedupeTextObjects
from .mscx_facts import DISPLAY_FACT_PASSES, UpgradeGradualTexts, UpgradeTempoTexts
from .mscx_display import (
    DISPLAY_PASSES,
    CanonicalVoiceOrder,
    DropPaddingVoices,
    DropTextVoiceRests,
    UnhideRealRests,
)
from .mscx_fragments import FRAGMENTS, SplitChordFragments
from .mscx_truncate import TRUNCATE_OVERFULL_MSCX, TruncateOverfullMscx
from .mscx_ties import MSXC_TIES, RestoreMscxTies
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
from .xml_beams import RESTORE_BEAMS, RestoreBeams
from .xml_clefs import DROP_REDUNDANT_CLEFS, DROP_REDUNDANT_KEYS, DropRedundantClefs, DropRedundantKeySignatures
from .xml_duplicates import DROP_DUPLICATE_NOTES, DropDuplicateNotes
from .xml_credits import INJECT_CREDITS, ApplyCreditsFacts
from .xml_empty_staves import PAD_EMPTY_STAVES, PadEmptyStaves
from .xml_facts import ApplyMarksFacts, INJECT_PASSES
from .xml_forwards import NORMALIZE_FORWARDS, NORMALIZE_TUPLET_RESTS, NormalizeForwardDurations, NormalizeTupletRests
from .xml_layers import REBUILD_VOICE_LAYERS, RebuildVoiceLayers
from .xml_measures import FILL_PASS, FillShortMeasures
from .xml_merge import MERGE_ALIGNED_VOICES, MergeAlignedVoices
from .xml_overflow import DROP_OVERFLOW_DUPLICATES, DropOverflowDuplicates
from .xml_pickup import MARK_PICKUP, MarkPickup
from .xml_rebase import DROP_OVERFLOW_RESTS, REBASE_MEASURES, RebaseMeasures
from .xml_redundant_voices import DROP_REDUNDANT_VOICES, DropRedundantVoices
from .xml_slurs import SLUR_PASS, SanitizeSlurs
from .xml_tail import DROP_DUPLICATE_TAIL, DropTrailingDuplicateMeasure
from .xml_voice_merge import MERGE_STAFF_VOICES, MergeStaffVoices
from .xml_slur_chains import MERGE_ADJACENT_SLURS, MergeAdjacentSlurs
from .xml_tie_slurs import RECONCILE_TIE_SLURS, ReconcileTieSlurs
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
        MARK_PICKUP,
        PAD_EMPTY_STAVES,
        REBUILD_VOICE_LAYERS,
        MERGE_STAFF_VOICES,
        DROP_REDUNDANT_VOICES,
        REBASE_MEASURES,
        MERGE_ALIGNED_VOICES,
        NORMALIZE_VOICES_PASS,
        SLUR_PASS,
        FILL_PASS,
        NORMALIZE_FORWARDS,
        NORMALIZE_TUPLET_RESTS,
        RESTORE_PAGE_TIES,
        RESTORE_PAGE_SLURS,
        RESTORE_PAGE_PEDALS,
        RESTORE_PAGE_ARPEGGIOS,
        RESTORE_PAGE_ARTICULATIONS,
        RESTORE_PAGE_WEDGES,
        MERGE_ADJACENT_SLURS,
        RECONCILE_TIE_SLURS,
        DROP_OVERFLOW_RESTS,
        RESTORE_BEAMS,
    ]
    + ANALYSIS_PASSES
)
DISPLAY_PASSES = DISPLAY_PASSES + [FRAGMENTS, MSXC_TIES] + DISPLAY_DEDUPE_PASSES + DISPLAY_FACT_PASSES
INJECT_PASSES = INJECT_PASSES + [INJECT_CREDITS]

__all__ = [
    "STRUCTURAL_PASSES",
    "DISPLAY_PASSES",
    "INJECT_PASSES",
    "ANALYSIS_PASSES",
    "TRUNCATE_OVERFULL_MSCX",
    "TruncateOverfullMscx",
    "MeasureLengthReport",
    "DedupeTies",
    "DropRedundantTimeSignatures",
    "UnhideRests",
    "SanitizeSlurs",
    "FillShortMeasures",
    "NormalizeVoiceNumbers",
    "DropTrailingDuplicateMeasure",
    "DropOverflowDuplicates",
    "MarkPickup",
    "RebuildVoiceLayers",
    "PadEmptyStaves",
    "MergeStaffVoices",
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
    "DedupePedalSpanners",
    "DedupeTextObjects",
    "RestoreMscxTies",
    "SplitChordFragments",
    "ApplyMarksFacts",
    "ApplyCreditsFacts",
    "DropTextVoiceRests",
    "UnhideRealRests",
    "DropPaddingVoices",
    "CanonicalVoiceOrder",
    "SLUR_PASS",
    "FILL_PASS",
]
