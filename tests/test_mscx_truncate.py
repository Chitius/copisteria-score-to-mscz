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


class TruncateOverfullMscxTest(unittest.TestCase):
    def test_removes_rest_before_shortening_notes(self):
        doc = score(rest("half") + chord("whole"))
        result = TruncateOverfullMscx().run(doc, Context())
        self.assertEqual(result.changed, 1)
        self.assertEqual(doc.root.findall(".//Rest"), [])
        self.assertEqual(len(doc.root.findall(".//Chord")), 1)

    def test_shortens_last_chord_when_there_is_no_rest(self):
        doc = score(chord("half") + chord("whole"))
        result = TruncateOverfullMscx().run(doc, Context())
        self.assertEqual(result.changed, 1)
        chords = doc.root.findall(".//Chord")
        self.assertEqual(len(chords), 2)
        self.assertIsNone(chords[0].find("duration"))
        self.assertIsNotNone(chords[-1].find("duration"))

    def test_underfull_voice_is_untouched(self):
        doc = score(chord("half"))
        result = TruncateOverfullMscx().run(doc, Context())
        self.assertEqual(result.changed, 0)

    def test_tuplet_is_not_cut(self):
        doc = score(
            "<Tuplet><actualNotes>3</actualNotes><normalNotes>2</normalNotes>"
            + chord()
            + chord()
            + "</Tuplet>"
            + rest("whole")
        )
        result = TruncateOverfullMscx().run(doc, Context())
        self.assertGreaterEqual(result.changed, 0)
        self.assertEqual(len(doc.root.findall(".//Chord")), 2)


if __name__ == "__main__":
    unittest.main()
