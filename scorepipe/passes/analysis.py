"""Read-only analysis passes: they report, the runner records, nothing changes."""

from __future__ import annotations

from ..core.document import Document
from ..core.invariants import measure_lengths
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase


class MeasureLengthReport:
    spec = PassSpec(
        name="measure_length_report",
        phase=Phase.STRUCTURAL,
        kind=Kind.ANALYSIS,
        description="report voices whose content does not fill the declared metre",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        violations = measure_lengths(doc, ctx)
        notes = [f"m{violation.measure}: {violation.detail}" for violation in violations]
        return PassResult(changed=0, notes=notes)


ANALYSIS_PASSES = [MeasureLengthReport()]
