#!/usr/bin/env python3
"""Paint where the OMR reader was unsure, one page at a time.

    python scripts/review_confidence.py --work-dir out/song/work
    python scripts/review_confidence.py --reading a.reading.json --page a.png --out review

Reads copisteria's ``<page>.reading.json`` (per-symbol ``det``/``v``/``p``/``ev``), ranks the
symbols by how much they deserve a second look and paints each scan: red where the context
rewrote the detector's choice, orange where the symbol's existence is uncertain, amber where an
attribute probability is low, blue for the rest (position reference only).

With ``--rendered-dir`` the render is put beside the painted scan.  Pairing is by stem by
default; ``--pair-rendered-order`` pairs the sorted pages positionally, which is only correct
when the render is paginated like the scan.

Exit codes: 0 = every requested page was painted (with or without findings), 1 = incomplete
(a page was skipped or failed), 2 = bad arguments.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scorepipe import confidence  # noqa: E402
from scorepipe.console import harden_stdout  # noqa: E402

harden_stdout()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--work-dir", type=Path, help="the OMR work directory (reads <work>/copisteria/*.reading.json)")
    parser.add_argument("--readings", type=Path, help="a directory of *.reading.json")
    parser.add_argument("--reading", type=Path, action="append", default=[], help="one reading file; repeatable")
    parser.add_argument("--page-dir", type=Path, action="append", default=[], help="where the page images are")
    parser.add_argument("--page", type=Path, help="the page image, for a single reading")
    parser.add_argument("--rendered-dir", type=Path, help="rendered pages to put beside the scan")
    parser.add_argument(
        "--pair-rendered-order",
        action="store_true",
        help="pair rendered pages positionally instead of by file stem",
    )
    parser.add_argument("--out", type=Path, help="output directory (default: <work>/review or review)")
    parser.add_argument("--top", type=int, default=40, help="numbered boxes per page (default 40)")
    parser.add_argument("--crops", type=int, default=8, help="context crops per page (default 8, 0 = none)")
    parser.add_argument(
        "--show-low",
        action="store_true",
        help="also outline normally-read symbols (blue); off by default because they outline whole systems",
    )
    args = parser.parse_args()

    if args.top < 0 or args.crops < 0:
        parser.error("--top and --crops cannot be negative")

    page_dirs = list(args.page_dir)
    if args.page is not None:
        page_dirs.append(args.page.parent)
    jobs = confidence.plan(
        readings_dir=args.readings,
        reading_paths=args.reading,
        page_dirs=page_dirs,
        rendered_dir=args.rendered_dir,
        work_dir=args.work_dir,
        positional_rendered=args.pair_rendered_order,
    )
    if args.page is not None and len(jobs) == 1:
        jobs = [confidence.PageJob(stem=jobs[0].stem, reading=jobs[0].reading, page=args.page, rendered=jobs[0].rendered)]
    if not jobs:
        parser.error("no reading.json found: use --work-dir, --readings or --reading")

    out_dir = Path(args.out) if args.out else (Path(args.work_dir) / "review" if args.work_dir else Path("review"))
    summary = confidence.review(jobs, out_dir, top=args.top, crops=args.crops, show_low=args.show_low)

    for page in summary["outputs"]["pages"]:
        print(f"{page['page']}: {Path(page['image']).name}")
    for skipped in summary["skipped_pages"]:
        print(f"skipped {skipped['page']}: {skipped['reason']}", file=sys.stderr)
    for failure in summary["failures"]:
        print(f"failed {failure['page']}: {failure['message']}", file=sys.stderr)
    print(f"status: {summary['status']} ({summary['pages']}/{summary['requested_pages']} pages)")
    print(f"out: {out_dir}")
    return 1 if summary["status"] == "incomplete" else 0


if __name__ == "__main__":
    sys.exit(main())
