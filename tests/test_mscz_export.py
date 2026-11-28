from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scorepipe.core.mscz import MsczArchive
from scorepipe.core.pass_base import Context
from scorepipe.core.pipeline import run_display, run_pipeline
from scorepipe.mscz_export import export_and_display, find_musescore
from scorepipe.passes import DISPLAY_PASSES, STRUCTURAL_PASSES

FIXTURE = Path(__file__).parent / "fixtures" / "tiny.musicxml"


class ExportAndDisplayTest(unittest.TestCase):
    def test_musicxml_becomes_mscz_and_display_passes_are_idempotent(self):
        try:
            musescore = find_musescore()
        except RuntimeError:
            self.skipTest("MuseScore is not available")

        from scorepipe.core.document import Document

        doc = Document.load(FIXTURE)
        run_pipeline(doc, Context(), structural=STRUCTURAL_PASSES, verifiers=[])
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.mscz"

            report = export_and_display(doc, target, Context(), musescore=musescore)
            self.assertTrue(target.is_file())
            self.assertTrue(report.phases[0].stable)
            self.assertEqual(report.verifier, [])

            archive = MsczArchive.open(target)
            again = run_display(archive.document, Context(), DISPLAY_PASSES)
            self.assertEqual(again.changes, 0)

    def test_forced_truncation_is_clean_after_musescore_roundtrip(self):
        try:
            musescore = find_musescore()
        except RuntimeError:
            self.skipTest("MuseScore is not available")

        from xml.etree import ElementTree

        from scorepipe.core.document import Document

        doc = Document(
            ElementTree.fromstring(
                """<score-partwise version="4.0">
                <part-list><score-part id="P1"><part-name>t</part-name></score-part></part-list>
                <part id="P1"><measure number="1">
                  <attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
                  <note><pitch><step>C</step><octave>4</octave></pitch><duration>16</duration><voice>1</voice><type>whole</type></note>
                  <note><pitch><step>D</step><octave>4</octave></pitch><duration>4</duration><voice>1</voice><type>quarter</type></note>
                </measure></part>
                </score-partwise>"""
            )
        )
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "forced.mscz"
            report = export_and_display(
                doc, target, Context(options={"truncate_overfull": True}), musescore=musescore
            )
            self.assertTrue(target.is_file())
            self.assertEqual(report.verifier, [])


if __name__ == "__main__":
    unittest.main()
