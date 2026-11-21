from __future__ import annotations

import unittest
from xml.etree import ElementTree

from scorepipe.core.document import Document
from scorepipe.core.pass_base import Context
from scorepipe.passes.xml_tie_slurs import ReconcileTieSlurs

PART = """
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>t</part-name></score-part></part-list>
  <part id="P1">{measures}</part>
</score-partwise>
"""


def note(step, octave, duration, *, tie=None, slur=None, voice="1", chord=False):
    tie_tag = f'<tie type="{tie}"/>' if tie else ""
    slur_tag = f'<slur type="{slur}" number="1"/>' if slur else ""
    notations = f"<notations>{slur_tag}</notations>" if slur_tag else ""
    chord_tag = "<chord/>" if chord else ""
    return (
        f"<note>{chord_tag}<pitch><step>{step}</step><octave>{octave}</octave></pitch>"
        f"<duration>{duration}</duration>{tie_tag}<voice>{voice}</voice>{notations}</note>"
    )


def measure(body, number=1):
    return (
        f'<measure number="{number}"><attributes><divisions>4</divisions>'
        "<time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
        + body
        + "</measure>"
    )


def build(body):
    measures = body if body.lstrip().startswith("<measure") else measure(body)
    return Document(ElementTree.fromstring(PART.format(measures=measures)))


class ReconcileTieSlursTest(unittest.TestCase):
    def test_tie_wins_over_a_duplicate_slur(self):
        doc = build(note("C", 4, 8, tie="start", slur="start") + note("C", 4, 8, tie="stop", slur="stop"))
        result = ReconcileTieSlurs().run(doc, Context())
        self.assertEqual(result.changed, 1)
        self.assertEqual(len(list(doc.root.iter("slur"))), 0)
        self.assertEqual(len(list(doc.root.iter("tie"))), 2)
        self.assertEqual(ReconcileTieSlurs().run(doc, Context()).changed, 0)

    def test_a_tie_spanning_another_pitch_becomes_a_slur(self):
        body = (
            note("C", 4, 4, tie="start")
            + note("D", 4, 4)
            + note("C", 4, 4, tie="stop")
            + note("C", 4, 4)
        )
        doc = build(body)
        result = ReconcileTieSlurs().run(doc, Context())
        self.assertEqual(result.changed, 1)
        self.assertEqual(len(list(doc.root.iter("tie"))), 0)
        self.assertEqual(len(list(doc.root.iter("slur"))), 2)

    def test_a_contiguous_same_pitch_slur_becomes_a_tie(self):
        doc = build(note("C", 4, 8, slur="start") + note("C", 4, 8, slur="stop"))
        result = ReconcileTieSlurs().run(doc, Context())
        self.assertEqual(result.changed, 1)
        self.assertEqual(len(list(doc.root.iter("slur"))), 0)
        self.assertEqual(len(list(doc.root.iter("tie"))), 2)

    def test_slur_sharing_the_tie_start_and_stop_time_is_removed(self):
        doc = build(
            measure(note("G", 4, 16, tie="start", slur="start"), 1)
            + measure(note("G", 4, 16, tie="stop") + note("E", 4, 16, slur="stop", chord=True), 2)
        )
        self.assertEqual(ReconcileTieSlurs().run(doc, Context()).changed, 1)
        self.assertEqual(len(list(doc.root.iter("slur"))), 0)
        self.assertEqual(len(list(doc.root.iter("tie"))), 2)

    def test_slur_sharing_the_tie_stop_and_start_time_is_removed(self):
        doc = build(
            measure(note("G", 4, 16, tie="start") + note("E", 4, 16, slur="start", chord=True), 1)
            + measure(note("G", 4, 16, tie="stop", slur="stop"), 2)
        )
        self.assertEqual(ReconcileTieSlurs().run(doc, Context()).changed, 1)
        self.assertEqual(len(list(doc.root.iter("slur"))), 0)
        self.assertEqual(len(list(doc.root.iter("tie"))), 2)


if __name__ == "__main__":
    unittest.main()
