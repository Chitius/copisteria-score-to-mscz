from __future__ import annotations

import contextlib
import io
import unittest
import zipfile
from pathlib import Path

from scorepipe.cli import main

SCORE = """<?xml version="1.0" encoding="UTF-8"?>
<museScore version="4.4">
  <Score><Staff id="1"><Measure>
    <voice><Chord><durationType>whole</durationType><Note><pitch>60</pitch></Note></Chord></voice>
    <voice><Rest><visible>0</visible><durationType>measure</durationType></Rest></voice>
  </Measure></Staff></Score>
</museScore>
"""
CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<container><rootfiles><rootfile full-path="score.mscx"/></rootfiles></container>
"""


class CliTest(unittest.TestCase):
    def test_mscz_display_pipeline_runs_end_to_end(self):
        work = Path(__file__).parent / ".runs" / "cli"
        work.mkdir(parents=True, exist_ok=True)
        source = work / "in.mscz"
        target = work / "out.mscz"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("META-INF/container.xml", CONTAINER)
            archive.writestr("score.mscx", SCORE)

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main([str(source), "-o", str(target)])
        output = buffer.getvalue()

        self.assertEqual(code, 0, output)
        self.assertIn("verifier: clean", output)
        self.assertTrue(target.is_file())
        with zipfile.ZipFile(target) as archive:
            score = archive.read("score.mscx").decode("utf-8")
        self.assertNotIn("<visible>0</visible>", score)
        self.assertEqual(score.count("<voice>"), 1)


if __name__ == "__main__":
    unittest.main()
