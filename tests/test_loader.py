from __future__ import annotations

import contextlib
import io
import unittest
from pathlib import Path

from scorepipe.cli import main
from scorepipe.core.document import Document
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

    def test_cli_accepts_a_page_directory(self):
        output = Path(__file__).parent / ".runs" / "pages" / "merged.musicxml"
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main([str(PAGES), "--check", "-o", str(output)])
        self.assertEqual(code, 0, buffer.getvalue())
        self.assertIn("pages: 2 files", buffer.getvalue())
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
