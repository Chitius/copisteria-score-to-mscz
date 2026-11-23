from __future__ import annotations

import unittest
from fractions import Fraction
from xml.etree import ElementTree

from scorepipe.core.musescore_ticks import (
    TICKS_PER_WHOLE,
    element_ticks,
    fraction_ticks,
    measure_report,
    voice_timeline,
    voice_ticks,
)


def voice(xml: str):
    return ElementTree.fromstring(f"<voice>{xml}</voice>")


def chord(kind: str = "quarter", duration: str | None = None) -> str:
    explicit = f"<duration>{duration}</duration>" if duration else ""
    return (
        f"<Chord><durationType>{kind}</durationType>{explicit}"
        "<Note><pitch>60</pitch></Note></Chord>"
    )


def rest(kind: str = "quarter") -> str:
    return f"<Rest><durationType>{kind}</durationType></Rest>"


class MuseScoreTicksTest(unittest.TestCase):
    def test_quarter_is_480_ticks(self):
        self.assertEqual(fraction_ticks(1), TICKS_PER_WHOLE)
        self.assertEqual(fraction_ticks(Fraction(1, 4)), 480)

    def test_fraction_ticks_rounds_half_away_from_zero(self):
        self.assertEqual(fraction_ticks(Fraction(1, 3840)), 1)
        self.assertEqual(fraction_ticks(Fraction(-1, 3840)), -1)
        self.assertEqual(fraction_ticks(Fraction(3, 3840)), 2)
        self.assertEqual(fraction_ticks(Fraction(-3, 3840)), -2)

    def test_duration_type_and_dot(self):
        self.assertEqual(element_ticks(ElementTree.fromstring("<Chord><durationType>quarter</durationType></Chord>")), 480)
        self.assertEqual(
            element_ticks(
                ElementTree.fromstring("<Chord><dots>1</dots><durationType>half</durationType></Chord>")
            ),
            1440,
        )

    def test_dots_after_duration_type_do_not_change_ticks(self):
        # MuseScore sets ticks when it reads <durationType>; a later <dots> is
        # only layout.  This is why the writer emits dots first.
        self.assertEqual(
            element_ticks(
                ElementTree.fromstring("<Chord><durationType>half</durationType><dots>1</dots></Chord>")
            ),
            960,
        )

    def test_tuplet_ratio(self):
        voice_xml = voice(
            "<Tuplet><normalNotes>2</normalNotes><actualNotes>3</actualNotes></Tuplet>"
            + chord("eighth")
            + "<endTuplet/>"
        )
        self.assertEqual(voice_ticks(voice_xml), 160)

    def test_explicit_duration_is_scaled_by_tuplet(self):
        body = (
            "<Tuplet><normalNotes>2</normalNotes><actualNotes>3</actualNotes></Tuplet>"
            + chord(duration="1/4") * 4
            + "<endTuplet/>"
        )
        self.assertEqual(voice_ticks(voice(body)), 1280)

    def test_explicit_whole_fraction(self):
        self.assertEqual(element_ticks(ElementTree.fromstring("<Rest><duration>5/12</duration></Rest>")), 800)

    def test_multiple_locations_accumulate_as_deltas(self):
        body = (
            "<location><fractions>1/8</fractions></location>"
            + chord()
            + "<location><fractions>1/8</fractions></location>"
            + chord()
        )
        timeline = voice_timeline(voice(body), Fraction(1))
        self.assertEqual([item.start for item in timeline.items], [Fraction(1, 8), Fraction(1, 2)])
        self.assertEqual(timeline.end, Fraction(3, 4))
        self.assertFalse(timeline.overlaps)

    def test_negative_location_moves_backwards(self):
        body = (
            "<location><fractions>1/2</fractions></location>"
            "<location><fractions>-1/8</fractions></location>"
            + rest("eighth")
        )
        timeline = voice_timeline(voice(body), Fraction(1))
        self.assertEqual(timeline.start, Fraction(3, 8))
        self.assertEqual(timeline.end, Fraction(1, 2))
        self.assertFalse(timeline.overlaps)

    def test_negative_location_can_create_an_overlap(self):
        body = chord("half") + "<location><fractions>-1/8</fractions></location>" + rest("eighth")
        timeline = voice_timeline(voice(body), Fraction(1))
        self.assertEqual(len(timeline.overlaps), 1)

    def test_nested_tuplets_multiply(self):
        body = (
            "<Tuplet><normalNotes>2</normalNotes><actualNotes>3</actualNotes>"
            "<baseNote>quarter</baseNote></Tuplet>"
            "<Tuplet><normalNotes>2</normalNotes><actualNotes>3</actualNotes>"
            "<baseNote>eighth</baseNote></Tuplet>"
            + chord("eighth") * 3
            + "<endTuplet/>"
            + chord("eighth") * 4
            + "<endTuplet/>"
            + chord("half")
        )
        timeline = voice_timeline(voice(body), Fraction(1))
        self.assertEqual(timeline.end, Fraction(1))
        self.assertEqual(len(timeline.spans), 2)
        self.assertFalse(timeline.invalid_tuplets)
        self.assertEqual(timeline.spans[0].nominal, Fraction(1, 2))
        self.assertEqual(timeline.spans[1].nominal, Fraction(1, 4))
        self.assertEqual(timeline.items[0].actual, Fraction(1, 18))

    def test_tuplet_written_span_detects_overfull(self):
        body = (
            "<Tuplet><normalNotes>4</normalNotes><actualNotes>6</actualNotes>"
            "<baseNote>16th</baseNote></Tuplet>"
            + chord("eighth") * 3
            + chord("16th") * 4
            + "<endTuplet/>"
        )
        timeline = voice_timeline(voice(body), Fraction(1))
        span = timeline.spans[0]
        self.assertEqual(span.written, Fraction(5, 8))
        self.assertEqual(span.target_written, Fraction(3, 8))
        self.assertEqual(span.delta, Fraction(1, 4))
        self.assertEqual(timeline.end, Fraction(5, 12))

    def test_measure_report_flags_delta(self):
        measure = ElementTree.fromstring(
            "<Measure><TimeSig><sigN>4</sigN><sigD>4</sigD></TimeSig>"
            "<voice><Chord><durationType>half</durationType></Chord></voice></Measure>"
        )
        self.assertEqual(measure_report(measure)[0]["delta"], -960)
        self.assertEqual(measure_report(measure)[0]["delta_fraction"], Fraction(-1, 2))


if __name__ == "__main__":
    unittest.main()
