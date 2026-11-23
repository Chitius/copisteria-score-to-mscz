from __future__ import annotations

import unittest
from fractions import Fraction
from xml.etree import ElementTree

from scorepipe.core.mscx import MsxcDocument
from scorepipe.core.musescore_ticks import voice_timeline
from scorepipe.passes.mscx_canonical import canonicalize


def score(voice_body: str, signature: str = "4/4") -> MsxcDocument:
    beats, unit = signature.split("/")
    root = ElementTree.fromstring(
        f"""<museScore><Score><Staff id="1"><Measure>
        <TimeSig><sigN>{beats}</sigN><sigD>{unit}</sigD></TimeSig>
        <voice>{voice_body}</voice>
        </Measure></Staff></Score></museScore>"""
    )
    return MsxcDocument(root)


def chord(kind: str = "quarter") -> str:
    return f"<Chord><durationType>{kind}</durationType><Note><pitch>60</pitch></Note></Chord>"


def rest(kind: str = "quarter", padding: bool = False) -> str:
    marker = "<padding>1</padding>" if padding else ""
    return f"<Rest>{marker}<durationType>{kind}</durationType></Rest>"


class CanonicalizeVoiceTest(unittest.TestCase):
    def test_retimes_an_overfull_tuplet_without_losing_notes(self):
        doc = score(
            "<Tuplet><normalNotes>4</normalNotes><actualNotes>6</actualNotes>"
            "<baseNote>16th</baseNote></Tuplet>"
            + chord("eighth") * 3
            + chord("16th") * 4
            + "<endTuplet/>"
        )
        notes: list[str] = []
        canonicalize(doc, notes)

        measure = doc.root.find(".//Measure")
        voices = measure.findall("voice")
        timeline = voice_timeline(voices[0], Fraction(1))
        self.assertEqual(timeline.end, Fraction(1))
        self.assertFalse(timeline.invalid_tuplets)
        self.assertEqual(len([i for i in timeline.items if i.element.tag == "Chord"]), 7)
        span = timeline.spans[0]
        self.assertEqual((span.normal, span.actual), (2, 5))
        self.assertEqual(span.node.findtext("baseNote"), "eighth")
        self.assertEqual(notes, [])

    def test_overlapping_voice_is_unresolved_and_byte_identical(self):
        doc = score(chord("half") + "<location><fractions>-1/8</fractions></location>" + rest("eighth"))
        measure = doc.root.find(".//Measure")
        before = ElementTree.tostring(measure.findall("voice")[0])
        notes: list[str] = []
        canonicalize(doc, notes)

        voice = measure.findall("voice")[0]
        self.assertEqual(ElementTree.tostring(voice), before)
        self.assertTrue(any(note.startswith("UNRESOLVED") for note in notes))

    def test_pads_a_short_voice_with_hidden_exact_rests(self):
        doc = score(chord())
        notes: list[str] = []
        canonicalize(doc, notes)

        voice = doc.root.find(".//Measure").findall("voice")[0]
        timeline = voice_timeline(voice, Fraction(1))
        self.assertEqual(timeline.end, Fraction(1))
        padding = [node for node in voice.findall("Rest") if node.find("padding") is not None]
        self.assertTrue(padding)
        self.assertTrue(all(node.findtext("visible") == "0" for node in padding))
        self.assertEqual(notes, [])

    def test_strips_stale_padding_tuplets_and_rests(self):
        body = (
            chord("whole")
            + "<Tuplet><normalNotes>4</normalNotes><actualNotes>15</actualNotes>"
            "<baseNote>128th</baseNote></Tuplet>"
            + rest("128th", padding=True)
            + "<endTuplet/>"
            + rest("half", padding=True)
        )
        doc = score(body)
        canonicalize(doc)
        voice = doc.root.find(".//Measure").findall("voice")[0]
        self.assertEqual(voice.findall("Tuplet"), [])
        self.assertEqual(voice.findall("Rest"), [])
        self.assertEqual(voice_timeline(voice, Fraction(1)).end, Fraction(1))

    def test_negative_location_with_stale_padding_rest_does_not_overlap(self):
        body = (
            chord("whole")
            + "<location><fractions>-1/128</fractions></location>"
            + "<Clef><concertClefType>F</concertClefType></Clef>"
            + rest("128th", padding=True)
        )
        doc = score(body)
        canonicalize(doc)
        voice = doc.root.find(".//Measure").findall("voice")[0]
        timeline = voice_timeline(voice, Fraction(1))
        self.assertEqual(timeline.end, Fraction(1))
        self.assertFalse(timeline.overlaps)
        self.assertEqual(voice.findall("Rest"), [])

    def test_dots_are_moved_before_duration_type(self):
        # A later <dots> is only layout in MuseScore; canonicalization must put
        # it before <durationType> so the intended dotted value is read.
        body = (
            "<Rest><durationType>quarter</durationType><dots>2</dots></Rest>"
            + chord("half")
        )
        doc = score(body)
        canonicalize(doc)
        voice = doc.root.find(".//Measure").findall("voice")[0]
        rest = voice.find("Rest")
        children = [child.tag for child in rest]
        self.assertLess(children.index("dots"), children.index("durationType"))
        timeline = voice_timeline(voice, Fraction(1))
        self.assertEqual(timeline.items[0].written, Fraction(7, 16))
        self.assertEqual(timeline.end, Fraction(1))

    def test_valid_nested_tuplets_are_left_alone(self):
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
        doc = score(body)
        before = ElementTree.tostring(doc.root.find(".//voice"))
        notes: list[str] = []
        canonicalize(doc, notes)
        self.assertEqual(ElementTree.tostring(doc.root.find(".//voice")), before)
        self.assertEqual(notes, [])


if __name__ == "__main__":
    unittest.main()
