from __future__ import annotations

import unittest
from xml.etree import ElementTree

from scorepipe.core.document import Document
from scorepipe.core.pass_base import Context
from scorepipe.passes.xml_tail import DropTrailingDuplicateMeasure

PART = """
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>t</part-name></score-part></part-list>
  <part id="P1">{measures}</part>
</score-partwise>
"""


def build(measures: str) -> Document:
    return Document(ElementTree.fromstring(PART.format(measures=measures)))


def measure(number: int, pitch: str, duration: int) -> str:
    return (
        f'<measure number="{number}">'
        "<attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
        f"<note><pitch><step>{pitch}</step><octave>4</octave></pitch><duration>{duration}</duration></note>"
        "</measure>"
    )


class DropTrailingDuplicateTest(unittest.TestCase):
    def test_shorter_repeat_of_the_last_pitch_set_is_dropped(self):
        doc = build(measure(1, "C", 16) + measure(2, "C", 8))
        result = DropTrailingDuplicateMeasure().run(doc, Context())
        self.assertEqual(result.changed, 1)
        self.assertEqual(len(doc.measures()), 1)

    def test_different_pitches_are_kept(self):
        doc = build(measure(1, "C", 16) + measure(2, "D", 8))
        self.assertEqual(DropTrailingDuplicateMeasure().run(doc, Context()).changed, 0)
        self.assertEqual(len(doc.measures()), 2)

    def test_equal_length_repeat_is_kept(self):
        doc = build(measure(1, "C", 16) + measure(2, "C", 16))
        self.assertEqual(DropTrailingDuplicateMeasure().run(doc, Context()).changed, 0)

    def test_option_can_disable_the_pass(self):
        doc = build(measure(1, "C", 16) + measure(2, "C", 8))
        ctx = Context(options={"drop_trailing_duplicate": False})
        self.assertEqual(DropTrailingDuplicateMeasure().run(doc, ctx).changed, 0)


if __name__ == "__main__":
    unittest.main()
