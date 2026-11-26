from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scorepipe.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "tiny.musicxml"


class ReportTest(unittest.TestCase):
    def test_report_contains_phases_analysis_and_verifier(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            report_path = work / "report.json"
            code = main([str(FIXTURE), "--report", str(report_path), "-o", str(work / "out.musicxml")])
            self.assertEqual(code, 0)
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual([phase["phase"] for phase in payload["phases"]], ["structural", "inject"])
        self.assertTrue(any(entry["pass"] == "measure_length_report" for entry in payload["analysis"]))
        self.assertEqual(payload["verifier"], [])

    def test_analysis_notes_are_collected(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            source = work / "short.musicxml"
            source.write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="4.0"><part-list><score-part id="P1"><part-name>t</part-name></score-part></part-list>
<part id="P1">
<measure number="1"><attributes><divisions>4</divisions>
<time><beats>4</beats><beat-type>4</beat-type></time></attributes>
<note><pitch><step>C</step><octave>4</octave></pitch><duration>16</duration><voice>1</voice></note>
</measure>
<measure number="2">
<note><pitch><step>D</step><octave>4</octave></pitch><duration>20</duration><voice>1</voice></note>
</measure></part></score-partwise>""",
                encoding="utf-8",
            )
            report_path = work / "short.json"
            main([str(source), "--report", str(report_path)])
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        notes = [note for entry in payload["analysis"] for note in entry["notes"]]
        self.assertTrue(any("m2" in note for note in notes), notes)


if __name__ == "__main__":
    unittest.main()
