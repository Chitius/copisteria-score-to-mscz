from __future__ import annotations

import unittest
from xml.etree import ElementTree

from scorepipe.core.mscx import MsxcDocument
from scorepipe.core.pass_base import Context, Phase
from scorepipe.core.pipeline import run_phase
from scorepipe.passes import DISPLAY_PASSES

MSCX = """
<museScore><Score><Staff id="1"><Measure>
  <voice><Chord><durationType>whole</durationType><Note><pitch>60</pitch></Note></Chord></voice>
</Measure></Staff></Score></museScore>
"""

FACTS = {
    "credits": [
        {"type": "title", "text": "Innocent"},
        {"type": "composer", "text": "Joe Hisaishi"},
    ]
}


class CreditsDisplayTest(unittest.TestCase):
    def test_credits_land_in_the_title_frame(self):
        doc = MsxcDocument(ElementTree.fromstring(MSCX))
        run_phase(doc, DISPLAY_PASSES, Context(facts=FACTS), Phase.DISPLAY)
        boxes = doc.root.findall("Score/Staff/VBox")
        self.assertEqual(len(boxes), 2)
        styles = [box.findtext("Text/style") for box in boxes]
        self.assertEqual(styles, ["title", "composer"])

    def test_second_run_is_idempotent(self):
        doc = MsxcDocument(ElementTree.fromstring(MSCX))
        ctx = Context(facts=FACTS)
        run_phase(doc, DISPLAY_PASSES, ctx, Phase.DISPLAY)
        again = run_phase(doc, DISPLAY_PASSES, ctx, Phase.DISPLAY)
        self.assertEqual(again.changes, 0)

    def test_arranger_is_appended_to_the_composer_line(self):
        facts = {
            "credits": [
                {"type": "title", "text": "Innocent"},
                {"type": "composer", "text": "Joe Hisaishi"},
                {"type": "arranger", "text": "Arranger Name"},
            ]
        }
        doc = MsxcDocument(ElementTree.fromstring(MSCX))
        run_phase(doc, DISPLAY_PASSES, Context(facts=facts), Phase.DISPLAY)
        styles = [box.findtext("Text/style") for box in doc.root.findall("Score/Staff/VBox")]
        self.assertEqual(styles, ["title", "composer"])
        composer_text = doc.root.findtext(".//Text[style='composer']/text")
        self.assertIn("Joe Hisaishi", composer_text)
        self.assertIn("Arranger Name", composer_text)


if __name__ == "__main__":
    unittest.main()
