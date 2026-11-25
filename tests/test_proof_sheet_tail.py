"""Tail-barline handling for the page proof sheets.

The final double barline emits two barlines in the SVG, so the last "measure" of a page can be a
11-px stroke at the staff edge.  These tests pin the two halves of the fix: the stroke is folded
into the bar on its left, and a page that still cannot be reconciled keeps its trustworthy prefix
tinted instead of going completely plain.
"""

from __future__ import annotations

from scorepipe import proof_sheet as ps


def _row(x_pairs, y0=0, y1=100):
    return [(x0, y0, x1, y1) for x0, x1 in x_pairs]


def test_folds_a_trailing_barline_stroke_into_the_previous_bar():
    cells = _row([(0, 400), (400, 800), (800, 811)])

    folded, operations = ps.fold_trailing_slivers(cells, expected=2)

    assert operations == 1
    assert len(folded) == 2
    assert folded[-1][:2] == (400.0, 0.0)
    assert folded[-1][2] == 811.0


def test_does_not_touch_a_page_whose_count_already_matches():
    cells = _row([(0, 400), (400, 411)])

    folded, operations = ps.fold_trailing_slivers(cells, expected=2)

    assert operations == 0
    assert folded == [(0.0, 0.0, 400.0, 100.0), (400.0, 0.0, 411.0, 100.0)]


def test_folds_only_the_last_system():
    first = _row([(0, 300), (300, 600)], y0=0)
    second = _row([(0, 300), (300, 600), (600, 611)], y0=200, y1=300)
    cells = first + second

    folded, operations = ps.fold_trailing_slivers(cells, expected=4)

    assert operations == 1
    assert ps.system_counts(folded) == [2, 2]


def test_prefix_keeps_going_when_the_last_system_has_an_appended_stroke():
    render = _row([(0, 400), (400, 800)]) + _row(
        [(0, 400), (400, 800), (800, 811)], y0=200, y1=300
    )
    scan = _row([(0, 400), (400, 800)]) + _row([(0, 400), (400, 800)], y0=200, y1=300)

    # The stroke starts at the right edge of the last real bar, so the four bars still line up.
    assert ps.common_prefix_measures(render, scan, expected=4) == 4


def test_prefix_stops_at_a_sliver_that_splits_a_bar():
    render = _row([(0, 400), (400, 460), (460, 800)], y0=200, y1=300)
    scan = _row([(0, 400), (400, 800)], y0=200, y1=300)

    # The extra cell starts at 460 but is 340 wide, not a stroke: it cuts the bar, so nothing
    # after the first system can be trusted.
    assert ps.common_prefix_measures(render, scan, expected=2) == 0


def test_system_counts_groups_by_the_y_band():
    cells = _row([(0, 100), (100, 200)]) + _row([(0, 100)], y0=200, y1=300)

    assert ps.system_counts(cells) == [2, 1]
