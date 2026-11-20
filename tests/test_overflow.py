from __future__ import annotations

import unittest
from xml.etree import ElementTree

from scorepipe.core.document import Document
from scorepipe.core.pass_base import Context
from scorepipe.passes.xml_overflow import DropOverflowDuplicates

PART = """
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>t</part-name></score-part></part-list>
  <part id="P1">{measures}</part>
</score-partwise>
"""


def note(pitch: str, duration: int) -> str:
    return (
        f"<note><pitch><step>{pitch}</step><octave>4</octave></pitch>"
        f"<duration>{duration}</duration><voice>1</voice></note>"
    )


def measure(number: int, body: str) -> str:
    return (
        f'<measure number="{number}">'
        "<attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
        f"{body}</measure>"
    )


def build(measures: str) -> Document:
    return Document(ElementTree.fromstring(PART.format(measures=measures)))


class DropOverflowDuplicatesTest(unittest.TestCase):
    def test_overflow_repeating_next_bar_is_dropped(self):
        doc = build(measure(1, note("C", 16) + note("C", 4)) + measure(2, note("C", 16)))
        result = DropOverflowDuplicates().run(doc, Context())
        self.assertEqual(result.changed, 1)

    def test_overflow_with_new_material_is_kept(self):
        doc = build(measure(1, note("C", 16) + note("D", 4)) + measure(2, note("E", 16)))
        self.assertEqual(DropOverflowDuplicates().run(doc, Context()).changed, 0)

    def test_removing_a_chord_base_removes_its_members(self):
        chord_member = (
            "<note><chord/><pitch><step>B</step><octave>4</octave></pitch>"
            "<duration>8</duration><voice>1</voice></note>"
        )
        doc = build(measure(1, note("C", 16) + note("G", 8) + chord_member) + measure(2, note("G", 8)))
        result = DropOverflowDuplicates().run(doc, Context())
        self.assertEqual(result.changed, 2)
        first = doc.measures()[0]
        self.assertEqual(first.findall(".//note/chord"), [])
        from scorepipe.core.invariants import chord_semantics

        self.assertEqual(chord_semantics(doc, Context()), [])


if __name__ == "__main__":
    unittest.main()
