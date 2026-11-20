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


def note(step: str, octave: int, duration: int, *, voice: str = "1") -> str:
    return (
        f"<note><pitch><step>{step}</step><octave>{octave}</octave></pitch>"
        f"<duration>{duration}</duration><voice>{voice}</voice></note>"
    )


def measure(body: str) -> str:
    return (
        '<measure number="1"><attributes><divisions>4</divisions>'
        "<time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
        + body
        + "</measure>"
    )


LAST = '<measure number="2"><note><pitch><step>A</step><octave>4</octave></pitch><duration>16</duration><voice>1</voice></note></measure>'


class MergeStaffVoicesTest(unittest.TestCase):
    def test_two_voices_become_one_retimed_line(self):
        body = (
            note("C", 4, 16)
            + "<backup><duration>16</duration></backup>"
            + "<forward><duration>8</duration></forward>"
            + note("D", 4, 8, voice="2")
        )
        doc = Document(ElementTree.fromstring(PART.format(measures=measure(body) + LAST)))
        run_pipeline(doc, Context(), structural=STRUCTURAL_PASSES, verifiers=[])
        first = doc.measures()[0]
        events = doc.events(first)
        self.assertEqual({event.voice for event in events}, {"1"})
        pitches = [(event.element.findtext("pitch/step"), event.duration) for event in events]
        self.assertEqual(pitches, [("C", 2.0), ("D", 2.0)])
        self.assertEqual(measure_lengths(doc, Context()), [])

    def test_fill_conflict_is_left_alone(self):
        quarters = "".join(note(step, 4, 4) for step in ("C", "D", "E", "F"))
        body = quarters + "<backup><duration>16</duration></backup>" + note("G", 3, 16, voice="2")
        doc = Document(ElementTree.fromstring(PART.format(measures=measure(body) + LAST)))
        run_pipeline(doc, Context(), structural=STRUCTURAL_PASSES, verifiers=[])
        voices = {event.voice for event in doc.events(doc.measures()[0])}
        self.assertIn("2", voices)


if __name__ == "__main__":
    unittest.main()
