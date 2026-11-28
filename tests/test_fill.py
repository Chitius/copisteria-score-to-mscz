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

    def test_last_measure_short_voice_is_padded_when_another_voice_fills_the_bar(self):
        # A 4/4 final bar: staff 1 has a whole note, staff 2 stops after a half note.  MuseScore's
        # importer pads staff 2 with a half rest, so the pipeline must write that rest as well;
        # otherwise the semantic master keeps a verifier finding nobody can see in the render.
        body = (
            note("C", 5, 16)
            + "<backup><duration>16</duration></backup>"
            + note("E", 3, 8, staff=2, voice="5")
        )
        measures = (
            '<measure number="1"><attributes><divisions>4</divisions>'
            "<time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
            + body
            + "</measure>"
        )
        doc = Document(ElementTree.fromstring(PART.format(measures=measures)))
        run_pipeline(doc, Context(), structural=STRUCTURAL_PASSES, verifiers=[])
        measure = doc.measures()[0]
        rests = [item for item in measure.findall("note") if item.find("rest") is not None]
        self.assertEqual(len(rests), 1)
        self.assertEqual(rests[0].findtext("duration"), "8")
        self.assertEqual(rests[0].findtext("voice"), "5")
        self.assertEqual(rests[0].findtext("staff"), "2")
        self.assertEqual(measure_lengths(doc, Context()), [])

    def test_last_measure_where_every_voice_is_short_keeps_its_printed_length(self):
        # A deliberate short ending (every voice stops together) must not be padded: the pass only
        # fills a final bar when another voice already proves the bar is a full metre long.
        measures = (
            '<measure number="1"><attributes><divisions>4</divisions>'
            "<time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
            + note("C", 5, 16)
            + "</measure>"
            + '<measure number="2">'
            + note("E", 4, 8)
            + "</measure>"
        )
        doc = Document(ElementTree.fromstring(PART.format(measures=measures)))
        run_pipeline(doc, Context(), structural=STRUCTURAL_PASSES, verifiers=[])
        measure = doc.measures()[1]
        self.assertEqual([item for item in measure.findall("note") if item.find("rest") is not None], [])
        violations = measure_lengths(doc, Context())
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].measure, 2)


if __name__ == "__main__":
    unittest.main()
