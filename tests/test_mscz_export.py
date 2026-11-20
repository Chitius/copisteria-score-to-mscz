from __future__ import annotations

import unittest
from pathlib import Path

from scorepipe.core.mscz import MsczArchive
from scorepipe.core.pass_base import Context, Phase
from scorepipe.core.pipeline import run_display, run_pipeline
from scorepipe.mscz_export import export_and_display, find_musescore
from scorepipe.passes import DISPLAY_PASSES, STRUCTURAL_PASSES

FIXTURE = Path(__file__).parent / "fixtures" / "tiny.musicxml"
WORK = Path(__file__).parent / ".runs" / "mscz"


class ExportAndDisplayTest(unittest.TestCase):
    def test_musicxml_becomes_mscz_and_display_passes_are_idempotent(self):
        try:
            musescore = find_musescore()
        except RuntimeError:
            self.skipTest("MuseScore is not available")

        from scorepipe.core.document import Document

        WORK.mkdir(parents=True, exist_ok=True)
        doc = Document.load(FIXTURE)
        run_pipeline(doc, Context(), structural=STRUCTURAL_PASSES, verifiers=[])
        target = WORK / "out.mscz"
        target.unlink(missing_ok=True)

        report = export_and_display(doc, target, Context(), musescore=musescore)
        self.assertTrue(target.is_file())
        self.assertTrue(report.phases[0].stable)
        self.assertEqual(report.verifier, [])

        archive = MsczArchive.open(target)
        again = run_display(archive.document, Context(), DISPLAY_PASSES)
        self.assertEqual(again.changes, 0)


if __name__ == "__main__":
    unittest.main()
