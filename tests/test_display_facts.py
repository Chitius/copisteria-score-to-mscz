from __future__ import annotations

import unittest
from xml.etree import ElementTree

from scorepipe.core.mscx import MsxcDocument
from scorepipe.core.pass_base import Context, Phase
from scorepipe.core.pipeline import run_phase
from scorepipe.passes import DISPLAY_PASSES
from scorepipe.passes.mscx_facts import UpgradeTempoTexts

MSCX = """
<museScore><Score><Staff id="1"><Measure>
  <voice><Chord><durationType>whole</durationType><Note><pitch>60</pitch></Note></Chord></voice>
  <voice><StaffText><text>Allegro</text></StaffText></voice>
</Measure></Staff></Score></museScore>
"""

# The importer turned the metronome direction into a glyph-only Tempo; there is no StaffText.
GLYPH_ONLY_MSCX = """
<museScore><Score><Staff id="1"><Measure>
  <voice><Tempo><tempo>2</tempo><text><sym>metNoteQuarterUp</sym> = 120</text></Tempo></voice>
</Measure></Staff></Score></museScore>
"""

# Both the glyph-only import artefact and the matching StaffText are present.
GLYPH_AND_TEXT_MSCX = """
<museScore><Score><Staff id="1"><Measure>
  <voice>
    <Tempo><tempo>2</tempo><text><sym>metNoteQuarterUp</sym> = 120</text></Tempo>
    <StaffText><text>Allegro</text></StaffText>
  </voice>
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

    def test_glyph_only_tempo_removal_is_counted(self):
        doc = MsxcDocument(ElementTree.fromstring(GLYPH_ONLY_MSCX))
        measure = doc.root.find("Score/Staff/Measure")
        before = doc.state_hash()
        result = UpgradeTempoTexts().run(doc, Context(facts=FACTS))
        self.assertGreater(result.changed, 0, "removing a Tempo was not counted as a change")
        self.assertNotEqual(doc.state_hash(), before, "the document did not actually change")
        self.assertEqual(list(measure.iter("Tempo")), [], "the glyph-only Tempo was not removed")

    def test_glyph_only_tempo_removal_is_idempotent(self):
        doc = MsxcDocument(ElementTree.fromstring(GLYPH_ONLY_MSCX))
        ctx = Context(facts=FACTS)
        UpgradeTempoTexts().run(doc, ctx)
        settled = doc.state_hash()
        again = UpgradeTempoTexts().run(doc, ctx)
        self.assertEqual(again.changed, 0, "a second run reported a change")
        self.assertEqual(doc.state_hash(), settled, "a second run mutated the document")

    def test_staff_text_replacement_is_counted(self):
        doc = MsxcDocument(ElementTree.fromstring(MSCX))
        measure = doc.root.find("Score/Staff/Measure")
        result = UpgradeTempoTexts().run(doc, Context(facts=FACTS))
        self.assertEqual(result.changed, 1, "the StaffText replacement was not counted once")
        self.assertEqual(list(measure.iter("StaffText")), [], "the StaffText was not replaced")
        tempos = list(measure.iter("Tempo"))
        self.assertEqual(len(tempos), 1)
        self.assertEqual((tempos[0].findtext("text") or "").strip(), "Allegro")
        self.assertAlmostEqual(float(tempos[0].findtext("tempo")), 110 / 60, places=5)

    def test_glyph_removal_and_replacement_are_both_counted(self):
        doc = MsxcDocument(ElementTree.fromstring(GLYPH_AND_TEXT_MSCX))
        measure = doc.root.find("Score/Staff/Measure")
        result = UpgradeTempoTexts().run(doc, Context(facts=FACTS))
        self.assertEqual(result.changed, 2, "removal and replacement must each count once")
        tempos = list(measure.iter("Tempo"))
        self.assertEqual(len(tempos), 1, "the glyph-only Tempo survived next to the replacement")
        self.assertEqual((tempos[0].findtext("text") or "").strip(), "Allegro")
        again = UpgradeTempoTexts().run(doc, Context(facts=FACTS))
        self.assertEqual(again.changed, 0)


if __name__ == "__main__":
    unittest.main()
