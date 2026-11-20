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


class RebaseMeasuresTest(unittest.TestCase):
    def test_overflow_moves_to_the_next_measure_as_a_new_voice(self):
        doc = build(measure(1, note("C", 16) + note("E", 4)) + measure(2, note("D", 16)))
        report = run_pipeline(doc, Context(), structural=STRUCTURAL_PASSES, verifiers=[])
        self.assertGreater(report.changes, 0)

        first = doc.measures()[0]
        self.assertEqual(max(event.end for event in doc.events(first)), 4.0)
        self.assertEqual(len(first.findall(".//note")), 1)

        second = doc.measures()[1]
        voices = {event.voice for event in doc.events(second)}
        self.assertIn("2", voices)
        self.assertEqual(measure_lengths(doc, Context()), [])

    def test_second_run_is_a_no_op(self):
        doc = build(measure(1, note("C", 16) + note("E", 4)) + measure(2, note("D", 16)))
        ctx = Context()
        run_pipeline(doc, ctx, structural=STRUCTURAL_PASSES, verifiers=[])
        again = run_pipeline(doc, ctx, structural=STRUCTURAL_PASSES, verifiers=[])
        self.assertEqual(again.changes, 0)

    def test_note_crossing_the_barline_is_split_and_tied(self):
        body = note("C", 4) + note("D", 4) + note("E", 4) + note("F", 8)
        doc = build(measure(1, body) + measure(2, note("G", 16)))
        run_pipeline(doc, Context(), structural=STRUCTURAL_PASSES, verifiers=[])
        self.assertEqual(measure_lengths(doc, Context()), [])

        first_notes = doc.measures()[0].findall(".//note")
        f_first = next(n for n in first_notes if n.findtext("pitch/step") == "F")
        self.assertEqual(f_first.findtext("duration"), "4")  # one beat left before the barline
        self.assertTrue(any(tie.get("type") == "start" for tie in f_first.findall("tie")))

        second_notes = doc.measures()[1].findall(".//note")
        f_second = next(n for n in second_notes if n.findtext("pitch/step") == "F")
        self.assertEqual(f_second.findtext("duration"), "4")
        self.assertTrue(any(tie.get("type") == "stop" for tie in f_second.findall("tie")))


if __name__ == "__main__":
    unittest.main()
