from __future__ import annotations

import unittest
from xml.etree import ElementTree

from scorepipe.core.document import Document
from scorepipe.core.pass_base import Context
from scorepipe.passes.xml_beams import RestoreBeams

PART = """
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>t</part-name></score-part></part-list>
  <part id="P1"><measure number="1">
    <attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
    {body}
  </measure></part>
</score-partwise>
"""


def note(step, *, beams=None, rest=False):
    beam_tags = "".join(f'<beam number="{number}">{kind}</beam>' for number, kind in (beams or []))
    if rest:
        return f"<note><rest/><duration>2</duration><voice>1</voice><type>eighth</type></note>"
    return (
        f"<note><pitch><step>{step}</step><octave>4</octave></pitch><duration>2</duration>"
        f"<voice>1</voice><type>eighth</type>{beam_tags}</note>"
    )


def build(body):
    return Document(ElementTree.fromstring(PART.format(body=body)))


class RestoreBeamsTest(unittest.TestCase):
    def test_an_unbeamed_eighth_run_gets_one_group(self):
        doc = build("".join(note(step) for step in "CDEFGABC"))
        self.assertEqual(RestoreBeams().run(doc, Context()).changed, 8)
        beams = [note.findall("beam") for note in doc.measures()[0].iter("note")]
        self.assertEqual([beam[0].text for beam in beams], ["begin"] + ["continue"] * 6 + ["end"])
        self.assertEqual(RestoreBeams().run(doc, Context()).changed, 0)

    def test_partial_edge_beams_are_extended(self):
        body = "".join(
            note(step, beams=[("1", "begin")] if index == 1 else ([('1', 'end')] if index == 4 else None))
            for index, step in enumerate("CDEFGABC")
        )
        doc = build(body)
        RestoreBeams().run(doc, Context())
        beams = [note.findall("beam") for note in doc.measures()[0].iter("note")]
        self.assertEqual(beams[0][0].text, "begin")
        self.assertEqual(beams[-1][0].text, "end")
        self.assertTrue(all(beam for beam in beams))

    def test_a_rest_breaks_the_beam_group(self):
        body = note("C") + note("D") + note("E") + note("", rest=True) + note("F") + note("G") + note("A")
        doc = build(body)
        RestoreBeams().run(doc, Context())
        notes = [note for note in doc.measures()[0].iter("note") if note.find("rest") is None]
        self.assertEqual([note.find("beam").text for note in notes[:3]], ["begin", "continue", "end"])
        self.assertEqual([note.find("beam").text for note in notes[3:]], ["begin", "continue", "end"])


if __name__ == "__main__":
    unittest.main()
