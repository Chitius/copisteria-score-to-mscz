"""Command line: run the pipeline on MusicXML or on a MuseScore .mscz."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core.document import Document
from .core.invariants import VERIFIERS, Violation
from .core.mscz import MsczArchive
from .core.mscx_invariants import MSCX_VERIFIERS
from .core.pass_base import Context, Phase
from .core.pipeline import RunReport, run_display, run_pipeline
from .core.registry import validate_all
from .facts import validate_facts
from .loader import load_pages
from .passes import DISPLAY_PASSES, INJECT_PASSES, STRUCTURAL_PASSES
from .producers import resolve as resolve_producer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scorepipe")
    parser.add_argument("input", nargs="?", help="MusicXML file or MuseScore .mscz")
    parser.add_argument("-o", "--output", help="write the repaired score here")
    parser.add_argument("--facts", help="marks facts JSON produced by the text layer or the agent")
    parser.add_argument("--trace", action="store_true", help="print every pass that changed something")
    parser.add_argument("--report", help="write the run report (phases, trace, verifier, analysis) as JSON")
    parser.add_argument("--check", action="store_true", help="verify only: never write the score")
    parser.add_argument("--list-passes", action="store_true", help="print the registered passes and exit")
    parser.add_argument("--max-rounds", type=int, default=8)
    args = parser.parse_args(argv)

    groups = {
        Phase.STRUCTURAL: STRUCTURAL_PASSES,
        Phase.INJECT: INJECT_PASSES,
        Phase.DISPLAY: DISPLAY_PASSES,
    }
    if args.list_passes:
        for phase, passes in groups.items():
            for one_pass in passes:
                owns = ",".join(one_pass.spec.owns) or "-"
                print(f"{phase.value:10s} {one_pass.spec.kind.value:10s} {one_pass.spec.name:32s} {owns}")
        return 0
    if not args.input:
        parser.error("input is required unless --list-passes is used")
    problems = validate_all(groups)
    if problems:
        for problem in problems:
            print(f"registry: {problem}")
        return 2

    path = Path(args.input)
    if path.suffix.lower() == ".mscz":
        return _run_mscz(path, args)

    facts = {}
    producer = resolve_producer(args.facts)
    if producer is not None:
        facts = {"marks": producer.produce(path).marks}
    for problem in validate_facts(facts):
        print(f"facts: {problem}")

    if path.is_dir():
        merged = load_pages(path)
        print(f"pages: {len(merged.pages)} files, measures per page {merged.measure_counts}")
        doc = merged.document
    else:
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
    _write_report(report, args.report)
    if args.output and not args.check:
        doc.save(args.output)
    return 0 if not report.verifier else 1


def _run_mscz(path: Path, args) -> int:
    archive = MsczArchive.open(path)
    ctx = Context()
    report = run_display(archive.document, ctx, DISPLAY_PASSES, MSCX_VERIFIERS, args.max_rounds)
    _print_report(report, args.trace)
    _write_report(report, args.report)
    if args.check:
        return 0 if not report.verifier else 1
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
    for entry in report.analysis:
        for note in entry.get("notes") or []:
            suffix = " (analysis mutated the score!)" if entry.get("mutated") else ""
            print(f"analysis: {entry['pass']}: {note}{suffix}")
    violations: list[Violation] = report.verifier or []
    if violations:
        print(f"verifier: {len(violations)} violation(s)")
        for violation in violations[:40]:
            print(f"  {violation.code} m{violation.measure}: {violation.detail}")
    else:
        print("verifier: clean")


def _write_report(report: RunReport, path: str | None) -> None:
    if not path:
        return
    payload = {
        "phases": [
            {
                "phase": phase.phase,
                "rounds": phase.rounds,
                "changes": phase.changes,
                "stable": phase.stable,
            }
            for phase in report.phases
        ],
        "trace": [
            {
                "phase": entry.phase,
                "round": entry.round,
                "pass": entry.pass_name,
                "changed": entry.changed,
            }
            for entry in report.trace
        ],
        "analysis": report.analysis,
        "verifier": [
            {"code": violation.code, "measure": violation.measure, "detail": violation.detail}
            for violation in report.verifier
        ],
    }
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
