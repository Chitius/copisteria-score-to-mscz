from __future__ import annotations

import contextlib
import io
import json
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scorepipe.cli import main
from scorepipe.core.invariants import Violation
from scorepipe.core.pipeline import PhaseReport, RunReport, TraceEntry

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

    def test_list_passes(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(["--list-passes"])
        self.assertEqual(code, 0)
        output = buffer.getvalue()
        self.assertIn("dedupe_ties", output)
        self.assertIn("canonical_voice_order", output)

    def test_check_mode_never_writes(self):
        work = Path(__file__).parent / ".runs" / "cli"
        work.mkdir(parents=True, exist_ok=True)
        source = work / "check_in.mscz"
        target = work / "check_out.mscz"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("META-INF/container.xml", CONTAINER)
            archive.writestr("score.mscx", SCORE)
        if target.exists():
            target.unlink()
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main([str(source), "--check", "-o", str(target)])
        self.assertEqual(code, 0, buffer.getvalue())
        self.assertFalse(target.exists())

    def test_display_failure_is_written_to_final_report(self):
        work = Path(__file__).parent / ".runs" / "cli"
        work.mkdir(parents=True, exist_ok=True)
        source = Path(__file__).parent / "fixtures" / "tiny.musicxml"
        output = work / "display_report.musicxml"
        report_path = work / "display_report.json"
        display_report = RunReport(
            phases=[PhaseReport(phase="display", rounds=2, changes=1, stable=True)],
            trace=[TraceEntry("display", 1, "mock_display", 1, "before", "after")],
            verifier=[Violation("mscx-measure-length", 8, "mock failure")],
        )
        with patch("scorepipe.cli.export_and_display", return_value=display_report):
            code = main(
                [
                    str(source),
                    "-o",
                    str(output),
                    "--mscz-out",
                    str(work / "display_report.mscz"),
                    "--report",
                    str(report_path),
                ]
            )

        self.assertEqual(code, 1)
        payload = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(
            [phase["phase"] for phase in payload["phases"]],
            ["structural", "inject", "display"],
        )
        self.assertEqual(payload["verifier"][0]["code"], "mscx-measure-length")
        self.assertEqual(payload["trace"][-1]["pass"], "mock_display")

    def test_tuplet_precedes_pipeline_and_ottava_follows_it(self):
        work = Path(__file__).parent / ".runs" / "cli"
        work.mkdir(parents=True, exist_ok=True)
        patch_path = work / "mixed-patches.json"
        patch_path.write_text(
            json.dumps(
                {
                    "patches": [
                        {"op": "tuplet"},
                        {"op": "ottava"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        events = []

        def fake_apply(doc, payload):
            events.append(payload["patches"][0]["op"])
            return 1

        def fake_pipeline(*args, **kwargs):
            events.append("pipeline")
            return RunReport()

        with (
            patch("scorepipe.cli.validate_patches", return_value=[]),
            patch("scorepipe.cli.apply_patches", side_effect=fake_apply),
            patch("scorepipe.cli.run_pipeline", side_effect=fake_pipeline),
        ):
            code = main(
                [
                    str(Path(__file__).parent / "fixtures" / "tiny.musicxml"),
                    "--patches",
                    str(patch_path),
                    "--check",
                ]
            )

        self.assertEqual(code, 1)
        self.assertEqual(events, ["tuplet", "pipeline", "ottava"])

    def test_truncate_overfull_requires_an_mscz_output(self):
        with self.assertRaises(SystemExit) as raised:
            main([str(Path(__file__).parent / "fixtures" / "tiny.musicxml"), "--truncate-overfull"])
        self.assertNotEqual(raised.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
