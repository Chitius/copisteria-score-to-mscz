"""Measure-level proof sheet: this page's render beside the scan, the same bars coloured.

The symbol heat map (:mod:`scorepipe.confidence`) answers "which glyph looks doubtful".  This
answers the other half: "do these bars say the same thing".  The left column is a MuseScore render
of **that page's** MusicXML, not of the merged score -- the merged score paginates differently, so
its page N is not the scan's page N.  Both columns tint the same bar in the same colour and carry
the same global measure number, so a reader compares a bar against the same bar.

Alignment is measured, never assumed.  On both images:

* a staff line is a row that is mostly ink; consecutive lines group into a staff;
* staves join into a system when a barline crosses the gap between them;
* a measure is the space between two full-height barlines inside a system.

The render must detect exactly as many measures as the page MusicXML declares.  When it does not,
nothing is overlaid and the sheet records ``render_layout_mismatch``: a wrong overlay would send
the reader to the wrong bar, which is worse than no overlay at all.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence
from xml.etree import ElementTree

from .confidence import summarise

RED = (214, 39, 40)
YELLOW = (255, 196, 0)
TINT_ALPHA = 46
RENDER_DPI = 110
DETECT_WIDTH = 1500
TALL_PAGE_HEIGHT = 30.0
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
        bucket = scores.setdefault(measure, {"measure": measure, "score": 0.0, "symbols": 0, "values": []})
        bucket["values"].append(result["score"])
        bucket["symbols"] += 1
    for bucket in scores.values():
        values = sorted(bucket.pop("values"), reverse=True)
        # One strong symbol is the signal; a second one in the same bar only backs it up a little.
        bucket["score"] = round(values[0] + (min(1.0, 0.4 * values[1]) if len(values) > 1 else 0.0), 3)
    return scores, unplaced


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


def _font(size: int):
    from PIL import ImageFont

    for name in ("DejaVuSans.ttf", "arial.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _badge(draw, text: str, box, colour, font) -> None:
    x0, y0, x1, _ = box
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    width = (right - left) + 14
    height = (bottom - top) + 10
    x = int(x0) + 2
    y = int(y0) - height - 4
    if y < 0:
        y = int(y0) + 2
    x = max(0, min(x, max(0, int(x1) - width)))
    draw.rounded_rectangle(
        (x, y, x + width, y + height), radius=6, fill=colour + (245,), outline=(255, 255, 255, 220)
    )
    draw.text((x + 7 - left, y + 5 - top), text, font=font, fill=(255, 255, 255, 255))


def annotate(image, cells: Sequence[tuple[int, int, int, int]], colours: dict[int, tuple], labels: dict[int, str]):
    """Tint the given cells (0-based index) and label them with the global measure number."""
    from PIL import Image, ImageDraw

    rgba = image.convert("RGBA")
    overlay = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = _font(max(13, round(22 * image.height / 1700)))
    thickness = max(2, font.size // 8)
    for index, colour in sorted(colours.items()):
        if index >= len(cells):
            continue
        box = cells[index]
        draw.rectangle(box, fill=colour + (TINT_ALPHA,), outline=colour + (210,), width=thickness)
        _badge(draw, labels.get(index, str(index + 1)), box, colour, font)
    return Image.alpha_composite(rgba, overlay).convert("RGB")


def stack(panels: Sequence):
    """Stack render pages into one column."""
    from PIL import Image

    if len(panels) == 1:
        return panels[0]
    gap = 12
    width = max(panel.width for panel in panels)
    height = sum(panel.height for panel in panels) + gap * (len(panels) - 1)
    canvas = Image.new("RGB", (width, height), (255, 255, 255))
    top = 0
    for panel in panels:
        canvas.paste(panel, (0, top))
        top += panel.height + gap
    return canvas


def compose(left, right, left_caption: str, right_caption: str, width: int = 900):
    """Put the two columns at one width with captions underneath."""
    from PIL import Image, ImageDraw

    def fit(panel):
        return panel.resize((width, max(1, round(panel.height * width / panel.width))), Image.LANCZOS)

    left, right = fit(left), fit(right)
    gap = 24
    caption_band = 54
    body = max(left.height, right.height)
    canvas = Image.new(
        "RGB", (width * 2 + gap, body + caption_band), (255, 255, 255)
    )
    canvas.paste(left, (0, 0))
    canvas.paste(right, (width + gap, 0))
    draw = ImageDraw.Draw(canvas)
    font = _font(15)
    draw.line((width + gap // 2, 0, width + gap // 2, body), fill=(200, 200, 200))
    draw.text((8, body + 8), left_caption, font=font, fill=(60, 60, 60))
    draw.text((width + gap + 8, body + 8), right_caption, font=font, fill=(60, 60, 60))
    return canvas


# ---------------------------------------------------------------------------
# one page
# ---------------------------------------------------------------------------


def build_sheet(
    page: SheetPage,
    out_dir: Path,
    *,
    musescore: str | None,
    report_path: Path | None = None,
    red_min: float = 2.0,
    yellow_min: float = 0.8,
    width: int = 900,
) -> dict:
    """Render the page, align both sides by measured bar count and write ``<stem>.sheet.png``."""
    from PIL import Image

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
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
        "unplaced_symbols": None,
        "red": [],
        "yellow": [],
        "length_issues": [],
        "render_measures": None,
        "scan_measures": None,
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
    measures = sorted(scores)
    red = [measure for measure in measures if scores[measure]["score"] >= red_min]
    yellow = [measure for measure in measures if yellow_min <= scores[measure]["score"] < red_min]
    lengths = length_measures(report_path, page.offset, expected)
    report["unplaced_symbols"] = unplaced
    report["red"] = [page.offset + measure for measure in red]
    report["yellow"] = [page.offset + measure for measure in yellow]
    report["length_issues"] = lengths

    colours: dict[int, tuple] = {}
    for measure in red:
        colours[measure - 1] = RED
    for measure in yellow:
        colours[measure - 1] = YELLOW
    labels = {index: str(page.offset + index + 1) for index in range(expected)}
    for measure in lengths:
        labels[measure - page.offset - 1] = f"{measure}≠"
    report["scan_measures"] = len(scan_cells)
    report["detections"] = str(page.dets) if detections else None

    left = None
    if musescore is None:
        warnings.append("MuseScore not found: the render column falls back to the scan")
        failures.append({"code": "render_unavailable", "message": "MuseScore not found"})
    else:
        try:
            render_dir = out_dir / "_render" / page.stem
            if render_dir.exists():
                shutil.rmtree(render_dir, ignore_errors=True)
            render_dir.mkdir(parents=True, exist_ok=True)
            panels = []
            flat: list[tuple[int, int, int, int]] = []
            offset_y = 0
            collapsed: list[tuple[int, int]] = []
            for path in render_page_musicxml(page.musicxml, musescore, render_dir):
                panel = crop_to_ink(Image.open(path).convert("RGB"))
                panel, removed = collapse_blank_bands(panel)
                collapsed.extend(removed)
                cells, _, _ = detect_measures(panel, narrow_filter=True)
                flat.extend(
                    (x0, y0 + offset_y, x1, y1 + offset_y) for x0, y0, x1, y1 in cells
                )
                panels.append(panel)
                offset_y += panel.height + 12  # matches the gap in stack()
            report["render_collapsed_bands"] = len(collapsed)
            report["render_measures"] = len(flat)
            if len(panels) > 1:
                warnings.append(f"the page MusicXML rendered as {len(panels)} pages; stacked in order")
            if len(flat) != expected:
                message = (
                    f"the render detected {len(flat)} measures but the page MusicXML declares "
                    f"{expected}; no overlay"
                )
                warnings.append(message)
                failures.append({"code": "render_layout_mismatch", "message": message})
                left = stack(panels)
            else:
                left = annotate(stack(panels), flat, colours, labels)
        except Exception as error:  # noqa: BLE001 - a renderer problem must not cost the sheet
            message = f"render failed: {error}"
            warnings.append(message)
            failures.append({"code": "render_failed", "message": message})
            left = None

    if left is None:
        left = scan_crop

    right = scan_crop
    if len(scan_cells) == expected:
        right = annotate(scan_crop, scan_cells, colours, labels)
        report["aligned"] = True
    else:
        message = (
            f"the scan detected {len(scan_cells)} measures but the page MusicXML declares "
            f"{expected}; the scan is not tinted"
        )
        warnings.append(message)
        failures.append({"code": "scan_layout_mismatch", "message": message})

    sheet = compose(
        left,
        right,
        f"render of {page.musicxml.name}",
        f"scan of {page.stem} (tinted bars are the ones to check)",
        width=width,
    )
    image_path = out_dir / f"{page.stem}.sheet.png"
    sheet.save(image_path)
    report["outputs"] = {"image": str(image_path), "json": str(out_dir / f"{page.stem}.sheet.json")}
    (out_dir / f"{page.stem}.sheet.json").write_text(
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


def review_sheets(pages: Sequence[SheetPage], out_dir: Path, **kwargs) -> dict:
    reports: list[dict] = []
    failures: list[dict] = []
    for page in pages:
        try:
            report = build_sheet(page, out_dir, **kwargs)
        except Exception as error:  # noqa: BLE001 - one page must not hide the others
            failures.append({"page": page.stem, "code": "page_failed", "message": str(error)})
            continue
        reports.append(report)
        failures.extend({"page": page.stem, **failure} for failure in report["failures"])
    issues = sum(len(report["red"]) + len(report["yellow"]) for report in reports)
    overall = status(issues, bool(failures))
    summary = {
        "status": overall,
        "pages": len(reports),
        "requested_pages": len(pages),
        "issues": issues,
        "failures": failures,
        "outputs": {"pages": [{"page": report["page"], **report["outputs"]} for report in reports]},
    }
    (Path(out_dir) / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (Path(out_dir) / "sheets.md").write_text(render_markdown(reports, summary), encoding="utf-8")
    return summary


def render_markdown(reports: Sequence[dict], summary: dict) -> str:
    lines = ["# Page proof sheets", "", f"Status: **{summary['status']}**.", ""]
    if summary["status"] == "incomplete":
        lines.append("Some pages could not be aligned; an unaligned sheet does not prove anything.")
        lines.append("")
    for report in reports:
        lines.append(f"## {report['page']}")
        lines.append("")
        lines.append(
            f"{report['measures_declared']} measure(s); {report['scan_measures']} detected on the "
            f"scan, {report['render_measures']} on the render; aligned: "
            f"{'yes' if report['aligned'] else 'no'}."
        )
        if report["red"] or report["yellow"]:
            lines.append("")
            lines.append(f"- red (check first): {report['red']}")
            lines.append(f"- yellow (check too): {report['yellow']}")
        if report["length_issues"]:
            lines.append(f"- measure length mismatch: {report['length_issues']}")
        for warning in report["warnings"]:
            lines.append(f"- warning: {warning}")
        lines.append("")
    return "\n".join(lines) + "\n"
