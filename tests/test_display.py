from __future__ import annotations

import unittest
from xml.etree import ElementTree

from scorepipe.core.mscx import MsxcDocument
from scorepipe.core.mscx_invariants import MSCX_VERIFIERS
from scorepipe.core.pass_base import Context, Phase
from scorepipe.core.pipeline import run_phase
from scorepipe.passes import DISPLAY_PASSES

MSCX = """
<museScore version="4.4">
  <Score>
    <Staff id="1">
      <Measure>
        <voice>
          <Chord><durationType>quarter</durationType><Note><pitch>60</pitch></Note></Chord>
        </voice>
        <voice>
          <Rest><visible>0</visible><durationType>measure</durationType></Rest>
        </voice>
        <voice>
          <StaffText><text>rit.</text></StaffText>
          <Rest><durationType>measure</durationType></Rest>
        </voice>
      </Measure>
      <Measure>
        <voice>
          <Chord><durationType>whole</durationType><Note><pitch>60</pitch></Note></Chord>
        </voice>
      </Measure>
    </Staff>
  </Score>
</museScore>
"""


def build() -> MsxcDocument:
    return MsxcDocument(ElementTree.fromstring(MSCX))


class DisplayPassesTest(unittest.TestCase):
    def test_padding_voice_is_dropped(self):
        doc = build()
        run_phase(doc, DISPLAY_PASSES, Context(), Phase.DISPLAY)
        voices = doc.staves()[0].findall("Measure")[0].findall("voice")
        self.assertEqual(len(voices), 1, "padding/text voice should be merged away")
        self.assertTrue(voices[0].findall("Chord"))

    def test_text_voice_loses_its_rest(self):
        doc = build()
        run_phase(doc, DISPLAY_PASSES, Context(), Phase.DISPLAY)
        measure = doc.staves()[0].findall("Measure")[0]
        text_voices = [voice for voice in measure.findall("voice") if voice.findall("StaffText")]
        self.assertEqual(len(text_voices), 1)
        self.assertTrue(text_voices[0].findall("Chord"))
        self.assertEqual(text_voices[0].findall("Rest"), [])

    def test_real_rest_is_unhidden(self):
        doc = MsxcDocument(
            ElementTree.fromstring(
                """
                <museScore><Score><Staff id="1"><Measure>
                  <voice>
                    <Chord><durationType>half</durationType><Note><pitch>60</pitch></Note></Chord>
                    <Rest><visible>0</visible><durationType>half</durationType></Rest>
                  </voice>
                </Measure></Staff></Score></museScore>
                """
            )
        )
        run_phase(doc, DISPLAY_PASSES, Context(), Phase.DISPLAY)
        rest = doc.staves()[0].findall("Measure")[0].find("voice/Rest")
        self.assertIsNotNone(rest)
        self.assertIsNone(rest.find("visible"))

    def test_chord_voice_comes_first_and_loop_is_idempotent(self):
        doc = build()
        report = run_phase(doc, DISPLAY_PASSES, Context(), Phase.DISPLAY)
        self.assertTrue(report.stable)
        measure = doc.staves()[0].findall("Measure")[0]
        self.assertTrue(measure.findall("voice")[0].findall("Chord"))
        second = run_phase(doc, DISPLAY_PASSES, Context(), Phase.DISPLAY)
        self.assertEqual(second.changes, 0)
        for verifier in MSCX_VERIFIERS:
            if verifier.__name__ == "measure_lengths":
                continue
            self.assertEqual(verifier(doc, Context()), [], verifier.__name__)


if __name__ == "__main__":
    unittest.main()

class PaddingVoiceContentTest(unittest.TestCase):
    def test_spanner_only_voice_is_not_padding(self):
        doc = MsxcDocument(ElementTree.fromstring('''
          <museScore><Score><Staff id="1"><Measure>
            <voice><Chord><durationType>whole</durationType><Note><pitch>60</pitch></Note></Chord></voice>
            <voice><Spanner type="Pedal"><Pedal><beginText>Ped.</beginText></Pedal>
              <next><location><measures>1</measures></location></next></Spanner></voice>
          </Measure></Staff></Score></museScore>'''))
        run_phase(doc, DISPLAY_PASSES, Context(), Phase.DISPLAY)
        self.assertEqual(len(list(doc.root.iter('Spanner'))), 1)

    def test_barline_only_voice_keeps_its_barline(self):
        doc = MsxcDocument(ElementTree.fromstring('''
          <museScore><Score><Staff id="1"><Measure>
            <voice><Chord><durationType>whole</durationType><Note><pitch>60</pitch></Note></Chord></voice>
            <voice><BarLine><subtype>end</subtype></BarLine></voice>
          </Measure></Staff></Score></museScore>'''))
        run_phase(doc, DISPLAY_PASSES, Context(), Phase.DISPLAY)
        measure = doc.root.find('Score/Staff/Measure')
        self.assertEqual(len(measure.findall('voice')), 1)
        self.assertEqual(len(list(measure.iter('BarLine'))), 1)
