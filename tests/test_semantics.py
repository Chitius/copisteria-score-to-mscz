from __future__ import annotations

import unittest
from xml.etree import ElementTree

from scorepipe.core.document import Document
from scorepipe.core.invariants import chord_semantics, measure_lengths, part_measure_alignment
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

    def test_multi_part_musicxml_is_loaded_and_verified_across_all_parts(self):
        root = ElementTree.fromstring(
            '<score-partwise version="4.0"><part-list>'
            '<score-part id="P1"><part-name>Voice</part-name></score-part>'
            '<score-part id="P2"><part-name>Piano</part-name></score-part></part-list>'
            '<part id="P1"><measure number="1"><attributes><divisions>4</divisions>'
            '<time><beats>4</beats><beat-type>4</beat-type></time></attributes>'
            '<note><pitch><step>C</step><octave>5</octave></pitch><duration>16</duration><voice>1</voice></note>'
            "</measure></part>"
            '<part id="P2"><measure number="1"><attributes><divisions>4</divisions>'
            '<staves>2</staves><time><beats>4</beats><beat-type>4</beat-type></time></attributes>'
            '<note><pitch><step>C</step><octave>4</octave></pitch><duration>8</duration><voice>1</voice><staff>1</staff></note>'
            "</measure></part>"
            "</score-partwise>"
        )
        doc = Document(root)
        self.assertEqual([pid for pid, _ in doc.iter_parts()], ["P1", "P2"])
        self.assertEqual(doc.part_staff_offsets(), {"P1": 0, "P2": 1})
        violations = measure_lengths(doc, Context())
        self.assertEqual(len(violations), 1)
        self.assertTrue(violations[0].detail.startswith("P2 "))

    def test_part_measure_alignment_reports_mismatch(self):
        root = ElementTree.fromstring(
            '<score-partwise version="4.0"><part-list>'
            '<score-part id="P1"><part-name>a</part-name></score-part>'
            '<score-part id="P2"><part-name>b</part-name></score-part></part-list>'
            '<part id="P1"><measure number="1"/><measure number="2"/></part>'
            '<part id="P2"><measure number="1"/></part>'
            "</score-partwise>"
        )
        violations = part_measure_alignment(Document(root), Context())
        self.assertEqual([v.code for v in violations], ["part-measure-mismatch"])


if __name__ == "__main__":
    unittest.main()
