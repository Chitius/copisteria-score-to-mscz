from __future__ import annotations

import unittest
from pathlib import Path

from scorepipe.core.invariants import measure_lengths
from scorepipe.core.pass_base import Context
from scorepipe.core.pairing import Endpoint, pair_endpoints
from scorepipe.core.pipeline import run_pipeline
from scorepipe.loader import load_pages, merge_pages
from scorepipe.passes import STRUCTURAL_PASSES
from scorepipe.passes.page_restore import _musical_order

PAGES = Path(__file__).parent / "fixtures" / "pages_restore"


def run() -> tuple:
    merged = load_pages(PAGES)
    ctx = Context(pages=merged)
    report = run_pipeline(merged.document, ctx, structural=STRUCTURAL_PASSES, verifiers=[])
    return merged.document, ctx, report


class PageRestoreTest(unittest.TestCase):
    def test_tie_crosses_the_page_boundary(self):
        doc, _ctx, _report = run()
        second = doc.measures()[1]
        third = doc.measures()[2]
        start = next(n for n in second.iter("note") if n.findtext("pitch/step") == "C")
        stop = next(n for n in third.iter("note") if n.findtext("pitch/step") == "C")
        self.assertTrue(any(tie.get("type") == "start" for tie in start.findall("tie")))
        self.assertTrue(any(tie.get("type") == "stop" for tie in stop.findall("tie")))

    def test_slur_crosses_the_page_boundary(self):
        doc, _ctx, _report = run()
        slurs = [(slur.get("type"), slur.get("number")) for slur in doc.root.iter("slur")]
        self.assertIn(("start", "1"), slurs)
        self.assertIn(("stop", "1"), slurs)

    def test_pedal_directions_come_from_the_pages(self):
        doc, _ctx, _report = run()
        first = doc.measures()[0].findall(".//pedal")
        third = doc.measures()[2].findall(".//pedal")
        self.assertEqual([pedal.get("type") for pedal in first], ["start"])
        self.assertEqual([pedal.get("type") for pedal in third], ["stop"])

    def test_restoration_is_idempotent(self):
        doc, ctx, _report = run()
        again = run_pipeline(doc, ctx, structural=STRUCTURAL_PASSES, verifiers=[])
        self.assertEqual(again.changes, 0)
        self.assertEqual(measure_lengths(doc, Context()), [])

    def test_slur_numbers_are_global_not_per_staff(self):
        work = Path(__file__).parent / ".runs" / "slur_numbers"
        work.mkdir(parents=True, exist_ok=True)
        page = work / "page1.musicxml"
        page.write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>t</part-name></score-part></part-list>
<part id="P1">
<measure number="1"><attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
<note><pitch><step>C</step><octave>5</octave></pitch><duration>16</duration><voice>1</voice><staff>1</staff>
<notations><slur type="start" number="1"/></notations></note>
<backup><duration>16</duration></backup>
<note><pitch><step>E</step><octave>3</octave></pitch><duration>16</duration><voice>1</voice><staff>2</staff>
<notations><slur type="start" number="1"/></notations></note>
</measure>
<measure number="2">
<note><pitch><step>D</step><octave>5</octave></pitch><duration>16</duration><voice>1</voice><staff>1</staff>
<notations><slur type="stop" number="1"/></notations></note>
<backup><duration>16</duration></backup>
<note><pitch><step>F</step><octave>3</octave></pitch><duration>16</duration><voice>1</voice><staff>2</staff>
<notations><slur type="stop" number="1"/></notations></note>
</measure>
</part></score-partwise>""",
            encoding="utf-8",
        )
        merged = merge_pages([page])
        ctx = Context(pages=merged)
        run_pipeline(merged.document, ctx, structural=STRUCTURAL_PASSES, verifiers=[])
        numbers = {}
        for _number, measure in merged.document.iter_measures():
            for note in measure.iter("note"):
                for slur in note.findall("notations/slur"):
                    if slur.get("type") == "start":
                        numbers[note.findtext("staff")] = slur.get("number")
        self.assertEqual(set(numbers), {"1", "2"})
        self.assertNotEqual(numbers["1"], numbers["2"])


    def test_reused_slur_number_does_not_create_a_long_arc(self):
        work = Path(__file__).parent / ".runs" / "slur_collision"
        work.mkdir(parents=True, exist_ok=True)
        measure = (
            '<measure number="{number}"><attributes><divisions>4</divisions>'
            "<time><beats>4</beats><beat-type>4</beat-type></time></attributes>{body}</measure>"
        )
        note = (
            '<note><pitch><step>{step}</step><octave>5</octave></pitch>'
            '<duration>8</duration><voice>1</voice>{slur}</note>'
        )
        start = '<notations><slur type="start" number="1"/></notations>'
        stop = '<notations><slur type="stop" number="1"/></notations>'
        page = work / "page1.musicxml"
        page.write_text(
            '<?xml version="1.0" encoding="UTF-8"?><score-partwise version="4.0">'
            "<part-list><score-part id=\"P1\"><part-name>t</part-name></score-part></part-list>"
            '<part id="P1">'
            + measure.format(number=1, body=note.format(step="G", slur=start))
            + measure.format(number=2, body=note.format(step="C", slur=start) + note.format(step="G", slur=stop))
            + measure.format(number=3, body=note.format(step="F", slur=""))
            + measure.format(number=4, body=note.format(step="D", slur=stop) + note.format(step="E", slur=start))
            + measure.format(number=5, body=note.format(step="F", slur=stop))
            + "</part></score-partwise>",
            encoding="utf-8",
        )
        merged = merge_pages([page])
        ctx = Context(pages=merged)
        run_pipeline(merged.document, ctx, structural=STRUCTURAL_PASSES, verifiers=[])
        starts = []
        for number, measure_element in merged.document.iter_measures():
            for event in merged.document.events(measure_element):
                for slur in event.element.findall("notations/slur"):
                    if slur.get("type") == "start":
                        starts.append((number, event.element.findtext("pitch/step")))
        self.assertEqual(starts, [(1, "G"), (2, "C"), (4, "E")])

    def test_slur_endpoints_are_ordered_by_music_not_by_xml_block(self):
        endpoints = [
            Endpoint(key=("1", "2"), position=(35, 2.0), kind="stop"),
            Endpoint(key=("1", "2"), position=(35, 1.5), kind="start"),
            Endpoint(key=("1", "2"), position=(36, 2.0), kind="stop"),
        ]
        pairing = pair_endpoints(_musical_order(endpoints))
        self.assertEqual(
            [(start.position, stop.position) for start, stop in pairing.pairs],
            [((35, 1.5), (35, 2.0))],
        )
        self.assertEqual(len(pairing.orphans), 1)

    def test_arpeggio_is_one_mark_on_the_chord_not_on_a_split_note(self):
        work = Path(__file__).parent / ".runs" / "arpeggio_chord"
        work.mkdir(parents=True, exist_ok=True)
        measure = (
            '<measure number="1"><attributes><divisions>4</divisions>'
            "<time><beats>4</beats><beat-type>4</beat-type></time></attributes>{body}</measure>"
        )
        note = (
            '<note>{chord}<pitch><step>{step}</step><octave>{octave}</octave></pitch>'
            '<duration>{duration}</duration><voice>{voice}</voice>'
            '<notations><arpeggiate/></notations></note>'
        )
        body = (
            note.format(chord="", step="D", octave=4, duration=16, voice=1)
            + note.format(chord="<chord/>", step="F", octave=4, duration=16, voice=1)
            + note.format(chord="<chord/>", step="A", octave=4, duration=16, voice=1)
            + "<backup><duration>16</duration></backup>"
            + note.format(chord="", step="C", octave=6, duration=4, voice=2)
        )
        page = work / "page1.musicxml"
        page.write_text(
            '<?xml version="1.0" encoding="UTF-8"?><score-partwise version="4.0">'
            "<part-list><score-part id=\"P1\"><part-name>t</part-name></score-part></part-list>"
            '<part id="P1">' + measure.format(body=body) + "</part></score-partwise>",
            encoding="utf-8",
        )
        merged = merge_pages([page])
        run_pipeline(merged.document, Context(pages=merged), structural=STRUCTURAL_PASSES, verifiers=[])
        marked = []
        for measure_element in merged.document.measures():
            for note_element in measure_element.iter("note"):
                if note_element.find("notations/arpeggiate") is not None:
                    marked.append((note_element.findtext("pitch/step"), note_element.findtext("voice")))
        self.assertEqual(marked, [("D", "1")])


if __name__ == "__main__":
    unittest.main()
