"""Page-level and score-wide proof-sheet orchestration."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Sequence

from .alignment import (
    common_prefix_measures,
    fit_cells_to_count,
    fold_trailing_slivers,
    reconcile_scan_rows,
)
from .compose import annotate, compose, stack
from .geometry import collapse_blank_bands, detect_measures, detect_rows, ink_crop_box
from .models import COLUMN_WIDTH, RED, RED_MIN, YELLOW, YELLOW_MIN, SheetPage, _numpy
from .scoring import (
    length_measures,
    measure_scores,
    page_measure_count,
    read_score_title,
    reconcile_page_measure_counts,
    score_measure_count,
)
from .svg import parse_svg_measures, svg_cells_to_panel


def _pkg():
    return sys.modules[__package__]


def analyze_page(page: SheetPage, report_path: Path | None = None) -> dict:
    """Everything that does not need the engraver: the scan's measures and the score buckets."""
    from PIL import Image

    expected = page_measure_count(page.musicxml)
    warnings: list[str] = []
    failures: list[dict] = []
    report = {
        "page": page.stem,
        "scan": str(page.scan),
        "musicxml": str(page.musicxml),
        "reading": str(page.reading),
        "offset": page.offset,
        "measures_declared": expected,
        "measures": 0,
        "unplaced_symbols": None,
        "red": [],
        "yellow": [],
        "length_issues": [],
        "measure_scores": [],
        "render_measures": None,
        "scan_measures": None,
        "scan_cells_inferred": [],
        "render_collapsed_bands": 0,
        "aligned": False,
        "warnings": warnings,
        "failures": failures,
        "outputs": {},
    }

    scan_full = Image.open(page.scan).convert("RGB")
    # Detect on the cropped page: the title block would otherwise register as a system and shift
    # every measure number.  The detection cache is in page coordinates, so shift it by the crop.
    box = ink_crop_box(scan_full)
    origin_x, origin_y = box[0], box[1]
    scan_crop = scan_full.crop(box)
    detections = None
    if page.dets is not None and Path(page.dets).is_file():
        try:
            raw = json.loads(Path(page.dets).read_text(encoding="utf-8"))
            detections = [
                {
                    **item,
                    "xyxy": [
                        item["xyxy"][0] - origin_x,
                        item["xyxy"][1] - origin_y,
                        item["xyxy"][2] - origin_x,
                        item["xyxy"][3] - origin_y,
                    ],
                }
                for item in raw
                if len(item.get("xyxy") or ()) == 4
            ]
        except Exception as error:  # noqa: BLE001 - the ink fallback still works
            warnings.append(f"could not read the detection cache: {error}")
    rows, systems, _ = detect_rows(scan_crop, detections)
    numpy = _numpy()
    ink = numpy.asarray(scan_crop.convert("L")) < 190
    right_edges = []
    for top, bottom in systems:
        band = ink[max(0, top) : bottom + 1]
        columns = numpy.nonzero(band.any(axis=0))[0]
        right_edges.append(int(columns[-1]) if len(columns) else scan_crop.width)
    rows, inferred, split_notes = reconcile_scan_rows(
        rows,
        systems,
        expected,
        page.reading,
        origin=(origin_x, origin_y),
        right_edges=right_edges,
    )
    if inferred:
        warnings.extend(split_notes)
        warnings.append(
            f"{len(inferred)} scan cell(s) got an inferred boundary; they are left untinted"
        )
        report["scan_cells_inferred"] = inferred
    scan_cells = [cell for row in rows for cell in row]
    counts = [len(row) for row in rows]
    offsets = [sum(counts[:index]) for index in range(len(counts))]
    scores, unplaced = measure_scores(
        page.reading,
        systems,
        offsets,
        origin=(origin_x, origin_y),
        system_counts=counts,
    )
    lengths = length_measures(report_path, page.offset, expected)

    report["unplaced_symbols"] = unplaced
    report["length_issues"] = lengths
    report["scan_measures"] = len(scan_cells)
    report["detections"] = str(page.dets) if detections else None
    report["measure_scores"] = [
        {
            "measure": page.offset + measure,
            "score": bucket["score"],
            "content_score": bucket["content_score"],
            "symbols": bucket["symbols"],
        }
        for measure, bucket in sorted(scores.items())
    ]
    return {
        "report": report,
        "scan": scan_crop,
        "cells": scan_cells,
        "scan_counts": counts,
        "scores": scores,
        "expected": expected,
        "lengths": lengths,
        "inferred": inferred,
    }


def _render_left_column(
    page: SheetPage,
    out_dir: Path,
    report: dict,
    *,
    musescore: str | None,
    expected_render: int,
    title_source: Path | None,
    prerendered: dict | None,
):
    """Obtain the rendered panel(s) and measure cells for the left column."""
    from PIL import Image

    pkg = _pkg()
    warnings = report["warnings"]
    failures = report["failures"]

    if prerendered is None and musescore is None:
        warnings.append("MuseScore not found: the render column falls back to the scan")
        failures.append({"code": "render_unavailable", "message": "MuseScore not found"})
        return None, []

    try:
        panels = []
        collapsed: list[tuple[int, int]] = []
        if prerendered is not None:
            png_pages = list(prerendered["png_pages"])
            svg_pages = list(prerendered.get("svg_pages") or [])
        else:
            render_dir = out_dir / "_render" / page.stem
            if render_dir.exists():
                shutil.rmtree(render_dir, ignore_errors=True)
            render_dir.mkdir(parents=True, exist_ok=True)
            source_xml = page.musicxml
            if page.offset == 0 and title_source is not None and Path(title_source).is_file():
                titled = render_dir / "with-title.musicxml"
                injected = pkg.copy_header(Path(title_source), page.musicxml, titled)
                if injected:
                    source_xml = titled
                    report["title_injected"] = injected
                    warnings.append(
                        "first page: title/credit block copied from "
                        f"{Path(title_source).name} before rendering ({len(injected)} credit(s))"
                    )
            png_pages = pkg.render_page_musicxml(source_xml, musescore, render_dir)
            svg_pages = []
            try:
                svg_pages = pkg.render_page_svg(source_xml, musescore, render_dir)
            except Exception as error:  # noqa: BLE001 - the ink fallback still works
                warnings.append(f"SVG export unavailable ({error}); using ink barline detection")
            if svg_pages and len(svg_pages) != len(png_pages):
                warnings.append(
                    f"SVG export produced {len(svg_pages)} page(s) for {len(png_pages)} render "
                    "page(s); using ink barline detection"
                )
                svg_pages = []
        svg_cells_by_panel: list[list[tuple[float, float, float, float]]] = []
        svg_ok = bool(svg_pages)
        for index, path in enumerate(png_pages):
            raw = Image.open(path).convert("RGB")
            box = ink_crop_box(raw)
            panel = raw.crop(box)
            panel, removed = collapse_blank_bands(panel)
            collapsed.extend(removed)
            panels.append(panel)
            if not svg_ok:
                continue
            try:
                geometry = parse_svg_measures(svg_pages[index])
                svg_cells_by_panel.append(svg_cells_to_panel(geometry, raw.size, box, removed))
            except Exception as error:  # noqa: BLE001 - fall back to the ink detector
                warnings.append(
                    f"SVG geometry unreadable ({error}); using ink barline detection"
                )
                svg_ok = False
        report["render_collapsed_bands"] = len(collapsed)
        report["render_source"] = "svg" if svg_ok else "ink"
        if svg_ok:
            cells_by_panel = svg_cells_by_panel
            plain_total = sum(len(cells) for cells in cells_by_panel)
        else:
            # Fallback: measure the barlines from the raster and fold sliver cells down.
            plain_by_panel = []
            for panel in panels:
                plain, _, _ = detect_measures(panel)
                plain_by_panel.append(plain)
            plain_total = sum(len(cells) for cells in plain_by_panel)
            cells_by_panel, folded = fit_cells_to_count(plain_by_panel, expected_render)
            if folded:
                report["slivers_merged"] = folded
        report["render_measures_detected"] = plain_total
        stacked, panel_offsets = stack(panels)
        flat: list[tuple[float, float, float, float]] = []
        for cells, offset_y in zip(cells_by_panel, panel_offsets):
            flat.extend((x0, y0 + offset_y, x1, y1 + offset_y) for x0, y0, x1, y1 in cells)
        flat, slivers = fold_trailing_slivers(flat, expected_render)
        if slivers:
            report["trailing_slivers_folded"] = slivers
            warnings.append(
                f"folded {slivers} trailing barline sliver(s) into the bar on their left"
            )
        report["render_measures"] = len(flat)
        if len(panels) > 1:
            warnings.append(f"the page rendered as {len(panels)} panels; stacked in order")
        return stacked, flat
    except Exception as error:  # noqa: BLE001 - a renderer problem must not cost the sheet
        message = f"render failed: {error}"
        warnings.append(message)
        failures.append({"code": "render_failed", "message": message})
        return None, []


def build_sheet(
    page: SheetPage,
    analysis: dict,
    out_dir: Path,
    *,
    musescore: str | None,
    red_min: float = RED_MIN,
    yellow_min: float = YELLOW_MIN,
    width: int = COLUMN_WIDTH,
    title_source: Path | None = None,
    prerendered: dict | None = None,
) -> dict:
    """Render the page, align both sides by measured bar count and write ``<stem>.compare.png``."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = analysis["report"]
    scan_crop = analysis["scan"]
    scan_cells = analysis["cells"]
    scores = analysis["scores"]
    expected = analysis["expected"]
    expected_render = (
        int(prerendered["delivered_measures"])
        if prerendered is not None and prerendered.get("delivered_measures") is not None
        else expected
    )
    lengths = analysis["lengths"]
    warnings = report["warnings"]
    failures = report["failures"]

    measures = sorted(scores)
    inferred = set(analysis.get("inferred") or [])
    red = [
        measure
        for measure in measures
        if scores[measure]["content_score"] >= red_min and measure - 1 not in inferred
    ]
    yellow = [
        measure
        for measure in measures
        if yellow_min <= scores[measure]["content_score"] < red_min and measure - 1 not in inferred
    ]
    report["measures"] = expected
    report["delivered_measures"] = expected_render
    report["render_mode"] = prerendered["render_mode"] if prerendered is not None else "raw-pages"
    if prerendered is not None:
        report["render_source_file"] = prerendered["source_path"]
        warnings.extend(prerendered.get("warnings") or [])
    report["red"] = [page.offset + measure for measure in red]
    report["yellow"] = [page.offset + measure for measure in yellow]

    colours: dict[int, tuple] = {}
    for measure in red:
        colours[measure - 1] = RED
    for measure in yellow:
        colours[measure - 1] = YELLOW
    labels = {index: str(page.offset + index + 1) for index in range(max(expected, expected_render))}
    for measure in lengths:
        labels[measure - page.offset - 1] = f"{measure}≠"

    left, render_cells = _render_left_column(
        page,
        out_dir,
        report,
        musescore=musescore,
        expected_render=expected_render,
        title_source=title_source,
        prerendered=prerendered,
    )
    if left is None:
        left = scan_crop

    # Tint as much as both columns agree on, not "all or nothing".  A page whose last bar was
    # mis-detected still has a trustworthy prefix: an uncoloured page tells the reviewer less
    # than a page with the verified bars coloured and the tail left plain.
    render_ok = bool(render_cells) and len(render_cells) == expected_render
    scan_ok = len(scan_cells) == expected
    shared_expected = min(expected, expected_render)
    report["render_aligned"] = render_ok
    report["scan_aligned"] = scan_ok
    report["render_available"] = bool(render_cells)
    if render_ok and scan_ok:
        tint = shared_expected
    elif render_cells:
        tint = common_prefix_measures(render_cells, scan_cells, shared_expected)
    else:
        # MusicXML-only run: there is no render column to compare with, so only the scan's own
        # bar count can be trusted.
        tint = expected if scan_ok else 0
    report["aligned"] = render_ok and scan_ok
    report["tinted_measures"] = tint
    report["partial"] = (not report["aligned"]) and tint > 0

    if render_cells and not render_ok:
        message = (
            f"the render detected {len(render_cells)} measures but the page expects "
            f"{expected_render}; "
            + (f"tinted the first {tint} bar(s)" if tint else "no overlay")
        )
        warnings.append(message)
        failures.append({"code": "render_layout_mismatch", "message": message})
    if not scan_ok:
        message = (
            f"the scan detected {len(scan_cells)} measures but the page MusicXML declares "
            f"{expected}; "
            + (f"tinted the first {tint} bar(s)" if tint else "the scan is not tinted")
        )
        warnings.append(message)
        failures.append({"code": "scan_layout_mismatch", "message": message})
    if render_cells and tint:
        left = annotate(left, render_cells[:tint], colours, labels)
    right = annotate(scan_crop, scan_cells[:tint], colours, labels) if tint else scan_crop

    if prerendered is not None:
        if prerendered["render_mode"] == "score-mscz":
            left_caption = f"delivered score \u00b7 MuseScore render of {prerendered['source_label']}"
        else:
            left_caption = f"repaired MusicXML \u00b7 MuseScore render of {prerendered['source_label']}"
    else:
        left_caption = f"OMR result \u00b7 MuseScore re-engraving of {page.musicxml.name}"
    sheet = compose(
        left,
        right,
        left_caption,
        f"original page \u00b7 scan of {page.stem}",
        red=len(red),
        yellow=len(yellow),
        length_count=len(lengths),
        width=width,
    )
    image_path = out_dir / f"{page.stem}.compare.png"
    sheet.save(image_path)
    report["outputs"] = {"image": str(image_path), "json": str(out_dir / f"{page.stem}.compare.json")}
    (out_dir / f"{page.stem}.compare.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return report


def review_sheets(
    pages: Sequence[SheetPage],
    out_dir: Path,
    *,
    musescore: str | None = None,
    report_path: Path | None = None,
    red_min: float = RED_MIN,
    yellow_min: float = YELLOW_MIN,
    width: int = COLUMN_WIDTH,
    title_source: Path | None = None,
    title: str | None = None,
    source_name: str | None = None,
    score_path: Path | None = None,
) -> dict:
    """Analyze every page first, then build the sheets; the ranking is score-wide.

    When ``score_path`` (a delivered ``.mscz`` or repaired ``.musicxml``) is supplied, the whole
    delivered score is rendered once with page breaks matching the scan pages so the left column
    shows the real delivered edition rather than raw per-page OMR output.
    """
    pkg = _pkg()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    failures: list[dict] = []
    skipped: list[dict] = []

    analyses: list[tuple[SheetPage, dict]] = []
    for page in pages:
        try:
            analyses.append((page, pkg.analyze_page(page, report_path)))
        except Exception as error:  # noqa: BLE001 - one page must not stop the score
            failures.append({"page": page.stem, "code": "page_analysis_failed", "message": str(error)})
            skipped.append({"page": page.stem, "reason": str(error)})

    prerendered_pages: list[dict | None] = [None] * len(analyses)
    active_render_mode = "raw-pages"
    score_warnings: list[str] = []
    if score_path is not None and Path(score_path).is_file() and musescore and analyses:
        if len(analyses) != len(pages):
            failures.append(
                {
                    "page": "global",
                    "code": "score_pagination_skipped",
                    "message": "some pages failed analysis; falling back to per-page rendering",
                }
            )
        else:
            raw_counts = [analysis["expected"] for _, analysis in analyses]
            try:
                delivered_total = score_measure_count(Path(score_path))
                reconciled, count_notes = reconcile_page_measure_counts(
                    raw_counts, delivered_total, report_path
                )
                if reconciled is None:
                    message = "; ".join(count_notes)
                    failures.append(
                        {"page": "global", "code": "score_measure_count_mismatch", "message": message}
                    )
                    score_warnings.append(message + "; falling back to raw per-page MusicXML")
                else:
                    score_warnings.extend(count_notes)
                    rendered_list, render_notes = pkg.render_paginated_score(
                        Path(score_path), reconciled, musescore, out_dir
                    )
                    if count_notes and rendered_list:
                        rendered_list[-1]["warnings"] = (
                            list(rendered_list[-1].get("warnings") or []) + count_notes
                        )
                    prerendered_pages = list(rendered_list)
                    active_render_mode = rendered_list[0]["render_mode"]
                    score_warnings.extend(render_notes)
            except Exception as error:  # noqa: BLE001 - report clearly and keep per-page fallback
                message = f"delivered score render failed ({error}); falling back to raw per-page MusicXML"
                failures.append({"page": "global", "code": "score_render_failed", "message": message})
                score_warnings.append(message)

    reports: list[dict] = []
    for (page, analysis), prerendered in zip(analyses, prerendered_pages):
        try:
            report = pkg.build_sheet(
                page,
                analysis,
                out_dir,
                musescore=musescore,
                red_min=red_min,
                yellow_min=yellow_min,
                width=width,
                title_source=title_source,
                prerendered=prerendered,
            )
        except Exception as error:  # noqa: BLE001 - same rule
            failures.append({"page": page.stem, "code": "page_build_failed", "message": str(error)})
            continue
        reports.append(report)
        failures.extend({"page": page.stem, **failure} for failure in report["failures"])

    reds = sum(len(report["red"]) for report in reports)
    yellows = sum(len(report["yellow"]) for report in reports)
    length_count = sum(len(report["length_issues"]) for report in reports)
    issue_total = reds + yellows + length_count
    overall = pkg.status(issue_total, bool(failures or skipped))
    summary = {
        "status": overall,
        "render_mode": active_render_mode,
        "score_path": str(score_path) if score_path is not None else None,
        "warnings": score_warnings,
        "pages": len(reports),
        "requested_pages": len(pages),
        "skipped": len(skipped),
        "skipped_pages": skipped,
        "failures": failures,
        "failure_count": len(failures),
        "issues": {
            "total": issue_total,
            "red": reds,
            "yellow": yellows,
            "length": length_count,
            "length_measures": len({measure for report in reports for measure in report["length_issues"]}),
        },
        "outputs": {
            "markdown": str(out_dir / "review_sheet.md"),
            "summary": str(out_dir / "review_sheet_summary.json"),
            "pages": [{"page": report["page"], "json": report["outputs"]["json"], "image": report["outputs"]["image"]} for report in reports],
        },
    }
    resolved_title = title or read_score_title(title_source) or read_score_title(score_path)
    combined = pkg.write_sheet_pdf(
        [report["outputs"]["image"] for report in reports],
        out_dir / "review-sheets.pdf",
        title=resolved_title,
        source_name=source_name,
        entries=[
            {
                "page": index,
                "pdf_page": index + 1,  # the cover is PDF page 1
                "label": report["page"],
                "measures": report["measures"],
                "red": len(report["red"]),
                "yellow": len(report["yellow"]),
                "aligned": report.get("aligned"),
                "partial": report.get("partial"),
                "tinted": report.get("tinted_measures"),
                "render_available": report.get("render_available"),
            }
            for index, report in enumerate(reports, start=1)
        ],
        render_mode=active_render_mode,
    )
    if combined is not None:
        summary["outputs"]["pdf"] = str(combined)
        summary["pdf_cover"] = {
            "title": resolved_title,
            "source": source_name,
            "pages": len(reports),
            "render_mode": active_render_mode,
        }
    pkg.write_priority_list(reports, out_dir, summary)
    (out_dir / "review_sheet_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return summary
