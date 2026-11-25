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

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from scorepipe.discovery import find_musescore as _discover_musescore
except Exception:  # pragma: no cover - the scorepipe import is probed separately
    _discover_musescore = None


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
    if _discover_musescore is not None:
        located = _discover_musescore(explicit)
        return Path(located) if located else None
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


def _pdf_pages(pdf: Path) -> int | None:
    from shutil import which

    binary = which("pdfinfo")
    if not binary:
        return None
    completed = subprocess.run(
        [binary, str(pdf)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    for line in completed.stdout.splitlines():
        if line.lower().startswith("pages:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError:
                return None
    return None


def _default_env_file() -> Path | None:
    """``env.local.json`` beside the caller, else beside the repository.

    ``preflight.py --save`` writes it once; reading it back here is what makes the documented
    two-step quick start work without repeating every path on every command.
    """
    for candidate in (Path.cwd() / "env.local.json", ROOT / "env.local.json"):
        if candidate.is_file():
            return candidate
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PDF -> OMR -> scorepipe -> MuseScore delivery")
    parser.add_argument("pdf", help="input score PDF")
    parser.add_argument("--outdir", help="delivery directory (default: <pdf>_deliver)")
    parser.add_argument("--work-dir", help="OMR work directory (default: <outdir>/work)")
    parser.add_argument(
        "--env",
        help="env.local.json written by preflight.py (default: ./env.local.json or <repo>/env.local.json)",
    )
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
    parser.add_argument("--force", action="store_true", help="replace existing delivery artifacts")
    args = parser.parse_args(argv)

    env_path = args.env or _default_env_file()
    config = _load_config(str(env_path) if env_path else None)
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

    expected_pages = _pdf_pages(pdf)
    actual_pages = len(list(page_dir.glob("*.musicxml")))
    if expected_pages is not None and actual_pages != expected_pages:
        raise RuntimeError(
            f"page coverage mismatch: PDF has {expected_pages} pages, OMR wrote {actual_pages} page MusicXML files"
        )

    musicxml = outdir / "score.musicxml"
    report = outdir / "report.json"
    existing = [path for path in (musicxml, report, outdir / "score.mscz", outdir / "score.pdf") if path.exists()]
    if existing and not args.force:
        parser.error("output already exists; pass --force to replace: " + ", ".join(str(path) for path in existing))
    for stale in (musicxml, report, outdir / "score.mscz", outdir / "score.pdf"):
        stale.unlink(missing_ok=True)
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
    if args.patches:
        score_command.extend(["--patches", str(Path(args.patches).resolve())])
    # Collect every credit into one facts file, in the order the title frame reads top to bottom.
    # Passing --title/--composer on the command line *and* --arranger through a facts file used to
    # interleave the two channels (arranger first), which moved the MuseScore title frame after
    # measure 1.  One file also makes delivery.json's audit trail show all four credits.
    facts_payload = {}
    if args.facts:
        facts_payload = json.loads(Path(args.facts).read_text(encoding="utf-8-sig"))
    credits = facts_payload.setdefault("credits", [])
    for credit_type, text in (
        ("title", args.title),
        ("composer", args.composer),
        ("arranger", args.arranger),
    ):
        if text:
            credits.append({"type": credit_type, "text": text})
    if credits:
        order = {"title": 0, "subtitle": 1, "composer": 2, "arranger": 3, "transcriber": 3, "lyricist": 4}
        credits.sort(key=lambda credit: order.get((credit.get("type") or "title").strip(), 5))
        facts_path = outdir / "facts.json"
        facts_path.write_text(
            json.dumps(facts_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        score_command.extend(["--facts", str(facts_path)])

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
        "skill": "copisteria-score-to-mscz",
        "reviewed": False,
        "delivery": "pipeline draft; run scripts/review.py before delivery",
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
