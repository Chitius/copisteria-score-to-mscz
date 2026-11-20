from __future__ import annotations

import unittest
from pathlib import Path

from scorepipe.core.document import Document
from scorepipe.core.pass_base import Context
from scorepipe.core.pipeline import run_pipeline
from scorepipe.passes import INJECT_PASSES, STRUCTURAL_PASSES

FIXTURE = Path(__file__).parent / "fixtures" / "tiny.musicxml"

FACTS = {
    "marks": [],
    "credits": [
        {"type": "title", "text": "Innocent"},
        {"type": "composer", "text": "Joe Hisaishi"},
    ],
}


class CreditsTest(unittest.TestCase):
    def test_credits_are_inserted_before_part_list(self):
        doc = Document.load(FIXTURE)
        ctx = Context(facts=FACTS)
        run_pipeline(doc, ctx, structural=STRUCTURAL_PASSES, inject=INJECT_PASSES, verifiers=[])
        texts = [credit.findtext("credit-words") for credit in doc.root.findall("credit")]
        self.assertIn("Innocent", texts)
        self.assertIn("Joe Hisaishi", texts)
        tags = [child.tag for child in doc.root]
        self.assertLess(tags.index("credit"), tags.index("part-list"))

    def test_credits_are_idempotent(self):
        doc = Document.load(FIXTURE)
        ctx = Context(facts=FACTS)
        run_pipeline(doc, ctx, structural=STRUCTURAL_PASSES, inject=INJECT_PASSES, verifiers=[])
        again = run_pipeline(doc, ctx, structural=STRUCTURAL_PASSES, inject=INJECT_PASSES, verifiers=[])
        self.assertEqual(again.changes, 0)
        self.assertEqual(len(doc.root.findall("credit")), 2)


if __name__ == "__main__":
    unittest.main()
