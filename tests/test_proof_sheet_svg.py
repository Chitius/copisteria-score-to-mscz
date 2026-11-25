from __future__ import annotations

import unittest
from pathlib import Path

from scorepipe.proof_sheet import (
    _collapsed_y,
    _group_barline_systems,
    _merge_svg_slivers,
    parse_svg_measures,
    svg_cells_to_panel,
)

WORK = Path(__file__).parent / ".runs" / "svg"

SVG = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<svg width="100mm" height="100mm" viewBox="0 0 1000 1000"
 xmlns="http://www.w3.org/2000/svg">
<polyline class="StaffLines" fill="none" points="100,100 500,100" />
<polyline class="BarLine" fill="none" points="100,100 100,350" />
<polyline class="BarLine" fill="none" points="100,340 100,470" />
<polyline class="BarLine" fill="none" points="300,100 300,350" />
<polyline class="BarLine" fill="none" points="300,340 300,470" />
<polyline class="BarLine" fill="none" points="500,100 500,350" />
<polyline class="BarLine" fill="none" points="500,340 500,470" />
<polyline class="BarLine" fill="none" points="100,700 100,830" />
<polyline class="BarLine" fill="none" points="100,820 100,950" />
<polyline class="BarLine" fill="none" points="250,700 250,830" />
<polyline class="BarLine" fill="none" points="250,820 250,950" />
<polyline class="BarLine" fill="none" points="400,700 400,830" />
<polyline class="BarLine" fill="none" points="400,820 400,950" />
<polyline class="BarLine" fill="none" points="550,700 550,830" />
<polyline class="BarLine" fill="none" points="550,820 550,950" />
</svg>
"""


class SvgParseTest(unittest.TestCase):
    def _parse(self, text: str) -> dict:
        WORK.mkdir(parents=True, exist_ok=True)
        path = WORK / "page.svg"
        path.write_text(text, encoding="utf-8")
        return parse_svg_measures(path)

    def test_systems_come_from_overlapping_staff_barlines(self):
        geometry = self._parse(SVG)
        self.assertEqual((geometry["width"], geometry["height"]), (1000.0, 1000.0))
        self.assertEqual([len(system["cells"]) for system in geometry["systems"]], [2, 3])
        first = geometry["systems"][0]
        self.assertEqual(first["top"], 100)
        self.assertEqual(first["bottom"], 470)

    def test_double_barline_sliver_is_folded_into_the_cell_on_its_left(self):
        cells = [(0, 0, 300, 100), (300, 0, 314, 100), (314, 0, 600, 100)]
        merged = _merge_svg_slivers(cells)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0], (0, 0, 314, 100))

    def test_real_short_measure_is_not_folded(self):
        cells = [(0, 0, 300, 100), (300, 0, 420, 100), (420, 0, 720, 100)]
        self.assertEqual(_merge_svg_slivers(cells), cells)

    def test_system_grouping_is_transitive(self):
        segments = [(10.0, 0.0, 100.0), (10.0, 90.0, 200.0), (10.0, 190.0, 300.0)]
        groups = _group_barline_systems(segments)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0][:2], (0.0, 300.0))

    def test_cells_scale_into_the_cropped_panel(self):
        geometry = {"width": 1000.0, "height": 1000.0,
                    "systems": [{"top": 100, "bottom": 300, "cells": [(100, 100, 300, 300)]}]}
        cells = svg_cells_to_panel(geometry, (500, 500), (10, 20, 490, 480), [])
        self.assertEqual(cells, [(40.0, 30.0, 140.0, 130.0)])

    def test_collapsed_y_matches_the_band_cut(self):
        removed = [(100, 200)]
        self.assertEqual(_collapsed_y(250, removed, margin=12), 250 - 76)
        self.assertEqual(_collapsed_y(150, removed, margin=12), 150 - 38)
        self.assertEqual(_collapsed_y(105, removed, margin=12), 105)


if __name__ == "__main__":
    unittest.main()
