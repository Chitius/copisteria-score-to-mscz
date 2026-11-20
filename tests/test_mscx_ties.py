from __future__ import annotations

import unittest
from xml.etree import ElementTree

from scorepipe.core.mscx import MsxcDocument
from scorepipe.core.pass_base import Context, Phase
from scorepipe.core.pipeline import run_phase
from scorepipe.passes import DISPLAY_PASSES

MSCX = """
<museScore><Score><Staff id="1">
  <Measure><voice>
    <Chord><durationType>whole</durationType><Note><pitch>60</pitch></Note></Chord>
  </voice></Measure>
  <Measure><voice>
    <Chord><durationType>whole</durationType><Note><pitch>60</pitch></Note></Chord>
  </voice></Measure>
</Staff></Score></museScore>
"""

TIES = [
    {
        "start_measure": 1,
        "start_onset": 0.0,
        "stop_measure": 2,
        "stop_onset": 0.0,
        "staff": "1",
        "pitch": 60,
    }
]


class RestoreMscxTiesTest(unittest.TestCase):
    def test_tie_spanners_are_attached(self):
        doc = MsxcDocument(ElementTree.fromstring(MSCX))
        run_phase(doc, DISPLAY_PASSES, Context(options={"ties": TIES}), Phase.DISPLAY)
        notes = list(doc.root.iter("Note"))
        start = notes[0]
        stop = notes[1]
        self.assertIsNotNone(start.find("Spanner/next/location/measures"))
        self.assertEqual(start.findtext("Spanner/next/location/measures"), "1")
        self.assertIsNotNone(stop.find("Spanner/prev/location/measures"))
        self.assertEqual(stop.findtext("Spanner/prev/location/measures"), "-1")

    def test_second_run_is_idempotent(self):
        doc = MsxcDocument(ElementTree.fromstring(MSCX))
        ctx = Context(options={"ties": TIES})
        run_phase(doc, DISPLAY_PASSES, ctx, Phase.DISPLAY)
        again = run_phase(doc, DISPLAY_PASSES, ctx, Phase.DISPLAY)
        self.assertEqual(again.changes, 0)


if __name__ == "__main__":
    unittest.main()
