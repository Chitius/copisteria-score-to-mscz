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
    def test_an_unbeamed_eighth_run_is_grouped_by_beat(self):
        doc = build("".join(note(step) for step in "CDEFGABC"))
        self.assertEqual(RestoreBeams().run(doc, Context()).changed, 8)
        beams = [note.findall("beam") for note in doc.measures()[0].iter("note")]
        self.assertEqual([beam[0].text for beam in beams], ["begin", "end"] * 4)
        self.assertEqual(RestoreBeams().run(doc, Context()).changed, 0)

    def test_source_begin_end_boundaries_are_hard(self):
        body = "".join(
            note(step, beams=[("1", "begin")] if index == 1 else ([("1", "end")] if index == 4 else None))
            for index, step in enumerate("CDEFGABC")
        )
        doc = build(body)
        RestoreBeams().run(doc, Context())
        beams = [note.findall("beam") for note in doc.measures()[0].iter("note")]
        self.assertIsNone(beams[0][0] if beams[0] else None)
        self.assertEqual(beams[1][0].text, "begin")
        self.assertEqual(beams[4][0].text, "end")
        self.assertFalse(beams[5])
        self.assertEqual(beams[6][0].text, "begin")
        self.assertEqual(beams[-1][0].text, "end")

    def test_a_rest_breaks_the_beam_group(self):
        body = note("C") + note("D") + note("E") + note("", rest=True) + note("F") + note("G") + note("A")
        doc = build(body)
        RestoreBeams().run(doc, Context())
        notes = [note for note in doc.measures()[0].iter("note") if note.find("rest") is None]
        values = [note.find("beam").text if note.find("beam") is not None else None for note in notes]
        self.assertEqual(values, ["begin", "end", None, "begin", "end", None])

    def test_an_unbeamed_eighth_between_sixteenths_stays_separate(self):
        body = (
            '<note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration>'
            "<voice>1</voice><type>16th</type><beam number=\"1\">begin</beam>"
            '<beam number="2">begin</beam></note>'
            '<note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration>'
            "<voice>1</voice><type>16th</type><beam number=\"1\">continue</beam>"
            '<beam number="2">end</beam></note>'
            '<note><pitch><step>E</step><octave>4</octave></pitch><duration>2</duration>'
            "<voice>1</voice><type>eighth</type></note>"
            '<note><pitch><step>F</step><octave>4</octave></pitch><duration>1</duration>'
            "<voice>1</voice><type>16th</type><beam number=\"1\">begin</beam>"
            '<beam number="2">begin</beam></note>'
            '<note><pitch><step>G</step><octave>4</octave></pitch><duration>1</duration>'
            "<voice>1</voice><type>16th</type><beam number=\"1\">end</beam>"
            '<beam number="2">end</beam></note>'
        )
        doc = build(body)
        RestoreBeams().run(doc, Context())
        notes = list(doc.measures()[0].iter("note"))
        self.assertEqual(list(notes[2].findall("beam")), [])
        self.assertEqual(notes[0].find("beam").text, "begin")
        self.assertEqual(notes[-1].find("beam").text, "end")

    def test_incomplete_sixteenth_groups_are_rebuilt_by_beat(self):
        body = ""
        primary = ["begin", "continue", "end", None, "begin", "end"]
        for index in range(6):
            beams = "" if primary[index] is None else (
                f'<beam number="1">{primary[index]}</beam><beam number="2">{primary[index]}</beam>'
            )
            body += (
                f'<note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration>'
                f'<voice>1</voice><type>16th</type>{beams}</note>'
            )
        body += note("D")
        doc = build(body)
        RestoreBeams().run(doc, Context())

        notes = list(doc.measures()[0].iter("note"))
        self.assertEqual(
            [note.find("beam").text if note.find("beam") is not None else None for note in notes],
            ["begin", "continue", "continue", "end", "begin", "end", None],
        )
        self.assertEqual(RestoreBeams().run(doc, Context()).changed, 0)

    def test_broken_primary_beams_do_not_fall_back_to_secondary_boundaries(self):
        primary = [
            "begin", "continue", "end", "continue", "continue", "continue", "begin",
            "end", "begin", "continue", "continue", "end", "begin", "continue",
        ]
        secondary = [
            "begin", "continue", "end", "forward hook", "begin", "end", "begin",
            "end", "begin", "continue", "continue", "end", "begin", "end",
        ]
        body = ""
        for index in range(14):
            body += (
                f'<note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration>'
                f'<voice>1</voice><type>16th</type>'
                f'<beam number="1">{primary[index]}</beam>'
                f'<beam number="2">{secondary[index]}</beam></note>'
            )
        body += (
            '<note><pitch><step>D</step><octave>4</octave></pitch><duration>2</duration>'
            '<voice>1</voice><type>eighth</type><beam number="1">end</beam></note>'
        )
        doc = build(body)
        RestoreBeams().run(doc, Context())

        notes = list(doc.measures()[0].iter("note"))
        values = [note.find("beam").text if note.find("beam") is not None else None for note in notes]
        self.assertEqual(
            values,
            ["begin", "continue", "continue", "end"] * 3 + ["begin", "continue", "end"],
        )
        self.assertEqual(RestoreBeams().run(doc, Context()).changed, 0)

    def test_malformed_source_pairs_are_not_trusted(self):
        # Suzume m33 beat 4: level 1 is begin,continue,end,end and level 2 is begin,begin,end,end.
        # Trusting those pairs rebuilt only the middle two sixteenths and left the outer two with
        # dangling begin/end beams; the whole beat must be one group.
        def sixteenth(step, beams):
            tags = "".join(f'<beam number="{number}">{kind}</beam>' for number, kind in beams)
            return (
                f"<note><pitch><step>{step}</step><octave>4</octave></pitch><duration>1</duration>"
                f"<voice>1</voice><type>16th</type>{tags}</note>"
            )

        body = (
            sixteenth("G", [("1", "begin"), ("2", "begin")])
            + sixteenth("F", [("1", "continue"), ("2", "begin")])
            + sixteenth("F", [("1", "end"), ("2", "end")])
            + sixteenth("G", [("1", "end"), ("2", "end")])
        )
        doc = build(body)
        RestoreBeams().run(doc, Context())
        notes = list(doc.measures()[0].iter("note"))
        for level in ("1", "2"):
            values = [
                next(beam.text for beam in note.findall("beam") if beam.get("number") == level)
                if any(beam.get("number") == level for beam in note.findall("beam"))
                else None
                for note in notes
            ]
            self.assertEqual(values, ["begin", "continue", "continue", "end"])


if __name__ == "__main__":
    unittest.main()
