from __future__ import annotations

import unittest
from xml.etree import ElementTree

from scorepipe.core.document import Document
from scorepipe.core.invariants import chord_semantics, measure_lengths
from scorepipe.core.pass_base import Context

BAD = """
<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>t</part-name></score-part></part-list>
<part id="P1"><measure number="1">
<attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
<note><chord/><pitch><step>C</step><octave>4</octave></pitch><duration>16</duration><voice>1</voice></note>
</measure></part></score-partwise>
"""

NEGATIVE = """
<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>t</part-name></score-part></part-list>
<part id="P1"><measure number="1">
<attributes><divisions>4</divisions></attributes>
<backup><duration>8</duration></backup>
</measure></part></score-partwise>
"""


class ChordSemanticsTest(unittest.TestCase):
    def test_orphan_chord_is_reported(self):
        doc = Document(ElementTree.fromstring(BAD))
        codes = [violation.code for violation in chord_semantics(doc, Context())]
        self.assertIn("orphan-chord", codes)

    def test_negative_cursor_is_reported(self):
        doc = Document(ElementTree.fromstring(NEGATIVE))
        codes = [violation.code for violation in chord_semantics(doc, Context())]
        self.assertIn("negative-cursor", codes)

    def test_empty_measure_is_reported(self):
        doc = Document(
            ElementTree.fromstring(
                '<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>t</part-name></score-part></part-list>'
                '<part id="P1"><measure number="1"><attributes><divisions>4</divisions>'
                '<time><beats>4</beats><beat-type>4</beat-type></time></attributes></measure></part></score-partwise>'
            )
        )
        self.assertTrue(measure_lengths(doc, Context()))

    def test_implicit_measure_may_be_short_but_not_overfull(self):
        root = ElementTree.fromstring(
            '<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>t</part-name></score-part></part-list>'
            '<part id="P1"><measure number="1" implicit="yes"><attributes><divisions>4</divisions>'
            '<time><beats>4</beats><beat-type>4</beat-type></time></attributes>'
            '<note><pitch><step>C</step><octave>4</octave></pitch><duration>32</duration><voice>1</voice></note>'
            "</measure></part></score-partwise>"
        )
        self.assertTrue(measure_lengths(Document(root), Context()))


if __name__ == "__main__":
    unittest.main()
