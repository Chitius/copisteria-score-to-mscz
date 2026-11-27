"""Pass behaviour contracts and isolated contract runner."""

from __future__ import annotations

from dataclasses import dataclass

from ..core.document import Document
from ..core.pass_base import Context
from .checkers import (
    _pass_name,
    check_idempotent,
    check_measure_health_preserved,
    check_no_new_verifier_violations,
    check_piece_pitch_set_preserved,
    check_sounding_notes_preserved,
    check_structure,
)
from .models import DocFactory, SanityReport, Snapshot
from .snapshot import _as_snapshot, diff_snapshots, snapshot


@dataclass(frozen=True)
class PassContract:
    """What a pass is allowed to change.  ``violations`` reports everything else.

    ``allows_remove_notes`` covers rests and duplicate occurrences only.  Losing a unique
    sounding pitch is never a contract dimension: :func:`run_contract` checks it for every
    pass, whatever the contract says.  The single exception is a pass that legitimately moves
    a note into another measure (``rebase``, overflow dedupe), declared by
    ``allows_relocate_notes``; those passes are then held to the weaker whole-piece check.
    """

    name: str
    allows_add_notes: bool = False
    allows_remove_notes: bool = False
    allows_move_onsets: bool = False
    allows_retime: bool = False
    allows_change_pitch: bool = False
    allows_add_or_remove_measures: bool = False
    allows_voice_changes: bool = False
    allows_relocate_notes: bool = False

    def violations(self, before: Snapshot | Document, after: Snapshot | Document) -> list[str]:
        before_snapshot = _as_snapshot(before)
        after_snapshot = _as_snapshot(after)
        diff = diff_snapshots(before_snapshot, after_snapshot)
        messages: list[str] = []

        if not self.allows_add_notes:
            messages.extend(f"{self.name}: {change.describe()}" for change in diff.added_notes)
        if not self.allows_remove_notes:
            messages.extend(
                f"{self.name}: {change.describe()}" for change in diff.removed_notes
            )
        if not self.allows_move_onsets:
            messages.extend(
                f"{self.name}: {change.describe()}" for change in diff.moved_onsets
            )
        if not self.allows_retime:
            messages.extend(
                f"{self.name}: {change.describe()}" for change in diff.retimed_notes
            )
        if not self.allows_change_pitch:
            messages.extend(
                f"{self.name}: {change.describe()}" for change in diff.changed_pitches
            )
        if not self.allows_add_or_remove_measures:
            messages.extend(
                f"{self.name}: m{number} added" for number in diff.added_measures
            )
            messages.extend(
                f"{self.name}: m{number} removed" for number in diff.removed_measures
            )
        if not self.allows_voice_changes:
            messages.extend(
                f"{self.name}: {change.describe()}" for change in diff.identity_changes
            )
            messages.extend(
                f"{self.name}: {change.describe()}"
                for change in diff.voice_count_changes
            )
        return messages


def run_contract(
    pass_obj,
    doc_factory: DocFactory,
    contract: PassContract,
    ctx: Context | None = None,
) -> SanityReport:
    """Exercise one pass against one contract on isolated document copies.

    ``doc_factory`` must return a fresh :class:`Document` on every call.  Three
    copies are used: before, after (the pass runs here) and idempotence.  The
    inventory/onset checkers are intentionally not part of ``checker_violations``;
    they are contract dimensions, so a contract that allows adding notes stays
    usable.
    """
    context = Context() if ctx is None else ctx
    name = _pass_name(pass_obj)

    before_doc = doc_factory()
    after_doc = doc_factory()
    before_snapshot = snapshot(before_doc)

    result = pass_obj.run(after_doc, context)
    after_snapshot = snapshot(after_doc)

    contract_violations = contract.violations(before_snapshot, after_snapshot)

    checker_violations: list[str] = []
    checker_violations.extend(check_structure(after_doc, context))
    checker_violations.extend(check_measure_health_preserved(before_doc, after_doc, context))
    checker_violations.extend(
        check_no_new_verifier_violations(before_doc, after_doc, context)
    )
    # Global invariant: no pass may make a sounding note disappear, whatever its contract
    # allows for rests or duplicates.  A relocating pass is held to the whole-piece version.
    if contract.allows_relocate_notes:
        checker_violations.extend(
            check_piece_pitch_set_preserved(before_snapshot, after_snapshot)
        )
    else:
        checker_violations.extend(
            check_sounding_notes_preserved(
                before_snapshot,
                after_snapshot,
                allow_measure_removal=contract.allows_add_or_remove_measures,
            )
        )

    idempotence_doc = doc_factory()
    idempotence_violations = check_idempotent(pass_obj, idempotence_doc, context)
    checker_violations.extend(idempotence_violations)

    return SanityReport(
        pass_name=name,
        contract_violations=contract_violations,
        checker_violations=checker_violations,
        idempotent=not idempotence_violations,
        changed=result.changed,
    )
