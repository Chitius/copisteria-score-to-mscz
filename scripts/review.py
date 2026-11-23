"""One review loop: page images -> agent facts/patches -> pipeline -> render -> report.

This is the operator entry point for the delivery stage. It deliberately stops when page coverage is
incomplete or when unresolved/corrections need a human decision; `--allow-unresolved` and
`--allow-corrections` are explicit overrides for an interim review.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the page-wise delivery review loop")
    parser.add_argument("pdf")
    parser.add_argument("--pages", required=True, help="OMR page directory")
    parser.add_argument("--facts-dir", help="directory containing agent-page*.json")
    parser.add_argument("--outdir", required=True)
    parser.add_argument("--patches", help="notation patches JSON")
    parser.add_argument("--musescore", help="MuseScore executable")
    parser.add_argument("--python", help="interpreter for scorepipe")
    parser.add_argument("--allow-unresolved", action="store_true")
    parser.add_argument("--allow-corrections", action="store_true")
    parser.add_argument("--no-mscz", action="store_true")
    parser.add_argument("--no-pdf", action="store_true")
    parser.add_argument("--no-mechanical", action="store_true", help="skip the no-agent-proposal baseline")
    parser.add_argument("--mechanical-dir", help="baseline directory (default: <outdir>/mechanical)")
    args = parser.parse_args(argv)

    pdf = Path(args.pdf).resolve()
    page_dir = Path(args.pages).resolve()
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    facts_dir = Path(args.facts_dir).resolve() if args.facts_dir else outdir / "facts"
    python = args.python or os.environ.get("SCOREPIPE_PYTHON") or sys.executable
    musescore = args.musescore or os.environ.get("MUSESCORE_EXE") or shutil.which("MuseScore4.exe")
    page_count = _pdf_pages(pdf)
    if page_count is None:
        page_count = len(_parts(facts_dir))

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
            _write(outdir / "review-report.json", {"ready": False, "errors": problems})
            for problem in problems:
                print(problem)
            return 1
        facts = merge_agent_facts(normalized)
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
    if missing_pages:
        blockers.append(f"missing pages: {missing_pages}")
    if unresolved and not args.allow_unresolved:
        blockers.append(f"{len(unresolved)} unresolved claim(s)")
    if corrections and not args.allow_corrections:
        blockers.append(f"{len(corrections)} proposed correction(s)")
    if image_count != page_count:
        blockers.append(f"rendered {image_count} images for {page_count} pages")

    patch_payload = None
    patch_problems = []
    if args.patches:
        patch_payload = load_patches(args.patches)
        patch_problems = validate_patches(patch_payload, merged.document)
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
        print("+ mechanical baseline (no agent facts or patches)")
        mech_exit = _run(mechanical_command, ROOT)
        mechanical = {
            "dir": str(mechanical_dir),
            "musicxml": str(mech_musicxml),
            "report": str(mech_report),
            "pipeline_exit": mech_exit,
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

    report = {
        "ready": not blockers,
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
        _write(outdir / "review-report.json", report)
        for blocker in blockers:
            print(f"blocked: {blocker}")
        return 2

    musicxml = outdir / "score.musicxml"
    report_json = outdir / "report.json"
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
    _write(outdir / "review-report.json", report)
    print(f"review ready: {report['ready']}")
    print(f"report: {outdir / 'review-report.json'}")
    return pipeline_exit or code or (0 if report["ready"] else 2)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
