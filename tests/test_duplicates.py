from __future__ import annotations

import unittest
from xml.etree import ElementTree

from scorepipe.core.document import Document
from scorepipe.core.pass_base import Context
from scorepipe.passes.xml_duplicates import DropDuplicateNotes

PART = """
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>t</part-name></score-part></part-list>
  <part id="P1"><measure number="1">
    <attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
    {body}
  </measure></part>
</score-partwise>
"""


def build(body: str) -> Document:
    return Document(ElementTree.fromstring(PART.format(body=body)))


def note(pitch: str, duration: int = 4, chord: bool = False) -> str:
    chord_tag = "<chord/>" if chord else ""
    return (
        f"<note>{chord_tag}<pitch><step>{pitch}</step><octave>4</octave></pitch>"
        f"<duration>{duration}</duration><voice>1</voice></note>"
    )


class DropDuplicateNotesTest(unittest.TestCase):
    def test_duplicate_chord_member_is_removed(self):
        doc = build(note("C", 16) + note("C", 16, chord=True))
        self.assertEqual(DropDuplicateNotes().run(doc, Context()).changed, 1)

    def test_base_note_with_chord_after_is_not_removed(self):
        doc = build(note("C", 4) + note("C", 4) + note("E", 4, chord=True))
        self.assertEqual(DropDuplicateNotes().run(doc, Context()).changed, 0)

    def test_different_pitches_are_kept(self):
        doc = build(note("C", 4) + note("D", 4))
        self.assertEqual(DropDuplicateNotes().run(doc, Context()).changed, 0)


if __name__ == "__main__":
    unittest.main()
