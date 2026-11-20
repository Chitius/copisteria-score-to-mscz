from __future__ import annotations

import unittest
from pathlib import Path

from scorepipe.core.pass_base import Context
from scorepipe.core.pipeline import run_pipeline
from scorepipe.loader import load_pages
from scorepipe.passes import STRUCTURAL_PASSES

PAGES = Path(__file__).parent / "fixtures" / "pages_notation"


def run() -> tuple:
    merged = load_pages(PAGES)
    ctx = Context(pages=merged)
    report = run_pipeline(merged.document, ctx, structural=STRUCTURAL_PASSES, verifiers=[])
    return merged.document, ctx, report


class PageNotationRestoreTest(unittest.TestCase):
    def test_wedge_start_and_stop_are_restored(self):
        doc, _ctx, _report = run()
        first = doc.measures()[0].findall(".//wedge")
        second = doc.measures()[1].findall(".//wedge")
        self.assertEqual([wedge.get("type") for wedge in first], ["crescendo"])
        self.assertEqual([wedge.get("type") for wedge in second], ["stop"])

    def test_arpeggio_and_articulation_are_restored(self):
        doc, _ctx, _report = run()
        third = doc.measures()[2]
        arpeggios = third.findall(".//arpeggiate")
        self.assertTrue(arpeggios)
        self.assertEqual(arpeggios[0].get("direction"), "up")
        self.assertTrue(third.findall(".//staccato"))

    def test_restoration_is_idempotent(self):
        doc, ctx, _report = run()
        again = run_pipeline(doc, ctx, structural=STRUCTURAL_PASSES, verifiers=[])
        self.assertEqual(again.changes, 0)


if __name__ == "__main__":
    unittest.main()
