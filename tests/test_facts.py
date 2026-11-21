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

    def test_rehearsal_without_words_is_idempotent(self):
        doc = Document.load(FIXTURE)
        ctx = Context(facts={"marks": [{"measure": 1, "rehearsal": "C"}]})
        run_pipeline(doc, ctx, structural=STRUCTURAL_PASSES, inject=INJECT_PASSES, verifiers=[])
        again = run_pipeline(doc, ctx, structural=STRUCTURAL_PASSES, inject=INJECT_PASSES, verifiers=[])
        self.assertEqual(again.changes, 0)
        self.assertEqual(len(list(doc.root.iter("rehearsal"))), 1)

    def test_offset_comes_after_direction_type(self):
        doc = Document.load(FIXTURE)
        ctx = Context(facts={"marks": [{"measure": 1, "beat": 2, "text": "rit."}]})
        run_pipeline(doc, ctx, structural=STRUCTURAL_PASSES, inject=INJECT_PASSES, verifiers=[])
        direction = next(d for d in doc.measures()[0].findall("direction") if d.findtext("direction-type/words") == "rit.")
        tags = [child.tag for child in direction]
        self.assertLess(tags.index("direction-type"), tags.index("offset"))

    def test_fact_style_reaches_the_words_element(self):
        doc = Document.load(FIXTURE)
        ctx = Context(
            facts={
                "marks": [
                    {
                        "measure": 1,
                        "text": "In the sense;",
                        "italic": True,
                        "font_size": 8,
                        "justify": "center",
                    }
                ]
            }
        )
        run_pipeline(doc, ctx, structural=STRUCTURAL_PASSES, inject=INJECT_PASSES, verifiers=[])
        words = next(w for w in doc.root.iter("words") if w.text == "In the sense;")
        self.assertEqual(words.get("font-size"), "8")
        self.assertEqual(words.get("font-style"), "italic")
        self.assertEqual(words.get("justify"), "center")

    def test_tempo_notation_text_does_not_add_a_second_metronome(self):
        doc = Document.load(FIXTURE)
        ctx = Context(
            facts={
                "marks": [
                    {
                        "measure": 1,
                        "text": "q = 72",
                        "tempo": 72,
                        "beat_unit": "quarter",
                    }
                ]
            }
        )
        run_pipeline(doc, ctx, structural=STRUCTURAL_PASSES, inject=INJECT_PASSES, verifiers=[])
        words = next(w for w in doc.root.iter("words") if w.text == "q = 72")
        direction = next(d for d in doc.measures()[0].findall("direction") if d.find(".//words") is not None)
        self.assertIsNotNone(direction.find("sound"))
        self.assertEqual(direction.find("sound").get("tempo"), "72")
        self.assertEqual(list(doc.root.iter("metronome")), [])


if __name__ == "__main__":
    unittest.main()
