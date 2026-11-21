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
    def test_source_measure_backup_shrinks_and_new_voices_are_distinct(self):
        body_one = (
            '<note><pitch><step>C</step><octave>4</octave></pitch><duration>16</duration><voice>1</voice></note>'
            '<note><pitch><step>D</step><octave>4</octave></pitch><duration>8</duration><voice>1</voice></note>'
            "<backup><duration>24</duration></backup>"
            '<note><pitch><step>E</step><octave>4</octave></pitch><duration>16</duration><voice>2</voice></note>'
            '<note><pitch><step>F</step><octave>4</octave></pitch><duration>8</duration><voice>2</voice></note>'
        )
        measures = measure(1, body_one) + measure(2, note("G", 16))
        doc = build(measures)
        from scorepipe.passes import REBASE_MEASURES

        REBASE_MEASURES.run(doc, Context())
        first = doc.measures()[0]
        self.assertEqual(measure_lengths(doc, Context()), [])
        onsets = [(event.voice, event.onset) for event in doc.events(first)]
        self.assertIn(("2", 0.0), onsets)
        second = doc.measures()[1]
        blocks = {}
        for event in doc.events(second):
            if event.rest:
                continue
            blocks.setdefault((event.staff, event.voice), 0)
            blocks[(event.staff, event.voice)] += 1
        self.assertEqual(set(blocks), {("1", "1"), ("1", "2"), ("1", "3")})

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

    def test_stray_padding_rest_after_the_barline_is_dropped(self):
        body = note("C", 16) + '<note><rest/><duration>8</duration><voice>1</voice></note>'
        doc = build(measure(1, body) + measure(2, note("D", 16)))
        from scorepipe.passes import DROP_OVERFLOW_RESTS

        DROP_OVERFLOW_RESTS.run(doc, Context())
        first = doc.measures()[0]
        self.assertEqual(measure_lengths(doc, Context()), [])
        self.assertEqual(len([e for e in doc.events(first) if e.rest]), 0)


if __name__ == "__main__":
    unittest.main()
