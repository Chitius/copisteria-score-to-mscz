from __future__ import annotations

import unittest
from xml.etree import ElementTree

from scorepipe.core.document import Document
from scorepipe.core.invariants import measure_lengths
from scorepipe.core.pass_base import Context
from scorepipe.passes.xml_redundant_voices import DropRedundantVoices

PART = """
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>t</part-name></score-part></part-list>
  <part id="P1">{measures}</part>
</score-partwise>
"""


def note(step="C", duration=16, *, voice="1", chord=False):
    chord_tag = "<chord/>" if chord else ""
    return (
        f"<note>{chord_tag}<pitch><step>{step}</step><octave>4</octave></pitch>"
        f"<duration>{duration}</duration><voice>{voice}</voice></note>"
    )


def measure(number, body):
    return (
        f'<measure number="{number}">'
        "<attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
        f"{body}</measure>"
    )


def build(measures):
    return Document(ElementTree.fromstring(PART.format(measures=measures)))


class DropRedundantVoicesTest(unittest.TestCase):
    def test_a_duplicate_secondary_voice_is_removed(self):
        body = note("C", 16) + "<backup><duration>16</duration></backup>" + note("C", 16, voice="2")
        doc = build(measure(1, body) + measure(2, note("D")))
        result = DropRedundantVoices().run(doc, Context())
        self.assertEqual(result.changed, 1)
        self.assertEqual({event.voice for event in doc.events(doc.measures()[0])}, {"1"})
        self.assertEqual(measure_lengths(doc, Context()), [])

    def test_a_voice_with_new_material_is_kept(self):
        body = note("C", 16) + "<backup><duration>16</duration></backup>" + note("E", 16, voice="2")
        doc = build(measure(1, body) + measure(2, note("D")))
        self.assertEqual(DropRedundantVoices().run(doc, Context()).changed, 0)

    def test_a_secondary_voice_of_only_rests_is_removed(self):
        rest = "<note><rest/><duration>16</duration><voice>2</voice></note>"
        body = note("C", 16) + "<backup><duration>16</duration></backup>" + rest
        doc = build(measure(1, body) + measure(2, note("D")))
        result = DropRedundantVoices().run(doc, Context())
        self.assertEqual(result.changed, 1)
        self.assertEqual({event.voice for event in doc.events(doc.measures()[0])}, {"1"})
        self.assertEqual(measure_lengths(doc, Context()), [])


if __name__ == "__main__":
    unittest.main()
