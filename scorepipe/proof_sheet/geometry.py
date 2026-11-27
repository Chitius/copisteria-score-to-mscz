"""Image/ink geometry: staff detection, barline detection, cropping, and blank-band collapsing."""

from __future__ import annotations

from typing import Iterable, Sequence

from .models import (
    BLANK_BAND_FRACTION,
    COVER_FRAC,
    DETECT_WIDTH,
    MIN_CELL_FRACTION,
    SIDE_CLEARANCE,
    SIDE_FRAC,
    _numpy,
)


def ink_mask(image, max_width: int = DETECT_WIDTH):
    """A boolean ink mask plus the scale from mask pixels back to the original image."""
    from PIL import Image

    numpy = _numpy()
    scale = 1.0
    if image.width > max_width:
        scale = max_width / image.width
        image = image.resize((max_width, max(1, round(image.height * scale))), Image.LANCZOS)
    return numpy.asarray(image.convert("L")) < 160, 1.0 / scale


def staff_bands(ink, width: int) -> list[tuple[int, int]]:
    """Rows that are mostly ink are staff lines; consecutive ones group into staves."""
    numpy = _numpy()
    rows = numpy.nonzero(ink.sum(axis=1) > width * 0.45)[0]
    if len(rows) == 0:
        return []
    groups = [[int(rows[0])]]
    for row in rows[1:]:
        if row - groups[-1][-1] <= 2:
            groups[-1].append(int(row))
        else:
            groups.append([int(row)])
    lines = [(group[0] + group[-1]) // 2 for group in groups]
    if len(lines) < 2:
        return []
    gaps = sorted(b - a for a, b in zip(lines, lines[1:]))
    typical = gaps[len(gaps) // 2] or 1
    staves = [[lines[0]]]
    for previous, current in zip(lines, lines[1:]):
        if current - previous > typical * 2.2:  # a gap of two staff spaces: a new staff
            staves.append([current])
        else:
            staves[-1].append(current)
    bands = [(staff[0], staff[-1]) for staff in staves]
    return [band for band in bands if band[1] - band[0] >= typical * 2]


def longest_run(columns):
    """Longest vertical run of ink per column; a barline spans a system, a stem does not."""
    numpy = _numpy()
    height, width = columns.shape
    best = numpy.zeros(width, dtype=numpy.int32)
    current = numpy.zeros(width, dtype=numpy.int32)
    for row in range(height):
        current = (current + 1) * columns[row]
        best = numpy.maximum(best, current)
    return best


def systems_from_ink(ink, bands: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Group staves into systems by what connects them: a barline drawn across the gap."""
    if not bands:
        return []
    groups = [[bands[0]]]
    for previous, current in zip(bands, bands[1:]):
        gap = current[0] - previous[1]
        if gap <= 0:
            groups[-1].append(current)
            continue
        strip = ink[max(0, previous[1] - 2) : current[0] + 3, :]
        runs = longest_run(strip)
        connected = bool((runs >= strip.shape[0] * 0.85).any())
        if connected:
            groups[-1].append(current)
        else:
            groups.append([current])
    return [(group[0][0], group[-1][1]) for group in groups]


def barline_columns(ink, band: tuple[int, int], height: int) -> list[int]:
    """Columns of a system that look like barlines.

    A barline is not a *continuous* run here: engravers and MuseScore both break it between the
    staves of a system, so the old "run spans 80% of the system" test finds nothing on a
    vocal-plus-piano page (measured: 0 cells on the Schubert page).  What survives the breaks is
    the combination of "tall here" and "empty just beside it": a stem or a beam has ink on both
    sides, a barline does not.  With that test the page yields 4+7+9+7+6 = 33 measures, exactly
    what the page MusicXML declares.
    """
    numpy = _numpy()
    top, bottom = band
    sub = ink[max(0, top - 2) : min(height, bottom + 3), :]
    rows = sub.shape[0]
    if rows == 0:
        return []
    cover = sub.sum(axis=0)
    left = numpy.roll(cover, SIDE_CLEARANCE)
    right = numpy.roll(cover, -SIDE_CLEARANCE)
    candidate = (
        (cover >= rows * COVER_FRAC)
        & (left <= rows * SIDE_FRAC)
        & (right <= rows * SIDE_FRAC)
    )
    columns = numpy.nonzero(candidate)[0]
    groups: list[list[int]] = []
    for column in columns:
        if groups and column - groups[-1][-1] <= 4:
            groups[-1].append(int(column))
        else:
            groups.append([int(column)])
    return [(group[0] + group[-1]) // 2 for group in groups]


def _cells_from_barlines(
    xs: Sequence[int],
    top: int,
    bottom: int,
    *,
    narrow_filter: bool = False,
) -> list[tuple[int, int, int, int]]:
    row = [
        (xs[index], top, xs[index + 1], bottom)
        for index in range(len(xs) - 1)
        if xs[index + 1] - xs[index] > 12
    ]
    return _merge_narrow_cells(row) if narrow_filter else row


def measure_cells(
    ink, systems: Sequence[tuple[int, int]], *, narrow_filter: bool = False
) -> list[list[tuple[int, int, int, int]]]:
    """Per system, the cells between barlines detected from ink: ``(x0, y0, x1, y1)``."""
    height = ink.shape[0]
    cells: list[list[tuple[int, int, int, int]]] = []
    for top, bottom in systems:
        xs = _merge(barline_columns(ink, (top, bottom), height))
        cells.append(_cells_from_barlines(xs, top, bottom, narrow_filter=narrow_filter))
    return cells


def _merge_narrow_cells(
    cells: Sequence[tuple[int, int, int, int]], fraction: float = MIN_CELL_FRACTION
) -> list[tuple[int, int, int, int]]:
    """Fold an interior sliver into the cell on its left; a stem read as a barline makes exactly that.

    The first and last cell of a system are never merged: they are often short for real (a pickup
    and a final bar), and merging them cost a correct bar on the measured page (36 detected cells
    merged down to 31 instead of 32).
    """
    if len(cells) < 3:
        return list(cells)
    widths = sorted(cell[2] - cell[0] for cell in cells)
    median = widths[len(widths) // 2]
    if not median:
        return list(cells)
    merged: list[tuple[int, int, int, int]] = [cells[0]]
    for cell in cells[1:-1]:
        if (cell[2] - cell[0]) < median * fraction:
            merged[-1] = (merged[-1][0], merged[-1][1], cell[2], merged[-1][3])
        else:
            merged.append(cell)
    merged.append(cells[-1])
    return merged


def barline_columns_from_dets(
    detections: Sequence[dict], systems: Sequence[tuple[int, int]], scale: float
) -> list[list[int]]:
    """Barlines per system from copisteria's own detections (``barLine_*`` boxes).

    The detections are exact where they exist -- a double barline is two boxes, a final barline is
    its own class -- so this is tried before the ink heuristic.  A barline the detections missed
    is recovered by the union in :func:`detect_measures`.
    """
    bars = [item for item in detections if str(item.get("cls", "")).lower().startswith("barline")]
    result: list[list[int]] = []
    for top, bottom in systems:
        y0, y1 = top * scale, bottom * scale
        xs = sorted(
            {
                round((item["xyxy"][0] + item["xyxy"][2]) / 2)
                for item in bars
                if len(item.get("xyxy") or ()) == 4
                and y0 - 10 <= (item["xyxy"][1] + item["xyxy"][3]) / 2 <= y1 + 10
            }
        )
        result.append(xs)
    return result


def _merge(xs: Iterable[int], tolerance: int = 8) -> list[int]:
    merged: list[int] = []
    for x in sorted(xs):
        if merged and x - merged[-1] <= tolerance:
            continue
        merged.append(int(x))
    return merged


def detect_rows(
    image,
    detections: Sequence[dict] | None = None,
    max_width: int = DETECT_WIDTH,
    *,
    narrow_filter: bool = False,
) -> tuple[list[list[tuple[int, int, int, int]]], list[tuple[int, int]], float]:
    """Measure cells per system (image coordinates), the systems, and the mask-to-image scale."""
    ink, mask_to_image = ink_mask(image, max_width)
    bands = staff_bands(ink, ink.shape[1])
    systems = systems_from_ink(ink, bands)
    scale = mask_to_image
    systems_scaled = [tuple(round(value * scale) for value in system) for system in systems]
    if detections:
        # The detections are the reader's own barlines: use them *instead of* the ink guess, not
        # merged with it.  Merging double-counts every stem the ink test happens to like (measured:
        # 32 -> 37 cells on one page, which then fails the count check for the wrong reason).
        rows = barline_columns_from_dets(detections, systems, scale)
        cells = [
            _cells_from_barlines(xs, top, bottom, narrow_filter=narrow_filter)
            for (top, bottom), xs in zip(systems_scaled, rows)
        ]
    else:
        cells = measure_cells(ink, systems, narrow_filter=narrow_filter)
    return cells, systems_scaled, scale


def detect_measures(
    image,
    detections: Sequence[dict] | None = None,
    max_width: int = DETECT_WIDTH,
    *,
    narrow_filter: bool = False,
) -> tuple[list[tuple[int, int, int, int]], list[tuple[int, int]], float]:
    """Measure boxes in reading order, the systems, and the scale from detection space to pixels."""
    rows, systems, scale = detect_rows(image, detections, max_width, narrow_filter=narrow_filter)
    flat = [cell for row in rows for cell in row]
    return flat, systems, scale


def collapse_blank_bands(
    image, *, min_fraction: float = BLANK_BAND_FRACTION, margin: int = 12
):
    """Remove page-layout gaps taller than ``min_fraction`` of the page height.

    A tall-page render spreads the systems over 30 inches, so the sheet was mostly white.  Removing
    the gaps (keeping a margin around the music) makes the two columns comparable at one glance
    without touching the notation.
    """
    numpy = _numpy()
    from PIL import Image

    gray = numpy.asarray(image.convert("L"))
    ink_rows = (gray < 200).any(axis=1)
    height = len(ink_rows)
    if height == 0 or not ink_rows.any():
        return image, []
    runs: list[tuple[int, int]] = []
    start = None
    for y, has_ink in enumerate(ink_rows):
        if not has_ink and start is None:
            start = y
        elif has_ink and start is not None:
            runs.append((start, y))
            start = None
    if start is not None:
        runs.append((start, height))
    removed = [(a, b) for a, b in runs if (b - a) > height * min_fraction]
    if not removed:
        return image, []
    keep = numpy.ones(height, dtype=bool)
    for a, b in removed:
        keep[a + margin : b - margin] = False
    rows = numpy.nonzero(keep)[0]
    segments: list[tuple[int, int]] = []
    segment_start = int(rows[0])
    previous = int(rows[0])
    for y in rows[1:]:
        if int(y) != previous + 1:
            segments.append((segment_start, previous + 1))
            segment_start = int(y)
        previous = int(y)
    segments.append((segment_start, previous + 1))
    total = sum(b - a for a, b in segments)
    canvas = Image.new(image.mode, (image.width, total), (255, 255, 255))
    top = 0
    for a, b in segments:
        canvas.paste(image.crop((0, a, image.width, b)), (0, top))
        top += b - a
    return canvas, removed


def ink_crop_box(image, margin: int = 26) -> tuple[int, int, int, int]:
    """The box that :func:`crop_to_ink` would cut; callers need it to shift detection coordinates."""
    from PIL import ImageOps

    gray = image.convert("L")
    box = ImageOps.invert(gray).getbbox()
    if not box:
        return (0, 0, image.width, image.height)
    left, top, right, bottom = box
    return (
        max(0, left - margin),
        max(0, top - margin),
        min(image.width, right + margin),
        min(image.height, bottom + margin),
    )


def crop_to_ink(image, margin: int = 26):
    """Trim the white margin so both columns start at the music."""
    return image.crop(ink_crop_box(image, margin))
