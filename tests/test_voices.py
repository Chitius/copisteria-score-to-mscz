from __future__ import annotations

import unittest
from xml.etree import ElementTree

from scorepipe.core.document import Document
from scorepipe.core.pass_base import Context
from scorepipe.passes.xml_voices import NormalizeVoiceNumbers

PART = """
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>t</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>16</duration><voice>5</voice></note>
      <backup><duration>16</duration></backup>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>4</duration><voice>9</voice></note>
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>4</duration><voice>9</voice></note>
      <note><pitch><step>F</step><octave>4</octave></pitch><duration>4</duration><voice>9</voice></note>
      <note><pitch><step>G</step><octave>4</octave></pitch><duration>4</duration><voice>9</voice></note>
    </measure>
  </part>
</score-partwise>
"""


class NormalizeVoicesTest(unittest.TestCase):
    def test_densest_voice_gets_number_one(self):
        doc = Document(ElementTree.fromstring(PART))
        result = NormalizeVoiceNumbers().run(doc, Context())
        self.assertGreater(result.changed, 0)
        voices = [note.findtext("voice") for note in doc.measures()[0].iter("note")]
        self.assertEqual(voices[0], "2")  # the single whole note
        self.assertEqual(voices[1:], ["1", "1", "1", "1"])

    def test_second_run_is_a_no_op(self):
        doc = Document(ElementTree.fromstring(PART))
        NormalizeVoiceNumbers().run(doc, Context())
        second = NormalizeVoiceNumbers().run(doc, Context())
        self.assertEqual(second.changed, 0)


if __name__ == "__main__":
    unittest.main()
