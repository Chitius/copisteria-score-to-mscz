from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from scorepipe.proof_sheet import (
    _content_change,
    _tier_score,
    build_cover_page,
    reconcile_scan_rows,
    write_sheet_pdf,
)


def _reading(directory: Path, changes: list[dict]) -> Path:
    path = directory / "reading.json"
    path.write_text(json.dumps({"tokens": {}, "changes": changes}), encoding="utf-8")
    return path


class ContentTierTest(unittest.TestCase):
    def test_routine_heads_do_not_tint(self):
        self.assertFalse(_content_change([{"head": "voice", "changed": True}]))
        self.assertFalse(_content_change([{"head": "dots", "changed": True}]))
        self.assertFalse(_content_change([{"head": "onset_p", "changed": True}]))

    def test_content_heads_do_tint(self):
        for head in ("cls", "pos", "alter", "tup", "real"):
            self.assertTrue(_content_change([{"head": head}]), head)

    def test_second_symbol_only_backs_the_first_up(self):
        self.assertEqual(_tier_score([]), 0.0)
        self.assertEqual(_tier_score([3.0]), 3.0)
        self.assertEqual(_tier_score([3.0, 3.0]), 4.0)


class LengthMeasuresTest(unittest.TestCase):
    def test_tuplet_length_counts_as_a_length_finding(self):
        """An overfull voice reports its bar *and* the short tuplet inside it (Gurenge m42)."""
        from scorepipe.proof_sheet import length_measures

        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "report.json"
            report.write_text(
                json.dumps(
                    {
                        "verifier": [
                            {"code": "mscx-measure-length", "measure": 42},
                            {"code": "mscx-tuplet-length", "measure": 42},
                            {"code": "mscx-tuplet-length", "measure": 76},
                            {"code": "duplicate-tie", "measure": 12},
                            {"code": "mscx-measure-length", "measure": 200},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(length_measures(report, 0, 130), [42, 76])


class ScanReconcileTest(unittest.TestCase):
    def test_missed_final_barline_is_closed_at_the_staff_edge(self):
        # First Step page 1: six detected cells, the reader still places bar 6 past the last one.
        rows = [[(0, 0, 300, 100), (300, 0, 600, 100)]]
        with tempfile.TemporaryDirectory() as tmp:
            reading = _reading(Path(tmp), [{"sym": 1, "bar": 6, "box": [700, 40, 720, 60]}])
            repaired, inferred, notes = reconcile_scan_rows(
                rows, [(0, 100)], 3, reading, origin=(0, 0), right_edges=[900]
            )
        self.assertEqual([len(row) for row in repaired], [3])
        self.assertEqual(repaired[0][-1][:3], (600, 0, 900))
        self.assertEqual(inferred, [])
        self.assertTrue(any("final barline" in note for note in notes))

    def test_missing_internal_barline_splits_and_marks_inferred(self):
        rows = [[(0, 0, 400, 100), (400, 0, 800, 100), (800, 0, 1600, 100), (1600, 0, 2000, 100)]]
        with tempfile.TemporaryDirectory() as tmp:
            reading = _reading(Path(tmp), [])
            repaired, inferred, _notes = reconcile_scan_rows(
                rows, [(0, 100)], 5, reading, origin=(0, 0), right_edges=[2000]
            )
        self.assertEqual([len(row) for row in repaired], [5])
        self.assertEqual(inferred, [2, 3])

    def test_no_change_when_the_count_already_matches(self):
        rows = [[(0, 0, 300, 100), (300, 0, 600, 100)]]
        with tempfile.TemporaryDirectory() as tmp:
            reading = _reading(Path(tmp), [{"sym": 1, "bar": 0, "box": [40, 40, 60, 60]}])
            repaired, inferred, notes = reconcile_scan_rows(
                rows, [(0, 100)], 2, reading, origin=(0, 0), right_edges=[600]
            )
        self.assertEqual([len(row) for row in repaired], [2])
        self.assertEqual(inferred, [])
        self.assertEqual(notes, [])


class CombinedSheetPdfTest(unittest.TestCase):
    def test_all_pages_are_bound_into_one_a4_pdf(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            first, second = work / "one.png", work / "two.png"
            Image.new("RGB", (900, 600), (250, 250, 250)).save(first)
            Image.new("RGB", (600, 900), (240, 240, 240)).save(second)
            entries = [
                {"page": 1, "pdf_page": 2, "label": "page-one", "measures": 12, "red": 1, "yellow": 0,
                 "aligned": True},
                {"page": 2, "pdf_page": 3, "label": "page-two", "measures": 9, "red": 0, "yellow": 2,
                 "aligned": True},
            ]
            pdf = write_sheet_pdf(
                [first, second],
                work / "review-sheets.pdf",
                title="Test Score",
                source_name="source.pdf",
                entries=entries,
            )
            self.assertIsNotNone(pdf)
            self.assertTrue(pdf.is_file())
            data = pdf.read_bytes()
        self.assertEqual(data[:5], b"%PDF-")
        # cover + one page per comparison image
        self.assertEqual(re.findall(rb"/Count (\d+)", data), [b"3"])

    def test_cover_page_is_a4_landscape_and_handles_cjk_source(self):
        cover = build_cover_page(
            "Test Score",
            "인터스텔라 - First Step 악보(최종).pdf",
            [{"page": 1, "pdf_page": 2, "label": "p01", "measures": 3, "red": 0, "yellow": 0,
              "aligned": True}],
        )
        self.assertEqual(cover.size, (3508, 2480))  # A4 landscape at 300 dpi
        self.assertEqual(cover.mode, "RGB")
        cover.close()


if __name__ == "__main__":
    unittest.main()
