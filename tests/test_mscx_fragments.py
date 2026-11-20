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
    <Chord><durationType>whole</durationType>
      <Note><pitch>60</pitch><tpc>14</tpc></Note>
      <Note><pitch>89</pitch><tpc>13</tpc></Note>
    </Chord>
  </voice>
</Measure></Staff></Score></museScore>
"""

FRAGMENTS = [
    {"measure": 1, "staff": "1", "pitch": 89, "onset": 0.0, "duration": 1.5}
]


class SplitChordFragmentsTest(unittest.TestCase):
    def test_conflicting_member_moves_to_its_own_voice(self):
        doc = MsxcDocument(ElementTree.fromstring(MSCX))
        run_phase(doc, DISPLAY_PASSES, Context(options={"chord_fragments": FRAGMENTS}), Phase.DISPLAY)
        voices = doc.root.findall("Score/Staff/Measure/voice")
        self.assertEqual(len(voices), 2)
        first_notes = [int(note.findtext("pitch")) for note in voices[0].iter("Note")]
        second_notes = [int(note.findtext("pitch")) for note in voices[1].iter("Note")]
        self.assertEqual(first_notes, [60])
        self.assertEqual(second_notes, [89])
        self.assertEqual(voices[1].find("Chord/durationType").text, "quarter")
        self.assertEqual(voices[1].find("Chord/dots").text, "1")

    def test_second_run_is_idempotent(self):
        doc = MsxcDocument(ElementTree.fromstring(MSCX))
        ctx = Context(options={"chord_fragments": FRAGMENTS})
        run_phase(doc, DISPLAY_PASSES, ctx, Phase.DISPLAY)
        again = run_phase(doc, DISPLAY_PASSES, ctx, Phase.DISPLAY)
        self.assertEqual(again.changes, 0)


if __name__ == "__main__":
    unittest.main()
