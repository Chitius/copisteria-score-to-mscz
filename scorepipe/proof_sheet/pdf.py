"""Score-wide proof-sheet outputs: cover/TOC page, combined PDF packet, and priority list."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Sequence

from .compose import _font
from .models import LIST_LABELS, SHEET_FOOTER, SHEET_PDF_DPI, SHEET_PDF_SIZE


def status(issues: int, incomplete: bool) -> str:
    if incomplete:
        return "incomplete"
    return "complete_with_issues" if issues else "complete_no_issues"


def write_priority_list(reports: Sequence[dict], out_dir: Path, summary: dict) -> str:
    """One list across the whole score: which measures to open first, page by page.

    The tiers are absolute (same heads and weights everywhere), so the numbers compare across
    pages; the order below is the score-wide ranking, which is what decides what to read first.
    """
    rows: list[tuple[float, int, str, str]] = []
    objective: list[dict] = []
    for report in reports:
        red = set(report["red"])
        yellow = set(report["yellow"])
        for entry in report["measure_scores"]:
            tier = (
                LIST_LABELS[0]
                if entry["measure"] in red
                else (LIST_LABELS[1] if entry["measure"] in yellow else "")
            )
            if tier:
                rows.append((entry.get("content_score", entry["score"]), entry["measure"], report["page"], tier))
        for measure in report["length_issues"]:
            objective.append({"measure": measure, "page": report["page"]})
    rows.sort(reverse=True)
    objective.sort(key=lambda item: (item["measure"], item["page"]))
    objective_measures = {item["measure"] for item in objective}

    lines = ["# Score-wide review order", "", f"Status: **{summary['status']}**.", ""]
    if summary.get("outputs", {}).get("pdf"):
        lines.append(
            f"All {summary['pages']} page comparison(s) are bound into one file: "
            f"`{Path(summary['outputs']['pdf']).name}`."
        )
        lines.append("")
    if summary["status"] == "incomplete":
        lines.append(
            "This review is incomplete; the list covers only what was processed and cannot be used "
            "to claim the rest is clean."
        )
        lines.append("")
    for failure in summary.get("failures", []):
        lines.append(f"- failed ({failure.get('page', 'global')}): {failure['message']}")
    for skipped in summary.get("skipped_pages", []):
        lines.append(f"- skipped ({skipped['page']}): {skipped['reason']}")
    if summary.get("failures") or summary.get("skipped_pages"):
        lines.append("")
    total = sum(report["measures"] for report in reports)
    reds = sum(len(report["red"]) for report in reports)
    yellows = sum(len(report["yellow"]) for report in reports)
    lines.append(f"{len(reports)} page(s), {total} measure(s); red {reds}, yellow {yellows}.")
    lines.append(
        "Tiers are absolute (red = a class/position was rewritten or existence is ambiguous; "
        "yellow = an accidental, tuplet or position was rewritten), so they compare across pages. "
        "Routine voice/dot/onset fixes stay in the symbol heat map but do not tint a bar."
    )
    lines.append("The order below is by content score, across the whole score.")
    lines.append("")
    if objective:
        lines.append("## Objective errors: voices that do not add up to the metre")
        lines.append("")
        for detail in objective:
            lines.append(
                f"- measure {detail['measure']} ({detail['page']}): check for a missed or extra note"
            )
        lines.append("")
    lines.append("## By suspicion")
    lines.append("")
    if not rows:
        if summary["status"] == "incomplete":
            lines.append(
                "Nothing reached the yellow tier in what was processed, but the review is incomplete."
            )
        else:
            lines.append("No measure reached the yellow tier: nothing here looks doubtful.")
    for score, measure, page, tier in rows:
        mark = " (length also wrong)" if measure in objective_measures else ""
        lines.append(f"- measure {measure} ({page}, {tier}, score {score:.2f}){mark}")
    lines.append("")
    lines.append("Per page: `<page>.compare.png`; per page numbers: `<page>.compare.json`.")
    markdown = "\n".join(lines) + "\n"
    (out_dir / "review_sheet.md").write_text(markdown, encoding="utf-8")
    return markdown


def _fit_text(draw, text: str, font, width: int) -> str:
    """Trim ``text`` with an ellipsis until it fits ``width`` pixels."""
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text + "…"


def build_cover_page(
    title: str | None,
    source_name: str | None,
    entries: Sequence[dict],
    *,
    size: tuple[int, int] = SHEET_PDF_SIZE,
    render_mode: str = "raw-pages",
):
    """A cover/TOC page so the printed packet explains itself.

    ``entries`` are per source page: ``page``, ``label``, ``measures``, ``red``, ``yellow``,
    ``aligned``.  Kept as a plain image, so the PDF stays a Pillow-only job.  Every size is scaled
    from the 1754-px design width, so the cover stays proportional at 300 dpi.
    """
    from PIL import Image, ImageDraw

    scale = size[0] / 1754
    canvas = Image.new("RGB", size, (255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    margin = round(90 * scale)
    title_text = title or "Score review"
    title_font = _font(round(46 * scale), title_text)
    sub_font = _font(round(20 * scale), source_name or "")
    head_font = _font(round(16 * scale))
    row_font = _font(round(17 * scale), " ".join(str(entry.get("label") or "") for entry in entries))
    note_font = _font(round(15 * scale))
    draw.text((margin, round(96 * scale)), title_text, font=title_font, fill=(28, 28, 28))
    y = round(176 * scale)
    draw.text(
        (margin, y),
        "OMR page review \u00b7 measure-level comparison",
        font=sub_font,
        fill=(90, 90, 90),
    )
    y += round(32 * scale)
    if source_name:
        draw.text((margin, y), f"Source: {source_name}", font=sub_font, fill=(90, 90, 90))
        y += round(28 * scale)

    draw.text(
        (margin, y),
        f"Generated {datetime.date.today().isoformat()}",
        font=sub_font,
        fill=(120, 120, 120),
    )
    y += round(34 * scale)
    if entries:
        total_measures = sum(int(entry.get("measures") or 0) for entry in entries)
        reds = sum(int(entry.get("red") or 0) for entry in entries)
        yellows = sum(int(entry.get("yellow") or 0) for entry in entries)
        all_aligned = all(entry.get("aligned") for entry in entries)
        summary_bits = [
            f"{len(entries)} page(s)",
            f"{total_measures} measures",
            f"{reds} red / {yellows} yellow",
            "all aligned" if all_aligned else "some pages not aligned",
        ]
        draw.text(
            (margin, y),
            "  \u00b7  ".join(summary_bits),
            font=sub_font,
            fill=(80, 80, 80),
        )
        y += round(34 * scale)
    y += round(10 * scale)
    columns = tuple(round(value * scale) for value in (0, 120, 620, 790, 1080))
    draw.text((margin + columns[0], y), "PDF page", font=head_font, fill=(60, 60, 60))
    draw.text((margin + columns[1], y), "OMR page", font=head_font, fill=(60, 60, 60))
    draw.text((margin + columns[2], y), "Measures", font=head_font, fill=(60, 60, 60))
    draw.text((margin + columns[3], y), "Red / yellow", font=head_font, fill=(60, 60, 60))
    draw.text((margin + columns[4], y), "Alignment", font=head_font, fill=(60, 60, 60))
    y += round(28 * scale)
    draw.line((margin, y, size[0] - margin, y), fill=(200, 200, 200), width=1)
    y += round(10 * scale)
    for entry in entries:
        label = _fit_text(
            draw, str(entry.get("label") or ""), row_font, columns[2] - columns[1] - round(20 * scale)
        )
        draw.text(
            (margin + columns[0], y),
            str(entry.get("pdf_page", entry.get("page", ""))),
            font=row_font,
            fill=(40, 40, 40),
        )
        draw.text((margin + columns[1], y), label, font=row_font, fill=(40, 40, 40))
        draw.text(
            (margin + columns[2], y),
            str(entry.get("measures", "")),
            font=row_font,
            fill=(40, 40, 40),
        )
        draw.text(
            (margin + columns[3], y),
            f"{entry.get('red', 0)} / {entry.get('yellow', 0)}",
            font=row_font,
            fill=(40, 40, 40),
        )
        aligned = entry.get("aligned")
        if aligned:
            text, colour = "aligned", (60, 60, 60)
        elif entry.get("render_available") is False:
            text, colour = "scan only", (90, 90, 90)
        elif entry.get("partial"):
            text = f"partial {entry.get('tinted') or 0}/{entry.get('measures') or 0}"
            colour = (170, 110, 20)
        elif aligned is not None:
            text, colour = "not aligned", (180, 60, 60)
        else:
            text, colour = "", (60, 60, 60)
        draw.text(
            (margin + columns[4], y),
            text,
            font=row_font,
            fill=colour,
        )
        y += round(28 * scale)
    note_y = size[1] - round(128 * scale)
    draw.line(
        (margin, note_y - round(18 * scale), size[0] - margin, note_y - round(18 * scale)),
        fill=(210, 210, 210),
        width=1,
    )
    if render_mode == "score-mscz":
        left_note = (
            "Left column: delivered MuseScore score (score.mscz), paginated to match the scan. "
            "Right column: the original scan."
        )
    elif render_mode == "score-musicxml":
        left_note = (
            "Left column: repaired MusicXML (score.musicxml), paginated to match the scan. "
            "Right column: the original scan."
        )
    else:
        left_note = (
            "Left column: MuseScore re-engraving of that page's raw OMR MusicXML. "
            "Right column: the original scan."
        )
    draw.text(
        (margin, note_y),
        left_note,
        font=note_font,
        fill=(90, 90, 90),
    )
    draw.text(
        (margin, note_y + round(26 * scale)),
        "Colour is a reading order, not a verdict: red = content doubt, yellow = attribute doubt, "
        "\u2260 = measure length violation.",
        font=note_font,
        fill=(90, 90, 90),
    )
    return canvas


def write_sheet_pdf(
    images: Sequence[Path | str],
    out_path: Path | str,
    *,
    dpi: int = SHEET_PDF_DPI,
    title: str | None = None,
    source_name: str | None = None,
    entries: Sequence[dict] | None = None,
    render_mode: str = "raw-pages",
) -> Path | None:
    """Bind the per-page comparison images into one A4-landscape PDF, in page order.

    One file is what a human actually opens: a folder of ``*.compare.png`` is fine for tooling but
    nobody wants to click through ten PNGs.  With ``entries`` the PDF opens with a cover/TOC page;
    every comparison page is fitted on A4 landscape at 300 dpi and carries a footer with the score
    name, the source file name and ``page i/N``.  Pillow writes the multi-page PDF without any
    external dependency.
    """
    from PIL import Image, ImageDraw

    out_path = Path(out_path)
    opened = []
    for image in images:
        path = Path(image)
        if not path.is_file():
            continue
        opened.append(Image.open(path).convert("RGB"))
    if not opened:
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    target = SHEET_PDF_SIZE
    scale = target[0] / 1754
    margin = round(28 * scale)
    pages = []
    try:
        if entries is not None:
            pages.append(
                build_cover_page(
                    title, source_name, entries, size=target, render_mode=render_mode
                )
            )
        label_font = _font(round(15 * scale), f"{title or ''} {source_name or ''}")
        total = len(opened)
        for index, image in enumerate(opened, start=1):
            canvas = Image.new("RGB", target, (255, 255, 255))
            fitted = image.copy()
            fitted.thumbnail(
                (target[0] - 2 * margin, target[1] - 2 * margin - SHEET_FOOTER), Image.LANCZOS
            )
            canvas.paste(
                fitted,
                (
                    (target[0] - fitted.width) // 2,
                    margin + (target[1] - SHEET_FOOTER - 2 * margin - fitted.height) // 2,
                ),
            )
            fitted.close()
            draw = ImageDraw.Draw(canvas)
            top = target[1] - SHEET_FOOTER
            draw.line((margin, top, target[0] - margin, top), fill=(205, 205, 205), width=1)
            left = _fit_text(
                draw,
                f"{title or 'Score review'} \u2014 OMR review",
                label_font,
                target[0] // 2 - round(60 * scale),
            )
            draw.text((margin, top + round(12 * scale)), left, font=label_font, fill=(90, 90, 90))
            right = f"page {index}/{total}"
            if source_name:
                right = (
                    f"{_fit_text(draw, source_name, label_font, target[0] // 2 - round(160 * scale))}"
                    f"  \u00b7  {right}"
                )
            draw.text(
                (target[0] - margin - draw.textlength(right, font=label_font), top + round(12 * scale)),
                right,
                font=label_font,
                fill=(90, 90, 90),
            )
            pages.append(canvas)
        pages[0].save(
            out_path,
            "PDF",
            resolution=dpi,
            save_all=True,
            append_images=pages[1:],
        )
    finally:
        for page in pages:
            page.close()
        for image in opened:
            image.close()
    return out_path
