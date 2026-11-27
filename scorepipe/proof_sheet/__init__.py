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

from .alignment import (
    common_prefix_measures,
    fit_cells_to_count,
    fold_trailing_slivers,
    reconcile_scan_rows,
    system_counts,
)
from .compose import annotate, compose, draw_legend, legend_size, stack
from .geometry import (
    _merge_narrow_cells as _merge_narrow_cells,
    barline_columns,
    barline_columns_from_dets,
    collapse_blank_bands,
    crop_to_ink,
    detect_measures,
    detect_rows,
    ink_crop_box,
    ink_mask,
    longest_run,
    measure_cells,
    staff_bands,
    systems_from_ink,
)
from .models import (
    A4_HEIGHT,
    A4_WIDTH,
    BACKGROUND,
    BLANK_BAND_FRACTION,
    CAPTION_BAND,
    CJK_RANGES,
    COLUMN_GAP,
    COLUMN_WIDTH,
    CONTENT_HEADS,
    COVER_FRAC,
    DESIGN_WIDTH,
    DETECT_WIDTH,
    FOOTNOTE,
    LEGEND_MARGIN,
    LEGEND_PAD,
    LIST_LABELS,
    MIN_CELL_FRACTION,
    RED,
    RED_MIN,
    RENDER_DPI,
    ROW_LABELS,
    SHEET_FOOTER,
    SHEET_PDF_DPI,
    SHEET_PDF_SIZE,
    SIDE_CLEARANCE,
    SIDE_FRAC,
    SVG_BARLINE,
    SVG_MIN_CELL,
    SVG_VIEWBOX,
    SVG_X_TOLERANCE,
    TALL_PAGE_HEIGHT,
    TINT_ALPHA,
    TRAILING_SLIVER_FRACTION,
    YELLOW,
    YELLOW_MIN,
    SheetPage,
)
from .pdf import build_cover_page, status, write_priority_list, write_sheet_pdf
from .pipeline import analyze_page, build_sheet, review_sheets
from .render import (
    _group_overflow_pages as _group_overflow_pages,
    _page_sort_key as _page_sort_key,
    copy_header,
    prepare_paginated_mscz,
    prepare_paginated_musicxml,
    render_page_musicxml,
    render_page_svg,
    render_paginated_score,
)
from .scoring import (
    _content_change as _content_change,
    _tier_score as _tier_score,
    length_measures,
    measure_scores,
    page_measure_count,
    read_score_title,
    reconcile_page_measure_counts,
    score_measure_count,
)
from .svg import (
    _collapsed_y as _collapsed_y,
    _group_barline_systems as _group_barline_systems,
    _merge_svg_slivers as _merge_svg_slivers,
    parse_svg_measures,
    svg_cells_to_panel,
)

__all__ = [
    "A4_HEIGHT",
    "A4_WIDTH",
    "BACKGROUND",
    "BLANK_BAND_FRACTION",
    "CAPTION_BAND",
    "CJK_RANGES",
    "COLUMN_GAP",
    "COLUMN_WIDTH",
    "CONTENT_HEADS",
    "COVER_FRAC",
    "DESIGN_WIDTH",
    "DETECT_WIDTH",
    "FOOTNOTE",
    "LEGEND_MARGIN",
    "LEGEND_PAD",
    "LIST_LABELS",
    "MIN_CELL_FRACTION",
    "RED",
    "RED_MIN",
    "RENDER_DPI",
    "ROW_LABELS",
    "SHEET_FOOTER",
    "SHEET_PDF_DPI",
    "SHEET_PDF_SIZE",
    "SIDE_CLEARANCE",
    "SIDE_FRAC",
    "SVG_BARLINE",
    "SVG_MIN_CELL",
    "SVG_VIEWBOX",
    "SVG_X_TOLERANCE",
    "SheetPage",
    "TALL_PAGE_HEIGHT",
    "TINT_ALPHA",
    "TRAILING_SLIVER_FRACTION",
    "YELLOW",
    "YELLOW_MIN",
    "analyze_page",
    "annotate",
    "barline_columns",
    "barline_columns_from_dets",
    "build_cover_page",
    "build_sheet",
    "collapse_blank_bands",
    "common_prefix_measures",
    "compose",
    "copy_header",
    "crop_to_ink",
    "detect_measures",
    "detect_rows",
    "draw_legend",
    "fit_cells_to_count",
    "fold_trailing_slivers",
    "ink_crop_box",
    "ink_mask",
    "legend_size",
    "length_measures",
    "longest_run",
    "measure_cells",
    "measure_scores",
    "page_measure_count",
    "parse_svg_measures",
    "prepare_paginated_mscz",
    "prepare_paginated_musicxml",
    "read_score_title",
    "reconcile_page_measure_counts",
    "reconcile_scan_rows",
    "render_page_musicxml",
    "render_page_svg",
    "render_paginated_score",
    "review_sheets",
    "score_measure_count",
    "staff_bands",
    "stack",
    "status",
    "svg_cells_to_panel",
    "system_counts",
    "systems_from_ink",
    "write_priority_list",
    "write_sheet_pdf",
]
