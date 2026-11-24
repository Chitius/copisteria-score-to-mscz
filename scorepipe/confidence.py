"""Where the OMR reader was unsure: rank the symbols, paint the page, compare with the render.

copisteria's ``<page>.reading.json`` records, per symbol and per attribute, the detector's own
choice (``det``), the choice the context settled on (``v``), a probability (``p``) and how many
nats of evidence the context added (``ev``).  :func:`summarise` turns those numbers into a
"look here first" score, :func:`build_page` paints the scan with boxes coloured by *why* a symbol
is suspect, and a rendered page can be put beside it as a comparison.

Two rules keep this honest:

* the score orders a human's attention, it is not a calibrated error probability;
* a context override is not an error.  The context usually repairs the detector, so an override
  means "worth checking", not "wrong".  That is why the red class is named ``changed`` and not
  ``bad``.

The colours are stable across pages so a reader learns them once: red ``changed`` (the context
rewrote the detector's choice), orange ``existence`` (the reader was unsure the symbol is there
at all), amber ``attribute`` (an attribute probability is low), blue ``low`` (read normally, kept
only as a position reference).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

HEAD_WEIGHTS = {
    "cls": 2.0,
    "pos": 1.5,
    "voice": 1.0,
    "dots": 0.8,
    "onset_p": 1.0,
    "alter": 0.5,
    "grace": 0.5,
    "tup": 0.5,
}
LOW_P = 0.80
VERY_LOW_P = 0.55
# How much a context override matters depends on the head.  A reassigned voice or a re-read dot
# is routine (the model corrects these constantly and is usually right); a changed class, or a
# symbol the model decided does not exist, is not.
CHANGE_WEIGHT = {
    "cls": 3.0,
    "pos": 2.0,
    "alter": 1.5,
    "tup": 1.5,
    "dots": 1.0,
    "voice": 1.0,
    "grace": 1.0,
    "onset_p": 1.0,
}

COLOURS = {
    "changed": (214, 39, 40),
    "existence": (255, 165, 0),
    "attribute": (255, 196, 0),
    "low": (120, 170, 220),
}
KINDS = ("changed", "existence", "attribute", "low")


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------


def summarise(token: dict) -> dict:
    """Score one symbol from its per-head readings and keep the numbers that produced it."""
    reasons: list[dict] = []
    score = 0.0

    real = token.get("real") or {}
    p_real = real.get("p")
    if isinstance(p_real, float):
        if 0.15 <= p_real <= 0.85:
            score += 2.0
            reasons.append({"head": "real", "value": p_real, "det": real.get("det"), "ev": real.get("ev")})
        elif p_real < 0.5:
            reasons.append({"head": "real", "value": p_real, "det": real.get("det"), "ev": real.get("ev")})

    for head, weight in HEAD_WEIGHTS.items():
        entry = token.get(head)
        if head == "onset_p":
            p = token.get("onset_p")
            det = None
            value = None
            evidence = None
        elif isinstance(entry, dict):
            p = entry.get("p")
            det = entry.get("det")
            value = entry.get("v")
            evidence = entry.get("ev")
        else:
            continue
        if not isinstance(p, float):
            continue
        changed = det is not None and value is not None and det != value
        if changed:
            score += CHANGE_WEIGHT.get(head, 1.0)
        if p < LOW_P:
            score += weight * (1.0 - p / LOW_P)
        if p < VERY_LOW_P:
            score += weight * 0.5
        if changed or p < LOW_P:
            reasons.append(
                {"head": head, "value": value, "p": p, "det": det, "ev": evidence, "changed": changed}
            )

    for head in ("chord", "tie"):
        p = token.get(head)
        if isinstance(p, float) and 0.2 < p < 0.8:
            score += 1.0
            reasons.append({"head": head, "value": p})

    return {"score": round(score, 3), "reasons": reasons}


def classify(score: float, reasons: Sequence[dict]) -> str:
    """Name *why* a symbol is suspect; the order of the tests is the precedence.

    ``changed`` is a real override (the reader's own choice differed from the final one).  A low
    probability on an unchanged attribute is *not* an override -- the old skill keyed on "a ``det``
    value exists", which made every low-probability attribute red and left the amber class empty.
    """
    if any(reason.get("changed") for reason in reasons):
        return "changed"
    if any(reason["head"] == "real" for reason in reasons):
        return "existence"
    if score >= 2.0:
        return "attribute"
    return "low"


# ---------------------------------------------------------------------------
# pages
# ---------------------------------------------------------------------------


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
    from PIL import Image, ImageDraw

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


def _paint(page, rows: Sequence[dict], suspects: Sequence[dict], *, show_low: bool = False):
    from PIL import Image, ImageDraw

    width, height = page.size
    overlay = Image.new("RGBA", page.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    line = max(1, round(max(width, height) / 900))
    for row in rows:
        if not row["box"]:
            continue
        if row["kind"] == "low" and not show_low:
            continue
        colour = COLOURS[row["kind"]]
        draw.rectangle(
            tuple(row["box"]),
            outline=colour + (110 if row["kind"] == "low" else 235,),
            width=line,
        )
    base_font = max(14, round(width / 70))
    for index, row in enumerate(suspects, start=1):
        x0, y0, x1, y1 = row["box"]
        colour = COLOURS[row["kind"]]
        # A fixed thick outline fills a small box solid; scale it to the box.
        thickness = max(2, min(line * 2 + 1, max(2, round(min(x1 - x0, y1 - y0) / 6))))
        draw.rectangle(tuple(row["box"]), outline=colour + (255,), width=thickness)
        font = _font(max(10, min(base_font, round(min(x1 - x0, y1 - y0) * 0.9))))
        _draw_index(draw, str(index), (x0, y0), colour, font, (width, height))
    result = page.convert("RGBA")
    result.alpha_composite(overlay)
    result = result.convert("RGB")
    _draw_legend(result, rows, show_low=show_low)
    return result


def _draw_index(draw, text: str, anchor: tuple[float, float], colour, font, size: tuple[int, int]) -> None:
    """A small white chip with the review number, kept inside the page."""
    width, height = size
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    text_width, text_height = right - left, bottom - top
    x = min(max(0, anchor[0]), max(0, width - text_width - 8))
    y = anchor[1] - text_height - 8
    if y < 0:
        y = min(height - text_height - 6, anchor[1] + 2)
    draw.rectangle(
        (x, y, x + text_width + 8, y + text_height + 6),
        fill=(255, 255, 255, 245),
        outline=colour + (255,),
        width=2,
    )
    draw.text((x + 4, y + 1), text, font=font, fill=(20, 20, 20, 255))


def _draw_legend(image, rows: Sequence[dict], *, show_low: bool = False) -> None:
    from PIL import ImageDraw

    draw = ImageDraw.Draw(image, "RGBA")
    width, height = image.size
    pad = max(10, round(width / 120))
    font = _font(max(13, round(width / 85)))
    small = _font(max(11, round(width / 115)))
    labels = {
        "changed": "changed by context",
        "existence": "existence uncertain",
        "attribute": "low attribute probability",
        "low": "read normally (reference)",
    }
    entries = [(kind, f"{labels[kind]}: {sum(1 for row in rows if row['kind'] == kind)}") for kind in KINDS]
    footer = "numbered = review order, not a verdict"
    hidden = None if show_low else "blue boxes hidden; --show-low to show"
    widest = max([draw.textlength(text, font=font) for _, text in entries] + [draw.textlength(footer, font=small)])
    swatch = round(font.size * 1.05)
    box_width = int(widest) + swatch + pad * 4
    line_height = round(font.size * 1.6)
    box_height = pad * 2 + line_height * len(entries) + round(small.size * 1.8) * (2 if hidden else 1)
    x0, y0 = _legend_origin(image, box_width, box_height, pad)
    draw.rounded_rectangle(
        (x0, y0, x0 + box_width, y0 + box_height),
        radius=8,
        fill=(255, 255, 255, 238),
        outline=(150, 150, 150, 255),
        width=1,
    )
    top = y0 + pad
    for index, (_, text) in enumerate(entries):
        colour = COLOURS[KINDS[index]]
        draw.rectangle((x0 + pad, top, x0 + pad + swatch, top + swatch), fill=colour + (255,))
        draw.text((x0 + pad * 2 + swatch, top - 2), text, font=font, fill=(30, 30, 30, 255))
        top += line_height
    draw.text((x0 + pad, top + 2), footer, font=small, fill=(90, 90, 90, 255))
    if hidden:
        draw.text((x0 + pad, top + 2 + round(small.size * 1.8)), hidden, font=small, fill=(90, 90, 90, 255))


def _legend_origin(image, box_width: int, box_height: int, pad: int) -> tuple[int, int]:
    """Put the legend in the emptiest corner so it covers no music or title."""
    from PIL import Image, ImageStat

    width, height = image.size
    candidates = [
        (pad, pad),
        (width - box_width - pad, pad),
        (pad, height - box_height - pad),
        (width - box_width - pad, height - box_height - pad),
    ]
    candidates = [(max(0, x), max(0, y)) for x, y in candidates]
    gray = image.convert("L")

    def darkness(origin: tuple[int, int]) -> float:
        x, y = origin
        box = (x, y, min(width, x + box_width), min(height, y + box_height))
        if box[2] - box[0] < 2 or box[3] - box[1] < 2:
            return 255.0
        return float(sum(ImageStat.Stat(gray.crop(box)).mean))

    return min(candidates, key=darkness)


def _compose(rendered: Path, annotated) -> object:
    """Put the render beside the painted scan, scaled to a common height."""
    from PIL import Image, ImageDraw

    left = Image.open(rendered).convert("RGB")
    right = annotated
    target = max(left.height, right.height)
    left = _fit_height(left, target)
    right = _fit_height(right, target)
    gap = max(12, target // 60)
    header = max(20, target // 40)
    canvas = Image.new("RGB", (left.width + gap + right.width, target + header), (255, 255, 255))
    canvas.paste(left, (0, header))
    canvas.paste(right, (left.width + gap, header))
    draw = ImageDraw.Draw(canvas)
    font = _font(max(12, header // 2))
    draw.text((8, 4), "render", font=font, fill=(60, 60, 60))
    draw.text((left.width + gap + 8, 4), "OMR page, coloured by doubt", font=font, fill=(60, 60, 60))
    draw.line((left.width + gap // 2, 0, left.width + gap // 2, target + header), fill=(180, 180, 180))
    return canvas


def _fit_height(image, height: int):
    if image.height == height:
        return image
    from PIL import Image

    scale = height / image.height
    return image.resize((max(1, round(image.width * scale)), height), Image.LANCZOS)


def _crops(page, suspects: Sequence[dict], out_dir: Path, stem: str, crops: int) -> list[str]:
    """Cut the context crops from the *painted* image, so a crop carries the box and its number."""
    if crops <= 0:
        return []
    crop_dir = out_dir / "crops"
    crop_dir.mkdir(exist_ok=True)
    width, height = page.size
    paths: list[str] = []
    for index, row in enumerate(suspects[:crops], start=1):
        x0, y0, x1, y1 = row["box"]
        pad = max(60, int((x1 - x0) * 1.8))
        box = (
            max(0, int(x0 - pad)),
            max(0, int(y0 - pad)),
            min(width, int(x1 + pad)),
            min(height, int(y1 + pad)),
        )
        patch = page.crop(box)
        if patch.width < 40 or patch.height < 40:
            continue
        patch = patch.resize((patch.width * 2, patch.height * 2), _resample())
        path = crop_dir / f"{stem}_s{index:02d}.png"
        patch.save(path)
        paths.append(str(path))
    return paths


def _resample():
    from PIL import Image

    return Image.LANCZOS


def _font(size: int):
    from PIL import ImageFont

    for name in ("DejaVuSans.ttf", "arial.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:  # Pillow < 10
        return ImageFont.load_default()


# ---------------------------------------------------------------------------
# the whole run
# ---------------------------------------------------------------------------


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


__all__ = [
    "COLOURS",
    "KINDS",
    "PageJob",
    "build_page",
    "classify",
    "load_reading",
    "overall_status",
    "plan",
    "render_markdown",
    "review",
    "summarise",
]
