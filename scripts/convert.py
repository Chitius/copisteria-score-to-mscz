"""End-to-end skill wrapper: PDF -> OMR pages -> scorepipe -> mscz/pdf.

This is intentionally a thin orchestrator. The OMR engine stays external and the pipeline stays
inside `scorepipe`; this script records the commands and artifacts so a delivery is auditable.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")


def _run(command: list[str], cwd: Path, tolerate: bool = False) -> tuple[int, str]:
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
    if completed.returncode != 0 and not tolerate:
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(map(str, command))}")
    return completed.returncode, output


def _load_config(path: str | None) -> dict:
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _resolve_page_dir(work: Path) -> Path | None:
    expected = work / "copisteria"
    if expected.is_dir() and list(expected.glob("*.musicxml")):
        return expected
    groups: dict[Path, list[Path]] = {}
    for page in work.rglob("*.musicxml"):
        groups.setdefault(page.parent, []).append(page)
    if not groups:
        return None
    return max(groups, key=lambda parent: len(groups[parent]))


def _find_musescore(explicit: str | None) -> Path | None:
    candidates = [explicit, os.environ.get("MUSESCORE_EXE")]
    for name in ("MuseScore4.exe", "MuseScore4", "mscore4", "musescore4"):
        from shutil import which

        found = which(name)
        if found:
            candidates.append(found)
    candidates.extend(
        [
            r"C:\Program Files\MuseScore 4\bin\MuseScore4.exe",
            r"C:\Program Files\MuseScore 4\bin\mscore4.exe",
            "/Applications/MuseScore 4.app/Contents/MacOS/mscore",
        ]
    )
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PDF -> OMR -> scorepipe -> MuseScore delivery")
    parser.add_argument("pdf", help="input score PDF")
    parser.add_argument("--outdir", help="delivery directory (default: <pdf>_deliver)")
    parser.add_argument("--work-dir", help="OMR work directory (default: <outdir>/work)")
    parser.add_argument("--env", help="env.local.json written by preflight.py")
    parser.add_argument("--python", help="interpreter that imports scorepipe")
    parser.add_argument("--omr-python", help="interpreter that imports copisteria/music21")
    parser.add_argument("--repo", help="copisteria source checkout")
    parser.add_argument("--converter", help="copisteria-to-musicxml/scripts/convert.py")
    parser.add_argument("--musescore", help="MuseScore executable")
    parser.add_argument("--pages", help="reuse an existing page directory; skip OMR")
    parser.add_argument("--facts", help="facts JSON for credits/marks")
    parser.add_argument("--patches", help="constrained notation patches JSON (ottava prototype)")
    parser.add_argument("--title")
    parser.add_argument("--composer")
    parser.add_argument("--arranger")
    parser.add_argument("--no-mscz", action="store_true", help="stop after MusicXML")
    parser.add_argument("--no-pdf", action="store_true", help="do not render a review PDF")
    parser.add_argument("--max-rounds", type=int, default=32)
    args = parser.parse_args(argv)

    config = _load_config(args.env)
    pdf = Path(args.pdf).expanduser().resolve()
    if not pdf.is_file():
        parser.error(f"PDF not found: {pdf}")
    outdir = Path(args.outdir or (pdf.with_name(pdf.stem + "_deliver"))).resolve()
    work = Path(args.work_dir or (outdir / "work")).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    pipeline_python = args.python or config.get("python") or os.environ.get("SCOREPIPE_PYTHON") or sys.executable
    omr_python = args.omr_python or config.get("omr_python") or os.environ.get("COPISTERIA_PYTHON") or pipeline_python
    repo = args.repo or config.get("copisteria_repo") or os.environ.get("COPISTERIA_REPO")
    converter = args.converter or config.get("converter") or os.environ.get("COPISTERIA_CONVERTER")
    musescore = _find_musescore(args.musescore or config.get("musescore"))

    page_dir: Path | None
    omr_command: list[str] | None = None
    started = time.time()
    if args.pages:
        page_dir = Path(args.pages).resolve()
        if not page_dir.is_dir():
            parser.error(f"page directory not found: {page_dir}")
    else:
        if not repo or not converter:
            parser.error("OMR needs --repo and --converter (or an env file from preflight.py)")
        omr_command = [
            omr_python,
            converter,
            str(pdf),
            "--repo",
            repo,
            "--python",
            omr_python,
            "--work-dir",
            str(work),
            "--no-mscz",
            "--no-credits",
            "--no-marks",
            "--no-auto-facts",
            "--no-text-check",
        ]
        code, _ = _run(omr_command, cwd=Path(__file__).resolve().parents[1], tolerate=True)
        page_dir = _resolve_page_dir(work)
        if page_dir is None:
            raise RuntimeError(f"OMR produced no page MusicXML under {work} (exit {code})")
        if code != 0:
            print(f"warning: OMR exited {code} after writing {page_dir}; continuing with page files")

    musicxml = outdir / "score.musicxml"
    report = outdir / "report.json"
    score_command = [
        pipeline_python,
        "-m",
        "scorepipe.cli",
        str(page_dir),
        "-o",
        str(musicxml),
        "--report",
        str(report),
        "--max-rounds",
        str(args.max_rounds),
    ]
    if args.facts:
        score_command.extend(["--facts", str(Path(args.facts).resolve())])
    if args.patches:
        score_command.extend(["--patches", str(Path(args.patches).resolve())])
    if args.title:
        score_command.extend(["--title", args.title])
    if args.composer:
        score_command.extend(["--composer", args.composer])
    if args.arranger:
        facts_payload = {}
        if args.facts:
            facts_payload = json.loads(Path(args.facts).read_text(encoding="utf-8-sig"))
        facts_payload.setdefault("credits", []).append(
            {"type": "arranger", "text": args.arranger}
        )
        arranger_facts = outdir / "facts.json"
        arranger_facts.write_text(
            json.dumps(facts_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if "--facts" in score_command:
            index = score_command.index("--facts")
            score_command[index + 1] = str(arranger_facts)
        else:
            score_command.extend(["--facts", str(arranger_facts)])

    mscz = None if args.no_mscz else outdir / "score.mscz"
    if mscz is not None:
        score_command.extend(["--mscz-out", str(mscz)])
        if musescore:
            score_command.extend(["--musescore", str(musescore)])
    pipeline_exit, _ = _run(score_command, cwd=Path(__file__).resolve().parents[1], tolerate=True)

    pdf_out = None
    render_exit = None
    if mscz is not None and mscz.is_file() and not args.no_pdf and musescore:
        pdf_out = outdir / "score.pdf"
        render_exit, _ = _run(
            [musescore, "-f", "-o", str(pdf_out), str(mscz)],
            cwd=Path(__file__).resolve().parents[1],
            tolerate=True,
        )

    manifest = {
        "skill": "copisteria-to-mscz",
        "ready": pipeline_exit == 0 and (render_exit is None or render_exit == 0),
        "pipeline_exit": pipeline_exit,
        "render_exit": render_exit,
        "started": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(started)),
        "pdf": str(pdf),
        "outdir": str(outdir),
        "work_dir": str(work),
        "page_dir": str(page_dir),
        "omr_command": omr_command,
        "pipeline_command": score_command,
        "musescore": str(musescore) if musescore else None,
        "artifacts": {
            "musicxml": str(musicxml) if musicxml.exists() else None,
            "mscz": str(mscz) if mscz and mscz.exists() else None,
            "pdf": str(pdf_out) if pdf_out and pdf_out.exists() else None,
            "report": str(report) if report.exists() else None,
        },
    }
    (outdir / "delivery.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"musicxml: {musicxml}")
    if mscz and mscz.exists():
        print(f"mscz:     {mscz}")
    if pdf_out and pdf_out.exists():
        print(f"pdf:      {pdf_out}")
    print(f"report:   {report}")
    print(f"manifest: {outdir / 'delivery.json'}")
    return pipeline_exit or render_exit or 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
