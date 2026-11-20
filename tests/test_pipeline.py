from __future__ import annotations

import unittest
from pathlib import Path

from scorepipe.core.document import Document
from scorepipe.core.invariants import (
    duplicate_ties,
    hidden_rests,
    measure_lengths,
    redundant_time_signatures,
)
from scorepipe.core.pass_base import Context
from scorepipe.core.pipeline import run_pipeline
from scorepipe.passes import STRUCTURAL_PASSES

FIXTURE = Path(__file__).parent / "fixtures" / "tiny.musicxml"


class PipelineTest(unittest.TestCase):
    def test_repairs_and_reaches_fixed_point(self):
        doc = Document.load(FIXTURE)
        ctx = Context()
        report = run_pipeline(doc, ctx, structural=STRUCTURAL_PASSES, verifiers=[])

        self.assertEqual(report.trace[0].pass_name, "dedupe_ties")
        by_name = {entry.pass_name: entry.changed for entry in report.trace}
        self.assertEqual(by_name["dedupe_ties"], 2)  # one <tie>, one <tied>
        self.assertEqual(by_name["drop_redundant_time_signatures"], 1)
        self.assertEqual(by_name["unhide_rests"], 1)
        self.assertTrue(report.phases[0].stable)

        # a second pass over the repaired document must find nothing
        second = run_pipeline(doc, ctx, structural=STRUCTURAL_PASSES, verifiers=[])
        self.assertEqual(second.phases[0].changes, 0)

    def test_verifiers_are_clean_after_repair(self):
        doc = Document.load(FIXTURE)
        ctx = Context()
        run_pipeline(doc, ctx, structural=STRUCTURAL_PASSES, verifiers=[])
        for verifier in (duplicate_ties, hidden_rests, redundant_time_signatures):
            self.assertEqual(verifier(doc, ctx), [], verifier.__name__)
        self.assertEqual(measure_lengths(doc, ctx), [])

    def test_measure_length_violation_is_reported(self):
        doc = Document.load(FIXTURE)
        ctx = Context()
        run_pipeline(doc, ctx, structural=STRUCTURAL_PASSES, verifiers=[])
        # delete the rest and shorten the C4 to a quarter: the bar is now three beats
        measure = doc.measures()[0]
        notes = measure.findall("note")
        measure.remove(notes[0])  # the rest
        notes[1].find("duration").text = "4"  # C4 becomes a quarter
        violations = measure_lengths(doc, ctx)
        self.assertTrue(any(v.code == "measure-length" for v in violations))

    def test_each_owned_property_has_one_writer(self):
        owner: dict[str, str] = {}
        for one_pass in STRUCTURAL_PASSES:
            for property_name in one_pass.spec.owns:
                self.assertNotIn(
                    property_name,
                    owner,
                    f"{property_name} owned by {owner.get(property_name)} and {one_pass.spec.name}",
                )
                owner[property_name] = one_pass.spec.name


if __name__ == "__main__":
    unittest.main()
