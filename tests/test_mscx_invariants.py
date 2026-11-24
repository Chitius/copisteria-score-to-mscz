from __future__ import annotations

import unittest
from xml.etree import ElementTree

from scorepipe.core.mscx import MsxcDocument
from scorepipe.core.mscx_invariants import (
    empty_voices,
    hidden_non_measure_rests,
    measure_lengths,
    padding_voices,
    text_voice_rests,
    voice_order,
)
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


def rest(kind: str = "quarter") -> str:
    return f"<Rest><durationType>{kind}</durationType></Rest>"


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

    def test_explicit_duration_is_scaled_by_tuplet(self):
        # MuseScore stores the *written* duration in <duration>; a tuplet then
        # divides it by actualNotes/normalNotes.  Four quarter notes inside a
        # 3:2 tuplet therefore sound for 4/6 of a whole note, not 4/4.
        body = (
            "<Tuplet><normalNotes>2</normalNotes><actualNotes>3</actualNotes></Tuplet>"
            + chord(duration="1/4") * 4
            + "<endTuplet/>"
        )
        result = violations(body)
        self.assertEqual(len(result), 1)
        self.assertIn("1280 ticks", result[0].detail)

    def test_nested_tuplets_enter_and_leave_the_ratio_stack(self):
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

    def test_secondary_voice_may_be_short_but_not_overfull(self):
        doc = MsxcDocument(
            ElementTree.fromstring(
                "<museScore><Score><Staff id='1'><Measure>"
                f"<voice>{chord('whole')}</voice>"
                f"<voice>{chord() * 5}</voice>"
                "</Measure></Staff></Score></museScore>"
            )
        )
        result = measure_lengths(doc, Context())
        self.assertEqual(len(result), 1)
        self.assertIn("5", result[0].detail)

    def test_short_secondary_voice_is_not_reported_as_measure_error(self):
        doc = MsxcDocument(
            ElementTree.fromstring(
                "<museScore><Score><Staff id='1'><Measure>"
                f"<voice>{chord('whole')}</voice>"
                f"<voice>{chord('half')}</voice>"
                "</Measure></Staff></Score></museScore>"
            )
        )
        self.assertEqual(measure_lengths(doc, Context()), [])

    def test_128th_duration_type(self):
        # 256th is below MuseScore's 1920-tick whole grid (7.5 ticks), so it
        # cannot sum to a whole measure without tick rounding.
        rests = "<Rest><durationType>128th</durationType></Rest>" * 128
        self.assertEqual(violations(rests), [])

    def test_incomplete_tuplet_ratio_falls_back_to_nominal_duration(self):
        body = "<Tuplet/><endTuplet/>" + chord() * 4
        self.assertEqual(violations(body), [])

    def test_explicitly_visible_rest_is_not_hidden(self):
        body = (
            '<Rest><durationType>quarter</durationType><visible>1</visible></Rest>'
            + chord("half")
        )
        doc = MsxcDocument(
            ElementTree.fromstring(
                "<museScore><Score><Staff id='1'><Measure><voice>"
                + body
                + "</voice></Measure></Staff></Score></museScore>"
            )
        )
        self.assertEqual(hidden_non_measure_rests(doc, Context()), [])

    def test_hidden_rest_is_reported(self):
        body = (
            '<Rest><durationType>quarter</durationType><visible>0</visible></Rest>'
            + chord("half")
        )
        doc = MsxcDocument(
            ElementTree.fromstring(
                "<museScore><Score><Staff id='1'><Measure><voice>"
                + body
                + "</voice></Measure></Staff></Score></museScore>"
            )
        )
        self.assertEqual(len(hidden_non_measure_rests(doc, Context())), 1)

    def test_text_voice_rest_is_reported(self):
        doc = _doc_with_voices(
            "<voice><StaffText>text</StaffText><Rest><durationType>measure</durationType></Rest></voice>"
            f"<voice>{chord('whole')}</voice>"
        )
        self.assertEqual(len(text_voice_rests(doc, Context())), 1)

    def test_lone_text_voice_keeps_its_measure_rest(self):
        # Suzume m1: Tempo + Dynamic + a whole-measure rest is the staff's only content.
        doc = _doc_with_voices(
            "<voice><Tempo><tempo>1.3</tempo><text>q = 78</text></Tempo>"
            "<Rest><durationType>measure</durationType><duration>1/1</duration></Rest></voice>"
        )
        self.assertEqual(text_voice_rests(doc, Context()), [])

    def test_measure_without_written_time_is_reported(self):
        doc = _doc_with_voices(
            "<voice><Dynamic><subtype>mf</subtype></Dynamic><TimeSig><sigN>4</sigN><sigD>4</sigD></TimeSig></voice>"
        )
        violations = measure_lengths(doc, Context())
        self.assertEqual([violation.code for violation in violations], ["mscx-measure-length"])

    def test_padding_voice_is_reported(self):
        doc = _doc_with_voices(f"<voice>{chord('whole')}</voice><voice>{rest('whole')}</voice>")
        self.assertEqual(len(padding_voices(doc, Context())), 1)

    def test_voice_order_is_reported_when_a_thin_voice_precedes_a_dense_one(self):
        doc = _doc_with_voices(
            f"<voice>{chord('whole')}</voice><voice>{chord()}{chord()}{chord()}{chord()}</voice>"
        )
        self.assertEqual(len(voice_order(doc, Context())), 1)

    def test_empty_voice_is_reported(self):
        doc = _doc_with_voices("<voice><BarLine/></voice>")
        self.assertEqual(len(empty_voices(doc, Context())), 1)


def _doc_with_voices(voices: str) -> MsxcDocument:
    return MsxcDocument(
        ElementTree.fromstring(
            "<museScore><Score><Staff id='1'><Measure>"
            + voices
            + "</Measure></Staff></Score></museScore>"
        )
    )


if __name__ == "__main__":
    unittest.main()


class MeterInheritanceTest(unittest.TestCase):
    """MuseScore writes the signature on the top staff; the others share the system metre."""

    def _two_staves(self, include_time_on_second: bool) -> MsxcDocument:
        timesig = "<TimeSig><sigN>3</sigN><sigD>4</sigD></TimeSig>"
        second = timesig if include_time_on_second else ""
        return MsxcDocument(
            ElementTree.fromstring(
                "<museScore><Score>"
                "<Staff id='1'><Measure><voice>"
                + timesig
                + "<Chord><durationType>half</durationType><Note><pitch>60</pitch></Note></Chord>"
                + "<Chord><durationType>quarter</durationType><Note><pitch>62</pitch></Note></Chord>"
                + "</voice></Measure></Staff>"
                "<Staff id='2'><Measure><voice>"
                + second
                + "<Chord><durationType>half</durationType><Note><pitch>40</pitch></Note></Chord>"
                + "<Chord><durationType>quarter</durationType><Note><pitch>41</pitch></Note></Chord>"
                + "</voice></Measure></Staff>"
                "</Score></museScore>"
            )
        )

    def test_the_second_staff_inherits_three_four(self):
        found = measure_lengths(self._two_staves(False), Context())
        self.assertEqual(found, [], [str(v) for v in found])

    def test_a_second_staff_with_its_own_signature_still_works(self):
        found = measure_lengths(self._two_staves(True), Context())
        self.assertEqual(found, [], [str(v) for v in found])
