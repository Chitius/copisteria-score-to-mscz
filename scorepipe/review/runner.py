"""Top-level orchestration for the delivery review loop."""

from __future__ import annotations

import hashlib
from pathlib import Path

from ..loader import load_pages
from ..notation_patches import score_map
from .helpers import ReviewHooks, _timing_report, _truncation_performed, _write
from .stages import (
    prepare_facts_and_gates,
    run_forced_truncation,
    run_mechanical_baseline,
    run_proof_sheets,
    run_reviewed_pipeline,
)


def run_review(
    args,
    *,
    python: str,
    musescore: str | None,
    root: Path,
    scripts_dir: Path,
    hooks: ReviewHooks | None = None,
) -> int:
    """Execute the full delivery review loop and write ``review-report.json`` + ``delivery.json``."""
    hooks = hooks or ReviewHooks()
    pdf = Path(args.pdf).resolve()
    page_dir = Path(args.pages).resolve()
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    pdf_sha256 = hashlib.sha256(pdf.read_bytes()).hexdigest()
    facts_dir = Path(args.facts_dir).resolve() if args.facts_dir else outdir / "facts"

    page_count = hooks.pdf_pages(pdf)
    if page_count is None:
        raise RuntimeError(
            "pdfinfo is required to verify page coverage; install poppler or pass a supported PDF"
        )

    merged = load_pages(page_dir)
    _write(outdir / "score-map.json", score_map(merged.document))
    image_count = hooks.render_pages(pdf, outdir / "pages")

    gated = prepare_facts_and_gates(
        args,
        outdir=outdir,
        facts_dir=facts_dir,
        page_count=page_count,
        image_count=image_count,
        pdf_sha256=pdf_sha256,
        merged=merged,
    )
    if gated is None:
        return 1

    blockers = gated["blockers"]
    overrides = gated["overrides"]
    findings = gated["findings"]
    artifacts_missing = gated["artifacts_missing"]
    facts = gated["facts"]

    mechanical = run_mechanical_baseline(
        args,
        outdir=outdir,
        page_dir=page_dir,
        python=python,
        musescore=musescore,
        root=root,
        hooks=hooks,
        findings=findings,
    )

    report = {
        "ready": not blockers,
        "interim": bool(overrides or artifacts_missing),
        "semantic_authority": True,
        "overrides": overrides,
        "findings": findings,
        "artifacts_missing": artifacts_missing,
        "source_pdf": {"path": str(pdf), "sha256": pdf_sha256},
        "page_count": page_count,
        "rendered_pages": image_count,
        "covered_pages": gated["covered"],
        "missing_pages": gated["missing_pages"],
        "facts": {
            "credits": len(facts.get("credits") or []),
            "marks": len(facts.get("marks") or []),
            "parts": len(facts.get("parts") or []),
        },
        "facts_skipped": bool(args.skip_facts),
        "unresolved": gated["unresolved"],
        "corrections": gated["corrections"],
        "patch_count": len((gated["patch_payload"] or {}).get("patches") or []),
        "mechanical": mechanical,
        "blockers": blockers,
        "artifacts": {
            "score_map": str(outdir / "score-map.json"),
            "facts": str(gated["facts_path"]),
            "pages": str(outdir / "pages"),
        },
    }
    if blockers:
        timing = _timing_report((mechanical or {}).get("timing"), None)
        report["timing"] = timing
        _write(outdir / "timing-report.json", timing)
        _write(outdir / "review-report.json", report)
        for blocker in blockers:
            print(f"blocked: {blocker}")
        for finding in findings:
            print(f"finding: {finding}")
        return 2

    reviewed_exit, reviewed_only_overfull = run_reviewed_pipeline(
        args,
        outdir=outdir,
        page_dir=page_dir,
        facts_path=gated["facts_path"],
        python=python,
        musescore=musescore,
        mechanical=mechanical,
        report=report,
        root=root,
        hooks=hooks,
    )

    if not args.no_confidence:
        report["confidence"] = hooks.confidence_map(page_dir, outdir)
        report["artifacts"]["confidence"] = report["confidence"].get("dir")

    forced = run_forced_truncation(
        args,
        outdir=outdir,
        page_dir=page_dir,
        facts_path=gated["facts_path"],
        python=python,
        musescore=musescore,
        mechanical=mechanical,
        report=report,
        root=root,
        hooks=hooks,
    )

    if reviewed_exit != 0:
        tolerated = (
            forced is not None
            and forced.get("ready")
            and _truncation_performed(forced.get("operations") or [])
            and reviewed_only_overfull
        )
        if tolerated:
            codes = ", ".join(report.get("reviewed_verifier_codes") or []) or "length findings"
            report["findings"].append(
                "reviewed (untruncated) tree reported length complaints only "
                f"({codes}); the editable delivery trims/retimes them"
            )
            report["ready"] = not report["blockers"]
        else:
            report["ready"] = False
            # ``pipeline_exit`` may already be the delivered (forced) run's exit once that copy
            # shipped, so name the failing tree explicitly instead of just "pipeline exited N".
            report["blockers"].append(f"reviewed pipeline exited {reviewed_exit}")

    if not args.no_sheets:
        run_proof_sheets(
            outdir=outdir,
            page_dir=page_dir,
            pdf=pdf,
            python=python,
            musescore=musescore,
            report=report,
            root=root,
            scripts_dir=scripts_dir,
            hooks=hooks,
        )

    _write(outdir / "review-report.json", report)
    _write(
        outdir / "delivery.json",
        {
            "reviewed": True,
            "ready": report["ready"],
            "interim": report.get("interim"),
            "source_pdf": report.get("source_pdf"),
            "artifacts_missing": report.get("artifacts_missing"),
            "pipeline_exit": report.get("pipeline_exit"),
            "reviewed_pipeline_exit": report.get("reviewed_pipeline_exit"),
            "render_exit": report.get("render_exit"),
            "artifacts": report.get("artifacts"),
            "semantic_authority": report.get("semantic_authority", True),
            "semantic_dir": report.get("semantic_dir"),
            "sheets": report.get("sheets"),
            "mechanical": mechanical,
            "forced_truncation": forced,
            "blockers": report.get("blockers") or [],
            "findings": report.get("findings") or [],
        },
    )
    print(f"review ready: {report['ready']}")
    if report["ready"]:
        print("delivery (open these):")
        for label, key in (
            ("musicxml", "musicxml"),
            ("mscz", "mscz"),
            ("score pdf", "pdf"),
            ("sheet pdf", "sheets_pdf"),
        ):
            value = report["artifacts"].get(key)
            if value:
                print(f"  {label:10s} {value}")
    else:
        for blocker in report.get("blockers") or []:
            print(f"blocked: {blocker}")
    print(f"report: {outdir / 'review-report.json'}")
    if report["ready"]:
        return 0
    return report.get("pipeline_exit") or report.get("render_exit") or 2
