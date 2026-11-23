from __future__ import annotations

import unittest
from xml.etree import ElementTree

from scorepipe.core.mscx import MsxcDocument
from scorepipe.core.pass_base import Context
from scorepipe.passes.mscx_truncate import TruncateOverfullMscx


def score(body: str) -> MsxcDocument:
    root = ElementTree.fromstring(
        f"""<museScore><Score><Staff id="1"><Measure>
        <TimeSig><sigN>4</sigN><sigD>4</sigD></TimeSig>
        <voice>{body}</voice>
        </Measure></Staff></Score></museScore>"""
    )
    return MsxcDocument(root)


def chord(kind: str = "quarter") -> str:
    return f"<Chord><durationType>{kind}</durationType><Note><pitch>60</pitch></Note></Chord>"


def rest(kind: str = "quarter") -> str:
    return f"<Rest><durationType>{kind}</durationType></Rest>"


def _written_ticks(element) -> int:
    from scorepipe.core.musescore_ticks import element_ticks

    return element_ticks(element)


class TruncateOverfullMscxTest(unittest.TestCase):
    def test_removes_only_a_trailing_rest_before_shortening_notes(self):
        doc = score(chord("whole") + rest("half"))
        result = TruncateOverfullMscx().run(doc, Context())
        self.assertEqual(result.changed, 1)
        self.assertEqual(doc.root.findall(".//Rest"), [])
        self.assertEqual(len(doc.root.findall(".//Chord")), 1)

    def test_positional_rest_survives_and_the_last_chord_is_shortened(self):
        doc = score(rest("half") + chord("whole"))
        result = TruncateOverfullMscx().run(doc, Context())
        self.assertEqual(result.changed, 1)
        self.assertEqual(len(doc.root.findall(".//Rest")), 1)
        chords = doc.root.findall(".//Chord")
        self.assertEqual(len(chords), 1)
        self.assertEqual(_written_ticks(chords[-1]), 960)
        self.assertIn("[60]", " ".join(result.notes))
        self.assertIn("shorten 4->2", " ".join(result.notes))

    def test_shortens_last_chord_when_there_is_no_trailing_rest(self):
        doc = score(chord("half") + chord("whole"))
        result = TruncateOverfullMscx().run(doc, Context())
        self.assertEqual(result.changed, 1)
        chords = doc.root.findall(".//Chord")
        self.assertEqual(len(chords), 2)
        self.assertEqual(_written_ticks(chords[0]), 960)
        self.assertEqual(_written_ticks(chords[-1]), 960)
        second = TruncateOverfullMscx().run(doc, Context())
        self.assertEqual(second.changed, 0)

    def test_underfull_voice_is_untouched(self):
        doc = score(chord("half"))
        result = TruncateOverfullMscx().run(doc, Context())
        self.assertEqual(result.changed, 0)

    def test_tuplet_tail_is_not_cut_or_mutated(self):
        doc = score(
            "<Tuplet><actualNotes>3</actualNotes><normalNotes>2</normalNotes></Tuplet>"
            + "".join(chord() for _ in range(7))
            + "<endTuplet/>"
            + rest("eighth")
        )
        result = TruncateOverfullMscx().run(doc, Context())
        self.assertEqual(result.changed, 0)
        self.assertEqual(len(doc.root.findall(".//Chord")), 7)
        self.assertEqual(len(doc.root.findall(".//Rest")), 1)
        self.assertTrue(any(note.startswith("DEFERRED") for note in result.notes))

    def test_short_secondary_voice_is_untouched(self):
        doc = MsxcDocument(
            ElementTree.fromstring(
                "<museScore><Score><Staff id='1'><Measure>"
                "<TimeSig><sigN>4</sigN><sigD>4</sigD></TimeSig>"
                "<voice><Chord><durationType>whole</durationType><Note><pitch>60</pitch></Note></Chord>"
                "<Chord><durationType>quarter</durationType><Note><pitch>62</pitch></Note></Chord></voice>"
                "<voice><Chord><durationType>half</durationType><Note><pitch>64</pitch></Note></Chord></voice>"
                "</Measure></Staff></Score></museScore>"
            )
        )
        result = TruncateOverfullMscx().run(doc, Context())
        self.assertEqual(result.changed, 1)
        secondary = doc.root.findall(".//voice")[1].find("Chord")
        self.assertIsNone(secondary.find("duration"))

    def test_three_four_target_is_honoured(self):
        doc = MsxcDocument(
            ElementTree.fromstring(
                "<museScore><Score><Staff id='1'><Measure>"
                "<TimeSig><sigN>3</sigN><sigD>4</sigD></TimeSig>"
                "<voice><Chord><durationType>quarter</durationType><Note><pitch>60</pitch></Note></Chord>"
                "<Chord><durationType>quarter</durationType><Note><pitch>62</pitch></Note></Chord>"
                "<Chord><durationType>quarter</durationType><Note><pitch>64</pitch></Note></Chord>"
                "<Chord><durationType>quarter</durationType><Note><pitch>65</pitch></Note></Chord></voice>"
                "</Measure></Staff></Score></museScore>"
            )
        )
        result = TruncateOverfullMscx().run(doc, Context())
        self.assertEqual(result.changed, 1)
        self.assertEqual(len(doc.root.findall(".//Chord")), 3)

    def test_measure_len_overrides_time_signature(self):
        doc = MsxcDocument(
            ElementTree.fromstring(
                "<museScore><Score><Staff id='1'><Measure len='3/4'>"
                "<TimeSig><sigN>4</sigN><sigD>4</sigD></TimeSig>"
                "<voice><Chord><durationType>quarter</durationType><Note><pitch>60</pitch></Note></Chord>"
                "<Chord><durationType>quarter</durationType><Note><pitch>62</pitch></Note></Chord>"
                "<Chord><durationType>quarter</durationType><Note><pitch>64</pitch></Note></Chord>"
                "<Chord><durationType>quarter</durationType><Note><pitch>65</pitch></Note></Chord></voice>"
                "</Measure></Staff></Score></museScore>"
            )
        )
        result = TruncateOverfullMscx().run(doc, Context())
        self.assertEqual(result.changed, 1)
        self.assertEqual(len(doc.root.findall(".//Chord")), 3)

    def test_removed_chord_reports_spanner_risk(self):
        doc = MsxcDocument(
            ElementTree.fromstring(
                "<museScore><Score><Staff id='1'><Measure>"
                "<TimeSig><sigN>4</sigN><sigD>4</sigD></TimeSig>"
                "<voice><Chord><durationType>whole</durationType><Note><pitch>60</pitch></Note></Chord>"
                "<Chord><durationType>quarter</durationType><Tie><start/></Tie>"
                "<Note><pitch>62</pitch></Note></Chord></voice>"
                "</Measure></Staff></Score></museScore>"
            )
        )
        result = TruncateOverfullMscx().run(doc, Context())
        self.assertIn("spanner-risk:Tie", " ".join(result.notes))

    def test_per_staff_meters_are_independent(self):
        four = "<Chord><durationType>quarter</durationType><Note><pitch>60</pitch></Note></Chord>"
        doc = MsxcDocument(
            ElementTree.fromstring(
                "<museScore><Score>"
                "<Staff id='1'><Measure><TimeSig><sigN>3</sigN><sigD>4</sigD></TimeSig>"
                f"<voice>{four * 4}</voice></Measure></Staff>"
                "<Staff id='2'><Measure><TimeSig><sigN>4</sigN><sigD>4</sigD></TimeSig>"
                f"<voice>{four * 4}</voice></Measure></Staff>"
                "</Score></museScore>"
            )
        )
        result = TruncateOverfullMscx().run(doc, Context())
        self.assertEqual(result.changed, 1)
        self.assertEqual(len(doc.root.findall(".//Staff")[0].findall(".//Chord")), 3)
        self.assertEqual(len(doc.root.findall(".//Staff")[1].findall(".//Chord")), 4)

    def test_stale_overlong_measure_len_is_removed(self):
        four = "<Chord><durationType>quarter</durationType><Note><pitch>60</pitch></Note></Chord>"
        doc = MsxcDocument(
            ElementTree.fromstring(
                "<museScore><Score><Staff id='1'><Measure len='5/4'>"
                "<TimeSig><sigN>4</sigN><sigD>4</sigD></TimeSig>"
                f"<voice>{four * 4}</voice></Measure></Staff></Score></museScore>"
            )
        )
        result = TruncateOverfullMscx().run(doc, Context())
        self.assertEqual(result.changed, 0)
        self.assertIsNone(doc.root.find(".//Measure").get("len"))


if __name__ == "__main__":
    unittest.main()
