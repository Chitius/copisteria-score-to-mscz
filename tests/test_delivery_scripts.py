from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import convert as convert_script
from scripts import review as review_script


FIXTURE = Path(__file__).parent / "fixtures" / "tiny.musicxml"
WORK = Path(__file__).parent / ".runs" / "delivery_scripts"


class ConvertFailureTest(unittest.TestCase):
    def test_display_failure_still_renders_and_writes_manifest(self):
        work = WORK / "convert"
        pages = work / "pages"
        pages.mkdir(parents=True, exist_ok=True)
        source = work / "source.pdf"
        source.write_bytes(b"draft")
        outdir = work / "out"
        calls = []

        def fake_run(command, cwd, tolerate=False):
            calls.append(command)
            if "scorepipe.cli" in command:
                Path(command[command.index("-o") + 1]).write_text("musicxml", encoding="utf-8")
                Path(command[command.index("--report") + 1]).write_text("{}", encoding="utf-8")
                Path(command[command.index("--mscz-out") + 1]).write_bytes(b"mscz")
                return 1, "display verifier failed"
            Path(command[command.index("-o") + 1]).write_bytes(b"pdf")
            return 0, ""

        with (
            patch.object(convert_script, "_run", side_effect=fake_run),
            patch.object(convert_script, "_find_musescore", return_value="musescore"),
        ):
            code = convert_script.main(
                [str(source), "--pages", str(pages), "--outdir", str(outdir)]
            )

        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 2)
        manifest = json.loads((outdir / "delivery.json").read_text(encoding="utf-8"))
        self.assertFalse(manifest["ready"])
        self.assertEqual(manifest["pipeline_exit"], 1)
        self.assertEqual(manifest["render_exit"], 0)
        self.assertIsNotNone(manifest["artifacts"]["pdf"])


class ReviewFailureTest(unittest.TestCase):
    def test_display_failure_still_renders_and_writes_review_report(self):
        work = WORK / "review"
        pages = work / "pages"
        pages.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FIXTURE, pages / "page1.musicxml")
        facts = work / "facts"
        facts.mkdir(parents=True, exist_ok=True)
        (facts / "agent-page1.json").write_text(
            json.dumps({"producer": {"name": "agent-visual", "pages": [1]}}),
            encoding="utf-8",
        )
        source = work / "source.pdf"
        source.write_bytes(b"draft")
        outdir = work / "out"
        calls = []

        def fake_run(command, cwd):
            calls.append(command)
            if "scorepipe.cli" in command:
                Path(command[command.index("-o") + 1]).write_text("musicxml", encoding="utf-8")
                Path(command[command.index("--report") + 1]).write_text("{}", encoding="utf-8")
                Path(command[command.index("--mscz-out") + 1]).write_bytes(b"mscz")
                return 1
            Path(command[command.index("-o") + 1]).write_bytes(b"pdf")
            return 0

        with (
            patch.object(review_script, "_pdf_pages", return_value=1),
            patch.object(review_script, "_render_pages", side_effect=[1, 1]) as render_pages,
            patch.object(review_script, "_run", side_effect=fake_run),
        ):
            code = review_script.main(
                [
                    str(source),
                    "--pages",
                    str(pages),
                    "--facts-dir",
                    str(facts),
                    "--outdir",
                    str(outdir),
                    "--musescore",
                    "musescore",
                ]
            )

        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(render_pages.call_count, 2)
        report = json.loads((outdir / "review-report.json").read_text(encoding="utf-8"))
        self.assertFalse(report["ready"])
        self.assertEqual(report["pipeline_exit"], 1)
        self.assertEqual(report["render_exit"], 0)
        self.assertEqual(report["rendered_after"], 1)
        self.assertIn("pdf", report["artifacts"])


if __name__ == "__main__":
    unittest.main()
