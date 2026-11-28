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
        return "<note><rest/><duration>2</duration><voice>1</voice><type>eighth</type></note>"
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
        self.assertEqual(
            [beam[0].text if beam else None for beam in beams],
            [None, "begin", "continue", "continue", "end", None, "begin", "end"],
        )
        self.assertEqual(RestoreBeams().run(doc, Context()).changed, 0)

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

    def test_compound_meters_group_three_eighths_per_beat(self):
        for beats, groups in ((3, 1), (6, 2), (9, 3), (12, 4)):
            body = "".join(note("C") for _ in range(beats))
            xml = f"""<score-partwise version="4.0">
              <part-list><score-part id="P1"><part-name>t</part-name></score-part></part-list>
              <part id="P1"><measure number="1">
                <attributes><divisions>4</divisions><time><beats>{beats}</beats><beat-type>8</beat-type></time></attributes>
                {body}
              </measure></part></score-partwise>"""
            doc = Document(ElementTree.fromstring(xml))
            RestoreBeams().run(doc, Context())
            beams = [n.findtext("beam") for n in doc.measures()[0].iter("note")]
            self.assertEqual(beams, ["begin", "continue", "end"] * groups)
            self.assertEqual(RestoreBeams().run(doc, Context()).changed, 0)

    def test_compound_meter_hooks_are_consistent_across_beats(self):
        # Beat 1 and beat 2 of 6/8 have the exact same dotted-eighth + 16th + eighth rhythm:
        # both 16ths must get a backward hook pointing to the dotted eighth, not flip at beat 2.
        beat_xml = (
            '<note><pitch><step>C</step><octave>5</octave></pitch><duration>3</duration>'
            '<voice>1</voice><type>eighth</type><dot/></note>'
            '<note><pitch><step>D</step><octave>5</octave></pitch><duration>1</duration>'
            '<voice>1</voice><type>16th</type></note>'
            '<note><pitch><step>E</step><octave>5</octave></pitch><duration>2</duration>'
            '<voice>1</voice><type>eighth</type></note>'
        )
        xml = f"""<score-partwise version="4.0">
          <part-list><score-part id="P1"><part-name>t</part-name></score-part></part-list>
          <part id="P1"><measure number="1">
            <attributes><divisions>4</divisions><time><beats>6</beats><beat-type>8</beat-type></time></attributes>
            {beat_xml}{beat_xml}
          </measure></part></score-partwise>"""
        doc = Document(ElementTree.fromstring(xml))
        RestoreBeams().run(doc, Context())
        notes = list(doc.measures()[0].iter("note"))
        levels = [{b.get("number"): b.text for b in n.findall("beam")} for n in notes]
        expected_beat = [
            {"1": "begin"},
            {"1": "continue", "2": "backward hook"},
            {"1": "end"},
        ]
        self.assertEqual(levels, expected_beat * 2)

    def test_asymmetric_meters_group_and_respect_source_split(self):
        five_eight = "".join(note("C") for _ in range(5))
        xml_default = f"""<score-partwise version="4.0">
          <part-list><score-part id="P1"><part-name>t</part-name></score-part></part-list>
          <part id="P1"><measure number="1">
            <attributes><divisions>4</divisions><time><beats>5</beats><beat-type>8</beat-type></time></attributes>
            {five_eight}
          </measure></part></score-partwise>"""
        doc = Document(ElementTree.fromstring(xml_default))
        RestoreBeams().run(doc, Context())
        self.assertEqual(
            [n.findtext("beam") for n in doc.measures()[0].iter("note")],
            ["begin", "continue", "end", "begin", "end"],
        )

        # Source marks 2+3 split on notes 0..1
        five_eight_23 = (
            note("C", beams=[("1", "begin")])
            + note("D", beams=[("1", "end")])
            + note("E")
            + note("F")
            + note("G")
        )
        xml_23 = f"""<score-partwise version="4.0">
          <part-list><score-part id="P1"><part-name>t</part-name></score-part></part-list>
          <part id="P1"><measure number="1">
            <attributes><divisions>4</divisions><time><beats>5</beats><beat-type>8</beat-type></time></attributes>
            {five_eight_23}
          </measure></part></score-partwise>"""
        doc23 = Document(ElementTree.fromstring(xml_23))
        RestoreBeams().run(doc23, Context())
        self.assertEqual(
            [n.findtext("beam") for n in doc23.measures()[0].iter("note")],
            ["begin", "end", "begin", "continue", "end"],
        )

        seven_eight = "".join(note("C") for _ in range(7))
        xml_78 = f"""<score-partwise version="4.0">
          <part-list><score-part id="P1"><part-name>t</part-name></score-part></part-list>
          <part id="P1"><measure number="1">
            <attributes><divisions>4</divisions><time><beats>7</beats><beat-type>8</beat-type></time></attributes>
            {seven_eight}
          </measure></part></score-partwise>"""
        doc78 = Document(ElementTree.fromstring(xml_78))
        RestoreBeams().run(doc78, Context())
        self.assertEqual(
            [n.findtext("beam") for n in doc78.measures()[0].iter("note")],
            ["begin", "end", "begin", "end", "begin", "continue", "end"],
        )

    def test_implicit_pickup_aligns_beam_grid_to_bar_end(self):
        # 3-eighth pickup in 4/4 fills beats [2.5..4.0) => [1] + [2] beamed together
        xml = """<score-partwise version="4.0">
          <part-list><score-part id="P1"><part-name>t</part-name></score-part></part-list>
          <part id="P1"><measure number="1" implicit="yes">
            <attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
            """ + note("C") + note("D") + note("E") + """
          </measure></part></score-partwise>"""
        doc = Document(ElementTree.fromstring(xml))
        RestoreBeams().run(doc, Context())
        self.assertEqual(
            [n.findtext("beam") for n in doc.measures()[0].iter("note")],
            [None, "begin", "end"],
        )

    def test_dangling_beam_on_isolated_single_note_is_cleared(self):
        body = (
            note("C", beams=[("1", "begin")])
            + note("", rest=True)
            + note("D")
            + note("E")
        )
        doc = build(body)
        RestoreBeams().run(doc, Context())
        notes = [n for n in doc.measures()[0].iter("note") if n.find("rest") is None]
        self.assertEqual([n.findtext("beam") for n in notes], [None, "begin", "end"])
        self.assertEqual(RestoreBeams().run(doc, Context()).changed, 0)


if __name__ == "__main__":
    unittest.main()
