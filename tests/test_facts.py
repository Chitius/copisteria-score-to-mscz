from __future__ import annotations

import unittest
from pathlib import Path

from scorepipe.core.document import Document
from scorepipe.core.pass_base import Context
from scorepipe.core.pipeline import run_pipeline
from scorepipe.passes import INJECT_PASSES, STRUCTURAL_PASSES

FIXTURE = Path(__file__).parent / "fixtures" / "tiny.musicxml"

FACTS = {
    "marks": [
        {"measure": 1, "beat": 0, "placement": "above", "text": "Tempo rubato"},
        {"measure": 2, "beat": 0, "placement": "above", "rehearsal": "A", "text": "Allegro",
         "tempo": 110, "beat_unit": "quarter"},
    ]
}


class ApplyFactsTest(unittest.TestCase):
    def test_directions_are_inserted_once(self):
        doc = Document.load(FIXTURE)
        ctx = Context(facts=FACTS)
        run_pipeline(doc, ctx, structural=STRUCTURAL_PASSES, inject=INJECT_PASSES, verifiers=[])
        words = [words.text for words in doc.root.iter("words")]
        self.assertIn("Tempo rubato", words)
        self.assertIn("Allegro", words)
        self.assertEqual([r.text for r in doc.root.iter("rehearsal")], ["A"])
        self.assertEqual([m.findtext("per-minute") for m in doc.root.iter("metronome")], ["110"])

    def test_injection_is_idempotent(self):
        doc = Document.load(FIXTURE)
        ctx = Context(facts=FACTS)
        first = run_pipeline(doc, ctx, structural=STRUCTURAL_PASSES, inject=INJECT_PASSES, verifiers=[])
        self.assertGreater(first.changes, 0)
        second = run_pipeline(doc, ctx, structural=STRUCTURAL_PASSES, inject=INJECT_PASSES, verifiers=[])
        self.assertEqual(second.changes, 0)

    def test_offset_comes_after_direction_type(self):
        doc = Document.load(FIXTURE)
        ctx = Context(facts={"marks": [{"measure": 1, "beat": 2, "text": "rit."}]})
        run_pipeline(doc, ctx, structural=STRUCTURAL_PASSES, inject=INJECT_PASSES, verifiers=[])
        direction = next(d for d in doc.measures()[0].findall("direction") if d.findtext("direction-type/words") == "rit.")
        tags = [child.tag for child in direction]
        self.assertLess(tags.index("direction-type"), tags.index("offset"))


if __name__ == "__main__":
    unittest.main()
