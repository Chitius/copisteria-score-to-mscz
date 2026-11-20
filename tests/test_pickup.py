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


class PickupTest(unittest.TestCase):
    def test_short_opening_bar_is_marked_not_padded(self):
        doc = build(measure(1, note("C", 8)) + measure(2, note("D", 16)))
        run_pipeline(doc, Context(), structural=STRUCTURAL_PASSES, verifiers=[])
        first = doc.measures()[0]
        self.assertEqual(first.get("implicit"), "yes")
        self.assertEqual(len(first.findall(".//note")), 1)  # no rest padding added
        self.assertEqual(measure_lengths(doc, Context()), [])

    def test_full_opening_bar_is_not_marked(self):
        doc = build(measure(1, note("C", 16)) + measure(2, note("D", 16)))
        run_pipeline(doc, Context(), structural=STRUCTURAL_PASSES, verifiers=[])
        self.assertIsNone(doc.measures()[0].get("implicit"))

    def test_second_run_is_a_no_op(self):
        doc = build(measure(1, note("C", 8)) + measure(2, note("D", 16)))
        ctx = Context()
        run_pipeline(doc, ctx, structural=STRUCTURAL_PASSES, verifiers=[])
        again = run_pipeline(doc, ctx, structural=STRUCTURAL_PASSES, verifiers=[])
        self.assertEqual(again.changes, 0)


if __name__ == "__main__":
    unittest.main()
