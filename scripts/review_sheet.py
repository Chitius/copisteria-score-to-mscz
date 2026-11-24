#!/usr/bin/env python3
"""One proof sheet per page: this page's render beside the scan, the same bars coloured.

    python scripts/review_sheet.py --pages out/song/work/copisteria --report out/song/report.json
    python scripts/review_sheet.py --dir review/pages --musescore "C:/.../MuseScore4.exe"

A page is ``<stem>.musicxml`` + ``<stem>.reading.json`` + ``<stem>.png`` in the same directory (or
the scan in a sibling ``pages/`` directory).  Each page is rendered on its own, so the left column
is the same music as the right one; both sides are cut into measures by measured barlines and a
bar that can be lined up gets the same colour and the same global measure number on both.

A page whose bar counts do not agree is left untinted and reported as a failure: an overlay on the
wrong bar is worse than none.  Exit 0 = every page aligned, 1 = some page did not, 2 = bad arguments.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scorepipe import proof_sheet  # noqa: E402
from scorepipe.mscz_export import find_musescore  # noqa: E402


def _stems(directory: Path) -> list[str]:
    return sorted(path.name[: -len(".musicxml")] for path in directory.glob("*.musicxml"))


def build_pages(directory: Path, scan_dir: Path | None) -> list[proof_sheet.SheetPage]:
    """Pair each page MusicXML with its reading, scan and detection cache, in name order."""
    pages: list[proof_sheet.SheetPage] = []
    offset = 0
    for stem in _stems(directory):
        musicxml = directory / f"{stem}.musicxml"
        reading = directory / f"{stem}.reading.json"
        scan = (scan_dir / f"{stem}.png") if scan_dir else (directory / f"{stem}.png")
        if not reading.is_file():
            raise FileNotFoundError(f"{stem}: no {stem}.reading.json next to the page MusicXML")
        if not scan.is_file():
            raise FileNotFoundError(f"{stem}: no page image (looked for {scan})")
        dets = next(iter(sorted(scan.parent.glob(f"{stem}.dets_*.json"))), None)
        if dets is None:
            dets = next(iter(sorted(directory.glob(f"{stem}.dets_*.json"))), None)
        pages.append(
            proof_sheet.SheetPage(
                stem=stem,
                scan=scan,
                musicxml=musicxml,
                reading=reading,
                offset=offset,
                dets=dets,
            )
        )
        offset += proof_sheet.page_measure_count(musicxml)
    return pages


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pages", type=Path, help="directory with <stem>.musicxml and <stem>.reading.json")
    parser.add_argument("--work-dir", type=Path, help="the OMR work dir (uses <work>/copisteria and <work>/pages)")
    parser.add_argument("--scan-dir", type=Path, help="where the page images are, if not beside the MusicXML")
    parser.add_argument("--report", type=Path, help="scorepipe report.json; marks measure-length mismatches with =")
    parser.add_argument("--out", type=Path, help="output directory (default: <pages>/sheet)")
    parser.add_argument("--musescore", help="MuseScore executable (default: discover)")
    parser.add_argument("--red", type=float, default=proof_sheet.RED_MIN, help="score at or above which a bar is red (default 3.0)")
    parser.add_argument("--yellow", type=float, default=proof_sheet.YELLOW_MIN, help="score at which a bar turns yellow (default 1.5)")
    parser.add_argument("--width", type=int, default=proof_sheet.COLUMN_WIDTH, help="width of each column in pixels")
    parser.add_argument(
        "--no-offset",
        action="store_true",
        help="number measures from 1 on every page instead of continuing across the score",
    )
    args = parser.parse_args()

    if args.pages is None and args.work_dir is None:
        parser.error("give --pages or --work-dir")
    if args.yellow < 0 or args.red < args.yellow:
        parser.error("--red must be >= --yellow, and both non-negative")

    directory = args.pages or (args.work_dir / "copisteria")
    if not directory.is_dir():
        parser.error(f"page directory not found: {directory}")
    scan_dir = args.scan_dir or (None if args.pages else args.work_dir / "pages")
    pages = build_pages(directory, scan_dir)
    if args.no_offset:
        pages = [
            proof_sheet.SheetPage(
                stem=page.stem, scan=page.scan, musicxml=page.musicxml, reading=page.reading, dets=page.dets
            )
            for page in pages
        ]
    if not pages:
        parser.error(f"no page MusicXML in {directory}")

    musescore = find_musescore(args.musescore)
    out_dir = args.out or (directory / "sheet")
    summary = proof_sheet.review_sheets(
        pages,
        out_dir,
        musescore=musescore,
        report_path=args.report,
        red_min=args.red,
        yellow_min=args.yellow,
        width=args.width,
    )
    for page in summary["outputs"]["pages"]:
        report = json.loads(Path(page["json"]).read_text(encoding="utf-8"))
        warn = f" ({len(report['warnings'])} warning(s))" if report["warnings"] else ""
        print(
            f"{page['page']}: red {len(report['red'])} / yellow {len(report['yellow'])} "
            f"/ {report['measures']} measure(s){warn}"
        )
    for failure in summary["failures"]:
        print(f"{failure.get('page')}: {failure['code']}: {failure['message']}", file=sys.stderr)
    print(f"status: {summary['status']} ({summary['pages']}/{summary['requested_pages']} pages)")
    print(f"priority list: {summary['outputs']['markdown']}")
    return 1 if summary["status"] == "incomplete" else 0


if __name__ == "__main__":
    sys.exit(main())
