from __future__ import annotations

import unittest
from xml.etree import ElementTree

from scorepipe.core.document import Document
from scorepipe.core.invariants import measure_lengths
from scorepipe.core.pass_base import Context
from scorepipe.passes.xml_measures import FillShortMeasures
from scorepipe.passes.xml_slurs import SanitizeSlurs

PART = """
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>t</part-name></score-part></part-list>
  <part id="P1">{measures}</part>
</score-partwise>
"""


def build(measures: str) -> Document:
    return Document(ElementTree.fromstring(PART.format(measures=measures)))


def measure(number: int, body: str, time: bool = True) -> str:
    attributes = (
        "<attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
        if time
        else ""
    )
    return f'<measure number="{number}">{attributes}{body}</measure>'


def note(step: str, duration: int, slur: str = "", voice: str = "1") -> str:
    notations = f'<notations><slur type="{slur}" number="1"/></notations>' if slur else ""
    return (
        f"<note><pitch><step>{step}</step><octave>4</octave></pitch>"
        f"<duration>{duration}</duration><voice>{voice}</voice>{notations}</note>"
    )


class SanitizeSlursTest(unittest.TestCase):
    def test_dangling_start_is_removed(self):
        doc = build(measure(1, note("C", 16, slur="start")))
        result = SanitizeSlurs().run(doc, Context())
        self.assertEqual(result.changed, 1)
        self.assertEqual(doc.root.findall(".//slur"), [])

    def test_long_pair_is_removed(self):
        parts = []
        for number in range(1, 9):
            slur = "start" if number == 1 else ("stop" if number == 8 else "")
            parts.append(measure(number, note("C", 16, slur=slur)))
        doc = build("".join(parts))
        result = SanitizeSlurs().run(doc, Context())
        self.assertEqual(result.changed, 2)
        self.assertEqual(doc.root.findall(".//slur"), [])

    def test_normal_pair_survives(self):
        doc = build(measure(1, note("C", 16, slur="start")) + measure(2, note("C", 16, slur="stop")))
        result = SanitizeSlurs().run(doc, Context())
        self.assertEqual(result.changed, 0)
        self.assertEqual(len(doc.root.findall(".//slur")), 2)


class FillShortMeasuresTest(unittest.TestCase):
    def test_short_voice_gets_a_rest(self):
        doc = build(measure(1, note("C", 4)) + measure(2, note("D", 16)))
        result = FillShortMeasures().run(doc, Context())
        self.assertEqual(result.changed, 1)
        events = doc.events(doc.measures()[0])
        self.assertEqual(max(event.end for event in events), 4.0)
        self.assertTrue(any(event.rest for event in events))
        self.assertEqual(measure_lengths(doc, Context()), [])

    def test_last_measure_is_left_alone_by_default(self):
        doc = build(measure(1, note("C", 16)) + measure(2, note("D", 8)))
        FillShortMeasures().run(doc, Context())
        self.assertEqual(max(event.end for event in doc.events(doc.measures()[1])), 2.0)


if __name__ == "__main__":
    unittest.main()
