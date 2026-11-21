from __future__ import annotations

import unittest
from xml.etree import ElementTree

from scorepipe.core.document import Document
from scorepipe.core.invariants import measure_lengths
from scorepipe.core.pass_base import Context
from scorepipe.core.pipeline import run_pipeline
from scorepipe.passes import STRUCTURAL_PASSES
from scorepipe.passes.xml_voice_merge import MERGE_STAFF_VOICES

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

    def test_other_staff_keeps_its_forward_gap(self):
        # staff 1 has two voices (a sustained chord and a run); staff 2 starts on beat 3.
        # The rebuild must not swallow staff 2's <forward> (laputa m31).
        body = (
            note("C", 4, 16)
            + "<backup><duration>16</duration></backup>"
            + note("E", 4, 16, voice="2")
            + "<backup><duration>16</duration></backup>"
            + "<forward><duration>8</duration></forward>"
            + '<note><pitch><step>D</step><octave>3</octave></pitch>'
            '<duration>8</duration><voice>1</voice><staff>2</staff></note>'
        )
        doc = Document(ElementTree.fromstring(PART.format(measures=measure(body) + LAST)))
        MERGE_STAFF_VOICES.run(doc, Context())
        events = doc.events(doc.measures()[0])
        staff_two = [event for event in events if event.staff == "2"]
        self.assertEqual(len(staff_two), 1)
        self.assertEqual(staff_two[0].onset, 2.0)
        pitches = {event.element.findtext("pitch/step") for event in events if not event.rest}
        self.assertEqual(pitches, {"C", "E", "D"})

    def test_fill_conflict_is_left_alone(self):
        quarters = "".join(note(step, 4, 4) for step in ("C", "D", "E", "F"))
        body = quarters + "<backup><duration>16</duration></backup>" + note("G", 3, 16, voice="2")
        doc = Document(ElementTree.fromstring(PART.format(measures=measure(body) + LAST)))
        run_pipeline(doc, Context(), structural=STRUCTURAL_PASSES, verifiers=[])
        voices = {event.voice for event in doc.events(doc.measures()[0])}
        self.assertIn("2", voices)


    def test_tie_survives_when_the_duration_does_not_change(self):
        tied = (
            "<note><pitch><step>C</step><octave>4</octave></pitch>"
            "<duration>16</duration><tie type=\"start\"/><voice>1</voice></note>"
        )
        body = tied + "<backup><duration>16</duration></backup>" + note("E", 4, 16, voice="2")
        doc = Document(ElementTree.fromstring(PART.format(measures=measure(body) + LAST)))
        MERGE_STAFF_VOICES.run(doc, Context())
        notes = [event.element for event in doc.events(doc.measures()[0]) if not event.rest]
        tied_note = next(note for note in notes if note.findtext("pitch/step") == "C")
        self.assertIsNotNone(tied_note.find("tie"))


    def test_a_whole_note_over_a_rest_is_protected_from_retiming(self):
        rest = '<note><rest/><duration>4</duration><voice>1</voice></note>'
        body = (
            rest
            + note("B", 4, 4)
            + note("G", 4, 4)
            + note("B", 4, 4)
            + "<backup><duration>16</duration></backup>"
            + note("E", 3, 16, voice="2")
        )
        doc = Document(ElementTree.fromstring(PART.format(measures=measure(body) + LAST)))
        MERGE_STAFF_VOICES.run(doc, Context())
        events = [event for event in doc.events(doc.measures()[0]) if not event.rest]
        whole = next(e for e in events if e.element.findtext("pitch/step") == "E")
        self.assertEqual(whole.duration, 4.0)
        self.assertNotEqual(whole.voice, "1")

    def test_protected_long_notes_do_not_stretch_the_merged_line(self):
        rest = '<note><rest/><duration>4</duration><voice>{voice}</voice></note>'
        chord = (
            '<note><chord/><pitch><step>{step}</step><octave>3</octave></pitch>'
            "<duration>4</duration><voice>2</voice></note>"
        )
        body = (
            note("A", 2, 8, voice="1")
            + note("A", 2, 8, voice="1")
            + "<backup><duration>16</duration></backup>"
            + rest.format(voice=2)
            + note("E", 3, 4, voice="2")
            + chord.format(step="A")
            + chord.format(step="C")
            + rest.format(voice=2)
            + note("F", 3, 4, voice="2")
            + chord.format(step="D")
            + chord.format(step="B")
        )
        doc = Document(ElementTree.fromstring(PART.format(measures=measure(body) + LAST)))
        MERGE_STAFF_VOICES.run(doc, Context())
        events = [event for event in doc.events(doc.measures()[0]) if not event.rest]
        a_notes = [e for e in events if e.element.findtext("pitch/step") == "A" and e.element.findtext("pitch/octave") == "2"]
        chords = [e for e in events if e.element.findtext("pitch/step") in ("E", "F")]
        self.assertEqual({e.duration for e in a_notes}, {2.0})
        self.assertEqual(len({e.voice for e in a_notes}), 1)
        self.assertEqual(len({e.voice for e in chords}), 1)
        self.assertNotEqual(a_notes[0].voice, chords[0].voice)

    def test_a_measure_without_a_time_signature_inherits_the_previous_meter(self):
        first = (
            '<measure number="1"><attributes><divisions>8</divisions>'
            "<time><beats>2</beats><beat-type>4</beat-type></time></attributes>"
            + note("C", 4, 16)
            + "</measure>"
        )
        second = (
            '<measure number="2"><attributes><divisions>8</divisions></attributes>'
            + note("E", 5, 4)
            + note("D", 5, 4)
            + note("A", 4, 4)
            + note("F", 4, 3)
            + note("E", 4, 1)
            + "<backup><duration>16</duration></backup>"
            + note("F", 4, 4, voice="2")
            + "</measure>"
        )
        doc = Document(ElementTree.fromstring(PART.format(measures=first + second)))
        MERGE_STAFF_VOICES.run(doc, Context())
        events = doc.events(doc.measures()[1])
        self.assertEqual({event.voice for event in events if not event.rest}, {"1"})
        self.assertEqual(max(event.end for event in events), 2.0)
        self.assertEqual([event for event in events if event.rest], [])


if __name__ == "__main__":
    unittest.main()
