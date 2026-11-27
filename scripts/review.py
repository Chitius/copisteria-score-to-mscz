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
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from scorepipe.mscz_export import find_musescore  # noqa: E402
from scorepipe.review import (  # noqa: E402
    ReviewHooks,
    _confidence_map as _confidence_map,
    _default_env_file as _default_env_file_for_root,
    _load_config as _load_config,
    _pdf_pages as _pdf_pages,
    _render_pages as _render_pages,
    _run as _run,
    _timing as _timing,
    _timing_report as _timing_report,
    run_review,
)


def _default_env_file() -> Path | None:
    """``env.local.json`` beside the caller, else beside the repository."""
    return _default_env_file_for_root(ROOT)


def _build_parser() -> argparse.ArgumentParser:
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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.env and not Path(args.env).is_file():
        parser.error(f"env file not found: {args.env}")
    env_path = Path(args.env) if args.env else _default_env_file()
    config = _load_config(env_path)
    python = (
        args.python
        or os.environ.get("SCOREPIPE_PYTHON")
        or config.get("python")
        or sys.executable
    )
    musescore = find_musescore(
        args.musescore or os.environ.get("MUSESCORE_EXE") or config.get("musescore")
    )
    hooks = ReviewHooks(
        run=_run,
        pdf_pages=_pdf_pages,
        render_pages=_render_pages,
        find_musescore=find_musescore,
        confidence_map=_confidence_map,
    )
    return run_review(
        args,
        python=python,
        musescore=musescore,
        root=ROOT,
        scripts_dir=SCRIPTS,
        hooks=hooks,
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
