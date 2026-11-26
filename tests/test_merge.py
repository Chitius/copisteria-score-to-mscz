from __future__ import annotations

import unittest
from xml.etree import ElementTree

from scorepipe.core.document import Document
from scorepipe.core.invariants import measure_lengths
from scorepipe.core.pass_base import Context
from scorepipe.core.pipeline import run_pipeline
from scorepipe.passes import STRUCTURAL_PASSES
from scorepipe.passes.xml_merge import MERGE_ALIGNED_VOICES

PART = """
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>t</part-name></score-part></part-list>
  <part id="P1">{measures}</part>
</score-partwise>
"""


def note(pitch: str, duration: int, voice: str = "1") -> str:
    return (
        f"<note><pitch><step>{pitch}</step><octave>4</octave></pitch>"
        f"<duration>{duration}</duration><voice>{voice}</voice></note>"
    )


def measure(number: int, body: str) -> str:
    return (
        f'<measure number="{number}">'
        "<attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
        f"{body}</measure>"
    )


def build(measures: str) -> Document:
    return Document(ElementTree.fromstring(PART.format(measures=measures)))


class MergeAlignedVoicesTest(unittest.TestCase):
    def test_aligned_secondary_voice_becomes_a_chord(self):
        body = note("C", 16) + "<backup><duration>16</duration></backup>" + note("E", 16, voice="2")
        doc = build(measure(1, body) + measure(2, note("G", 16)))
        run_pipeline(doc, Context(), structural=STRUCTURAL_PASSES, verifiers=[])
        first = doc.measures()[0]
        voices = {event.voice for event in doc.events(first)}
        self.assertEqual(voices, {"1"})
        self.assertEqual(len(first.findall(".//note")), 2)
        self.assertIsNotNone(first.find(".//note/chord"))
        self.assertEqual(measure_lengths(doc, Context()), [])

    def test_misaligned_voice_keeps_its_notes(self):
        body = note("C", 16) + "<backup><duration>16</duration></backup>" + note("E", 8, voice="2")
        doc = build(measure(1, body) + measure(2, note("G", 16)))
        run_pipeline(doc, Context(), structural=STRUCTURAL_PASSES, verifiers=[])
        events = [event for event in doc.events(doc.measures()[0]) if not event.rest]
        pitches = {event.element.findtext("pitch/step") for event in events}
        self.assertEqual(pitches, {"C", "E"})

    def test_second_run_is_a_no_op(self):
        body = note("C", 16) + "<backup><duration>16</duration></backup>" + note("E", 16, voice="2")
        doc = build(measure(1, body) + measure(2, note("G", 16)))
        ctx = Context()
        run_pipeline(doc, ctx, structural=STRUCTURAL_PASSES, verifiers=[])
        again = run_pipeline(doc, ctx, structural=STRUCTURAL_PASSES, verifiers=[])
        self.assertEqual(again.changes, 0)

    def test_a_pitch_already_in_the_primary_chord_is_not_doubled(self):
        chord = (
            "<note><pitch><step>E</step><octave>4</octave></pitch>"
            "<duration>16</duration><voice>1</voice></note>"
            "<note><chord/><pitch><step>G</step><octave>4</octave></pitch>"
            "<duration>16</duration><voice>1</voice></note>"
        )
        body = (
            note("C", 16)
            + "<note><chord/><pitch><step>E</step><octave>4</octave></pitch>"
            "<duration>16</duration><voice>1</voice></note>"
            + "<backup><duration>16</duration></backup>"
            + chord.replace("<voice>1</voice>", "<voice>2</voice>")
        )
        doc = build(measure(1, body) + measure(2, note("A", 16)))
        MERGE_ALIGNED_VOICES.run(doc, Context())
        pitches = [event.element.findtext("pitch/step") for event in doc.events(doc.measures()[0]) if not event.rest]
        self.assertEqual(sorted(pitches), ["C", "E", "G"])

    def test_direction_in_merged_secondary_voice_is_preserved(self):
        from scorepipe.core.directions import direction_onsets

        mf = (
            '<direction placement="below">'
            "<direction-type><dynamics><mf/></dynamics></direction-type>"
            "<staff>1</staff></direction>"
        )
        body = (
            note("C", 8)
            + "<note><chord/><pitch><step>G</step><octave>4</octave></pitch>"
            "<duration>8</duration><voice>1</voice></note>"
            + note("D", 8)
            + "<backup><duration>16</duration></backup>"
            + note("E", 8, voice="2")
            + mf
            + note("F", 8, voice="2")
        )
        doc = build(measure(1, body) + measure(2, note("A", 16)))
        MERGE_ALIGNED_VOICES.run(doc, Context())
        first = doc.measures()[0]
        self.assertEqual({event.voice for event in doc.events(first)}, {"1"})
        directions = first.findall("direction")
        self.assertEqual(len(directions), 1)
        self.assertIsNotNone(directions[0].find("direction-type/dynamics/mf"))
        self.assertEqual(direction_onsets(first)[id(directions[0])], 8)
        self.assertEqual(directions[0].findtext("offset"), "8")


if __name__ == "__main__":
    unittest.main()
