"""Measure-level proof sheet: this page's render beside the scan, the same bars coloured.

The symbol heat map (:mod:`scorepipe.confidence`) answers "which glyph looks doubtful".  This
answers the other half: "do these bars say the same thing".  The left column is a MuseScore render
of **that page's** MusicXML, not of the merged score -- the merged score paginates differently, so
its page N is not the scan's page N.  Both columns tint the same bar in the same colour and carry
the same global measure number, so a reader compares a bar against the same bar.

Alignment is measured, never assumed.  The render column now uses MuseScore's own SVG export:
``<polyline class="BarLine">`` elements carry the exact vector geometry, so barlines and systems are
read, not guessed.  The ink heuristic is kept only as a fallback when SVG export is unavailable.
On the scan (a raster, so no vector geometry exists):

* a staff line is a row that is mostly ink; consecutive lines group into a staff;
* staves join into a system when a barline crosses the gap between them;
* a measure is the space between two full-height barlines inside a system.

A bar is tinted only where both sides agree on its boundaries.  A trailing barline stroke (the
final double barline emits two polylines, the right one on the staff edge) is folded into the bar
on its left, so a page whose count was off by that stroke now aligns completely.  When the counts
still disagree, the sheet tints the trustworthy prefix -- systems compared in order, stopping at
the first system whose counts differ -- and records ``render_layout_mismatch`` /
``scan_layout_mismatch`` with the number of bars it could tint.  A wrong overlay would send the
reader to the wrong bar; an entirely uncoloured page throws away the bars that were never in doubt.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence
from xml.etree import ElementTree

from .confidence import summarise

RED = (214, 39, 40)
YELLOW = (235, 170, 0)
TINT_ALPHA = 64
# The printed packet is A4 at 300 dpi; the render is rasterised at the same density and the columns
# are wide enough that the sheet is close to 1:1 with the page (at 150 dpi it was a 118-dpi
# downscale and looked soft).
RENDER_DPI = 300
DETECT_WIDTH = 1500
TALL_PAGE_HEIGHT = 30.0
# MuseScore's SVG export writes exact barlines as ``<polyline class="BarLine">``; both staves of a
# grand staff emit their own segment, so the system is the union of the overlapping segments.
SVG_BARLINE = re.compile(r'<polyline class="BarLine"[^>]*?points="([^"]*)"')
SVG_VIEWBOX = re.compile(r'viewBox="([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+)"')
SVG_X_TOLERANCE = 8.0  # a double barline is two elements a few units apart
SVG_MIN_CELL = 12.0  # narrower than this is a sliver, not a measure
# The tiers are absolute: the same heads and weights everywhere, so a score means the same thing
# on every page.  Red is "a class or position was rewritten, or existence plus something else";
# yellow is "a routine context override, or a weak low-probability signal".
RED_MIN = 3.0
YELLOW_MIN = 1.5
# Column width in output pixels; DESIGN_WIDTH is the layout the type sizes were tuned at, so
# everything below scales with ``COLUMN_WIDTH / DESIGN_WIDTH``.
COLUMN_WIDTH = 1600
DESIGN_WIDTH = 900
COLUMN_GAP = 28
CAPTION_BAND = 96
LEGEND_MARGIN = 18
LEGEND_PAD = 12
BACKGROUND = (250, 250, 247)
# Barline vs stem: a barline is tall and has nothing beside it; a stem is tall with ink around.
COVER_FRAC = 0.40
SIDE_FRAC = 0.30
SIDE_CLEARANCE = 4
# A bar cannot be this much narrower than its neighbours in the same system.  MuseScore output
# sometimes gets a stem accepted as a barline; merging the sliver back is what turns 36 detected
# cells into the 32 the page MusicXML declares.
MIN_CELL_FRACTION = 0.55
# Blank bands taller than this share of the page are page-layout gaps, not music spacing.
BLANK_BAND_FRACTION = 0.05


@dataclass(frozen=True)
class SheetPage:
    """One page: its scan, its own MusicXML, its reading, and the measures printed before it."""

    stem: str
    scan: Path
    musicxml: Path
    reading: Path
    offset: int = 0
    dets: Path | None = None


# ---------------------------------------------------------------------------
# image geometry
# ---------------------------------------------------------------------------


def _numpy():
    try:
        import numpy
    except ImportError as error:  # pragma: no cover - environment problem, reported by callers
        raise RuntimeError("numpy is required for the proof sheet") from error
    return numpy


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


def measure_cells(
    ink, systems: Sequence[tuple[int, int]], *, narrow_filter: bool = False
) -> list[list[tuple[int, int, int, int]]]:
    """Per system, the cells between barlines detected from ink: ``(x0, y0, x1, y1)``."""
    height = ink.shape[0]
    cells: list[list[tuple[int, int, int, int]]] = []
    for top, bottom in systems:
        xs = _merge(barline_columns(ink, (top, bottom), height))
        row = [
            (xs[index], top, xs[index + 1], bottom)
            for index in range(len(xs) - 1)
            if xs[index + 1] - xs[index] > 12
        ]
        cells.append(_merge_narrow_cells(row) if narrow_filter else row)
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
    cells = measure_cells(ink, systems, narrow_filter=narrow_filter)
    scale = mask_to_image
    if detections:
        # The detections are the reader's own barlines: use them *instead of* the ink guess, not
        # merged with it.  Merging double-counts every stem the ink test happens to like (measured:
        # 32 -> 37 cells on one page, which then fails the count check for the wrong reason).
        scaled_systems = [tuple(round(value * scale) for value in system) for system in systems]
        rows = barline_columns_from_dets(detections, systems, scale)
        built = []
        for (top, bottom), xs in zip(scaled_systems, rows):
            row = [
                (xs[index], top, xs[index + 1], bottom)
                for index in range(len(xs) - 1)
                if xs[index + 1] - xs[index] > 12
            ]
            built.append(_merge_narrow_cells(row) if narrow_filter else row)
        cells = built
    systems_scaled = [tuple(round(value * scale) for value in system) for system in systems]
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


# ---------------------------------------------------------------------------
# what to colour
# ---------------------------------------------------------------------------


def reconcile_scan_rows(
    rows: Sequence[Sequence[tuple[int, int, int, int]]],
    systems: Sequence[tuple[int, int]],
    expected: int,
    reading: Path,
    *,
    origin: tuple[int, int] = (0, 0),
    right_edges: Sequence[int] | None = None,
) -> tuple[list[list[tuple[int, int, int, int]]], list[int], list[str]]:
    """Give a row the bars the reader knows it has, even when a barline was missed.

    The render side is exact (SVG geometry); the scan side depends on copisteria's barline
    detections and can miss one.  Two measured shapes:

    * the **final** barline of a system is missing (First Step page 1, system 1): the reader's
      change records still place a symbol past the last detected barline, so the row gets one more
      cell from that barline to the staff's right edge -- that edge *is* where the final barline
      stands, so this cell is not a guess;
    * an **internal** barline is missing: there is no evidence for the boundary, so the widest cell
      is split and both halves are returned as inferred; the sheet does not tint them.

    Everything after the repair keeps its measured boundaries, so one missed barline no longer
    throws away the whole page.
    """
    data = json.loads(Path(reading).read_text(encoding="utf-8"))
    origin_y = origin[1]
    system_bars: dict[int, set[int]] = {}
    bar_x: dict[int, dict[int, float]] = {}
    for entry in data.get("changes") or []:
        if entry.get("bar") is None or not entry.get("box"):
            continue
        y = (entry["box"][1] + entry["box"][3]) / 2 - origin_y
        system = next(
            (index for index, (top, bottom) in enumerate(systems) if top - 6 <= y <= bottom + 6),
            None,
        )
        if system is None:
            continue
        bar = int(entry["bar"])
        system_bars.setdefault(system, set()).add(bar)
        x = min(entry["box"][0], entry["box"][2]) - origin[0]
        slot = bar_x.setdefault(system, {})
        slot[bar] = min(slot.get(bar, float("inf")), x)

    result = [list(row) for row in rows]
    inferred_by_row: list[set[int]] = [set() for _ in result]
    notes: list[str] = []
    targets = []
    for index, row in enumerate(result):
        bars = system_bars.get(index) or set()
        targets.append(max(len(row), (max(bars) + 1) if bars else 0))
    total = sum(targets)
    while total > expected:
        candidates = [index for index in range(len(result)) if targets[index] > len(result[index])]
        if not candidates:
            break
        index = max(candidates, key=lambda item: targets[item] - len(result[item]))
        targets[index] -= 1
        total -= 1
    while total < expected:
        index = _widest_splittable_row(result)
        if index is None:
            break
        targets[index] += 1
        total += 1

    for index, row in enumerate(result):
        while len(row) < targets[index]:
            appended = _append_tail(row, index, systems, right_edges, bar_x.get(index) or {})
            if appended:
                notes.append(
                    f"system {index + 1}: closed the missed final barline at "
                    f"x={round(row[-1][2])}"
                )
                continue
            position = _split_widest(row)
            if position is None:
                break
            inferred_by_row[index].update({position - 1, position})
            notes.append(f"system {index + 1}: split a wide cell at x={round(row[position][0])}")

    offsets: list[int] = []
    running = 0
    for row in result:
        offsets.append(running)
        running += len(row)
    flat_inferred = sorted(
        offsets[index] + position
        for index, positions in enumerate(inferred_by_row)
        for position in positions
    )
    return result, flat_inferred, notes


def _append_tail(
    row: list[tuple[int, int, int, int]],
    index: int,
    systems: Sequence[tuple[int, int]],
    right_edges: Sequence[int] | None,
    bar_x: dict[int, float],
) -> bool:
    """Append a final cell when a bar's symbols start past the last detected barline."""
    if not row or right_edges is None or index >= len(right_edges):
        return False
    edge = int(right_edges[index])
    last = row[-1]
    if edge <= last[2] + 8:
        return False
    # A bar whose first symbol lies past the last barline proves the system continues.
    if not any(x > last[2] - 6 for x in bar_x.values()):
        return False
    row.append((last[2], last[1], edge, last[3]))
    return True


def _widest_splittable_row(rows: Sequence[list[tuple[int, int, int, int]]]) -> int | None:
    best: tuple[float, int] | None = None
    for index, row in enumerate(rows):
        if len(row) < 2:
            continue
        widths = sorted(cell[2] - cell[0] for cell in row)
        median = widths[len(widths) // 2] or 1
        widest = max(cell[2] - cell[0] for cell in row)
        if widest > median * 1.5 and (best is None or widest > best[0]):
            best = (float(widest), index)
    return best[1] if best else None


def _split_widest(row: list[tuple[int, int, int, int]]) -> int | None:
    """Split the widest cell one typical measure from its left edge; return the new index."""
    if len(row) < 2:
        return None
    widths = sorted(cell[2] - cell[0] for cell in row)
    median = widths[len(widths) // 2] or 1
    index = max(range(len(row)), key=lambda item: row[item][2] - row[item][0])
    cell = row[index]
    if cell[2] - cell[0] < median * 1.5:
        return None
    cut = min(max(cell[0] + median, cell[0] + 1), cell[2] - 1)
    row.insert(index + 1, (cut, cell[1], cell[2], cell[3]))
    row[index] = (cell[0], cell[1], cut, cell[3])
    return index + 1


def page_measure_count(musicxml: Path) -> int:
    root = ElementTree.parse(str(musicxml)).getroot()
    part = root.find("part")
    return len(part.findall("measure")) if part is not None else 0


def measure_scores(
    reading: Path,
    systems: Sequence[tuple[int, int]],
    offsets: Sequence[int],
    *,
    origin: tuple[int, int] = (0, 0),
    system_counts: Sequence[int] | None = None,
) -> tuple[dict[int, dict], int]:
    """Page measure (1-based) -> score bucket, plus how many suspects could not be placed.

    A change record carries the symbol's ``staff`` and ``bar``, and ``bar`` is **system-local**
    (measured on the Schubert page: 0..8 across five systems), so the bar has to be placed in its
    system first -- by the symbol's own y -- and only then added to the measures of the systems
    above it.  A bar index past the end of its system means the geometry and the OMR disagree; such
    a symbol is counted as unplaced rather than tinting a neighbouring bar.

    Two scores are kept per measure.  ``score`` is every suspect symbol (it orders the written
    priority list).  ``content_score`` keeps only symbols whose doubt can change the *content* --
    class, position, accidental, tuplet, existence -- because ``voice``/``dots`` reassignments are
    routine and the reader is usually right: on a dense piano page they occur on nearly every
    eighth note and made 33 of 40 bars tint (First Step page 2).  The sheet tints by
    ``content_score``; the heat map still shows every routine symbol.
    """
    data = json.loads(Path(reading).read_text(encoding="utf-8"))
    tokens = data.get("tokens") or {}
    changes = {int(entry["sym"]): entry for entry in data.get("changes") or []}
    counts = list(system_counts) if system_counts is not None else None
    scores: dict[int, dict] = {}
    unplaced = 0
    origin_x, origin_y = origin
    for key, token in tokens.items():
        result = summarise(token)
        if result["score"] <= 0:
            continue
        change = changes.get(int(key))
        if change is None or change.get("bar") is None or not change.get("box"):
            unplaced += 1
            continue
        x0, y0, x1, y1 = change["box"]
        center_y = (y0 + y1) / 2 - origin_y
        system = next(
            (index for index, (top, bottom) in enumerate(systems) if top - 6 <= center_y <= bottom + 6),
            None,
        )
        if system is None:
            unplaced += 1
            continue
        bar = int(change["bar"])
        if counts is not None and bar >= counts[system]:
            unplaced += 1
            continue
        measure = offsets[system] + bar + 1
        bucket = scores.setdefault(
            measure,
            {"measure": measure, "score": 0.0, "symbols": 0, "values": [], "content": []},
        )
        bucket["values"].append(result["score"])
        bucket["symbols"] += 1
        if _content_change(result["reasons"]):
            bucket["content"].append(result["score"])
    for bucket in scores.values():
        bucket["score"] = _tier_score(bucket.pop("values"))
        bucket["content_score"] = _tier_score(bucket.pop("content"))
    return scores, unplaced


# Heads whose doubt can change what the bar says.  ``voice``, ``dots``, ``onset_p``, ``grace``,
# ``chord`` and ``tie`` are routine context fixes; they stay in the heat map and in ``score`` but
# do not tint a bar.
CONTENT_HEADS = {"cls", "pos", "alter", "tup", "real"}


def _content_change(reasons: Sequence[dict]) -> bool:
    return any(reason.get("head") in CONTENT_HEADS for reason in reasons)


def _tier_score(values: Sequence[float]) -> float:
    """One strong symbol is the signal; a second one in the same bar only backs it up a little."""
    if not values:
        return 0.0
    ranked = sorted(values, reverse=True)
    return round(ranked[0] + (min(1.0, 0.4 * ranked[1]) if len(ranked) > 1 else 0.0), 3)



def length_measures(report_path: Path | None, offset: int, page_measures: int) -> list[int]:
    """Global measures with a measure-length violation that fall on this page."""
    if report_path is None or not Path(report_path).is_file():
        return []
    data = json.loads(Path(report_path).read_text(encoding="utf-8"))
    found = set()
    for violation in data.get("verifier") or []:
        if violation.get("code") not in ("measure-length", "mscx-measure-length"):
            continue
        measure = violation.get("measure")
        if not isinstance(measure, int):
            continue
        if 1 <= measure - offset <= page_measures:
            found.add(measure)
    return sorted(found)


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def fit_cells_to_count(
    rows: Sequence[Sequence[tuple[int, int, int, int]]],
    expected: int,
    fraction: float = 0.70,
) -> tuple[list[list[tuple[int, int, int, int]]], int]:
    """Fold the narrowest interior cells until the count reaches ``expected``.

    Used only when the detector found *more* cells than the page declares: the extra ones are
    stems read as barlines, and the narrowest cells are the suspects.  It never invents a cell, so
    a page that genuinely has fewer bars than its MusicXML still fails the count check.  Every fold
    is counted and reported, and a fold needs the cell to be under ``fraction`` of its system's
    median width -- if nothing qualifies, the mismatch stands.
    """
    merged = [list(row) for row in rows]
    folded = 0
    while sum(len(row) for row in merged) > expected:
        best: tuple[float, int, int] | None = None
        for row_index, row in enumerate(merged):
            if len(row) < 3:
                continue
            widths = sorted(cell[2] - cell[0] for cell in row)
            median = widths[len(widths) // 2] or 1
            for cell_index in range(1, len(row) - 1):
                width = row[cell_index][2] - row[cell_index][0]
                if width < median * fraction and (best is None or width < best[0]):
                    best = (float(width), row_index, cell_index)
        if best is None:
            break
        _, row_index, cell_index = best
        row = merged[row_index]
        row[cell_index - 1] = (
            row[cell_index - 1][0],
            row[cell_index - 1][1],
            row[cell_index][2],
            row[cell_index - 1][3],
        )
        del row[cell_index]
        folded += 1
    return merged, folded


A4_WIDTH = 2100
A4_HEIGHT = 2970

#: A barline sliver at the end of a system is a stroke, not a measure: the final double barline
#: emits two polylines and the right one sits on the staff edge (measured: 11 px beside a 460 px
#: bar).  Anything under this share of its system's median width is folded into the bar on its
#: left.  Real short final bars are well above it (the first/last bar of a system is short, but
#: still tens of percent of the median).
TRAILING_SLIVER_FRACTION = 0.20


def _system_groups(cells: Sequence[Sequence[float]]) -> list[list[tuple[float, float, float, float]]]:
    """Split cells into systems; consecutive cells sharing a y band belong to one system."""
    groups: list[list[tuple[float, float, float, float]]] = []
    previous: tuple[int, int] | None = None
    for cell in cells:
        key = (round(cell[1]), round(cell[3]))
        if key != previous:
            groups.append([])
            previous = key
        groups[-1].append(tuple(float(value) for value in cell[:4]))
    return groups


def system_counts(cells: Sequence[Sequence[float]]) -> list[int]:
    """Cells per system, using the y band each cell occupies as the system identity."""
    return [len(group) for group in _system_groups(cells)]


def _trailing_extra(
    cells: Sequence[Sequence[float]], kept: int, fraction: float = 0.15
) -> bool:
    """True when everything after ``kept`` is a narrow stroke appended at the right edge.

    That is the shape of a final-barline stroke or a duplicate closing cell: it is appended after
    the real bar, not inserted inside it, so the first ``kept`` cells still line up.  The width
    guard keeps a sliver that *splits* a bar from being read as an appended cell.
    """
    if kept <= 0 or len(cells) <= kept:
        return False
    edge = cells[kept - 1][2]
    widths = sorted(cell[2] - cell[0] for cell in cells)
    median = widths[len(widths) // 2] or 1.0
    return all(
        cell[0] >= edge - 2 and (cell[2] - cell[0]) < median * fraction
        for cell in cells[kept:]
    )


def fold_trailing_slivers(
    cells: Sequence[Sequence[float]],
    expected: int,
    fraction: float = TRAILING_SLIVER_FRACTION,
) -> tuple[list[tuple[float, float, float, float]], int]:
    """Fold barline-stroke cells at the *end* of a system into the cell on their left.

    Only runs while the total exceeds ``expected``, so a page whose count already matches is never
    touched.  The suspect has to be the last cell of its system and narrower than ``fraction`` of
    that system's median width; it is merged, never dropped, so the bar it belonged to keeps its
    right edge.  This is the tail counterpart of :func:`fit_cells_to_count`, which only folds
    interior cells.
    """
    folded = [tuple(float(value) for value in cell[:4]) for cell in cells]
    operations = 0
    while len(folded) > expected:
        counts = system_counts(folded)
        if not counts:
            break
        # Rebuild system groups with their index ranges.
        groups: list[tuple[int, int]] = []
        start = 0
        for count in counts:
            groups.append((start, start + count))
            start += count
        best: tuple[float, int, int] | None = None
        for first, last in groups:
            if last - first < 2:
                continue
            widths = sorted(folded[index][2] - folded[index][0] for index in range(first, last))
            median = widths[len(widths) // 2] or 1.0
            candidate = last - 1
            width = folded[candidate][2] - folded[candidate][0]
            if width < median * fraction and (best is None or width < best[0]):
                best = (float(width), first, last)
        if best is None:
            break
        _, first, last = best
        tail = last - 1
        left = folded[tail - 1]
        folded[tail - 1] = (left[0], left[1], folded[tail][2], left[3])
        del folded[tail]
        operations += 1
    return folded, operations


def common_prefix_measures(
    render_cells: Sequence[Sequence[float]],
    scan_cells: Sequence[Sequence[float]],
    expected: int,
) -> int:
    """How many measures can be tinted on both sides before the bar counts disagree.

    Systems are compared in order; a system whose two counts differ ends the trustworthy prefix,
    because from there on the measure numbers may be shifted.  The one tolerated exception is the
    *last* system with extra cells appended at its right edge (the final-barline case): those sit
    after the real bars, so the shorter side still lines up and is tinted.
    """
    render_groups = _system_groups(render_cells)
    scan_groups = _system_groups(scan_cells)
    last = min(len(render_groups), len(scan_groups)) - 1
    total = 0
    for index, (render, scan) in enumerate(zip(render_groups, scan_groups)):
        if len(render) == len(scan):
            total += len(render)
        elif len(render) > len(scan) and index == last and _trailing_extra(render, len(scan)):
            total += len(scan)
        elif len(scan) > len(render) and index == last and _trailing_extra(scan, len(render)):
            total += len(render)
        else:
            break
        if total >= expected:
            break
    return min(total, expected)



def _position_credit(credit) -> None:
    """Give a credit-words element the page-1 position MuseScore needs to draw it at the top.

    MuseScore stacks a credit without ``default-y`` at the bottom of the page (measured: a garbled
    strip under the last system), so the copied credits are placed like the previous skill's
    ``write_credits``: title centred near the top, composer right-aligned under it.
    """
    words = credit.find("credit-words")
    if words is None or words.get("default-y"):
        return
    kind = (credit.findtext("credit-type") or "title").strip()
    if kind == "title":
        x, y, justify, size = A4_WIDTH // 2, A4_HEIGHT - 170, "center", "28"
    elif kind == "subtitle":
        x, y, justify, size = A4_WIDTH // 2, A4_HEIGHT - 260, "center", "16"
    elif kind == "lyricist":
        x, y, justify, size = A4_WIDTH - 150, A4_HEIGHT - 250, "right", "12"
    elif kind == "arranger":
        x, y, justify, size = A4_WIDTH - 150, A4_HEIGHT - 330, "right", "12"
    else:
        x, y, justify, size = A4_WIDTH - 150, A4_HEIGHT - 250, "right", "12"
    words.set("default-x", str(x))
    words.set("default-y", str(y))
    words.set("justify", justify)
    words.set("valign", "top")
    words.set("font-size", size)


def copy_header(source: Path, page: Path, target: Path) -> list[tuple[str, str]]:
    """Copy ``work``/``identification``/``credit`` from the merged score into a page copy.

    A page MusicXML is what the reader wrote for that page; the title block lives in the merged
    score (``apply_credits_facts``) or was copied into the first page by the conversion step.  The
    sheet renders each page on its own, so without this the first page's render has no title while
    the scan does.  Only header elements are copied -- notes are never touched.

    Returns the ``(credit-type, credit-words)`` pairs that were added.
    """
    import copy as copy_module
    from xml.etree import ElementTree

    source_root = ElementTree.parse(str(source)).getroot()
    page_root = ElementTree.parse(str(page)).getroot()
    added: list[tuple[str, str]] = []

    for index, tag in enumerate(("work", "identification")):
        element = source_root.find(tag)
        if element is None:
            continue
        existing = page_root.find(tag)
        if existing is not None:
            page_root.remove(existing)
        # MusicXML order: work, movement-number, movement-title, identification, ..., credit,
        # part-list.  Insert by position so `identification` never lands before `work`.
        page_root.insert(index, copy_module.deepcopy(element))

    credits = source_root.findall("credit")
    if credits:
        for credit in page_root.findall("credit"):
            page_root.remove(credit)
        part_list = page_root.find("part-list")
        index = list(page_root).index(part_list) if part_list is not None else len(page_root)
        copied = []
        for credit in credits:
            element = copy_module.deepcopy(credit)
            element.set("page", element.get("page") or "1")
            _position_credit(element)
            page_root.insert(index, element)
            index += 1
            copied.append(element)
        # MuseScore puts every right-justified credit on the same baseline, so a separate composer
        # and arranger line print on top of each other ("Hans Zimmer" over "PianiCast").  Join them
        # into one credit with a newline, which is how its own title frame spells the pair.
        _join_role_credits(page_root, copied)
        added = [
            (
                (element.findtext("credit-type") or "").strip(),
                (element.findtext("credit-words") or "").strip(),
            )
            for element in copied
            if element in list(page_root)
        ]

    ElementTree.ElementTree(page_root).write(target, encoding="utf-8", xml_declaration=True)
    return added


def _join_role_credits(root, credits: list) -> None:
    """Merge composer/arranger/transcriber credits into the first one, newline-separated."""
    roles = [
        credit
        for credit in credits
        if (credit.findtext("credit-type") or "").strip() in ("composer", "arranger", "transcriber")
        and credit.find("credit-words") is not None
    ]
    if len(roles) < 2:
        return
    first = roles[0]
    words = first.find("credit-words")
    lines = []
    for credit in roles:
        text = (credit.find("credit-words").text or "").strip()
        if text:
            lines.append(text)
    if not lines:
        return
    words.text = "\n".join(lines)
    for credit in roles[1:]:
        root.remove(credit)


def render_page_svg(musicxml: Path, musescore: str, out_dir: Path) -> list[Path]:
    """Export the page's MusicXML to SVG; MuseScore writes the exact barline geometry into it."""
    pages = _render_svg(musicxml, musescore, out_dir, tall=False)
    if len(pages) > 1:
        pages = _render_svg(musicxml, musescore, out_dir, tall=True)
    return pages


def _render_svg(musicxml: Path, musescore: str, out_dir: Path, *, tall: bool) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{musicxml.stem}_svg.svg"
    for stale in list(out_dir.glob(f"{musicxml.stem}_svg-*.svg")) + [target]:
        stale.unlink(missing_ok=True)
    extra: list[str] = []
    if tall:
        style = out_dir / "onepage.mss"
        style.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<museScore version="4.00">\n  <Style>\n'
            "    <pageWidth>8.27</pageWidth>\n"
            f"    <pageHeight>{TALL_PAGE_HEIGHT:.2f}</pageHeight>\n"
            "    <spatium>1.35</spatium>\n"
            "  </Style>\n</museScore>\n",
            encoding="utf-8",
        )
        extra = ["-S", str(style)]
    completed = subprocess.run(
        [musescore, "-f", *extra, "-o", str(target), str(musicxml)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    pages = sorted(out_dir.glob(f"{musicxml.stem}_svg-*.svg"))
    if not pages and target.is_file():
        pages = [target]
    if not pages:
        raise RuntimeError(
            f"MuseScore wrote no SVG for {musicxml.name}: {(completed.stderr or '').strip()[:300]}"
        )
    return pages


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


def render_page_musicxml(musicxml: Path, musescore: str, out_dir: Path) -> list[Path]:
    """Render one page's MusicXML; retry on a tall page when MuseScore splits it in two."""
    pages = _render(musicxml, musescore, out_dir, tall=False)
    if len(pages) > 1:
        pages = _render(musicxml, musescore, out_dir, tall=True)
    return pages


def _render(musicxml: Path, musescore: str, out_dir: Path, *, tall: bool) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf = out_dir / f"{musicxml.stem}.pdf"
    for stale in list(out_dir.glob(f"{musicxml.stem}_render-*.png")) + [pdf]:
        stale.unlink(missing_ok=True)
    extra: list[str] = []
    if tall:
        style = out_dir / "onepage.mss"
        style.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<museScore version="4.00">\n  <Style>\n'
            "    <pageWidth>8.27</pageWidth>\n"
            f"    <pageHeight>{TALL_PAGE_HEIGHT:.2f}</pageHeight>\n"
            "    <spatium>1.35</spatium>\n"
            "  </Style>\n</museScore>\n",
            encoding="utf-8",
        )
        extra = ["-S", str(style)]
    completed = subprocess.run(
        [musescore, "-f", *extra, "-o", str(pdf), str(musicxml)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if not pdf.is_file():
        raise RuntimeError(
            f"MuseScore wrote no PDF for {musicxml.name}: {(completed.stderr or '').strip()[:300]}"
        )
    prefix = out_dir / f"{musicxml.stem}_render"
    rasterize = shutil.which("pdftoppm")
    if not rasterize:
        raise RuntimeError("pdftoppm is required to rasterise the render")
    raster = subprocess.run(
        [rasterize, "-r", str(RENDER_DPI), "-png", str(pdf), str(prefix)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    pages = sorted(out_dir.glob(f"{prefix.name}-*.png"))
    if raster.returncode != 0 or not pages:
        raise RuntimeError(f"pdftoppm failed for {pdf.name}: {(raster.stderr or '').strip()[:300]}")
    return pages


# ---------------------------------------------------------------------------
# drawing
# ---------------------------------------------------------------------------


def _font(size: int, text: str | None = None):
    """A font that can actually render ``text`` (CJK/Hangul files otherwise print as boxes)."""
    from PIL import ImageFont

    names = ["DejaVuSans.ttf", "arial.ttf", "segoeui.ttf"]
    if text and _needs_cjk(text):
        names = [
            "malgun.ttf",  # Windows Korean
            "malgunbd.ttf",
            "msyh.ttc",  # Windows Chinese
            "simsun.ttc",
            "YuGothR.ttc",  # Windows Japanese
            "msgothic.ttc",
        ] + names
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


CJK_RANGES = (
    (0x1100, 0x11FF),  # Hangul Jamo
    (0x2E80, 0x2FFF),  # CJK radicals
    (0x3000, 0x303F),  # CJK punctuation
    (0x3040, 0x30FF),  # kana
    (0x4E00, 0x9FFF),  # CJK unified
    (0xAC00, 0xD7AF),  # Hangul syllables
    (0xFF00, 0xFFEF),  # full-width forms
)


def _needs_cjk(text: str) -> bool:
    return any(
        any(low <= ord(character) <= high for low, high in CJK_RANGES) for character in text
    )



def _badge(draw, text: str, box, colour, font, ink=None, image_size=None) -> None:
    """A filled badge above the measure, nudged until it covers no ink.

    A filled badge with white text is what the previous skill drew, and it stays readable over
    staff lines.  The nudge order matters: shift right first, then up, and stop at the bar's own
    right edge -- a label that drifts onto the neighbouring bar is worse than one that overlaps.
    """
    left, upper, right, lower = draw.textbbox((0, 0), text, font=font)
    text_width, text_height = right - left, lower - upper
    width_px = text_width + int(font.size * 0.7)
    height_px = text_height + int(font.size * 0.45)
    x0, y0, x1, _ = (int(value) for value in box)
    x = x0 + 2
    y = max(0, y0 - height_px - max(6, int(font.size * 0.55)))
    max_x = x1 - width_px + 6

    def ink_share(candidate: tuple[int, int]) -> float:
        if ink is None or image_size is None:
            return 0.0
        cx, cy = candidate
        x0c, y0c = max(0, cx), max(0, cy)
        x1c, y1c = min(image_size[0], cx + width_px), min(image_size[1], cy + height_px)
        if x1c <= x0c or y1c <= y0c:
            return 1.0
        patch = ink[y0c:y1c, x0c:x1c]
        return float(patch.mean()) if patch.size else 1.0

    for dx, dy in [(0, 0)] + [(int(width_px * step), 0) for step in (0.8, 1.6, 2.4)] + [(0, -int(height_px * 1.5))]:
        bx, by = x + dx, y + dy
        if bx < 0 or by < 0 or image_size is None:
            continue
        if bx + width_px > image_size[0] or by + height_px > image_size[1]:
            continue
        if max_x is not None and bx > max_x:
            continue
        if ink_share((bx, by)) < 0.04:
            x, y = bx, by
            break
    draw.rounded_rectangle(
        (x, y, x + width_px, y + height_px),
        radius=max(3, font.size // 5),
        fill=colour + (240,),
        outline=(255, 255, 255, 210),
        width=max(1, font.size // 12),
    )
    draw.text(
        (x + (width_px - text_width) / 2 - left, y + (height_px - text_height) / 2 - upper),
        text,
        font=font,
        fill=(255, 255, 255, 255),
    )


def annotate(
    image,
    cells: Sequence[tuple[int, int, int, int]],
    colours: dict[int, tuple],
    labels: dict[int, str],
):
    """Tint the given cells (0-based index) and label them with the global measure number."""
    numpy = _numpy()
    from PIL import Image, ImageDraw

    rgba = image.convert("RGBA")
    ink = numpy.asarray(image.convert("L")) < 190
    overlay = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = _font(max(13, round(22 * image.height / 1700)))
    thickness = max(2, font.size // 8)
    for index, colour in sorted(colours.items()):
        if index >= len(cells):
            continue
        box = cells[index]
        draw.rectangle(box, fill=colour + (TINT_ALPHA,), outline=colour + (210,), width=thickness)
        _badge(draw, labels.get(index, str(index + 1)), box, colour, font, ink=ink, image_size=image.size)
    return Image.alpha_composite(rgba, overlay).convert("RGB")


def stack(panels: Sequence):
    """Stack render pages into one column, keeping each panel's y offset."""
    from PIL import Image

    if len(panels) == 1:
        return panels[0], [0]
    width = max(panel.width for panel in panels)
    height = sum(panel.height for panel in panels) + 24 * (len(panels) - 1)
    canvas = Image.new("RGB", (width, height), BACKGROUND)
    offsets = []
    top = 0
    for panel in panels:
        canvas.paste(panel, (0, top))
        offsets.append(top)
        top += panel.height + 24
    return canvas, offsets


ROW_LABELS = (
    "confidence lowest: check for a wrong class/position or a missing/extra symbol",
    "confidence medium: an accidental, tuplet or position was rewritten",
)
LIST_LABELS = ("red", "yellow")
FOOTNOTE = (
    "Source: copisteria per-symbol posteriors and evidence. Colour is a reading order, not a "
    "verdict; an unmarked bar is not proven correct."
)


def legend_size(canvas, red: int, yellow: int, length_count: int, font, small, *, scale: float = 1.0) -> tuple[int, int]:
    """Wide enough for its longest line, so the text never spills out of the box."""
    from PIL import ImageDraw

    pad = round(LEGEND_PAD * scale)
    gap = round(28 * scale)
    probe = ImageDraw.Draw(canvas)
    rows = list(ROW_LABELS)
    if length_count:
        rows.append("also: bars whose voices do not add up to the metre (badge has ≠)")
    width = max(
        max(probe.textlength(text, font=font) for text in rows) + 2 * gap + round(16 * scale),
        probe.textlength(FOOTNOTE, font=small),
    )
    big = probe.textbbox((0, 0), rows[0], font=font)
    small_box = probe.textbbox((0, 0), FOOTNOTE, font=small)
    height = (
        2 * pad
        + len(rows) * (big[3] - big[1] + round(6 * scale))
        + round(8 * scale)
        + (small_box[3] - small_box[1])
    )
    return int(width) + 2 * pad + round(8 * scale), int(height)


def draw_legend(canvas, box, red: int, yellow: int, length_count: int, font, small, *, scale: float = 1.0) -> None:
    from PIL import ImageDraw

    pad = round(LEGEND_PAD * scale)
    gap = round(8 * scale)
    swatch_min = round(12 * scale)
    radius = max(4, round(8 * scale))
    outline = max(1, round(2 * scale))
    draw = ImageDraw.Draw(canvas, "RGBA")
    x0, y0, _, _ = box
    draw.rounded_rectangle(box, radius=radius, fill=(255, 255, 255, 236), outline=(150, 150, 150, 255), width=1)

    def row(text: str, colour: tuple[int, int, int], top: int) -> int:
        left, upper, right, lower = draw.textbbox((0, 0), text, font=font)
        text_height = lower - upper
        swatch = max(swatch_min, text_height)
        centre = top + text_height / 2
        draw.rectangle(
            (x0 + pad, centre - swatch / 2, x0 + pad + swatch, centre + swatch / 2),
            fill=colour + (80,),
            outline=colour + (220,),
            width=outline,
        )
        draw.text((x0 + pad + swatch + gap, top - upper), text, font=font, fill=(30, 30, 30, 255))
        return int(text_height) + round(6 * scale)

    line_height = row(ROW_LABELS[0], RED, y0 + pad)
    line_height = row(ROW_LABELS[1], YELLOW, y0 + pad + line_height)
    top = y0 + pad + 2 * line_height
    if length_count:
        top += row("also: bars whose voices do not add up to the metre (badge has ≠)", (28, 32, 40), top)
    draw.text((x0 + pad, top + gap), FOOTNOTE, font=small, fill=(90, 90, 90, 255))


def compose(
    left,
    right,
    left_caption: str,
    right_caption: str,
    *,
    red: int,
    yellow: int,
    length_count: int,
    width: int = COLUMN_WIDTH,
):
    """Two columns at one width, captions under each, legend in the caption band.

    Type sizes and paddings were tuned at ``DESIGN_WIDTH``; everything scales with the requested
    column width so a 300-dpi sheet does not end up with 15 px captions.
    """
    from PIL import Image, ImageDraw

    scale = width / DESIGN_WIDTH
    gap = round(COLUMN_GAP * scale)
    caption_band = round(CAPTION_BAND * scale)
    legend_margin = round(LEGEND_MARGIN * scale)

    def fit(panel):
        return panel.resize((width, max(1, round(panel.height * width / panel.width))), Image.LANCZOS)

    left, right = fit(left), fit(right)
    body = max(left.height, right.height)
    right_x = width + gap
    canvas = Image.new("RGB", (right_x + width, body + caption_band), BACKGROUND)
    canvas.paste(left, (0, 0))
    canvas.paste(right, (right_x, 0))

    draw = ImageDraw.Draw(canvas)
    rule_y = body + round(20 * scale)
    caption_font = _font(round(24 * scale))
    caption_ink = (72, 72, 68)
    for x, text in ((0, left_caption), (right_x, right_caption)):
        inset = round(44 * scale)
        draw.line((x + inset, rule_y, x + width - inset, rule_y), fill=(206, 204, 197), width=1)
        left_box = draw.textbbox((0, 0), text, font=caption_font)
        text_width = left_box[2] - left_box[0]
        draw.text(
            (x + (width - text_width) / 2 - left_box[0], rule_y + round(16 * scale) - left_box[1]),
            text,
            font=caption_font,
            fill=caption_ink,
        )
    draw.line(
        (right_x - gap // 2, 0, right_x - gap // 2, body + caption_band - round(24 * scale)),
        fill=(232, 230, 223),
    )

    font = _font(round(20 * scale))
    small = _font(round(15 * scale))
    legend_w, legend_h = legend_size(canvas, red, yellow, length_count, font, small, scale=scale)
    band_height = caption_band + legend_h + round(24 * scale)
    extended = Image.new("RGB", (canvas.width, body + band_height), BACKGROUND)
    extended.paste(canvas, (0, 0))
    canvas = extended
    draw = ImageDraw.Draw(canvas)
    draw.line(
        (right_x - gap // 2, 0, right_x - gap // 2, body + band_height - round(24 * scale)),
        fill=(232, 230, 223),
    )
    draw_legend(
        canvas,
        (legend_margin, body + caption_band + round(6 * scale), legend_margin + legend_w, body + caption_band + round(6 * scale) + legend_h),
        red,
        yellow,
        length_count,
        font,
        small,
        scale=scale,
    )
    return canvas


# ---------------------------------------------------------------------------
# one page
# ---------------------------------------------------------------------------


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
) -> dict:
    """Render the page, align both sides by measured bar count and write ``<stem>.compare.png``."""
    from PIL import Image

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = analysis["report"]
    scan_crop = analysis["scan"]
    scan_cells = analysis["cells"]
    scores = analysis["scores"]
    expected = analysis["expected"]
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
    report["red"] = [page.offset + measure for measure in red]
    report["yellow"] = [page.offset + measure for measure in yellow]

    colours: dict[int, tuple] = {}
    for measure in red:
        colours[measure - 1] = RED
    for measure in yellow:
        colours[measure - 1] = YELLOW
    labels = {index: str(page.offset + index + 1) for index in range(expected)}
    for measure in lengths:
        labels[measure - page.offset - 1] = f"{measure}≠"

    left = None
    render_cells: list[tuple[float, float, float, float]] = []
    if musescore is None:
        warnings.append("MuseScore not found: the render column falls back to the scan")
        failures.append({"code": "render_unavailable", "message": "MuseScore not found"})
    else:
        try:
            render_dir = out_dir / "_render" / page.stem
            if render_dir.exists():
                shutil.rmtree(render_dir, ignore_errors=True)
            render_dir.mkdir(parents=True, exist_ok=True)
            source_xml = page.musicxml
            if page.offset == 0 and title_source is not None and Path(title_source).is_file():
                titled = render_dir / "with-title.musicxml"
                injected = copy_header(Path(title_source), page.musicxml, titled)
                if injected:
                    source_xml = titled
                    report["title_injected"] = injected
                    warnings.append(
                        "first page: title/credit block copied from "
                        f"{Path(title_source).name} before rendering ({len(injected)} credit(s))"
                    )
            panels = []
            collapsed: list[tuple[int, int]] = []
            png_pages = render_page_musicxml(source_xml, musescore, render_dir)
            svg_pages: list[Path] = []
            try:
                svg_pages = render_page_svg(source_xml, musescore, render_dir)
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
                cells_by_panel, folded = fit_cells_to_count(plain_by_panel, expected)
                if folded:
                    report["slivers_merged"] = folded
            report["render_measures_detected"] = plain_total
            stacked, panel_offsets = stack(panels)
            flat: list[tuple[int, int, int, int]] = []
            for cells, offset_y in zip(cells_by_panel, panel_offsets):
                flat.extend((x0, y0 + offset_y, x1, y1 + offset_y) for x0, y0, x1, y1 in cells)
            flat, slivers = fold_trailing_slivers(flat, expected)
            if slivers:
                report["trailing_slivers_folded"] = slivers
                warnings.append(
                    f"folded {slivers} trailing barline sliver(s) into the bar on their left"
                )
            report["render_measures"] = len(flat)
            if len(panels) > 1:
                warnings.append(f"the page MusicXML rendered as {len(panels)} pages; stacked in order")
            render_cells = flat
            left = stacked
        except Exception as error:  # noqa: BLE001 - a renderer problem must not cost the sheet
            message = f"render failed: {error}"
            warnings.append(message)
            failures.append({"code": "render_failed", "message": message})
            left = None

    if left is None:
        left = scan_crop

    # Tint as much as both columns agree on, not "all or nothing".  A page whose last bar was
    # mis-detected still has a trustworthy prefix: an uncoloured page tells the reviewer less
    # than a page with the verified bars coloured and the tail left plain.
    render_ok = bool(render_cells) and len(render_cells) == expected
    scan_ok = len(scan_cells) == expected
    report["render_aligned"] = render_ok
    report["scan_aligned"] = scan_ok
    report["render_available"] = bool(render_cells)
    if render_ok and scan_ok:
        tint = expected
    elif render_cells:
        tint = common_prefix_measures(render_cells, scan_cells, expected)
    else:
        # MusicXML-only run: there is no render column to compare with, so only the scan's own
        # bar count can be trusted.
        tint = expected if scan_ok else 0
    report["aligned"] = render_ok and scan_ok
    report["tinted_measures"] = tint
    report["partial"] = (not report["aligned"]) and tint > 0

    if render_cells and not render_ok:
        message = (
            f"the render detected {len(render_cells)} measures but the page MusicXML declares "
            f"{expected}; "
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
        left = annotate(stacked, render_cells[:tint], colours, labels)
    right = annotate(scan_crop, scan_cells[:tint], colours, labels) if tint else scan_crop

    sheet = compose(
        left,
        right,
        f"OMR result \u00b7 MuseScore re-engraving of {page.musicxml.name}",
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


# ---------------------------------------------------------------------------
# the whole run
# ---------------------------------------------------------------------------


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


def read_score_title(musicxml: Path | str | None) -> str | None:
    """The ``title`` credit of a MusicXML file, if it has one."""
    if musicxml is None:
        return None
    path = Path(musicxml)
    if not path.is_file():
        return None
    try:
        root = ElementTree.parse(str(path)).getroot()
    except ElementTree.ParseError:
        return None
    for credit in root.findall("credit"):
        if (credit.findtext("credit-type") or "").strip() != "title":
            continue
        words = credit.find("credit-words")
        if words is not None and (words.text or "").strip():
            return words.text.strip()
    return None


SHEET_PDF_SIZE = (3508, 2480)  # A4 landscape at 300 dpi
SHEET_PDF_DPI = 300
SHEET_FOOTER = 74


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
    import datetime

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
    draw.text(
        (margin, note_y),
        "Left column: MuseScore re-engraving of that page's MusicXML. Right column: the original scan.",
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
            pages.append(build_cover_page(title, source_name, entries, size=target))
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
) -> dict:
    """Analyze every page first, then build the sheets; the ranking is score-wide."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    failures: list[dict] = []
    skipped: list[dict] = []

    analyses: list[tuple[SheetPage, dict]] = []
    for page in pages:
        try:
            analyses.append((page, analyze_page(page, report_path)))
        except Exception as error:  # noqa: BLE001 - one page must not stop the score
            failures.append({"page": page.stem, "code": "page_analysis_failed", "message": str(error)})
            skipped.append({"page": page.stem, "reason": str(error)})

    reports: list[dict] = []
    for page, analysis in analyses:
        try:
            report = build_sheet(
                page,
                analysis,
                out_dir,
                musescore=musescore,
                red_min=red_min,
                yellow_min=yellow_min,
                width=width,
                title_source=title_source,
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
    overall = status(issue_total, bool(failures or skipped))
    summary = {
        "status": overall,
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
    combined = write_sheet_pdf(
        [report["outputs"]["image"] for report in reports],
        out_dir / "review-sheets.pdf",
        title=title or read_score_title(title_source),
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
    )
    if combined is not None:
        summary["outputs"]["pdf"] = str(combined)
        summary["pdf_cover"] = {
            "title": title or read_score_title(title_source),
            "source": source_name,
            "pages": len(reports),
        }
    write_priority_list(reports, out_dir, summary)
    (out_dir / "review_sheet_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return summary
