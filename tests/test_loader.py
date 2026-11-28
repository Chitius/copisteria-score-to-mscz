from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from scorepipe.cli import main
from scorepipe.core.invariants import redundant_time_signatures
from scorepipe.core.pass_base import Context
from scorepipe.core.pipeline import run_pipeline
from scorepipe.loader import load_pages, merge_pages
from scorepipe.passes import STRUCTURAL_PASSES

PAGES = Path(__file__).parent / "fixtures" / "pages"


class LoaderTest(unittest.TestCase):
    def test_pages_are_concatenated_and_renumbered(self):
        merged = merge_pages([PAGES / "page1.musicxml", PAGES / "page2.musicxml"])
        self.assertEqual(merged.measure_counts, [2, 2])
        numbers = [measure.get("number") for measure in merged.document.measures()]
        self.assertEqual(numbers, ["1", "2", "3", "4"])
        self.assertEqual(merged.page_of_measure(1), 1)
        self.assertEqual(merged.page_of_measure(3), 2)

    def test_pipeline_cleans_page_join_duplicates(self):
        merged = load_pages(PAGES)
        run_pipeline(merged.document, Context(), structural=STRUCTURAL_PASSES, verifiers=[])
        self.assertEqual(redundant_time_signatures(merged.document, Context()), [])
        self.assertEqual(len(merged.document.measures()), 4)

    def test_pages_are_rescaled_to_one_divisions(self):
        template = (
            '<?xml version="1.0" encoding="UTF-8"?><score-partwise version="4.0">'
            '<part-list><score-part id="P1"><part-name>t</part-name></score-part></part-list>'
            '<part id="P1"><measure number="1"><attributes><divisions>{divisions}</divisions>'
            "<time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
            '<note><pitch><step>{step}</step><octave>4</octave></pitch>'
            '<duration>{duration}</duration><voice>1</voice></note></measure>'
            "</part></score-partwise>"
        )
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            first = work / "page1.musicxml"
            second = work / "page2.musicxml"
            first.write_text(template.format(divisions=4, step="C", duration=4), encoding="utf-8")
            second.write_text(template.format(divisions=8, step="D", duration=8), encoding="utf-8")
            merged = merge_pages([first, second])
        self.assertEqual(merged.document.divisions(), 8)
        durations = [
            event.duration
            for _number, measure in merged.document.iter_measures()
            for event in merged.document.events(measure)
            if not event.rest
        ]
        self.assertEqual(durations, [1.0, 1.0])

    def test_cli_accepts_a_page_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "merged.musicxml"
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = main([str(PAGES), "--check", "-o", str(output)])
            self.assertEqual(code, 0, buffer.getvalue())
            self.assertIn("pages: 2 files", buffer.getvalue())
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()


class MultiPartPageTest(unittest.TestCase):
    def _two_part_xml(self, *, p1_divs=4, p2_divs=8, p1_measures=2, p2_measures=2, part_ids=("P1", "P2")):
        score_parts = "".join(
            f'<score-part id="{pid}"><part-name>{pid}</part-name></score-part>' for pid in part_ids
        )
        parts_xml = []
        for idx, pid in enumerate(part_ids):
            divs = p1_divs if idx == 0 else p2_divs
            count = p1_measures if idx == 0 else p2_measures
            step = "C" if idx == 0 else "G"
            bars = "".join(
                f'<measure number="{m}"><attributes><divisions>{divs}</divisions>'
                f"<time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
                f"<note><pitch><step>{step}</step><octave>4</octave></pitch>"
                f"<duration>{divs * 4}</duration><voice>1</voice></note></measure>"
                for m in range(1, count + 1)
            )
            parts_xml.append(f'<part id="{pid}">{bars}</part>')
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f'<score-partwise version="4.0"><part-list>{score_parts}</part-list>'
            f'{"".join(parts_xml)}</score-partwise>'
        )

    def test_multi_part_pages_merge_all_parts_and_rescale_divisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            p1 = work / "page1.musicxml"
            p2 = work / "page2.musicxml"
            p1.write_text(self._two_part_xml(p1_divs=4, p2_divs=6, p1_measures=2, p2_measures=2), encoding="utf-8")
            p2.write_text(self._two_part_xml(p1_divs=8, p2_divs=12, p1_measures=1, p2_measures=1), encoding="utf-8")
            merged = merge_pages([p1, p2])

        self.assertEqual(merged.part_ids, ["P1", "P2"])
        self.assertEqual(merged.measure_counts, [2, 1])
        self.assertEqual(merged.document.divisions(), 24.0)
        self.assertEqual([pid for pid, _ in merged.document.iter_parts()], ["P1", "P2"])
        for pid in ("P1", "P2"):
            numbers = [m.get("number") for m in merged.document.measures(pid)]
            self.assertEqual(numbers, ["1", "2", "3"])
            durations = [
                event.duration
                for _n, measure in merged.document.iter_measures(pid)
                for event in merged.document.events(measure)
            ]
            self.assertEqual(durations, [4.0, 4.0, 4.0])

    def test_mismatched_parts_across_pages_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            p1 = work / "page1.musicxml"
            p2 = work / "page2.musicxml"
            p1.write_text(self._two_part_xml(part_ids=("P1", "P2")), encoding="utf-8")
            p2.write_text(self._two_part_xml(part_ids=("P1",)), encoding="utf-8")
            with self.assertRaises(ValueError) as raised:
                merge_pages([p1, p2])
        self.assertIn("do not match", str(raised.exception))

    def test_mismatched_measure_counts_between_parts_on_a_page_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "unequal.musicxml"
            target.write_text(self._two_part_xml(p1_measures=2, p2_measures=1), encoding="utf-8")
            with self.assertRaises(ValueError) as raised:
                merge_pages([target])
        self.assertIn("disagree on measure count", str(raised.exception))
