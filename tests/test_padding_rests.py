"""Padding rests: the OMR rest that fills a short voice must not overlap the notes of its voice."""

from __future__ import annotations

import unittest
from xml.etree import ElementTree

from scorepipe.core.document import Document
from scorepipe.core.invariants import measure_lengths
from scorepipe.core.pass_base import Context
from scorepipe.passes import FILL_PASS

PART = """
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>t</part-name></score-part></part-list>
  <part id="P1">{measures}</part>
</score-partwise>
"""


def note(step: str, octave: int, duration: int, *, staff: str = "1") -> str:
    return (
        f"<note><pitch><step>{step}</step><octave>{octave}</octave></pitch>"
        f"<duration>{duration}</duration><voice>1</voice><staff>{staff}</staff></note>"
    )


def measure(number: int, body: str) -> str:
    return (
        f'<measure number="{number}">'
        "<attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
        f"{body}</measure>"
    )


LAST = measure(2, note("A", 4, 16))


def build(body: str) -> Document:
    return Document(ElementTree.fromstring(PART.format(measures=measure(1, body) + LAST)))


# Suzume m16: eighth, 16th, 16th, eighth, 16th, 16th, dotted quarter = 14 ticks (3.5 beats); the
# OMR padding rest starts at beat 3 instead of 3.5 and runs to the barline.
MELODY = (
    note("D", 5, 2)
    + note("E", 5, 1)
    + note("F", 5, 1)
    + note("G", 5, 2)
    + note("F", 5, 1)
    + note("E", 5, 1)
    + note("D", 5, 6)
)
EARLY_REST = (
    "<backup><duration>2</duration></backup>"
    '<note><rest/><duration>4</duration><voice>1</voice><staff>1</staff></note>'
)


class PaddingRestTest(unittest.TestCase):
    def test_rest_starting_under_a_note_is_moved_to_the_note_end(self):
        doc = build(MELODY + EARLY_REST)
        result = FILL_PASS.run(doc, Context())
        self.assertEqual(result.changed, 1)
        rests = [event for event in doc.events(doc.measures()[0]) if event.rest]
        self.assertEqual([(event.onset, event.duration) for event in rests], [(3.5, 0.5)])
        self.assertEqual(measure_lengths(doc, Context()), [])
        self.assertIsNotNone(doc.measures()[0].find("forward"))

    def test_rest_that_does_not_overlap_is_left_alone(self):
        doc = build(MELODY + '<note><rest/><duration>2</duration><voice>1</voice><staff>1</staff></note>')
        result = FILL_PASS.run(doc, Context())
        self.assertEqual(result.changed, 0)
        self.assertIsNone(doc.measures()[0].find("forward"))

    def test_second_run_is_a_no_op(self):
        doc = build(MELODY + EARLY_REST)
        FILL_PASS.run(doc, Context())
        self.assertEqual(FILL_PASS.run(doc, Context()).changed, 0)


if __name__ == "__main__":
    unittest.main()
