"""One review loop: page images -> agent facts/patches -> pipeline -> render -> report.

This is the operator entry point for the delivery stage. It deliberately stops when page coverage is
incomplete or when unresolved/corrections need a human decision; `--allow-unresolved` and
`--allow-corrections` are explicit overrides for an interim review.
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
    before = baseline or {"count": 0, "violations": []}
    after = reviewed or {"count": 0, "violations": []}
    before_counts = Counter((item["measure"], item["detail"]) for item in before["violations"])
    after_counts = Counter((item["measure"], item["detail"]) for item in after["violations"])
    introduced = sorted((after_counts - before_counts).elements(), key=lambda item: (item[0], item[1]))
    resolved = sorted((before_counts - after_counts).elements(), key=lambda item: (item[0], item[1]))
    return {
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


def _verifier_count(report_path: Path) -> int:
    if not report_path.is_file():
        return 0
    data = json.loads(report_path.read_text(encoding="utf-8"))
    return len(data.get("verifier") or [])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the page-wise delivery review loop")
    parser.add_argument("pdf")
    parser.add_argument("--pages", required=True, help="OMR page directory")
    parser.add_argument("--facts-dir", help="directory containing agent-page*.json")
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--patches", help="notation patches JSON")
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
    parser.add_argument("--mechanical-dir", help="baseline directory (default: <outdir>/mechanical)")
    parser.add_argument("--no-forced-truncation", action="store_true", help="skip the forced editable copy")
    parser.add_argument("--forced-dir", help="forced editable directory (default: <outdir>/forced-truncation)")
    parser.add_argument(
        "--allow-incomplete-delivery",
        action="store_true",
        help="explicitly allow skipped mechanical/forced artifacts (still recorded as interim)",
    )
    args = parser.parse_args(argv)

    pdf = Path(args.pdf).resolve()
    page_dir = Path(args.pages).resolve()
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    pdf_sha256 = hashlib.sha256(pdf.read_bytes()).hexdigest()
    facts_dir = Path(args.facts_dir).resolve() if args.facts_dir else outdir / "facts"
    python = args.python or os.environ.get("SCOREPIPE_PYTHON") or sys.executable
    musescore = find_musescore(args.musescore or os.environ.get("MUSESCORE_EXE"))
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
    artifacts_missing = []
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
        blockers.append("mechanical baseline did not complete cleanly")

    report = {
        "ready": not blockers,
        "interim": bool(overrides or artifacts_missing),
        "overrides": overrides,
        "artifacts_missing": artifacts_missing,
        "source_pdf": {"path": str(pdf), "sha256": pdf_sha256},
        "page_count": page_count,
        "rendered_pages": image_count,
        "covered_pages": covered,
        "missing_pages": missing_pages,
        "facts": {"credits": len(facts.get("credits") or []), "marks": len(facts.get("marks") or [])},
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
    report["pipeline_exit"] = code
    report["artifacts"].update({"musicxml": str(musicxml), "report": str(report_json)})
    if mscz:
        report["artifacts"]["mscz"] = str(mscz)
    timing = _timing_report((mechanical or {}).get("timing"), _timing(report_json))
    report["timing"] = timing
    _write(outdir / "timing-report.json", timing)
    if code != 0:
        report["ready"] = False
        report["blockers"].append(f"pipeline exited {code}")

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
            forced_pdf = None
            forced_render_exit = None
            if forced_mscz.is_file() and not args.no_pdf and musescore:
                forced_pdf = forced_dir / "score.pdf"
                forced_render_exit = _run([musescore, "-f", "-o", str(forced_pdf), str(forced_mscz)], ROOT)
                if forced_render_exit == 0 and forced_pdf.is_file():
                    try:
                        _render_pages(forced_pdf, forced_dir / "rendered")
                    except RuntimeError as exc:
                        report["forced_truncation"] = {"render_error": str(exc)}
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
                "operations": operations,
                "unresolved": unresolved,
                "verifier_count": _verifier_count(forced_report),
            }
            forced["ready"] = (
                forced_exit == 0
                and forced["verifier_count"] == 0
                and not unresolved
                and forced_mscz.is_file()
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
            "mechanical": mechanical,
            "forced_truncation": forced,
            "blockers": report.get("blockers") or [],
        },
    )
    print(f"review ready: {report['ready']}")
    print(f"report: {outdir / 'review-report.json'}")
    return pipeline_exit or code or (0 if report["ready"] else 2)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
