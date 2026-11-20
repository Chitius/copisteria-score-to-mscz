from __future__ import annotations

import unittest
from pathlib import Path

from scorepipe.core.invariants import measure_lengths
from scorepipe.core.pass_base import Context
from scorepipe.core.pipeline import run_pipeline
from scorepipe.loader import load_pages
from scorepipe.passes import STRUCTURAL_PASSES

PAGES = Path(__file__).parent / "fixtures" / "pages_restore"


def run() -> tuple:
    merged = load_pages(PAGES)
    ctx = Context(pages=merged)
    report = run_pipeline(merged.document, ctx, structural=STRUCTURAL_PASSES, verifiers=[])
    return merged.document, ctx, report


class PageRestoreTest(unittest.TestCase):
    def test_tie_crosses_the_page_boundary(self):
        doc, _ctx, _report = run()
        second = doc.measures()[1]
        third = doc.measures()[2]
        start = next(n for n in second.iter("note") if n.findtext("pitch/step") == "C")
        stop = next(n for n in third.iter("note") if n.findtext("pitch/step") == "C")
        self.assertTrue(any(tie.get("type") == "start" for tie in start.findall("tie")))
        self.assertTrue(any(tie.get("type") == "stop" for tie in stop.findall("tie")))

    def test_slur_crosses_the_page_boundary(self):
        doc, _ctx, _report = run()
        slurs = [(slur.get("type"), slur.get("number")) for slur in doc.root.iter("slur")]
        self.assertIn(("start", "1"), slurs)
        self.assertIn(("stop", "1"), slurs)

    def test_pedal_directions_come_from_the_pages(self):
        doc, _ctx, _report = run()
        first = doc.measures()[0].findall(".//pedal")
        third = doc.measures()[2].findall(".//pedal")
        self.assertEqual([pedal.get("type") for pedal in first], ["start"])
        self.assertEqual([pedal.get("type") for pedal in third], ["stop"])

    def test_restoration_is_idempotent(self):
        doc, ctx, _report = run()
        again = run_pipeline(doc, ctx, structural=STRUCTURAL_PASSES, verifiers=[])
        self.assertEqual(again.changes, 0)
        self.assertEqual(measure_lengths(doc, Context()), [])


if __name__ == "__main__":
    unittest.main()
