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
  <voice><StaffText><text>Allegro</text></StaffText></voice>
</Measure></Staff></Score></museScore>
"""

FACTS = {"marks": [{"measure": 1, "text": "Allegro", "tempo": 110, "beat_unit": "quarter"}]}


class UpgradeTempoTest(unittest.TestCase):
    def test_staff_text_becomes_a_tempo_object(self):
        doc = MsxcDocument(ElementTree.fromstring(MSCX))
        run_phase(doc, DISPLAY_PASSES, Context(facts=FACTS), Phase.DISPLAY)
        section = doc.staves()[0].findall("Measure")[0]
        tempo = section.find("voice/Tempo")
        self.assertIsNotNone(tempo)
        self.assertAlmostEqual(float(tempo.findtext("tempo")), 110 / 60, places=5)
        text = tempo.find("text")
        self.assertIsNotNone(text)
        self.assertIsNotNone(text.find("sym"))

    def test_second_run_is_idempotent(self):
        doc = MsxcDocument(ElementTree.fromstring(MSCX))
        ctx = Context(facts=FACTS)
        run_phase(doc, DISPLAY_PASSES, ctx, Phase.DISPLAY)
        again = run_phase(doc, DISPLAY_PASSES, ctx, Phase.DISPLAY)
        self.assertEqual(again.changes, 0)


if __name__ == "__main__":
    unittest.main()
