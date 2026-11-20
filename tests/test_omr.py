from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path

from scorepipe.cli import main

PAGES = Path(__file__).parent / "fixtures" / "pages"
WORK = Path(__file__).parent / ".runs" / "omr"


class OmrFrontEndTest(unittest.TestCase):
    def test_external_omr_command_produces_pages_and_runs(self):
        WORK.mkdir(parents=True, exist_ok=True)
        script = WORK / "fake_omr.py"
        script.write_text(
            "import shutil, sys\n"
            "from pathlib import Path\n"
            "pdf, outdir = sys.argv[1], Path(sys.argv[2])\n"
            "outdir.mkdir(parents=True, exist_ok=True)\n"
            f'shutil.copyfile(r"{PAGES / "page1.musicxml"}", outdir / "p01.musicxml")\n'
            f'shutil.copyfile(r"{PAGES / "page2.musicxml"}", outdir / "p02.musicxml")\n',
            encoding="utf-8",
        )
        pdf = WORK / "score.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        command = f'"{sys.executable}" "{script}" {{pdf}} {{outdir}}'
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(
                [
                    str(pdf),
                    "--omr",
                    command,
                    "--omr-dir",
                    str(WORK / "pages"),
                    "--check",
                ]
            )
        output = buffer.getvalue()
        self.assertEqual(code, 0, output)
        self.assertIn("omr: 2 page files", output)
        self.assertIn("verifier: clean", output)

    def test_failing_omr_command_is_reported(self):
        WORK.mkdir(parents=True, exist_ok=True)
        pdf = WORK / "bad.pdf"
        pdf.write_bytes(b"%PDF-1.4 fake")
        with self.assertRaises(RuntimeError):
            main([str(pdf), "--omr", "exit 3", "--omr-dir", str(WORK / "none")])


if __name__ == "__main__":
    unittest.main()
