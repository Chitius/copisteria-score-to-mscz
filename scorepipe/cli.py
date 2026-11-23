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
from .loader import load_pages, merge_pages
from .mscz_export import export_and_display
from .notation_patches import apply_patches, load_patches, validate_patches, verify_patches
from .omr import run_omr
from .passes import DISPLAY_PASSES, INJECT_PASSES, STRUCTURAL_PASSES
from .producers import resolve as resolve_producer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scorepipe")
    parser.add_argument("input", nargs="?", help="MusicXML file or MuseScore .mscz")
    parser.add_argument("-o", "--output", help="write the repaired score here")
    parser.add_argument("--facts", help="marks facts JSON produced by the text layer or the agent")
    parser.add_argument("--layout", help="JSON measure boxes for a PDF text-layer facts producer")
    parser.add_argument("--trace", action="store_true", help="print every pass that changed something")
    parser.add_argument("--report", help="write the run report (phases, trace, verifier, analysis) as JSON")
    parser.add_argument("--compare-golden", help="compare the written output with a golden MusicXML")
    parser.add_argument("--check", action="store_true", help="verify only: never write the score")
    parser.add_argument("--list-passes", action="store_true", help="print the registered passes and exit")
    parser.add_argument(
        "--omr",
        help="external OMR command with {pdf} and {outdir} placeholders; its page MusicXML is merged first",
    )
    parser.add_argument("--omr-dir", help="directory for the OMR page output (default: <pdf>_omr)")
    parser.add_argument("--mscz-out", help="also convert to .mscz and run the display phase")
    parser.add_argument("--patches", help="constrained notation patches JSON (ottava prototype)")
    parser.add_argument("--musescore", help="MuseScore executable (default: MSCORE or common paths)")
    parser.add_argument("--title", help="title credit to inject (agent-recognised for scans)")
    parser.add_argument("--composer", help="composer credit to inject")
    parser.add_argument("--max-rounds", type=int, default=32)
    parser.add_argument(
        "--truncate-overfull",
        action="store_true",
        help="trim overfull voices for an editable .mscz; may delete/shorten notes and rests; requires --mscz-out",
    )
    args = parser.parse_args(argv)
    if args.truncate_overfull and (not args.mscz_out or args.check):
        parser.error("--truncate-overfull requires --mscz-out and cannot be used with --check")

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
    layout = None
    if args.layout:
        layout = json.loads(Path(args.layout).read_text(encoding="utf-8-sig"))
    producer = resolve_producer(args.facts, layout=layout)
    if producer is not None:
        if Path(args.facts).suffix.lower() == ".pdf" and layout is None:
            print("facts: PDF text layer has no --layout, so no marks will be produced")
        produced = producer.produce(path)
        facts = {"marks": produced.marks, "credits": produced.credits}
    credits = facts.setdefault("credits", [])
    if args.title:
        credits.append({"type": "title", "text": args.title})
    if args.composer:
        credits.append({"type": "composer", "text": args.composer})
    for problem in validate_facts(facts):
        print(f"facts: {problem}")

    pages = None
    if args.omr:
        outdir = Path(args.omr_dir) if args.omr_dir else path.with_name(path.stem + "_omr")
        page_paths = run_omr(args.omr, path, outdir)
        merged = merge_pages(page_paths)
        print(f"omr: {len(page_paths)} page files, measures per page {merged.measure_counts}")
        doc = merged.document
        pages = merged
    elif path.is_dir():
        merged = load_pages(path)
        print(f"pages: {len(merged.pages)} files, measures per page {merged.measure_counts}")
        doc = merged.document
        pages = merged
    else:
        doc = Document.load(path)
    tuplets_payload = None
    ottava_payload = None
    if args.patches:
        patches_payload = load_patches(args.patches)
        problems = validate_patches(patches_payload, doc, require_acceptance=True)
        if problems:
            for problem in problems:
                print(f"patches: {problem}")
            return 1
        tuplets_payload = {
            "patches": [patch for patch in patches_payload.get("patches") or [] if patch.get("op") == "tuplet"]
        }
        ottava_payload = {
            "patches": [patch for patch in patches_payload.get("patches") or [] if patch.get("op") == "ottava"]
        }
    if tuplets_payload and tuplets_payload["patches"]:
        changed = apply_patches(doc, tuplets_payload)
        print(f"patches: {changed} tuplet change(s)")
    ctx = Context(facts=facts, pages=pages, options={"truncate_overfull": args.truncate_overfull})
    structural_passes = STRUCTURAL_PASSES
    report = run_pipeline(
        doc,
        ctx,
        structural=structural_passes,
        inject=INJECT_PASSES,
        verifiers=VERIFIERS,
        max_rounds=args.max_rounds,
    )
    _print_report(report, args.trace)
    if not args.mscz_out or args.check:
        _write_report(report, args.report)
    if ottava_payload and ottava_payload["patches"]:
        changed = apply_patches(doc, ottava_payload)
        print(f"patches: {changed} octave direction(s)")
    patch_failed = False
    if args.patches:
        patch_problems = verify_patches(doc, patches_payload)
        for problem in patch_problems:
            print(f"patches: {problem}")
        if patch_problems:
            patch_failed = True
            report.analysis.append(
                {"phase": "patches", "pass": "verify_patches", "notes": patch_problems}
            )
    if args.output and not args.check:
        doc.save(args.output)
    if args.compare_golden:
        if not args.output or args.check:
            print("compare: needs a written output (-o, without --check)")
        else:
            from .compare import compare

            result = compare(args.compare_golden, args.output)
            print(
                f"compare: {result['ratio'] * 100:.2f}% mismatch "
                f"(missing {result['missing']}, extra {result['extra']})"
            )
            print(f"compare: worst missing {result['missing_by_measure']}")
            print(f"compare: worst extra   {result['extra_by_measure']}")
    status = 0 if not report.verifier else 1
    if patch_failed:
        status = 1
    if args.mscz_out and not args.check:
        display_report = export_and_display(
            doc, args.mscz_out, ctx, args.musescore, work_musicxml=args.output
        )
        print(f"mscz: {args.mscz_out}")
        _print_report(display_report, args.trace)
        report = RunReport(
            phases=report.phases + display_report.phases,
            trace=report.trace + display_report.trace,
            verifier=report.verifier + display_report.verifier,
            analysis=report.analysis + display_report.analysis,
        )
        _write_report(report, args.report)
        if display_report.verifier:
            status = 1
    return status


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
                "notes": entry.notes,
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
