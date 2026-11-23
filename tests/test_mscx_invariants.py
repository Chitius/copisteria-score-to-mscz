from __future__ import annotations

import unittest
from xml.etree import ElementTree

from scorepipe.core.mscx import MsxcDocument
from scorepipe.core.mscx_invariants import measure_lengths
from scorepipe.core.pass_base import Context


def violations(voice: str, time_signature: str = ""):
    doc = MsxcDocument(
        ElementTree.fromstring(
            "<museScore><Score><Staff id='1'><Measure><voice>"
            + time_signature
            + voice
            + "</voice></Measure></Staff></Score></museScore>"
        )
    )
    return measure_lengths(doc, Context())


def chord(kind: str = "quarter", duration: str | None = None) -> str:
    explicit = f"<duration>{duration}</duration>" if duration is not None else ""
    return (
        f"<Chord><durationType>{kind}</durationType>{explicit}"
        "<Note><pitch>60</pitch></Note></Chord>"
    )


class MscxMeasureLengthTest(unittest.TestCase):
    def test_tuplets_and_their_rests_use_sounding_duration(self):
        triplet = (
            "<Tuplet><normalNotes>2</normalNotes><actualNotes>3</actualNotes></Tuplet>"
            + chord()
            + "<Rest><durationType>quarter</durationType></Rest>"
            + chord()
            + "<endTuplet/>"
        )
        self.assertEqual(violations(triplet + triplet), [])

    def test_explicit_duration_overrides_type_and_dots(self):
        rest = (
            "<Rest><dots>2</dots><durationType>64th</durationType>"
            "<duration>1/48</duration></Rest>"
        )
        self.assertEqual(violations(rest + chord("whole", "47/48")), [])

    def test_explicit_duration_is_not_scaled_by_tuplet(self):
        body = (
            "<Tuplet><normalNotes>2</normalNotes><actualNotes>3</actualNotes></Tuplet>"
            + chord(duration="1/4") * 4
            + "<endTuplet/>"
        )
        self.assertEqual(violations(body), [])

    def test_nested_tuplets_enter_and_leave_the_ratio_stack(self):
        body = (
            "<Tuplet><normalNotes>2</normalNotes><actualNotes>3</actualNotes></Tuplet>"
            "<Tuplet><normalNotes>2</normalNotes><actualNotes>3</actualNotes></Tuplet>"
            + chord() * 9
            + "<endTuplet/><endTuplet/>"
        )
        self.assertEqual(violations(body), [])

    def test_real_overfull_measure_is_still_reported(self):
        result = violations(chord() * 4 + chord("eighth"))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].code, "mscx-measure-length")
        self.assertEqual(result[0].measure, 1)
        self.assertIn("4.5", result[0].detail)

    def test_dotted_notes_and_three_four_are_preserved(self):
        signature = "<TimeSig><sigN>3</sigN><sigD>4</sigD></TimeSig>"
        dotted_quarter = "<Chord><dots>1</dots><durationType>quarter</durationType></Chord>"
        self.assertEqual(violations(dotted_quarter * 2, signature), [])

    def test_secondary_voice_does_not_define_measure_length(self):
        doc = MsxcDocument(
            ElementTree.fromstring(
                "<museScore><Score><Staff id='1'><Measure>"
                f"<voice>{chord('whole')}</voice>"
                f"<voice>{chord() * 5}</voice>"
                "</Measure></Staff></Score></museScore>"
            )
        )
        self.assertEqual(measure_lengths(doc, Context()), [])

    def test_128th_and_256th_duration_types(self):
        for kind, count in (("128th", 128), ("256th", 256)):
            with self.subTest(kind=kind):
                rests = f"<Rest><durationType>{kind}</durationType></Rest>" * count
                self.assertEqual(violations(rests), [])

    def test_incomplete_tuplet_ratio_falls_back_to_nominal_duration(self):
        body = "<Tuplet/><endTuplet/>" + chord() * 4
        self.assertEqual(violations(body), [])


if __name__ == "__main__":
    unittest.main()
