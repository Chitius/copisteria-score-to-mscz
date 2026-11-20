from __future__ import annotations

import unittest
from xml.etree import ElementTree

from scorepipe.core.document import Document
from scorepipe.core.invariants import measure_lengths
from scorepipe.core.pass_base import Context
from scorepipe.core.pipeline import run_pipeline
from scorepipe.passes import STRUCTURAL_PASSES

PART = """
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>t</part-name></score-part></part-list>
  <part id="P1">{measures}</part>
</score-partwise>
"""


def note(step: str, octave: int, duration: int, *, staff: int = 1, voice: str = "1") -> str:
    return (
        f"<note><pitch><step>{step}</step><octave>{octave}</octave></pitch>"
        f"<duration>{duration}</duration><voice>{voice}</voice><staff>{staff}</staff></note>"
    )


class FillBackupTest(unittest.TestCase):
    def test_padding_a_voice_does_not_shift_the_next_staff(self):
        body = (
            note("C", 5, 16)
            + "<backup><duration>16</duration></backup>"
            + note("E", 5, 12, voice="2")
            + "<backup><duration>12</duration></backup>"
            + note("G", 3, 16, staff=2)
        )
        measures = (
            '<measure number="1"><attributes><divisions>4</divisions>'
            "<time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
            + body
            + "</measure>"
            + '<measure number="2">'
            + note("A", 4, 16)
            + "</measure>"
        )
        doc = Document(ElementTree.fromstring(PART.format(measures=measures)))
        run_pipeline(doc, Context(), structural=STRUCTURAL_PASSES, verifiers=[])
        staff_two = [event for event in doc.events(doc.measures()[0]) if event.staff == "2"]
        self.assertEqual(len(staff_two), 1)
        self.assertEqual(staff_two[0].onset, 0.0)
        self.assertEqual(staff_two[0].duration, 4.0)
        self.assertEqual(measure_lengths(doc, Context()), [])


if __name__ == "__main__":
    unittest.main()
