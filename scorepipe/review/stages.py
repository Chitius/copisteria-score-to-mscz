"""Individual stages of the delivery review loop."""

from __future__ import annotations

import shutil
from pathlib import Path

from ..agent_facts import (
    load_agent_facts,
    merge_agent_facts,
    normalize_agent_facts,
    validate_agent_facts,
)
from ..notation_patches import load_patches, validate_patches
from .helpers import (
    ReviewHooks,
    _only_overfull_violations,
    _parts,
    _timing,
    _timing_report,
    _truncation_notes,
    _truncation_performed,
    _verifier_count,
    _write,
)


def prepare_facts_and_gates(
    args,
    *,
    outdir: Path,
    facts_dir: Path,
    page_count: int,
    image_count: int,
    pdf_sha256: str,
    merged,
) -> dict | None:
    """Validate/merge agent facts, check coverage & patch gates, and write ``facts.json``."""
    parts = _parts(facts_dir)
    facts = {"credits": [], "marks": [], "corrections": [], "unresolved": [], "producer": {"pages": []}}
    if parts:
        normalized = [normalize_agent_facts(load_agent_facts(path)) for path in parts]
        problems = []
        for path, payload in zip(parts, normalized):
            problems.extend(
                f"{path.name}: {problem}"
                for problem in validate_agent_facts(payload, page_count=page_count)
            )
        if problems:
            _write(
                outdir / "review-report.json",
                {"ready": False, "blockers": problems, "errors": problems},
            )
            for problem in problems:
                print(problem)
            return None
        facts = merge_agent_facts(normalized)

    if args.title:
        facts.setdefault("credits", []).append({"type": "title", "text": args.title})
    if args.composer:
        facts.setdefault("credits", []).append({"type": "composer", "text": args.composer})
    declared_pdf_hash = (facts.get("producer") or {}).get("pdf_sha256")
    if declared_pdf_hash and declared_pdf_hash != pdf_sha256:
        facts.setdefault("producer", {})["pdf_sha256_mismatch"] = True
    else:
        facts.setdefault("producer", {})["pdf_sha256"] = pdf_sha256

    facts_path = outdir / "facts.json"
    _write(facts_path, facts)
    _write(outdir / "facts-corrections.json", facts.get("corrections") or [])

    covered = sorted(facts.get("producer", {}).get("pages") or [])
    missing_pages = [page for page in range(1, page_count + 1) if page not in covered] if page_count else []
    unresolved = facts.get("unresolved") or []
    corrections = facts.get("corrections") or []
    blockers = []
    overrides = []
    findings = []
    artifacts_missing = []

    if (facts.get("producer") or {}).get("pdf_sha256_mismatch"):
        blockers.append("facts were produced for a different source PDF (sha256 mismatch)")
    if args.skip_facts:
        findings.append(
            "no per-page facts were supplied (--skip-facts): this is the mechanical tree, "
            "no credits or tempo marks were injected"
        )
    else:
        if page_count and len(parts) < page_count and not args.allow_combined_pages:
            blockers.append(
                f"facts coverage uses {len(parts)} file(s) for {page_count} pages; "
                "use one agent-page file per page or pass --allow-combined-pages"
            )
        if missing_pages:
            blockers.append(f"missing pages: {missing_pages}")
    if unresolved:
        if args.allow_unresolved:
            overrides.append(f"{len(unresolved)} unresolved claim(s)")
        else:
            blockers.append(f"{len(unresolved)} unresolved claim(s)")
    if corrections:
        if args.allow_corrections:
            overrides.append(f"{len(corrections)} proposed correction(s)")
        else:
            blockers.append(f"{len(corrections)} proposed correction(s)")
    if args.no_mechanical:
        artifacts_missing.append("mechanical baseline")
        if not args.allow_incomplete_delivery:
            blockers.append("mechanical baseline skipped by --no-mechanical")
    if args.no_forced_truncation:
        artifacts_missing.append("forced-truncation tree")
        if not args.allow_incomplete_delivery:
            blockers.append("forced-truncation tree skipped by --no-forced-truncation")
    if args.no_mscz:
        artifacts_missing.append("mscz/forced-truncation")
    if args.no_pdf:
        artifacts_missing.append("pdf")
    if artifacts_missing and not args.allow_incomplete_delivery:
        blockers.append("required artifacts missing: " + ", ".join(artifacts_missing))
    if image_count != page_count:
        blockers.append(f"rendered {image_count} images for {page_count} pages")

    patch_payload = None
    if args.patches:
        patch_payload = load_patches(args.patches)
        patch_problems = validate_patches(patch_payload, merged.document, require_acceptance=True)
        if patch_problems:
            blockers.extend(f"patch: {problem}" for problem in patch_problems)

    return {
        "facts": facts,
        "facts_path": facts_path,
        "covered": covered,
        "missing_pages": missing_pages,
        "unresolved": unresolved,
        "corrections": corrections,
        "blockers": blockers,
        "overrides": overrides,
        "findings": findings,
        "artifacts_missing": artifacts_missing,
        "patch_payload": patch_payload,
    }


def run_mechanical_baseline(
    args,
    *,
    outdir: Path,
    page_dir: Path,
    python: str,
    musescore: str | None,
    root: Path,
    hooks: ReviewHooks,
    findings: list[str],
) -> dict | None:
    """Build the no-facts/no-patches baseline tree for comparison."""
    if args.no_mechanical:
        return None
    mechanical_dir = Path(args.mechanical_dir).resolve() if args.mechanical_dir else outdir / "mechanical"
    mech_musicxml = mechanical_dir / "score.musicxml"
    mech_report = mechanical_dir / "report.json"
    mech_mscz = None if args.no_mscz else mechanical_dir / "score.mscz"
    mechanical_command = [
        python,
        "-m",
        "scorepipe.cli",
        str(page_dir),
        "-o",
        str(mech_musicxml),
        "--report",
        str(mech_report),
    ]
    if mech_mscz:
        mechanical_command.extend(["--mscz-out", str(mech_mscz)])
        if musescore:
            mechanical_command.extend(["--musescore", str(musescore)])
    for stale in (mech_musicxml, mech_report, mech_mscz, mechanical_dir / "score.pdf"):
        if stale:
            stale.unlink(missing_ok=True)
    print("+ mechanical baseline (no agent facts or patches)")
    mech_exit = hooks.run(mechanical_command, root)
    mechanical = {
        "dir": str(mechanical_dir),
        "musicxml": str(mech_musicxml),
        "report": str(mech_report),
        "pipeline_exit": mech_exit,
        "timing": _timing(mech_report),
        "mscz": str(mech_mscz) if mech_mscz and mech_mscz.is_file() else None,
        "pdf": None,
        "render_exit": None,
        "ready": mech_exit == 0,
    }
    if mech_mscz and mech_mscz.is_file() and not args.no_pdf and musescore:
        mech_pdf = mechanical_dir / "score.pdf"
        render_exit = hooks.run([musescore, "-f", "-o", str(mech_pdf), str(mech_mscz)], root)
        mechanical["pdf"] = str(mech_pdf) if mech_pdf.is_file() else None
        mechanical["render_exit"] = render_exit
        if render_exit == 0 and mech_pdf.is_file():
            try:
                mechanical["rendered_pages"] = hooks.render_pages(mech_pdf, mechanical_dir / "rendered")
            except RuntimeError as exc:
                mechanical["render_error"] = str(exc)

    if not mechanical.get("ready"):
        # The baseline is the *comparison* tree, not a delivery candidate.  A display defect in
        # it (typically an overfull voice the forced copy exists to repair) must not stop the
        # reviewed run: the reviewed verifier below is the real acceptance gate.
        findings.append(
            "mechanical baseline is not verifier-clean "
            f"(pipeline exit {mechanical.get('pipeline_exit')}, "
            f"{len((mechanical.get('timing') or {}).get('violations') or [])} measure-length finding(s)); "
            "kept as the no-facts comparison only"
        )
    return mechanical


def run_reviewed_pipeline(
    args,
    *,
    outdir: Path,
    page_dir: Path,
    facts_path: Path,
    python: str,
    musescore: str | None,
    mechanical: dict | None,
    report: dict,
    root: Path,
    hooks: ReviewHooks,
) -> tuple[int, bool]:
    """Run the reviewed scorepipe pipeline and render the reviewed score to PDF/PNG."""
    musicxml = outdir / "score.musicxml"
    report_json = outdir / "report.json"
    for stale in (musicxml, report_json, outdir / "score.mscz", outdir / "score.pdf"):
        stale.unlink(missing_ok=True)
    command = [
        python,
        "-m",
        "scorepipe.cli",
        str(page_dir),
        "-o",
        str(musicxml),
        "--report",
        str(report_json),
        "--facts",
        str(facts_path),
    ]
    if args.patches:
        command.extend(["--patches", str(Path(args.patches).resolve())])
    if args.compare_golden:
        command.extend(["--compare-golden", str(Path(args.compare_golden).resolve())])
    mscz = None if args.no_mscz else outdir / "score.mscz"
    if mscz:
        command.extend(["--mscz-out", str(mscz)])
        if musescore:
            command.extend(["--musescore", str(musescore)])
    reviewed_exit = hooks.run(command, root)
    reviewed_only_overfull = _only_overfull_violations(report_json)
    report["pipeline_exit"] = reviewed_exit
    report["artifacts"].update({"musicxml": str(musicxml), "report": str(report_json)})
    if mscz:
        report["artifacts"]["mscz"] = str(mscz)
    timing = _timing_report((mechanical or {}).get("timing"), _timing(report_json))
    report["timing"] = timing
    _write(outdir / "timing-report.json", timing)
    # A reviewed failure is decided after the forced copy: an overfull voice that the editable
    # copy trims is exactly why that copy exists, but any other violation still blocks.
    if reviewed_exit != 0:
        report["ready"] = False

    if mscz and mscz.is_file() and not args.no_pdf and musescore:
        pdf_out = outdir / "score.pdf"
        render_exit = hooks.run([musescore, "-f", "-o", str(pdf_out), str(mscz)], root)
        report["render_exit"] = render_exit
        report["artifacts"]["pdf"] = str(pdf_out)
        if render_exit != 0:
            report["ready"] = False
            report["blockers"].append(f"renderer exited {render_exit}")
        if render_exit == 0 and not args.no_pdf:
            out_pages = outdir / "rendered"
            try:
                count = hooks.render_pages(pdf_out, out_pages)
                report["rendered_after"] = count
                report["artifacts"]["rendered"] = str(out_pages)
            except RuntimeError as exc:
                report["render_error"] = str(exc)
                report["ready"] = False
    return reviewed_exit, reviewed_only_overfull


def run_forced_truncation(
    args,
    *,
    outdir: Path,
    page_dir: Path,
    facts_path: Path,
    python: str,
    musescore: str | None,
    mechanical: dict | None,
    report: dict,
    root: Path,
    hooks: ReviewHooks,
) -> dict | None:
    """Build the forced-truncation editable tree and promote it to root when it trims notes."""
    if args.no_forced_truncation:
        return None
    forced_dir = Path(args.forced_dir).resolve() if args.forced_dir else outdir / "forced-truncation"
    if args.no_mscz:
        forced = {
            "semantic_authority": False,
            "status": "skipped",
            "reason": "--no-mscz prevents mscx truncation; forced repair requires a .mscz",
            "dir": str(forced_dir),
            "operations": [],
            "unresolved": [],
            "irregular_durations": [],
            "spanner_risks": [],
            "ready": False,
        }
        report["forced_truncation"] = forced
        _write(forced_dir / "truncation-report.json", forced)
        print("forced truncation: skipped because --no-mscz was used")
        if not args.allow_incomplete_delivery:
            report["ready"] = False
            report["blockers"].append("forced truncation skipped by --no-mscz")
        return forced

    forced_musicxml = forced_dir / "score.musicxml"
    forced_report = forced_dir / "report.json"
    forced_mscz = forced_dir / "score.mscz"
    for stale in (forced_musicxml, forced_report, forced_mscz, forced_dir / "score.pdf"):
        stale.unlink(missing_ok=True)
    forced_command = [
        python,
        "-m",
        "scorepipe.cli",
        str(page_dir),
        "-o",
        str(forced_musicxml),
        "--report",
        str(forced_report),
        "--facts",
        str(facts_path),
        "--truncate-overfull",
    ]
    if args.patches:
        forced_command.extend(["--patches", str(Path(args.patches).resolve())])
    forced_command.extend(["--mscz-out", str(forced_mscz)])
    if musescore:
        forced_command.extend(["--musescore", str(musescore)])
    print("+ forced-truncation copy (editable only; semantic_authority=false)")
    forced_exit = hooks.run(forced_command, root)
    operations = _truncation_notes(forced_report)
    unresolved = [note for note in operations if note.startswith("UNRESOLVED")]
    irregular = [note for note in operations if "[explicit-duration]" in note]
    spanner_risks = [note for note in operations if "[spanner-risk:" in note]
    forced_pdf = None
    forced_render_exit = None
    forced_render_error = None
    if forced_mscz.is_file() and not args.no_pdf and musescore:
        forced_pdf = forced_dir / "score.pdf"
        forced_render_exit = hooks.run([musescore, "-f", "-o", str(forced_pdf), str(forced_mscz)], root)
        if forced_render_exit == 0 and forced_pdf.is_file():
            try:
                hooks.render_pages(forced_pdf, forced_dir / "rendered")
            except RuntimeError as exc:
                forced_render_error = str(exc)
    forced = {
        "semantic_authority": False,
        "status": (
            "failed"
            if forced_exit != 0
            else "unresolved"
            if unresolved
            else "applied"
            if operations
            else "noop"
        ),
        "purpose": "make overfull measures editable; may remove or shorten notes/rests",
        "dir": str(forced_dir),
        "musicxml": str(forced_musicxml) if forced_musicxml.is_file() else None,
        "mscz": str(forced_mscz) if forced_mscz.is_file() else None,
        "pdf": str(forced_pdf) if forced_pdf and forced_pdf.is_file() else None,
        "report": str(forced_report) if forced_report.is_file() else None,
        "pipeline_exit": forced_exit,
        "render_exit": forced_render_exit,
        "render_error": forced_render_error,
        "operations": operations,
        "unresolved": unresolved,
        "irregular_durations": irregular,
        "spanner_risks": spanner_risks,
        "verifier_count": _verifier_count(forced_report),
    }
    forced["ready"] = (
        forced_exit == 0
        and forced["verifier_count"] == 0
        and not unresolved
        and forced_mscz.is_file()
        and (forced_render_exit is None or forced_render_exit == 0)
        and forced_render_error is None
    )
    report["forced_truncation"] = forced
    _write(forced_dir / "truncation-report.json", forced)
    if operations:
        print(f"forced truncation: {len(operations)} operation(s); see {forced_dir / 'truncation-report.json'}")
        for operation in operations:
            print(f"  {operation}")
    else:
        print("forced truncation: no operation needed")

    if not forced["ready"]:
        report["ready"] = False
        report["blockers"].append("forced-truncation copy is not clean/complete")
    elif _truncation_performed(operations):
        # The editable copy is what the user opens, so it becomes the delivery root and the
        # page comparison is rasterized from it.  The untruncated reviewed tree moves to
        # semantic/ because the trim is not a semantic repair (semantic_authority=false).
        semantic_dir = outdir / "semantic"
        semantic_dir.mkdir(parents=True, exist_ok=True)
        for name in ("score.musicxml", "score.mscz", "score.pdf", "report.json"):
            current = outdir / name
            if current.is_file():
                shutil.move(str(current), str(semantic_dir / name))
        for name in ("score.musicxml", "score.mscz", "score.pdf", "report.json"):
            produced = forced_dir / name
            if produced.is_file():
                shutil.copy2(produced, outdir / name)
        shutil.copy2(forced_dir / "truncation-report.json", outdir / "truncation-report.json")
        report["semantic_authority"] = False
        report["semantic_dir"] = str(semantic_dir)
        report["delivery_note"] = (
            "root score.mscz/score.pdf are the truncated editable copy; root "
            "score.musicxml is the untruncated semantic master (truncation is an mscx "
            "display repair and is not reflected in MusicXML)"
        )
        report["pipeline_exit"] = forced_exit
        report["render_exit"] = forced_render_exit
        if not args.no_pdf and (outdir / "score.pdf").is_file():
            try:
                report["rendered_after"] = hooks.render_pages(outdir / "score.pdf", outdir / "rendered")
            except RuntimeError as exc:
                report["render_error"] = str(exc)
                report["ready"] = False
        report["timing"] = _timing_report(
            (mechanical or {}).get("timing"), _timing(outdir / "report.json")
        )
        _write(outdir / "timing-report.json", report["timing"])
        report["artifacts"].update(
            {
                "musicxml": str(outdir / "score.musicxml"),
                "mscz": str(outdir / "score.mscz"),
                "pdf": str(outdir / "score.pdf"),
                "report": str(outdir / "report.json"),
                "truncation_report": str(outdir / "truncation-report.json"),
                "semantic": str(semantic_dir),
            }
        )
        print("delivery: forced-editable copy is the root artifact (semantic_authority=false)")
        print(f"semantic: untruncated reviewed tree kept in {semantic_dir}")
    return forced


def run_proof_sheets(
    *,
    outdir: Path,
    page_dir: Path,
    pdf: Path,
    python: str,
    musescore: str | None,
    report: dict,
    root: Path,
    scripts_dir: Path,
    hooks: ReviewHooks,
) -> None:
    """Build measure-level page proof sheets and copy ``review-sheets.pdf`` to root."""
    # Measure-level proof sheets of the delivered tree: same pages, same measure numbers, the
    # same bars tinted on the scan and on the render.  A reading aid, so a failure is a finding.
    sheets_dir = outdir / "review" / "sheets"
    delivered_score = (
        outdir / "score.mscz"
        if (outdir / "score.mscz").is_file()
        else (outdir / "score.musicxml" if (outdir / "score.musicxml").is_file() else None)
    )
    sheet_command = [
        python,
        str(scripts_dir / "review_sheet.py"),
        "--pages",
        str(page_dir),
        "--out",
        str(sheets_dir),
        "--report",
        str(outdir / "report.json"),
        "--title-from",
        str(outdir / "score.musicxml"),
        "--source-name",
        pdf.name,
    ]
    if delivered_score is not None:
        sheet_command.extend(["--score", str(delivered_score)])
    scan_dir = page_dir.parent / "pages"
    if scan_dir.is_dir():
        sheet_command.extend(["--scan-dir", str(scan_dir)])
    if musescore:
        sheet_command.extend(["--musescore", str(musescore)])
    print("+ page proof sheets (measure-level; reading aid)")
    sheet_exit = hooks.run(sheet_command, root)
    report["sheets"] = {"dir": str(sheets_dir), "exit": sheet_exit}
    sheets_pdf = sheets_dir / "review-sheets.pdf"
    if sheets_pdf.is_file():
        # One obvious file at the delivery root as well: a human opening the folder should not
        # have to know that the pages live three levels down.
        delivery_pdf = outdir / "review-sheets.pdf"
        shutil.copy2(sheets_pdf, delivery_pdf)
        report["sheets"]["pdf"] = str(delivery_pdf)
        report["artifacts"]["sheets_pdf"] = str(delivery_pdf)
        print(f"sheets:        {delivery_pdf}")
    if sheet_exit != 0:
        report["findings"].append(
            "page proof sheets reported an incomplete alignment; see review/sheets"
        )
