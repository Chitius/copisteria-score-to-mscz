from __future__ import annotations

import unittest
from xml.etree import ElementTree

from scorepipe.core.mscx import MsxcDocument
from scorepipe.core.pass_base import Context, Phase
from scorepipe.core.pipeline import run_phase
from scorepipe.passes import DISPLAY_PASSES

MSCX = """
<museScore><Score><Staff id="1">
  <Measure>
    <voice>
      <Chord><durationType>quarter</durationType><Note><pitch>60</pitch></Note></Chord>
      <Chord><durationType>quarter</durationType><Note><pitch>62</pitch></Note></Chord>
      <Chord><durationType>quarter</durationType><Note><pitch>64</pitch></Note></Chord>
      <Chord><durationType>quarter</durationType><Note><pitch>65</pitch></Note></Chord>
      <StaffText><text>rit.</text></StaffText>
    </voice>
  </Measure>
  <Measure>
    <voice><Chord><durationType>whole</durationType><Note><pitch>67</pitch></Note></Chord></voice>
  </Measure>
</Staff></Score></museScore>
"""

FACTS = {
    "marks": [
        {
            "measure": 1,
            "beat": 3,
            "text": "rit.",
            "gradual": "ritardando",
        }
    ]
}


class UpgradeGradualTest(unittest.TestCase):
    def test_staff_text_becomes_a_paired_spanner(self):
        doc = MsxcDocument(ElementTree.fromstring(MSCX))
        run_phase(doc, DISPLAY_PASSES, Context(facts=FACTS), Phase.DISPLAY)
        measures = doc.staves()[0].findall("Measure")
        start = [
            spanner
            for spanner in measures[0].iter("Spanner")
            if spanner.get("type") == "GradualTempoChange"
        ]
        self.assertEqual(len(start), 1)
        change = start[0].find("GradualTempoChange")
        self.assertEqual(change.findtext("beginText"), "rit.")
        self.assertEqual(change.findtext("tempoChangeType"), "ritardando")
        self.assertEqual(change.findtext("continueText"), "(rit.)")
        self.assertIsNotNone(start[0].find("next"))

        end = [
            spanner
            for spanner in measures[1].iter("Spanner")
            if spanner.get("type") == "GradualTempoChange"
        ]
        self.assertEqual(len(end), 1)
        self.assertIsNotNone(end[0].find("prev"))

    def test_second_run_is_idempotent(self):
        doc = MsxcDocument(ElementTree.fromstring(MSCX))
        ctx = Context(facts=FACTS)
        run_phase(doc, DISPLAY_PASSES, ctx, Phase.DISPLAY)
        again = run_phase(doc, DISPLAY_PASSES, ctx, Phase.DISPLAY)
        self.assertEqual(again.changes, 0)
        self.assertEqual(len(list(doc.root.iter("GradualTempoChange"))), 1)


if __name__ == "__main__":
    unittest.main()
