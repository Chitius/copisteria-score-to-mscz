from __future__ import annotations

import unittest
from xml.etree import ElementTree

from scorepipe.core.document import Document
from scorepipe.core.pass_base import Context
from scorepipe.passes.xml_clefs import DropRedundantClefs, DropRedundantKeySignatures

PART = """
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>t</part-name></score-part></part-list>
  <part id="P1">{measures}</part>
</score-partwise>
"""


def build(measures: str) -> Document:
    return Document(ElementTree.fromstring(PART.format(measures=measures)))


def measure(number: int, clef: str = "", key: str = "") -> str:
    attributes = '<attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time>' + clef + key + "</attributes>"
    return f'<measure number="{number}">{attributes}<note><rest/><duration>16</duration></note></measure>'


G_CLEF = "<clef><sign>G</sign><line>2</line></clef>"
F_CLEF = "<clef><sign>F</sign><line>4</line></clef>"
C_NONE = "<key><fifths>0</fifths></key>"
C_G = "<key><fifths>1</fifths></key>"


class DropRedundantClefsTest(unittest.TestCase):
    def test_repeated_clef_is_removed(self):
        doc = build(measure(1, G_CLEF) + measure(2, G_CLEF))
        self.assertEqual(DropRedundantClefs().run(doc, Context()).changed, 1)
        self.assertEqual(doc.measures()[1].findall(".//clef"), [])

    def test_changed_clef_is_kept(self):
        doc = build(measure(1, G_CLEF) + measure(2, F_CLEF))
        self.assertEqual(DropRedundantClefs().run(doc, Context()).changed, 0)
        self.assertEqual(len(doc.measures()[1].findall(".//clef")), 1)

    def test_clef_returns_after_a_change_is_kept(self):
        doc = build(measure(1, G_CLEF) + measure(2, F_CLEF) + measure(3, G_CLEF))
        self.assertEqual(DropRedundantClefs().run(doc, Context()).changed, 0)


class DropRedundantKeySignaturesTest(unittest.TestCase):
    def test_repeated_key_is_removed(self):
        doc = build(measure(1, key=C_NONE) + measure(2, key=C_NONE))
        self.assertEqual(DropRedundantKeySignatures().run(doc, Context()).changed, 1)

    def test_key_change_is_kept(self):
        doc = build(measure(1, key=C_NONE) + measure(2, key=C_G))
        self.assertEqual(DropRedundantKeySignatures().run(doc, Context()).changed, 0)

    def test_key_is_removed_even_when_other_attributes_stay(self):
        doc = build(measure(1, key=C_NONE) + measure(2, key=C_NONE))
        DropRedundantKeySignatures().run(doc, Context())
        second = doc.measures()[1]
        self.assertEqual(second.findall(".//key"), [])
        self.assertIsNotNone(second.find("attributes/time"))


if __name__ == "__main__":
    unittest.main()
