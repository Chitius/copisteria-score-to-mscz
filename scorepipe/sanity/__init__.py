"""Reusable sanity checks and behaviour contracts for single passes.

A pass has a declared contract (what it may change) and an implicit one (it must be
idempotent).  This module makes both testable without touching the pipeline:

* :func:`snapshot` freezes the note-level view of a document.
* :func:`diff_snapshots` reports note/measure effects in a structured form.
* :class:`PassContract` turns "this pass may not add notes" into a list of messages.
* the ``check_*`` functions report plain strings, so pytest assertions stay simple.
* :func:`run_contract` wires everything together on *fresh* copies of a document,
  which keeps one test from contaminating the next.

Only the standard library is used.
"""

from __future__ import annotations

from .checkers import (
    check_idempotent,
    check_measure_health_preserved,
    check_mscx_pitched_notes_preserved,
    check_no_new_verifier_violations,
    check_note_inventory_preserved,
    check_onsets_preserved,
    check_piece_pitch_set_preserved,
    check_pitch_set_preserved,
    check_sounding_notes_preserved,
    check_structure,
)
from .contract import PassContract, run_contract
from .models import (
    ADDED,
    CHANGED_IDENTITY,
    CHANGED_PITCH,
    MOVED,
    REMOVED,
    RETIMED,
    DocFactory,
    MeasureSnapshot,
    NoteChange,
    NoteSnapshot,
    SanityDiff,
    SanityReport,
    Snapshot,
    Verifier,
    VoiceCountChange,
)
from .snapshot import diff_snapshots, snapshot

__all__ = [
    "ADDED",
    "REMOVED",
    "MOVED",
    "RETIMED",
    "CHANGED_PITCH",
    "CHANGED_IDENTITY",
    "DocFactory",
    "Verifier",
    "NoteSnapshot",
    "MeasureSnapshot",
    "Snapshot",
    "NoteChange",
    "VoiceCountChange",
    "SanityDiff",
    "PassContract",
    "SanityReport",
    "snapshot",
    "diff_snapshots",
    "check_structure",
    "check_measure_health_preserved",
    "check_no_new_verifier_violations",
    "check_note_inventory_preserved",
    "check_onsets_preserved",
    "check_pitch_set_preserved",
    "check_sounding_notes_preserved",
    "check_piece_pitch_set_preserved",
    "check_mscx_pitched_notes_preserved",
    "check_idempotent",
    "run_contract",
]
