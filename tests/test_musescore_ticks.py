from __future__ import annotations

import unittest
from xml.etree import ElementTree

from scorepipe.core.musescore_ticks import (
    TICKS_PER_WHOLE,
    element_ticks,
    fraction_ticks,
    measure_report,
    voice_ticks,
)


def voice(xml: str):
    return ElementTree.fromstring(f"<voice>{xml}</voice>")


class MuseScoreTicksTest(unittest.TestCase):
    def test_quarter_is_480_ticks(self):
        self.assertEqual(fraction_ticks(1), TICKS_PER_WHOLE)
        self.assertEqual(fraction_ticks(1 / 4), 480)

    def test_duration_type_and_dot(self):
        self.assertEqual(element_ticks(ElementTree.fromstring("<Chord><durationType>quarter</durationType></Chord>")), 480)
        self.assertEqual(element_ticks(ElementTree.fromstring("<Chord><durationType>half</durationType><dots>1</dots></Chord>")), 1440)

    def test_tuplet_ratio(self):
        voice_xml = voice(
            "<Tuplet><normalNotes>2</normalNotes><actualNotes>3</actualNotes></Tuplet>"
            "<Chord><durationType>eighth</durationType></Chord>"
            "<endTuplet/>"
        )
        self.assertEqual(voice_ticks(voice_xml), 160)

    def test_explicit_whole_fraction(self):
        self.assertEqual(element_ticks(ElementTree.fromstring("<Rest><duration>5/12</duration></Rest>")), 800)

    def test_measure_report_flags_delta(self):
        measure = ElementTree.fromstring(
            "<Measure><TimeSig><sigN>4</sigN><sigD>4</sigD></TimeSig>"
            "<voice><Chord><durationType>half</durationType></Chord></voice></Measure>"
        )
        self.assertEqual(measure_report(measure)[0]["delta"], -960)


if __name__ == "__main__":
    unittest.main()
