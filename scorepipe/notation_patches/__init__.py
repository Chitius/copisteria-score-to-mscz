"""Constrained notation patches: agent proposes symbols, the compiler writes MusicXML.

``ottava`` (8va/8vb) is emitted as standard MusicXML ``<octave-shift>`` directions. ``tuplet``
rewrites an explicitly evidenced, continuous note segment with one duration ratio and bracket.
``clef`` places a staff clef at a musical anchor (and can retire the clef the OMR put elsewhere).
The agent never has to serialize mscx ids or location fractions.
"""

from __future__ import annotations

from .clef import list_clefs
from .common import (
    CLEF_SIGNS,
    DYNAMIC_MARKS,
    NOTE_TYPE_BEATS,
    OTTAAVA_SUBTYPES,
    WEDGE_SUBTYPES,
    load_patches,
    score_map,
)
from .compiler import apply_patches, validate_patches, verify_patches
from .dynamic import list_dynamics
from .ottava import list_octave_shifts, remove_octave_shifts
from .pedal import list_pedals, remove_pedals
from .wedge import list_wedges, remove_wedges

__all__ = [
    "CLEF_SIGNS",
    "DYNAMIC_MARKS",
    "NOTE_TYPE_BEATS",
    "OTTAAVA_SUBTYPES",
    "WEDGE_SUBTYPES",
    "apply_patches",
    "list_clefs",
    "list_dynamics",
    "list_octave_shifts",
    "list_pedals",
    "list_wedges",
    "load_patches",
    "remove_octave_shifts",
    "remove_pedals",
    "remove_wedges",
    "score_map",
    "validate_patches",
    "verify_patches",
]
