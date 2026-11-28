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

    def test_a_sustained_quarter_is_not_shortened_to_fit_a_run(self):
        first = (
            '<measure number="1"><attributes><divisions>4</divisions>'
            "<time><beats>2</beats><beat-type>4</beat-type></time></attributes>"
            '<note><pitch><step>C</step><octave>4</octave></pitch>'
            "<duration>8</duration><voice>1</voice><type>half</type></note></measure>"
        )
        second = (
            '<measure number="2"><attributes><divisions>4</divisions></attributes>'
            '<note><pitch><step>A</step><octave>3</octave></pitch>'
            '<duration>4</duration><voice>1</voice><type>quarter</type></note>'
            '<note><chord/><pitch><step>D</step><octave>4</octave></pitch>'
            '<duration>4</duration><voice>1</voice><type>quarter</type></note>'
            '<note><chord/><pitch><step>F</step><octave>4</octave></pitch>'
            '<duration>4</duration><voice>1</voice><type>quarter</type></note>'
            '<note><chord/><pitch><step>A</step><octave>4</octave></pitch>'
            '<duration>4</duration><voice>1</voice><type>quarter</type></note>'
            + "".join(
                f'<note><pitch><step>{step}</step><octave>4</octave></pitch>'
                f"<duration>1</duration><voice>1</voice><type>16th</type></note>"
                for step in ("G", "F", "E", "D")
            )
            + "<backup><duration>8</duration></backup>"
            '<note><rest/><duration>4</duration><voice>2</voice><type>quarter</type></note>'
            '<note><pitch><step>D</step><octave>4</octave></pitch>'
            '<duration>4</duration><voice>2</voice><type>quarter</type></note>'
            "</measure>"
        )
        doc = Document(ElementTree.fromstring(PART.format(measures=first + second)))
        MERGE_STAFF_VOICES.run(doc, Context())
        second_measure = doc.events(doc.measures()[1])
        sustained = [
            event
            for event in second_measure
            if not event.rest
            and event.element.findtext("pitch/step") == "D"
            and event.onset == 1.0
            and event.duration == 1.0
        ]
        self.assertEqual(len(sustained), 1)
        self.assertEqual(sustained[0].voice, "2")

    def test_a_tuplet_measure_is_left_alone(self):
        measure = (
            '<measure number="1"><attributes><divisions>10080</divisions>'
            "<time><beats>3</beats><beat-type>4</beat-type></time></attributes>"
            '<note><pitch><step>G</step><octave>4</octave></pitch><duration>1680</duration>'
            "<voice>1</voice><type>16th</type>"
            "<time-modification><actual-notes>3</actual-notes><normal-notes>2</normal-notes>"
            "<normal-type>16th</normal-type></time-modification></note>"
            '<note><pitch><step>A</step><octave>4</octave></pitch><duration>1680</duration>'
            "<voice>1</voice><type>16th</type>"
            "<time-modification><actual-notes>3</actual-notes><normal-notes>2</normal-notes>"
            "<normal-type>16th</normal-type></time-modification></note>"
            "<backup><duration>3360</duration></backup>"
            '<note><pitch><step>B</step><octave>3</octave></pitch><duration>3360</duration>'
            "<voice>2</voice></note></measure>"
        )
        doc = Document(ElementTree.fromstring(PART.format(measures=measure)))
        result = MERGE_STAFF_VOICES.run(doc, Context())
        self.assertEqual(result.changed, 0)
        self.assertEqual(len(list(doc.root.iter("time-modification"))), 2)

    def test_a_rest_between_notes_stops_the_previous_note(self):
        first = (
            '<measure number="1"><attributes><divisions>4</divisions>'
            "<time><beats>2</beats><beat-type>4</beat-type></time></attributes>"
            '<note><pitch><step>C</step><octave>4</octave></pitch>'
            "<duration>8</duration><voice>1</voice></note></measure>"
        )
        second = (
            '<measure number="2"><attributes><divisions>4</divisions></attributes>'
            '<note><pitch><step>A</step><octave>3</octave></pitch>'
            '<duration>4</duration><voice>1</voice><type>quarter</type></note>'
            '<note><rest/><duration>4</duration><voice>1</voice><type>quarter</type></note>'
            "<backup><duration>8</duration></backup>"
            "<forward><duration>4</duration></forward>"
            '<note><pitch><step>A</step><octave>4</octave></pitch>'
            '<duration>2</duration><voice>2</voice><type>eighth</type></note>'
            '<note><rest/><duration>2</duration><voice>2</voice><type>eighth</type></note>'
            "</measure>"
        )
        doc = Document(ElementTree.fromstring(PART.format(measures=first + second)))
        MERGE_STAFF_VOICES.run(doc, Context())
        events = doc.events(doc.measures()[1])
        a4 = [event for event in events if not event.rest and event.element.findtext("pitch/octave") == "4"]
        rests = [event for event in events if event.rest]
        self.assertEqual([event.duration for event in a4], [0.5])
        self.assertEqual([event.onset for event in rests], [1.5])
        self.assertEqual([event.duration for event in rests], [0.5])

    def test_source_backup_inside_one_staff_is_kept(self):
        # Suzume m16: staff 1 is one voice whose padding rest starts half a beat early, so the
        # source splits that staff's stream with its own <backup 2>. Rebuilding staff 2 must not
        # re-insert the two halves as independent blocks: that moved the rest to the barline.
        staff_one = (
            note("D", 5, 2)
            + note("E", 5, 1)
            + note("F", 5, 1)
            + note("G", 5, 2)
            + note("F", 5, 1)
            + note("E", 5, 1)
            + note("D", 5, 6)
            + "<backup><duration>2</duration></backup>"
            + '<note><rest/><duration>4</duration><voice>1</voice><staff>1</staff></note>'
        )
        staff_two = (
            '<note><pitch><step>G</step><octave>3</octave></pitch><duration>16</duration>'
            "<voice>1</voice><staff>2</staff></note>"
            + "<backup><duration>16</duration></backup>"
            + '<note><pitch><step>B</step><octave>3</octave></pitch><duration>16</duration>'
            "<voice>2</voice><staff>2</staff></note>"
        )
        doc = Document(ElementTree.fromstring(PART.format(measures=measure(staff_one + staff_two) + LAST)))
        MERGE_STAFF_VOICES.run(doc, Context())
        rests = [event for event in doc.events(doc.measures()[0]) if event.rest]
        self.assertEqual(len(rests), 1)
        self.assertEqual(rests[0].onset, 3.0)
        self.assertEqual(rests[0].duration, 1.0)
    def test_generated_durations_never_silently_fall_back_to_quarter(self):
        from scorepipe.passes.xml_voice_merge import _type_for

        self.assertEqual(_type_for(0.125), ("32nd", 0))
        with self.assertRaises(ValueError):
            _type_for(1.0 / 3.0)

    def test_directions_in_rebuilt_staff_are_preserved_with_exact_onset(self):
        from scorepipe.core.directions import direction_onsets

        staff_one = (
            '<note><pitch><step>G</step><octave>4</octave></pitch><duration>16</duration>'
            "<voice>1</voice><staff>1</staff></note>"
        )
        ff = (
            '<direction placement="above">'
            "<direction-type><dynamics><ff/></dynamics></direction-type>"
            "<staff>2</staff></direction>"
        )
        mp = (
            '<direction placement="below">'
            "<direction-type><dynamics><mp/></dynamics></direction-type>"
            "<staff>2</staff></direction>"
        )
        staff_two = (
            ff
            + '<note><pitch><step>C</step><octave>3</octave></pitch><duration>8</duration>'
            "<voice>1</voice><staff>2</staff></note>"
            + mp
            + '<note><pitch><step>D</step><octave>3</octave></pitch><duration>8</duration>'
            "<voice>1</voice><staff>2</staff></note>"
            + "<backup><duration>16</duration></backup>"
            + "<forward><duration>8</duration></forward>"
            + '<note><pitch><step>E</step><octave>3</octave></pitch><duration>8</duration>'
            "<voice>2</voice><staff>2</staff></note>"
        )
        body = staff_one + "<backup><duration>16</duration></backup>" + staff_two
        doc = Document(ElementTree.fromstring(PART.format(measures=measure(body) + LAST)))
        MERGE_STAFF_VOICES.run(doc, Context())
        first = doc.measures()[0]
        onsets = direction_onsets(first)
        by_dyn = {}
        for direction in first.findall("direction"):
            dyn = direction.find("direction-type/dynamics")
            self.assertIsNotNone(dyn)
            tag = list(dyn)[0].tag
            by_dyn[tag] = (onsets[id(direction)], direction)
        self.assertEqual(set(by_dyn), {"ff", "mp"})
        self.assertEqual(by_dyn["ff"][0], 0)
        self.assertIsNone(by_dyn["ff"][1].find("offset"))
        self.assertEqual(by_dyn["ff"][1].findtext("staff"), "2")
        self.assertEqual(by_dyn["mp"][0], 8)
        self.assertEqual(by_dyn["mp"][1].findtext("offset"), "8")
        self.assertEqual(
            [child.tag for child in by_dyn["mp"][1]],
            ["direction-type", "offset", "staff"],
        )

    def test_tuplet_voices_merge_preserving_time_modification_and_brackets(self):
        # 4/4 bar at divisions=12:
        # beat 1: voice 1 has 3 eighth-triplets (dur=4 each, 3:2) + rest(36);
        #         voice 2 has matching harmony on beat 1 triplets + beats 2-4 dotted-half.
        def trip(step: str, octave: int, *, voice: str, tuplet: str | None = None) -> str:
            notations = f"<notations><tuplet type=\"{tuplet}\"/></notations>" if tuplet else ""
            return (
                f"<note><pitch><step>{step}</step><octave>{octave}</octave></pitch>"
                f"<duration>4</duration><voice>{voice}</voice><type>eighth</type>"
                "<time-modification><actual-notes>3</actual-notes><normal-notes>2</normal-notes>"
                "</time-modification>"
                f"{notations}</note>"
            )

        v1 = (
            trip("C", 5, voice="1", tuplet="start")
            + trip("D", 5, voice="1")
            + trip("E", 5, voice="1", tuplet="stop")
            + '<note><rest/><duration>36</duration><voice>1</voice><type>half</type><dot/></note>'
        )
        v2 = (
            trip("A", 4, voice="2", tuplet="start")
            + trip("B", 4, voice="2")
            + trip("C", 5, voice="2", tuplet="stop")
            + '<note><pitch><step>G</step><octave>4</octave></pitch>'
            '<duration>36</duration><voice>2</voice><type>half</type><dot/></note>'
        )
        body = (
            '<measure number="1"><attributes><divisions>12</divisions>'
            "<time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
            + v1
            + "<backup><duration>48</duration></backup>"
            + v2
            + "</measure>"
        )
        doc = Document(ElementTree.fromstring(PART.format(measures=body)))
        result = MERGE_STAFF_VOICES.run(doc, Context())
        self.assertEqual(result.changed, 1)
        events = doc.events(doc.measures()[0], 12.0)
        self.assertEqual({event.voice for event in events}, {"1"})
        chords = [e for e in events if e.chord]
        primaries = [e for e in events if not e.chord and not e.rest]
        self.assertEqual(len(chords), 3)
        # All 6 triplet notes retain time-modification, and only primary notes keep tuplet brackets
        for chord_ev in chords:
            self.assertIsNotNone(chord_ev.element.find("time-modification"))
            self.assertIsNone(chord_ev.element.find("notations/tuplet"))
        self.assertEqual(
            [e.element.find("notations/tuplet").get("type") for e in primaries if e.element.find("notations/tuplet") is not None],
            ["start", "stop"],
        )
        self.assertEqual(measure_lengths(doc, Context()), [])

    def test_sustained_note_over_tuplet_is_protected_and_tuplet_rest_kept(self):
        # divisions=12, 4/4:
        # voice 1: C5(4, 3:2, start) + rest(4, 3:2) + E5(4, 3:2, stop) + half+quarter rest(36)
        # voice 2: sustained C3 whole note(48)
        v1 = (
            '<note><pitch><step>C</step><octave>5</octave></pitch><duration>4</duration>'
            '<voice>1</voice><type>eighth</type>'
            '<time-modification><actual-notes>3</actual-notes><normal-notes>2</normal-notes></time-modification>'
            '<notations><tuplet type="start"/></notations></note>'
            '<note><rest/><duration>4</duration><voice>1</voice><type>eighth</type>'
            '<time-modification><actual-notes>3</actual-notes><normal-notes>2</normal-notes></time-modification></note>'
            '<note><pitch><step>E</step><octave>5</octave></pitch><duration>4</duration>'
            '<voice>1</voice><type>eighth</type>'
            '<time-modification><actual-notes>3</actual-notes><normal-notes>2</normal-notes></time-modification>'
            '<notations><tuplet type="stop"/></notations></note>'
            '<note><rest/><duration>36</duration><voice>1</voice><type>half</type><dot/></note>'
        )
        v2 = (
            '<note><pitch><step>C</step><octave>3</octave></pitch>'
            '<duration>48</duration><voice>2</voice><type>whole</type></note>'
        )
        body = (
            '<measure number="1"><attributes><divisions>12</divisions>'
            "<time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
            + v1
            + "<backup><duration>48</duration></backup>"
            + v2
            + "</measure>"
        )
        doc = Document(ElementTree.fromstring(PART.format(measures=body)))
        result = MERGE_STAFF_VOICES.run(doc, Context())
        self.assertEqual(result.changed, 1)
        self.assertEqual(measure_lengths(doc, Context()), [])
        rests = [e for e in doc.events(doc.measures()[0], 12.0) if e.rest]
        self.assertEqual(len(rests), 2)
        self.assertIsNotNone(rests[0].element.find("time-modification"))


if __name__ == "__main__":
    unittest.main()
