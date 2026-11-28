"""Constrained notation patches: agent proposes symbols, the compiler writes MusicXML.

``ottava`` (8va/8vb) is emitted as standard MusicXML ``<octave-shift>`` directions. ``tuplet``
rewrites an explicitly evidenced, continuous note segment with one duration ratio and bracket.
``clef`` places a staff clef at a musical anchor (and can retire the clef the OMR put elsewhere).
The agent never has to serialize mscx ids or location fractions.
"""

from __future__ import annotations

from .arpeggio import list_arpeggios
from .clef import list_clefs
from .common import (
    ARPEGGIO_DIRECTIONS,
    ARPEGGIO_KINDS,
    CLEF_SIGNS,
    DYNAMIC_MARKS,
    FERMATA_SHAPES,
    FERMATA_TYPES,
    GLISSANDO_LINE_TYPES,
    NAVIGATION_MARKS,
    NOTE_TYPE_BEATS,
    ORNAMENT_KINDS,
    OTTAAVA_SUBTYPES,
    PARENTHESES_TARGETS,
    REPEAT_DIRECTIONS,
    SUPPORTED_PATCH_OPS,
    VOLTA_STOP_TYPES,
    WEDGE_SUBTYPES,
    load_patches,
    score_map,
)
from .compiler import apply_patches, validate_patches, verify_patches
from .dynamic import list_dynamics
from .fermata import list_fermatas
from .glissando import list_glissandos, remove_glissandos
from .navigation import list_navigations
from .ornament import list_ornaments
from .ottava import list_octave_shifts, remove_octave_shifts
from .parentheses import list_parentheses
from .pedal import list_pedals, remove_pedals
from .repeat import list_repeats
from .volta import list_voltas
from .wedge import list_wedges, remove_wedges

__all__ = [
    "ARPEGGIO_DIRECTIONS",
    "ARPEGGIO_KINDS",
    "CLEF_SIGNS",
    "DYNAMIC_MARKS",
    "FERMATA_SHAPES",
    "FERMATA_TYPES",
    "GLISSANDO_LINE_TYPES",
    "NAVIGATION_MARKS",
    "NOTE_TYPE_BEATS",
    "ORNAMENT_KINDS",
    "OTTAAVA_SUBTYPES",
    "PARENTHESES_TARGETS",
    "REPEAT_DIRECTIONS",
    "SUPPORTED_PATCH_OPS",
    "VOLTA_STOP_TYPES",
    "WEDGE_SUBTYPES",
    "apply_patches",
    "list_arpeggios",
    "list_clefs",
    "list_dynamics",
    "list_fermatas",
    "list_glissandos",
    "list_navigations",
    "list_ornaments",
    "list_octave_shifts",
    "list_parentheses",
    "list_pedals",
    "list_repeats",
    "list_voltas",
    "list_wedges",
    "load_patches",
    "remove_glissandos",
    "remove_octave_shifts",
    "remove_pedals",
    "remove_wedges",
    "score_map",
    "validate_patches",
    "verify_patches",
]
