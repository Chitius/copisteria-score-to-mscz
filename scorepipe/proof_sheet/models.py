"""Shared constants, data types, and lazy dependency helpers for proof sheets."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

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

# Heads whose doubt can change what the bar says.  ``voice``, ``dots``, ``onset_p``, ``grace``,
# ``chord`` and ``tie`` are routine context fixes; they stay in the heat map and in ``score`` but
# do not tint a bar.
CONTENT_HEADS = {"cls", "pos", "alter", "tup", "real"}

A4_WIDTH = 2100
A4_HEIGHT = 2970

#: A barline sliver at the end of a system is a stroke, not a measure: the final double barline
#: emits two polylines and the right one sits on the staff edge (measured: 11 px beside a 460 px
#: bar).  Anything under this share of its system's median width is folded into the bar on its
#: left.  Real short final bars are well above it (the first/last bar of a system is short, but
#: still tens of percent of the median).
TRAILING_SLIVER_FRACTION = 0.20

CJK_RANGES = (
    (0x1100, 0x11FF),  # Hangul Jamo
    (0x2E80, 0x2FFF),  # CJK radicals
    (0x3000, 0x303F),  # CJK punctuation
    (0x3040, 0x30FF),  # kana
    (0x4E00, 0x9FFF),  # CJK unified
    (0xAC00, 0xD7AF),  # Hangul syllables
    (0xFF00, 0xFFEF),  # full-width forms
)

ROW_LABELS = (
    "confidence lowest: check for a wrong class/position or a missing/extra symbol",
    "confidence medium: an accidental, tuplet or position was rewritten",
)
LIST_LABELS = ("red", "yellow")
FOOTNOTE = (
    "Source: copisteria per-symbol posteriors and evidence. Colour is a reading order, not a "
    "verdict; an unmarked bar is not proven correct."
)

SHEET_PDF_SIZE = (3508, 2480)  # A4 landscape at 300 dpi
SHEET_PDF_DPI = 300
SHEET_FOOTER = 74


@dataclass(frozen=True)
class SheetPage:
    """One page: its scan, its own MusicXML, its reading, and the measures printed before it."""

    stem: str
    scan: Path
    musicxml: Path
    reading: Path
    offset: int = 0
    dets: Path | None = None


def _numpy():
    try:
        import numpy
    except ImportError as error:  # pragma: no cover - environment problem, reported by callers
        raise RuntimeError("numpy is required for the proof sheet") from error
    return numpy
