from __future__ import annotations

import unittest
from xml.etree import ElementTree

from scorepipe.core.mscx import MsxcDocument
from scorepipe.core.pass_base import Context, Phase
from scorepipe.core.pipeline import run_phase
from scorepipe.passes import DISPLAY_PASSES
from scorepipe.passes.mscx_dedupe import DISPLAY_DEDUPE_PASSES

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

# A text-only voice that also carries notation the old pass deleted with the slot.
SPANNER_MSCX = """
<museScore><Score><Staff id="1"><Measure>
  <voice>
    <Clef><concertClefType>G</concertClefType></Clef>
    <Chord><durationType>whole</durationType><Note><pitch>60</pitch></Note></Chord>
  </voice>
  <voice>
    <StaffText><text>dolce</text></StaffText>
    <Dynamic><subtype>mf</subtype></Dynamic>
    <Spanner type="Tie"><Tie><eid>tie-1</eid></Tie>
      <next><location><measures>1</measures><notes>0</notes></location></next></Spanner>
  </voice>
</Measure></Staff></Score></museScore>
"""

# A chord voice plus a second slot whose only content is a barline.
BARLINE_VOICE_MSCX = """
<museScore><Score><Staff id="1"><Measure>
  <voice>
    <Chord><durationType>whole</durationType><Note><pitch>60</pitch></Note></Chord>
  </voice>
  <voice><BarLine><subtype>normal</subtype></BarLine></voice>
</Measure></Staff></Score></museScore>
"""

# The barline slot comes first, so there is no previous voice to inherit it.
LEADING_BARLINE_MSCX = """
<museScore><Score><Staff id="1"><Measure>
  <voice><BarLine><subtype>normal</subtype></BarLine></voice>
  <voice>
    <Chord><durationType>whole</durationType><Note><pitch>60</pitch></Note></Chord>
  </voice>
</Measure></Staff></Score></museScore>
"""

# The only voice is a barline: there is nowhere to move it, so the slot must stay.
SOLO_BARLINE_MSCX = """
<museScore><Score><Staff id="1"><Measure>
  <voice><BarLine><subtype>end</subtype></BarLine></voice>
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

    def test_text_only_voice_moves_into_the_chord_voice(self):
        doc = MsxcDocument(ElementTree.fromstring(MSCX))
        measure = doc.root.find("Score/Staff/Measure")
        voice = ElementTree.SubElement(measure, "voice")
        ElementTree.SubElement(voice, "StaffText").append(ElementTree.Element("text"))
        voice.find("StaffText/text").text = "dolce"
        run_phase(doc, DISPLAY_PASSES, Context(), Phase.DISPLAY)
        self.assertEqual(len(measure.findall("voice")), 1)
        self.assertEqual(measure.findtext("voice/StaffText/text"), "dolce")

    def test_spanner_in_a_text_voice_survives_the_merge(self):
        doc = MsxcDocument(ElementTree.fromstring(SPANNER_MSCX))
        measure = doc.root.find("Score/Staff/Measure")
        run_phase(doc, DISPLAY_PASSES, Context(), Phase.DISPLAY)
        self.assertEqual(len(measure.findall("voice")), 1, "text voice was not merged away")
        self.assertEqual(len(measure.findall("voice/Chord")), 1, "the chord voice was lost")
        ties = [spanner for spanner in measure.iter("Spanner") if spanner.get("type") == "Tie"]
        self.assertEqual(len(ties), 1, "the Tie spanner was deleted with the text voice")
        self.assertEqual(measure.findtext("voice/StaffText/text"), "dolce")
        self.assertEqual(len(measure.findall(".//Dynamic")), 1, "the Dynamic was lost")
        target = measure.find("voice")
        tags = [child.tag for child in target]
        self.assertLess(
            tags.index("Clef"), tags.index("StaffText"), "text was inserted before the clef"
        )

    def test_merge_text_voices_is_idempotent_with_a_spanner(self):
        doc = MsxcDocument(ElementTree.fromstring(SPANNER_MSCX))
        ctx = Context()
        run_phase(doc, DISPLAY_PASSES, ctx, Phase.DISPLAY)
        again = run_phase(doc, DISPLAY_PASSES, ctx, Phase.DISPLAY)
        self.assertEqual(again.changes, 0)


class DropEmptyVoicesBarLineTest(unittest.TestCase):
    def run_dedupe(self, xml: str) -> MsxcDocument:
        doc = MsxcDocument(ElementTree.fromstring(xml))
        run_phase(doc, DISPLAY_DEDUPE_PASSES, Context(), Phase.DISPLAY)
        return doc

    def test_solo_barline_moves_to_the_chord_voice(self):
        doc = self.run_dedupe(BARLINE_VOICE_MSCX)
        measure = doc.root.find("Score/Staff/Measure")
        self.assertEqual(len(measure.findall("voice")), 1, "the empty slot was not removed")
        self.assertTrue(measure.find("voice").findall("Chord"))
        barlines = list(measure.iter("BarLine"))
        self.assertEqual(len(barlines), 1, "the barline was deleted with the empty voice")
        self.assertIsNotNone(measure.find("voice/BarLine"))

    def test_barline_in_the_first_slot_moves_to_the_next_voice(self):
        doc = self.run_dedupe(LEADING_BARLINE_MSCX)
        measure = doc.root.find("Score/Staff/Measure")
        self.assertEqual(len(measure.findall("voice")), 1)
        self.assertEqual(len(list(measure.iter("BarLine"))), 1)
        self.assertTrue(measure.find("voice").findall("Chord"))

    def test_only_barline_voice_is_kept(self):
        doc = self.run_dedupe(SOLO_BARLINE_MSCX)
        measure = doc.root.find("Score/Staff/Measure")
        self.assertEqual(len(measure.findall("voice")), 1, "the only slot was dropped")
        self.assertEqual(len(list(measure.iter("BarLine"))), 1, "the only barline was dropped")

    def test_second_run_is_idempotent(self):
        for xml in (BARLINE_VOICE_MSCX, LEADING_BARLINE_MSCX, SOLO_BARLINE_MSCX):
            doc = MsxcDocument(ElementTree.fromstring(xml))
            ctx = Context()
            run_phase(doc, DISPLAY_DEDUPE_PASSES, ctx, Phase.DISPLAY)
            again = run_phase(doc, DISPLAY_DEDUPE_PASSES, ctx, Phase.DISPLAY)
            self.assertEqual(again.changes, 0, xml)


if __name__ == "__main__":
    unittest.main()
