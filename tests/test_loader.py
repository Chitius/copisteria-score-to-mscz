from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from scorepipe.cli import main
from scorepipe.core.document import Document
from scorepipe.core.invariants import redundant_time_signatures
from scorepipe.core.pass_base import Context
from scorepipe.core.pipeline import run_pipeline
from scorepipe.loader import load_pages, merge_pages
from scorepipe.passes import STRUCTURAL_PASSES

PAGES = Path(__file__).parent / "fixtures" / "pages"


class LoaderTest(unittest.TestCase):
    def test_pages_are_concatenated_and_renumbered(self):
        merged = merge_pages([PAGES / "page1.musicxml", PAGES / "page2.musicxml"])
        self.assertEqual(merged.measure_counts, [2, 2])
        numbers = [measure.get("number") for measure in merged.document.measures()]
        self.assertEqual(numbers, ["1", "2", "3", "4"])
        self.assertEqual(merged.page_of_measure(1), 1)
        self.assertEqual(merged.page_of_measure(3), 2)

    def test_pipeline_cleans_page_join_duplicates(self):
        merged = load_pages(PAGES)
        run_pipeline(merged.document, Context(), structural=STRUCTURAL_PASSES, verifiers=[])
        self.assertEqual(redundant_time_signatures(merged.document, Context()), [])
        self.assertEqual(len(merged.document.measures()), 4)

    def test_pages_are_rescaled_to_one_divisions(self):
        template = (
            '<?xml version="1.0" encoding="UTF-8"?><score-partwise version="4.0">'
            '<part-list><score-part id="P1"><part-name>t</part-name></score-part></part-list>'
            '<part id="P1"><measure number="1"><attributes><divisions>{divisions}</divisions>'
            "<time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
            '<note><pitch><step>{step}</step><octave>4</octave></pitch>'
            '<duration>{duration}</duration><voice>1</voice></note></measure>'
            "</part></score-partwise>"
        )
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            first = work / "page1.musicxml"
            second = work / "page2.musicxml"
            first.write_text(template.format(divisions=4, step="C", duration=4), encoding="utf-8")
            second.write_text(template.format(divisions=8, step="D", duration=8), encoding="utf-8")
            merged = merge_pages([first, second])
        self.assertEqual(merged.document.divisions(), 8)
        durations = [
            event.duration
            for _number, measure in merged.document.iter_measures()
            for event in merged.document.events(measure)
            if not event.rest
        ]
        self.assertEqual(durations, [1.0, 1.0])

    def test_cli_accepts_a_page_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "merged.musicxml"
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = main([str(PAGES), "--check", "-o", str(output)])
            self.assertEqual(code, 0, buffer.getvalue())
            self.assertIn("pages: 2 files", buffer.getvalue())
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()


class MultiPartPageTest(unittest.TestCase):
    def test_a_page_with_two_parts_is_refused_instead_of_losing_one(self):
        page = PAGES / "page1.musicxml"
        root_text = page.read_text(encoding="utf-8")
        # duplicate the single part into a second part, as a two-staff piano page would arrive
        import xml.etree.ElementTree as ElementTree

        root = ElementTree.fromstring(root_text)
        part = root.find("part")
        clone = ElementTree.fromstring(ElementTree.tostring(part))
        clone.set("id", "P2")
        root.append(clone)
        score_part = root.find("part-list/score-part")
        clone_list = ElementTree.fromstring(ElementTree.tostring(score_part))
        clone_list.set("id", "P2")
        root.find("part-list").append(clone_list)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "two_parts.musicxml"
            ElementTree.ElementTree(root).write(target, encoding="utf-8", xml_declaration=True)

            with self.assertRaises(ValueError) as raised:
                merge_pages([target])
        self.assertIn("2 parts", str(raised.exception))
        self.assertIn("silently", str(raised.exception))
