"""SVG vector barline parsing and mapping to cropped/collapsed render panels."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .models import SVG_BARLINE, SVG_MIN_CELL, SVG_VIEWBOX, SVG_X_TOLERANCE


def parse_svg_measures(svg_path: Path) -> dict:
    """Barlines, systems and measure cells from MuseScore's SVG, in SVG units.

    The export draws each staff's barline as a vertical ``polyline``; the two staves of a grand
    staff produce two segments whose y ranges overlap (the upper one reaches the lower staff's top
    line), so grouping the segments by overlap recovers the systems without any pixel heuristic.
    """
    text = Path(svg_path).read_text(encoding="utf-8", errors="replace")
    view = SVG_VIEWBOX.search(text)
    width = float(view.group(3)) if view else 0.0
    height = float(view.group(4)) if view else 0.0
    segments: list[tuple[float, float, float]] = []
    for points in SVG_BARLINE.findall(text):
        try:
            pts = [tuple(float(value) for value in pair.split(",")) for pair in points.split()]
        except ValueError:
            continue
        if len(pts) < 2:
            continue
        if len({round(point[0], 1) for point in pts}) != 1:
            continue  # not a vertical line
        segments.append((pts[0][0], min(p[1] for p in pts), max(p[1] for p in pts)))
    if not segments:
        raise RuntimeError(f"{Path(svg_path).name}: no <polyline class='BarLine'> geometry")

    systems = []
    for top, bottom, xs in _group_barline_systems(segments):
        unique: list[float] = []
        for x in sorted(xs):
            if not unique or x - unique[-1] > SVG_X_TOLERANCE:
                unique.append(x)
        cells = [
            (unique[index], top, unique[index + 1], bottom)
            for index in range(len(unique) - 1)
            if unique[index + 1] - unique[index] > SVG_MIN_CELL
        ]
        cells = _merge_svg_slivers(cells)
        if cells:
            systems.append({"top": top, "bottom": bottom, "cells": cells})
    return {"width": width, "height": height, "systems": systems}


def _merge_svg_slivers(
    cells: Sequence[tuple[float, float, float, float]], fraction: float = 0.2
) -> list[tuple[float, float, float, float]]:
    """Fold a double-barline sliver into the cell on its left; keep the first and last cell.

    MuseScore draws a final/repeat barline as two polylines a few units apart, which would show up
    as a 14-unit "measure" between 350-unit neighbours.  A real short bar (pickup, fermata bar) is
    far wider than 20% of the system median, so the threshold cannot eat one.
    """
    if len(cells) < 3:
        return list(cells)
    widths = sorted(cell[2] - cell[0] for cell in cells)
    median = widths[len(widths) // 2] or 1
    merged = [cells[0]]
    for cell in cells[1:-1]:
        if (cell[2] - cell[0]) < median * fraction:
            merged[-1] = (merged[-1][0], merged[-1][1], cell[2], merged[-1][3])
        else:
            merged.append(cell)
    merged.append(cells[-1])
    return merged


def _group_barline_systems(
    segments: Sequence[tuple[float, float, float]],
) -> list[tuple[float, float, list[float]]]:
    """Group barline segments into systems by y-overlap (both staves of a system overlap)."""
    bands: list[dict] = []
    for x, top, bottom in sorted(segments, key=lambda item: (item[1], item[0])):
        for band in bands:
            if top <= band["bottom"] + 0.5 and bottom >= band["top"] - 0.5:
                band["top"] = min(band["top"], top)
                band["bottom"] = max(band["bottom"], bottom)
                band["xs"].append(x)
                break
        else:
            bands.append({"top": top, "bottom": bottom, "xs": [x]})
    merged: list[dict] = []
    for band in sorted(bands, key=lambda item: item["top"]):
        if merged and band["top"] <= merged[-1]["bottom"] + 0.5:
            merged[-1]["bottom"] = max(merged[-1]["bottom"], band["bottom"])
            merged[-1]["xs"].extend(band["xs"])
        else:
            merged.append(band)
    return [(band["top"], band["bottom"], band["xs"]) for band in merged]


def _collapsed_y(y: float, removed: Sequence[tuple[int, int]], margin: int = 12) -> float:
    """Map a y from the cropped page to the band-collapsed page.

    :func:`collapse_blank_bands` cuts every blank run longer than the threshold except its
    ``margin`` rows; the same cut has to be applied to the coordinates that come from the SVG.
    """
    shift = 0
    for start, end in removed:
        cut_from, cut_to = start + margin, end - margin
        if cut_to <= cut_from:
            continue
        if y >= cut_to:
            shift += cut_to - cut_from
        elif y > cut_from:
            shift += y - cut_from
    return y - shift


def svg_cells_to_panel(
    geometry: dict,
    image_size: tuple[int, int],
    crop_box: tuple[int, int, int, int],
    removed: Sequence[tuple[int, int]],
) -> list[tuple[float, float, float, float]]:
    """Scale SVG measure cells into the cropped, band-collapsed PNG of the same page."""
    width, height = image_size
    scale_x = width / geometry["width"] if geometry.get("width") else 1.0
    scale_y = height / geometry["height"] if geometry.get("height") else 1.0
    origin_x, origin_y = crop_box[0], crop_box[1]
    cells = []
    for system in geometry["systems"]:
        for x0, y0, x1, y1 in system["cells"]:
            cells.append(
                (
                    x0 * scale_x - origin_x,
                    _collapsed_y(y0 * scale_y - origin_y, removed),
                    x1 * scale_x - origin_x,
                    _collapsed_y(y1 * scale_y - origin_y, removed),
                )
            )
    return cells
