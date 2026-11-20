from __future__ import annotations

import unittest
from xml.etree import ElementTree

from scorepipe.core.mscx import MsxcDocument
from scorepipe.core.pass_base import Context, Phase
from scorepipe.core.pipeline import run_phase
from scorepipe.passes import DISPLAY_PASSES

MSCX = """
<museScore><Score><Staff id="1"><Measure>
  <voice>
    <Chord><durationType>whole</durationType><Note><pitch>60</pitch></Note></Chord>
    <StaffText><text>simile</text></StaffText>
    <StaffText><text>simile</text></StaffText>
    <Spanner type="Pedal"><Pedal><beginText>Ped.</beginText></Pedal>
      <next><location><measures>1</measures></location></next></Spanner>
    <Spanner type="Pedal"><Pedal><beginText>Ped.</beginText></Pedal>
      <next><location><measures>1</measures></location></next></Spanner>
  </voice>
</Measure></Staff></Score></museScore>
"""


class DisplayDedupeTest(unittest.TestCase):
    def test_duplicate_text_and_pedal_are_removed(self):
        doc = MsxcDocument(ElementTree.fromstring(MSCX))
        run_phase(doc, DISPLAY_PASSES, Context(), Phase.DISPLAY)
        measure = doc.staves()[0].findall("Measure")[0]
        texts = [node for node in measure.iter("StaffText")]
        pedals = [
            spanner
            for spanner in measure.iter("Spanner")
            if spanner.get("type") == "Pedal"
        ]
        self.assertEqual(len(texts), 1)
        self.assertEqual(len(pedals), 1)

    def test_second_run_is_idempotent(self):
        doc = MsxcDocument(ElementTree.fromstring(MSCX))
        ctx = Context()
        run_phase(doc, DISPLAY_PASSES, ctx, Phase.DISPLAY)
        again = run_phase(doc, DISPLAY_PASSES, ctx, Phase.DISPLAY)
        self.assertEqual(again.changes, 0)


if __name__ == "__main__":
    unittest.main()
