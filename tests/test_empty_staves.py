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


def measure(number: int, body: str) -> str:
    return (
        f'<measure number="{number}">'
        "<attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
        f"{body}</measure>"
    )


NOTE = (
    "<note><pitch><step>C</step><octave>5</octave></pitch>"
    "<duration>16</duration><voice>1</voice><staff>1</staff></note>"
)
LOW = (
    "<note><pitch><step>C</step><octave>3</octave></pitch>"
    "<duration>16</duration><voice>1</voice><staff>2</staff></note>"
)


class EmptyStaffTest(unittest.TestCase):
    def test_short_bar_backup_matches_the_content(self):
        measures = (
            '<measure number="1"><attributes><divisions>4</divisions>'
            "<time><beats>3</beats><beat-type>4</beat-type></time></attributes>"
            '<note><pitch><step>A</step><octave>4</octave></pitch>'
            '<duration>8</duration><voice>1</voice><staff>1</staff></note></measure>'
            + '<measure number="2"><note><pitch><step>B</step><octave>3</octave></pitch>'
            '<duration>12</duration><voice>1</voice><staff>2</staff></note></measure>'
        )
        doc = Document(ElementTree.fromstring(PART.format(measures=measures)))
        from scorepipe.core.invariants import chord_semantics
        from scorepipe.passes.xml_empty_staves import PAD_EMPTY_STAVES

        PAD_EMPTY_STAVES.run(doc, Context())
        self.assertEqual(chord_semantics(doc, Context()), [])
        staff_two = [event for event in doc.events(doc.measures()[0]) if event.staff == "2"]
        self.assertEqual(len(staff_two), 1)
        self.assertEqual(staff_two[0].onset, 0.0)
        self.assertEqual(staff_two[0].duration, 3.0)

    def test_pickup_is_not_padded(self):
        measures = (
            '<measure number="1" implicit="yes"><attributes><divisions>4</divisions>'
            "<time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
            '<note><pitch><step>A</step><octave>4</octave></pitch>'
            '<duration>8</duration><voice>1</voice><staff>1</staff></note></measure>'
            + '<measure number="2"><note><pitch><step>B</step><octave>3</octave></pitch>'
            '<duration>16</duration><voice>1</voice><staff>2</staff></note></measure>'
        )
        doc = Document(ElementTree.fromstring(PART.format(measures=measures)))
        from scorepipe.passes.xml_empty_staves import PAD_EMPTY_STAVES

        PAD_EMPTY_STAVES.run(doc, Context())
        staff_two = [event for event in doc.events(doc.measures()[0]) if event.staff == "2"]
        self.assertEqual(staff_two, [])
    def test_silent_staff_gets_a_measure_rest(self):
        measures = measure(1, NOTE) + measure(2, NOTE) + measure(3, LOW)
        doc = Document(ElementTree.fromstring(PART.format(measures=measures)))
        run_pipeline(doc, Context(), structural=STRUCTURAL_PASSES, verifiers=[])
        for number, measure_element in doc.iter_measures():
            if number == 3:
                continue
            staff_two = [event for event in doc.events(measure_element) if event.staff == "2"]
            self.assertEqual(len(staff_two), 1, f"measure {number}")
            self.assertIsNotNone(staff_two[0].element.find("rest"))
            self.assertEqual(staff_two[0].element.find("rest").get("measure"), "yes")
        self.assertEqual(measure_lengths(doc, Context()), [])

    def test_second_run_is_a_no_op(self):
        measures = measure(1, NOTE) + measure(2, NOTE) + measure(3, LOW)
        doc = Document(ElementTree.fromstring(PART.format(measures=measures)))
        ctx = Context()
        run_pipeline(doc, ctx, structural=STRUCTURAL_PASSES, verifiers=[])
        again = run_pipeline(doc, ctx, structural=STRUCTURAL_PASSES, verifiers=[])
        self.assertEqual(again.changes, 0)


if __name__ == "__main__":
    unittest.main()
