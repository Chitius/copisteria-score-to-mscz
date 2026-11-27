"""Confidence heat-map planning, per-page report generation, and markdown summary."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from .paint import _compose, _crops, _paint
from .scoring import KINDS, classify, summarise


@dataclass(frozen=True)
class PageJob:
    """One page to paint: its reading, the scan it refers to, and an optional render to compare."""

    stem: str
    reading: Path
    page: Path | None = None
    rendered: Path | None = None


def plan(
    *,
    readings_dir: Path | None = None,
    reading_paths: Iterable[Path] = (),
    page_dirs: Iterable[Path] = (),
    rendered_dir: Path | None = None,
    work_dir: Path | None = None,
    positional_rendered: bool = False,
) -> list[PageJob]:
    """Find reading/page pairs.

    Page lookup is by identical stem in the reading directory, then in ``page_dirs``, then in
    ``work_dir/pages`` and ``work_dir``.  A rendered page is matched by stem unless
    ``positional_rendered`` says the caller knows the render is paginated like the scan (same
    count, same order), which is the only reason that pairing is offered.
    """
    readings: list[Path] = list(reading_paths)
    if readings_dir is not None:
        readings.extend(sorted(Path(readings_dir).glob("*.reading.json")))
    if work_dir is not None:
        work = Path(work_dir)
        candidate = work / "copisteria"
        if candidate.is_dir():
            readings.extend(sorted(candidate.glob("*.reading.json")))
        elif not readings:
            readings.extend(sorted(work.glob("*.reading.json")))

    search_dirs = [Path(reading).parent for reading in readings]
    search_dirs.extend(Path(directory) for directory in page_dirs)
    if work_dir is not None:
        search_dirs.extend([Path(work_dir) / "pages", Path(work_dir)])

    rendered_paths: list[Path] = []
    if rendered_dir is not None and Path(rendered_dir).is_dir():
        rendered_paths = sorted(Path(rendered_dir).glob("*.png"))

    jobs: list[PageJob] = []
    seen: set[Path] = set()
    for reading in readings:
        reading = Path(reading)
        if reading in seen:
            continue
        seen.add(reading)
        stem = reading.name[: -len(".reading.json")]
        page = _find_page(stem, search_dirs)
        rendered = None
        if rendered_paths and not positional_rendered:
            rendered = next((path for path in rendered_paths if path.stem == stem), None)
        jobs.append(PageJob(stem=stem, reading=reading, page=page, rendered=rendered))

    if positional_rendered and rendered_paths:
        if len(rendered_paths) == len(jobs):
            jobs = [
                PageJob(stem=job.stem, reading=job.reading, page=job.page, rendered=rendered)
                for job, rendered in zip(jobs, rendered_paths)
            ]
        else:
            raise ValueError(
                f"positional pairing needs one rendered page per reading "
                f"({len(jobs)} readings, {len(rendered_paths)} rendered pages)"
            )
    return jobs


def _find_page(stem: str, directories: Iterable[Path]) -> Path | None:
    seen: set[Path] = set()
    for directory in directories:
        directory = Path(directory)
        if directory in seen:
            continue
        seen.add(directory)
        candidate = directory / f"{stem}.png"
        if candidate.is_file():
            return candidate
    return None


def load_reading(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_page(
    job: PageJob,
    out_dir: Path,
    *,
    top: int = 40,
    crops: int = 8,
    show_low: bool = False,
) -> dict:
    """Paint one page and write its image, JSON and crops; return the page report.

    ``top`` limits only the *numbered* boxes on the image.  The JSON keeps every positive score,
    including symbols that have no box (a suspect the reader cannot point at is still a suspect).
    ``show_low`` also outlines the normally-read symbols; they are pure position reference and are
    hidden by default because on a dense page they outline whole systems and hide the signal.
    """
    from PIL import Image

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if job.page is None:
        raise FileNotFoundError(f"no page image for {job.stem}")
    data = load_reading(job.reading)
    tokens = data.get("tokens") or {}
    changes = {int(entry["sym"]): entry for entry in data.get("changes") or []}

    page = Image.open(job.page).convert("RGB")
    width, height = page.size

    rows: list[dict] = []
    for key, token in tokens.items():
        symbol = int(key)
        result = summarise(token)
        change = changes.get(symbol) or {}
        box = change.get("box")
        rows.append(
            {
                "symbol": symbol,
                "cls": (token.get("cls") or {}).get("v"),
                "box": [round(float(value), 1) for value in box] if box else None,
                "staff": change.get("staff"),
                "bar": change.get("bar"),
                "kind": classify(result["score"], result["reasons"]),
                "score": result["score"],
                "reasons": result["reasons"],
            }
        )
    ranked = sorted(rows, key=lambda row: row["score"], reverse=True)
    all_suspects = [row for row in ranked if row["score"] > 0]
    suspects = [row for row in all_suspects if row["box"]][: max(0, top)]

    annotated = _paint(page, rows, suspects, show_low=show_low)
    image_path = out_dir / f"{job.stem}.review.png"
    composed = None
    if job.rendered is not None and Path(job.rendered).is_file():
        composed = _compose(Path(job.rendered), annotated)
        image_path = out_dir / f"{job.stem}.compare.png"
    annotated.save(out_dir / f"{job.stem}.review.png")
    if composed is not None:
        composed.save(image_path)

    crop_paths = _crops(annotated, suspects, out_dir, job.stem, crops)

    counts = {kind: sum(1 for row in rows if row["kind"] == kind) for kind in KINDS}
    suspect_counts = {kind: sum(1 for row in all_suspects if row["kind"] == kind) for kind in KINDS}
    suspect_counts.update(
        {
            "total": len(all_suspects),
            "with_box": sum(1 for row in all_suspects if row["box"]),
            "without_box": sum(1 for row in all_suspects if not row["box"]),
        }
    )
    report = {
        "reading": str(job.reading),
        "page_image": str(job.page),
        "rendered_page": str(job.rendered) if job.rendered else None,
        "page_stem": job.stem,
        "size": [width, height],
        "symbols": len(tokens),
        "context_changes": len(changes),
        "counts": counts,
        "suspect_counts": suspect_counts,
        "note": (
            "staff and bar are page-local indices from the reading (staff counts from 0, bar is "
            "the number of that staff's barline; both are 0-based); box is in page pixels and is "
            "the reliable part. The score orders attention, it is not a probability of error."
        ),
        "suspects": suspects,
        "all_suspects": all_suspects,
        "outputs": {
            "image": str(image_path),
            "annotated": str(out_dir / f"{job.stem}.review.png"),
            "json": str(out_dir / f"{job.stem}.review.json"),
            "crops": crop_paths,
        },
    }
    (out_dir / f"{job.stem}.review.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return report


def overall_status(issue_count: int, incomplete: bool) -> str:
    """Failures dominate findings: a partial clean-looking review is not clean."""
    if incomplete:
        return "incomplete"
    return "complete_with_issues" if issue_count else "complete_no_issues"


def review(
    jobs: Sequence[PageJob], out_dir: Path, *, top: int = 40, crops: int = 8, show_low: bool = False
) -> dict:
    """Paint every page that has one, then write ``review.md`` and the summary JSON."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    reports: list[dict] = []
    skipped: list[dict] = []
    failures: list[dict] = []
    for job in jobs:
        if job.page is None:
            skipped.append({"page": job.stem, "reading": str(job.reading), "reason": "no page image"})
            continue
        try:
            reports.append(build_page(job, out_dir, top=top, crops=crops, show_low=show_low))
        except Exception as error:  # noqa: BLE001 - one bad page must not hide the others
            failures.append({"page": job.stem, "code": "page_failed", "message": str(error)})

    issue_counts = {kind: sum(report["suspect_counts"][kind] for report in reports) for kind in KINDS}
    issue_total = sum(issue_counts.values())
    status = overall_status(issue_total, bool(failures or skipped))
    summary = {
        "status": status,
        "pages": len(reports),
        "requested_pages": len(jobs),
        "skipped": len(skipped),
        "skipped_pages": skipped,
        "failures": failures,
        "failure_count": len(failures),
        "issues": {"total": issue_total, **issue_counts},
        "outputs": {
            "markdown": str(out_dir / "review.md"),
            "summary": str(out_dir / "summary.json"),
            "pages": [{"page": report["page_stem"], **report["outputs"]} for report in reports],
        },
    }
    render_markdown(reports, out_dir, summary)
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return summary


def render_markdown(reports: Sequence[dict], out_dir: Path, summary: dict | None = None) -> None:
    total = sum(report["symbols"] for report in reports)
    flagged = sum(len(report["all_suspects"]) for report in reports)
    if summary is None:
        summary = {"status": overall_status(flagged, False), "failures": [], "skipped_pages": []}
    lines = ["# Where to look first", "", f"Status: **{summary['status']}**.", ""]
    if summary["status"] == "incomplete":
        lines.append(
            "This review is incomplete; the results below cover only the pages that were read. "
            "Do not conclude that the rest is clean."
        )
        lines.append("")
    if total:
        changes = sum(report["context_changes"] for report in reports)
        lines.append(
            f"{len(reports)} page(s), {total} symbols; {changes} context override(s), "
            f"{flagged} symbol(s) worth checking first ({flagged / total:.1%})."
        )
    else:
        lines.append("No page with symbols was processed.")
    lines.append("")
    lines.append("The score orders attention, it is not a probability of error; judge against the scan.")
    lines.append("")
    for failure in summary.get("failures", []):
        lines.append(f"- failed ({failure.get('page', 'global')}): {failure['message']}")
    for skipped in summary.get("skipped_pages", []):
        lines.append(f"- skipped ({skipped['page']}): {skipped['reason']}")
    if summary.get("failures") or summary.get("skipped_pages"):
        lines.append("")
    for report in reports:
        lines.append(f"## {report['page_stem']}")
        lines.append("")
        lines.append(
            f"Image: `{Path(report['outputs']['image']).name}`; "
            f"numbers: `{report['page_stem']}.review.json`."
        )
        lines.append("")
        if not report["all_suspects"]:
            lines.append(
                "No symbol scored above zero."
                if summary["status"] != "incomplete"
                else "No symbol scored above zero, but the review is incomplete."
            )
            lines.append("")
            continue
        for index, row in enumerate(report["all_suspects"], start=1):
            bits = [
                f"{reason['head']}="
                f"{reason.get('value') if reason.get('value') is not None else reason.get('p')}"
                for reason in row["reasons"][:4]
            ]
            where = ""
            if row["bar"] is not None:
                where = f", staff {row['staff'] + 1} bar {row['bar'] + 1}"
            lines.append(
                f"{index}. `{row['cls']}` score {row['score']} ({row['kind']})"
                + where
                + (f", box {row['box']}" if row["box"] else ", no box")
                + ("; " + "; ".join(bits) if bits else "")
            )
        lines.append("")
    Path(out_dir, "review.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
