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


def note(step: str, octave: int, duration: int, *, chord: bool = False) -> str:
    return (
        ("<note><chord/>" if chord else "<note>")
        + f"<pitch><step>{step}</step><octave>{octave}</octave></pitch>"
        + f"<duration>{duration}</duration><voice>1</voice></note>"
    )


def measure(number: int, body: str) -> str:
    return (
        f'<measure number="{number}">'
        "<attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
        f"{body}</measure>"
    )


def build(measures: str) -> Document:
    return Document(ElementTree.fromstring(PART.format(measures=measures)))


class VoiceLayersTest(unittest.TestCase):
    def test_fragments_become_clean_voices(self):
        body = (
            note("C", 4, 16)
            + note("E", 4, 16, chord=True)
            + "<backup><duration>16</duration></backup>"
            + note("F", 6, 6)
        )
        doc = build(measure(1, body) + measure(2, note("G", 4, 16)))
        run_pipeline(doc, Context(), structural=STRUCTURAL_PASSES, verifiers=[])
        first = doc.measures()[0]
        events = doc.events(first)
        self.assertEqual({event.voice for event in events}, {"1", "2"})
        short = next(event for event in events if event.element.findtext("pitch/step") == "F")
        self.assertEqual(short.duration, 1.5)
        self.assertIsNone(short.element.find("chord"))
        self.assertEqual(len([e for e in events if not e.rest and e.voice == "1"]), 2)
        self.assertEqual(measure_lengths(doc, Context()), [])

    def test_rest_overlapping_later_notes_is_rebuilt(self):
        body = (
            note("C", 4, 4)
            + note("D", 4, 4)
            + note("E", 4, 4)
            + "<note><rest/><duration>2</duration><voice>1</voice><type>eighth</type></note>"
            + "<backup><duration>1</duration></backup>"
            + note("F", 4, 1)
            + note("G", 4, 1)
            + note("A", 4, 1)
        )
        doc = build(measure(1, body) + measure(2, note("G", 4, 16)))
        run_pipeline(doc, Context(), structural=STRUCTURAL_PASSES, verifiers=[])

        events = doc.events(doc.measures()[0])
        end = 0.0
        for event in events:
            if event.chord:
                continue
            self.assertGreaterEqual(event.onset + 1e-6, end)
            end = max(end, event.end)
        self.assertEqual(end, 4.0)
        self.assertEqual(measure_lengths(doc, Context()), [])

    def test_clean_measure_is_untouched(self):
        doc = build(measure(1, note("C", 4, 16)) + measure(2, note("G", 4, 16)))
        run_pipeline(doc, Context(), structural=STRUCTURAL_PASSES, verifiers=[])
        first = doc.measures()[0]
        notes = first.findall(".//note")
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].findtext("duration"), "16")

    def test_second_run_is_a_no_op(self):
        body = (
            note("C", 4, 16)
            + note("E", 4, 16, chord=True)
            + "<backup><duration>16</duration></backup>"
            + note("F", 6, 6)
        )
        doc = build(measure(1, body) + measure(2, note("G", 4, 16)))
        ctx = Context()
        run_pipeline(doc, ctx, structural=STRUCTURAL_PASSES, verifiers=[])
        again = run_pipeline(doc, ctx, structural=STRUCTURAL_PASSES, verifiers=[])
        self.assertEqual(again.changes, 0)


if __name__ == "__main__":
    unittest.main()
