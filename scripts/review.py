"""One review loop: page images -> agent facts/patches -> pipeline -> forced repair -> report.

This is the operator entry point for the delivery stage.  It deliberately stops when page coverage
is incomplete or when unresolved/corrections need a human decision; `--allow-unresolved` and
`--allow-corrections` are explicit overrides for an interim review.

The run order is mechanical baseline -> reviewed pipeline -> forced-truncation pipeline, and the
forced copy is what ships when it had to trim an overfull voice: the root `score.mscz`/`score.pdf`
become the truncated editable copy, `rendered/` is rasterised from it, and the untruncated reviewed
tree is kept in `semantic/`.  Root `score.musicxml` stays the untruncated semantic master.  The
measure-level proof sheets run last, on the delivered tree, and are also bound into
`review-sheets.pdf`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from scorepipe.agent_facts import (  # noqa: E402
    load_agent_facts,
    merge_agent_facts,
    normalize_agent_facts,
    validate_agent_facts,
)
from scorepipe.loader import load_pages  # noqa: E402
from scorepipe.mscz_export import find_musescore  # noqa: E402
from scorepipe.notation_patches import (  # noqa: E402
    load_patches,
    score_map,
    validate_patches,
)


def _run(command: list[str], cwd: Path) -> int:
    print("+ " + " ".join(str(part) for part in command))
    completed = subprocess.run(
        [str(part) for part in command],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    if output.strip():
        print(output.rstrip())
    return completed.returncode


def _pdf_pages(pdf: Path) -> int | None:
    binary = shutil.which("pdfinfo")
    if not binary:
        return None
    completed = subprocess.run([binary, str(pdf)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    for line in completed.stdout.splitlines():
        if line.lower().startswith("pages:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError:
                return None
    return None


def _parts(facts_dir: Path) -> list[Path]:
    return sorted(facts_dir.glob("agent-page*.json"))


def _render_pages(pdf: Path, outdir: Path) -> int:
    binary = shutil.which("pdftoppm")
    if not binary:
        raise RuntimeError("pdftoppm not found")
    outdir.mkdir(parents=True, exist_ok=True)
    for old in outdir.glob("source-*.png"):
        old.unlink()
    completed = subprocess.run(
        [binary, "-png", "-r", "150", str(pdf), str(outdir / "source")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"pdftoppm failed: {(completed.stderr or '').strip()[:400]}")
    return len(list(outdir.glob("source-*.png")))


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _default_env_file() -> Path | None:
    """``env.local.json`` beside the caller, else beside the repository."""
    for candidate in (Path.cwd() / "env.local.json", ROOT / "env.local.json"):
        if candidate.is_file():
            return candidate
    return None


def _load_config(path: str | Path | None) -> dict:
    if not path:
        return {}
    source = Path(path)
    if not source.is_file():
        return {}
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _timing(report_path: Path) -> dict:
    """Extract measure-length findings from a scorepipe report."""
    if not report_path.is_file():
        return {"count": 0, "violations": []}
    data = json.loads(report_path.read_text(encoding="utf-8"))
    violations = [
        {"measure": violation.get("measure"), "detail": violation.get("detail")}
        for violation in data.get("verifier") or []
        if violation.get("code") in ("measure-length", "mscx-measure-length")
    ]
    return {"count": len(violations), "violations": violations}


def _timing_report(baseline: dict | None, reviewed: dict | None) -> dict:
    """Compare measure-length findings; report non-comparability instead of faking deltas."""
    if baseline is None or reviewed is None:
        return {
            "available": False,
            "reason": (
                "timing deltas need both a mechanical baseline report and a reviewed report; "
                "a skipped or failed run is not an empty finding list"
            ),
            "baseline": baseline,
            "reviewed": reviewed,
            "introduced": [],
            "resolved": [],
        }
    before = baseline
    after = reviewed
    before_counts = Counter((item["measure"], item["detail"]) for item in before["violations"])
    after_counts = Counter((item["measure"], item["detail"]) for item in after["violations"])
    introduced = sorted((after_counts - before_counts).elements(), key=lambda item: (item[0], item[1]))
    resolved = sorted((before_counts - after_counts).elements(), key=lambda item: (item[0], item[1]))
    return {
        "available": True,
        "baseline": before,
        "reviewed": after,
        "introduced": [{"measure": measure, "detail": detail} for measure, detail in introduced],
        "resolved": [{"measure": measure, "detail": detail} for measure, detail in resolved],
    }


def _truncation_notes(report_path: Path) -> list[str]:
    if not report_path.is_file():
        return []
    data = json.loads(report_path.read_text(encoding="utf-8"))
    return [
        note
        for entry in data.get("trace") or []
        if entry.get("pass") == "truncate_overfull_mscx"
        for note in entry.get("notes") or []
    ]


def _truncation_performed(operations: list[str]) -> bool:
    """True when a voice was really trimmed, not only normalized.

    The truncation pass reports ``m82 staff 1: 3.25->3 beats; remove 0.25`` for a real edit and
    ``DEFERRED``/``UNRESOLVED`` for the cases it refuses; the duration normalization that runs
    with it reports ``normalized ...``/``converted ...``.  Only the first form changes what the
    user sees, so only that form makes the editable copy the delivery.
    """
    for operation in operations:
        if operation.startswith("m") and " staff " in operation:
            return True
    return False


def _only_overfull_violations(report_path: Path) -> bool:
    """True when every verifier finding is a measure-length complaint.

    The reviewed (untruncated) tree is allowed to report an overfull voice: that is exactly the
    condition the editable copy repairs.  Any other verifier finding still blocks.
    """
    if not report_path.is_file():
        return False
    data = json.loads(report_path.read_text(encoding="utf-8"))
    violations = data.get("verifier") or []
    return bool(violations) and all(
        violation.get("code") in ("measure-length", "mscx-measure-length") for violation in violations
    )


def _verifier_count(report_path: Path) -> int:
    if not report_path.is_file():
        return 0
    data = json.loads(report_path.read_text(encoding="utf-8"))
    return len(data.get("verifier") or [])


def _confidence_map(page_dir: Path, outdir: Path) -> dict:
    """Paint where the OMR reader was unsure.

    This is a reading aid for the human, never a delivery gate: a failure here is recorded in the
    report and does not change ``ready``.  ``page_dir`` is the directory the OMR wrote (``--pages``),
    which is where copisteria puts ``<page>.reading.json``; the page images are looked up next to
    it and in the usual ``<work>/pages`` layout.
    """
    try:
        from scorepipe import confidence
    except Exception as exc:  # noqa: BLE001 - report, never raise, a missing aid is not a failure
        return {"status": "failed", "reason": str(exc)}
    jobs = confidence.plan(
        readings_dir=page_dir,
        page_dirs=[page_dir, page_dir.parent / "pages"],
        work_dir=page_dir.parent,
    )
    if not jobs:
        return {
            "status": "skipped",
            "reason": f"no <page>.reading.json in {page_dir}",
        }
    target = outdir / "review" / "confidence"
    try:
        summary = confidence.review(jobs, target)
    except Exception as exc:  # noqa: BLE001 - same rule as above
        return {"status": "failed", "reason": str(exc)}
    print(
        f"confidence map: {summary['status']}, "
        f"{summary['issues']['total']} symbol(s) worth checking first"
    )
    return {**summary, "dir": str(target)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the page-wise delivery review loop")
    parser.add_argument("pdf")
    parser.add_argument("--pages", required=True, help="OMR page directory")
    parser.add_argument("--facts-dir", help="directory containing agent-page*.json")
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--patches", help="notation patches JSON")
    parser.add_argument(
        "--env",
        help="env.local.json written by preflight.py (default: ./env.local.json or <repo>/env.local.json)",
    )
    parser.add_argument("--musescore", help="MuseScore executable")
    parser.add_argument("--python", help="interpreter for scorepipe")
    parser.add_argument("--title", help="title credit to inject into the reviewed score")
    parser.add_argument("--composer", help="composer credit to inject into the reviewed score")
    parser.add_argument("--compare-golden", help="compare the reviewed MusicXML with a golden file")
    parser.add_argument("--allow-unresolved", action="store_true")
    parser.add_argument("--allow-corrections", action="store_true")
    parser.add_argument("--no-mscz", action="store_true")
    parser.add_argument("--no-pdf", action="store_true")
    parser.add_argument("--no-mechanical", action="store_true", help="skip the no-agent-proposal baseline")
    parser.add_argument(
        "--no-confidence",
        action="store_true",
        help="skip the OMR confidence heat map (it is only an aid, never a delivery gate)",
    )
    parser.add_argument(
        "--no-sheets",
        action="store_true",
        help="skip the measure-level page proof sheets (review/sheets)",
    )
    parser.add_argument("--mechanical-dir", help="baseline directory (default: <outdir>/mechanical)")
    parser.add_argument("--no-forced-truncation", action="store_true", help="skip the forced editable copy")
    parser.add_argument("--forced-dir", help="forced editable directory (default: <outdir>/forced-truncation)")
    parser.add_argument(
        "--allow-combined-pages",
        action="store_true",
        help="allow one facts file to claim multiple pages instead of one file per page",
    )
    parser.add_argument(
        "--skip-facts",
        action="store_true",
        help="no per-page facts yet: skip the page-coverage gate and deliver the mechanical "
        "tree; the report records that no credits/tempo were injected",
    )
    parser.add_argument(
        "--allow-incomplete-delivery",
        action="store_true",
        help="explicitly allow skipped mechanical/forced artifacts (still recorded as interim)",
    )
    args = parser.parse_args(argv)

    if args.env and not Path(args.env).is_file():
        parser.error(f"env file not found: {args.env}")
    env_path = Path(args.env) if args.env else _default_env_file()
    config = _load_config(env_path)
    pdf = Path(args.pdf).resolve()
    page_dir = Path(args.pages).resolve()
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    pdf_sha256 = hashlib.sha256(pdf.read_bytes()).hexdigest()
    facts_dir = Path(args.facts_dir).resolve() if args.facts_dir else outdir / "facts"
    python = (
        args.python
        or os.environ.get("SCOREPIPE_PYTHON")
        or config.get("python")
        or sys.executable
    )
    musescore = find_musescore(
        args.musescore or os.environ.get("MUSESCORE_EXE") or config.get("musescore")
    )
    page_count = _pdf_pages(pdf)
    if page_count is None:
        raise RuntimeError("pdfinfo is required to verify page coverage; install poppler or pass a supported PDF")

    merged = load_pages(page_dir)
    _write(outdir / "score-map.json", score_map(merged.document))
    image_count = _render_pages(pdf, outdir / "pages")

    parts = _parts(facts_dir)
    facts = {"credits": [], "marks": [], "corrections": [], "unresolved": [], "producer": {"pages": []}}
    if parts:
        normalized = [normalize_agent_facts(load_agent_facts(path)) for path in parts]
        problems = []
        for path, payload in zip(parts, normalized):
            problems.extend(f"{path.name}: {problem}" for problem in validate_agent_facts(payload, page_count=page_count))
        if problems:
            _write(
                outdir / "review-report.json",
                {"ready": False, "blockers": problems, "errors": problems},
            )
            for problem in problems:
                print(problem)
            return 1
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
    _write(
        outdir / "facts-corrections.json",
        facts.get("corrections") or [],
    )
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
    patch_problems = []
    if args.patches:
        patch_payload = load_patches(args.patches)
        patch_problems = validate_patches(patch_payload, merged.document, require_acceptance=True)
        if patch_problems:
            blockers.extend(f"patch: {problem}" for problem in patch_problems)

    mechanical = None
    if not args.no_mechanical:
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
        mech_exit = _run(mechanical_command, ROOT)
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
            render_exit = _run([musescore, "-f", "-o", str(mech_pdf), str(mech_mscz)], ROOT)
            mechanical["pdf"] = str(mech_pdf) if mech_pdf.is_file() else None
            mechanical["render_exit"] = render_exit
            if render_exit == 0 and mech_pdf.is_file():
                try:
                    mechanical["rendered_pages"] = _render_pages(mech_pdf, mechanical_dir / "rendered")
                except RuntimeError as exc:
                    mechanical["render_error"] = str(exc)

    if mechanical is not None and not mechanical.get("ready"):
        # The baseline is the *comparison* tree, not a delivery candidate.  A display defect in
        # it (typically an overfull voice the forced copy exists to repair) must not stop the
        # reviewed run: the reviewed verifier below is the real acceptance gate.
        findings.append(
            "mechanical baseline is not verifier-clean "
            f"(pipeline exit {mechanical.get('pipeline_exit')}, "
            f"{len((mechanical.get('timing') or {}).get('violations') or [])} measure-length finding(s)); "
            "kept as the no-facts comparison only"
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
        "covered_pages": covered,
        "missing_pages": missing_pages,
        "facts": {"credits": len(facts.get("credits") or []), "marks": len(facts.get("marks") or [])},
        "facts_skipped": bool(args.skip_facts),
        "unresolved": unresolved,
        "corrections": corrections,
        "patch_count": len((patch_payload or {}).get("patches") or []),
        "mechanical": mechanical,
        "blockers": blockers,
        "artifacts": {"score_map": str(outdir / "score-map.json"), "facts": str(facts_path), "pages": str(outdir / "pages")},
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
    code = _run(command, ROOT)
    pipeline_exit = code
    reviewed_exit = code
    reviewed_only_overfull = _only_overfull_violations(report_json)
    report["pipeline_exit"] = code
    report["artifacts"].update({"musicxml": str(musicxml), "report": str(report_json)})
    if mscz:
        report["artifacts"]["mscz"] = str(mscz)
    timing = _timing_report((mechanical or {}).get("timing"), _timing(report_json))
    report["timing"] = timing
    _write(outdir / "timing-report.json", timing)
    # A reviewed failure is decided after the forced copy: an overfull voice that the editable
    # copy trims is exactly why that copy exists, but any other violation still blocks.
    if code != 0:
        report["ready"] = False

    if mscz and mscz.is_file() and not args.no_pdf and musescore:
        pdf_out = outdir / "score.pdf"
        code = _run([musescore, "-f", "-o", str(pdf_out), str(mscz)], ROOT)
        report["render_exit"] = code
        report["artifacts"]["pdf"] = str(pdf_out)
        if code != 0:
            report["ready"] = False
            report["blockers"].append(f"renderer exited {code}")
        if code == 0 and not args.no_pdf:
            out_pages = outdir / "rendered"
            try:
                count = _render_pages(pdf_out, out_pages)
                report["rendered_after"] = count
                report["artifacts"]["rendered"] = str(out_pages)
            except RuntimeError as exc:
                report["render_error"] = str(exc)
                report["ready"] = False

    if not args.no_confidence:
        report["confidence"] = _confidence_map(page_dir, outdir)
        report["artifacts"]["confidence"] = report["confidence"].get("dir")

    forced = None
    if not args.no_forced_truncation:
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
        else:
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
            forced_exit = _run(forced_command, ROOT)
            operations = _truncation_notes(forced_report)
            unresolved = [note for note in operations if note.startswith("UNRESOLVED")]
            irregular = [note for note in operations if "[explicit-duration]" in note]
            spanner_risks = [note for note in operations if "[spanner-risk:" in note]
            forced_pdf = None
            forced_render_exit = None
            forced_render_error = None
            if forced_mscz.is_file() and not args.no_pdf and musescore:
                forced_pdf = forced_dir / "score.pdf"
                forced_render_exit = _run([musescore, "-f", "-o", str(forced_pdf), str(forced_mscz)], ROOT)
                if forced_render_exit == 0 and forced_pdf.is_file():
                    try:
                        _render_pages(forced_pdf, forced_dir / "rendered")
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
                        report["rendered_after"] = _render_pages(outdir / "score.pdf", outdir / "rendered")
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

    if reviewed_exit != 0:
        tolerated = (
            forced is not None
            and forced.get("ready")
            and _truncation_performed(forced.get("operations") or [])
            and reviewed_only_overfull
        )
        if tolerated:
            report["findings"].append(
                "reviewed (untruncated) tree reported overfull voices only; "
                "the editable delivery trims them"
            )
            report["ready"] = not report["blockers"]
        else:
            report["ready"] = False
            report["blockers"].append(f"pipeline exited {reviewed_exit}")

    if not args.no_sheets:
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
            str(SCRIPTS / "review_sheet.py"),
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
        sheet_exit = _run(sheet_command, ROOT)
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


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
