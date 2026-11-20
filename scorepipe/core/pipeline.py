"""Pass manager: phase-local fixpoints, trace, bounded outer rounds."""

from __future__ import annotations

from dataclasses import dataclass, field

from .document import Document
from .pass_base import Context, Kind, Pass, PassResult, Phase


@dataclass
class TraceEntry:
    phase: str
    round: int
    pass_name: str
    changed: int
    hash_before: str
    hash_after: str


@dataclass
class PhaseReport:
    phase: str
    rounds: int = 0
    changes: int = 0
    stable: bool = False


@dataclass
class RunReport:
    phases: list[PhaseReport] = field(default_factory=list)
    trace: list[TraceEntry] = field(default_factory=list)
    verifier: list = field(default_factory=list)

    @property
    def changes(self) -> int:
        return sum(phase.changes for phase in self.phases)


def run_phase(
    doc: Document,
    passes: list[Pass],
    ctx: Context,
    phase: Phase,
    max_rounds: int = 8,
    trace: list[TraceEntry] | None = None,
) -> PhaseReport:
    """Run a pass set to a fixed point: a full round with no change and no hash move."""
    report = PhaseReport(phase=phase.value)
    if trace is None:
        trace = []
    for round_number in range(1, max_rounds + 1):
        report.rounds = round_number
        before = doc.state_hash()
        round_changes = 0
        for one_pass in passes:
            if one_pass.spec.phase != phase:
                continue
            if one_pass.spec.kind is not Kind.MECHANICAL:
                continue
            hash_before = doc.state_hash()
            result: PassResult = one_pass.run(doc, ctx)
            hash_after = doc.state_hash()
            round_changes += result.changed
            if result.changed:
                trace.append(
                    TraceEntry(
                        phase=phase.value,
                        round=round_number,
                        pass_name=one_pass.spec.name,
                        changed=result.changed,
                        hash_before=hash_before[:12],
                        hash_after=hash_after[:12],
                    )
                )
        report.changes += round_changes
        if round_changes == 0 and doc.state_hash() == before:
            report.stable = True
            break
    return report


def run_pipeline(
    doc: Document,
    ctx: Context,
    structural: list[Pass],
    inject: list[Pass] | None = None,
    display: list[Pass] | None = None,
    verifiers: list | None = None,
    max_rounds: int = 8,
    max_outer_rounds: int = 3,
) -> RunReport:
    """structural fixpoint -> inject fixpoint -> display fixpoint -> verify.

    A verifier violation whose code is listed in ``ctx.options["repairable"]`` triggers one more
    outer round over structural+inject, bounded by ``max_outer_rounds``.
    """
    report = RunReport()
    inject = inject or []
    display = display or []
    repairable = set(ctx.options.get("repairable") or [])
    for outer in range(1, max_outer_rounds + 1):
        report.phases.append(run_phase(doc, structural, ctx, Phase.STRUCTURAL, max_rounds, report.trace))
        report.phases.append(run_phase(doc, inject, ctx, Phase.INJECT, max_rounds, report.trace))
        if not verifiers:
            report.verifier = []
            break
        violations = [violation for verifier in verifiers for violation in verifier(doc, ctx)]
        report.verifier = violations
        if not violations or not any(violation.code in repairable for violation in violations):
            break
        if outer == max_outer_rounds:
            break
    if display:
        report.phases.append(run_phase(doc, display, ctx, Phase.DISPLAY, max_rounds, report.trace))
    return report
