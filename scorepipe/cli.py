"""Command line: run the pipeline on MusicXML or on a MuseScore .mscz."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core.document import Document
from .core.invariants import VERIFIERS, Violation
from .core.mscz import MsczArchive
from .core.mscx_invariants import MSCX_VERIFIERS
from .core.pass_base import Context
from .core.pipeline import RunReport, run_display, run_pipeline
from .facts import load_facts, validate_facts
from .passes import DISPLAY_PASSES, INJECT_PASSES, STRUCTURAL_PASSES


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scorepipe")
    parser.add_argument("input", help="MusicXML file or MuseScore .mscz")
    parser.add_argument("-o", "--output", help="write the repaired score here")
    parser.add_argument("--facts", help="marks facts JSON produced by the text layer or the agent")
    parser.add_argument("--trace", action="store_true", help="print every pass that changed something")
    parser.add_argument("--max-rounds", type=int, default=8)
    args = parser.parse_args(argv)

    path = Path(args.input)
    if path.suffix.lower() == ".mscz":
        return _run_mscz(path, args)

    facts = load_facts(args.facts)
    for problem in validate_facts(facts):
        print(f"facts: {problem}")
    doc = Document.load(path)
    ctx = Context(facts=facts)
    report = run_pipeline(
        doc,
        ctx,
        structural=STRUCTURAL_PASSES,
        inject=INJECT_PASSES,
        verifiers=VERIFIERS,
        max_rounds=args.max_rounds,
    )
    _print_report(report, args.trace)
    if args.output:
        doc.save(args.output)
    return 0 if not report.verifier else 1


def _run_mscz(path: Path, args) -> int:
    archive = MsczArchive.open(path)
    ctx = Context()
    report = run_display(archive.document, ctx, DISPLAY_PASSES, MSCX_VERIFIERS, args.max_rounds)
    _print_report(report, args.trace)
    if args.output:
        archive.save(args.output)
    else:
        print("mscz: pass -o to write the repaired container")
    return 0 if not report.verifier else 1


def _print_report(report: RunReport, trace: bool) -> None:
    if trace:
        for entry in report.trace:
            print(f"{entry.phase:10s} r{entry.round} {entry.pass_name:32s} {entry.changed:3d}")
    for phase in report.phases:
        print(f"{phase.phase}: rounds={phase.rounds} changes={phase.changes} stable={phase.stable}")
    violations: list[Violation] = report.verifier or []
    if violations:
        print(f"verifier: {len(violations)} violation(s)")
        for violation in violations[:40]:
            print(f"  {violation.code} m{violation.measure}: {violation.detail}")
    else:
        print("verifier: clean")


if __name__ == "__main__":
    sys.exit(main())
