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
                [str(source), "--pages", str(pages), "--outdir", str(outdir), "--force"]
            )

        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 2)
        manifest = json.loads((outdir / "delivery.json").read_text(encoding="utf-8"))
        self.assertFalse(manifest["ready"])
        self.assertEqual(manifest["pipeline_exit"], 1)
        self.assertEqual(manifest["render_exit"], 0)

    def test_success_reports_this_run_artifacts(self):
        work = WORK / "convert_success"
        pages = work / "pages"
        pages.mkdir(parents=True, exist_ok=True)
        source = work / "source.pdf"
        source.write_bytes(b"draft")
        outdir = work / "out"

        def fake_run(command, cwd, tolerate=False):
            if "scorepipe.cli" in command:
                Path(command[command.index("-o") + 1]).write_text("musicxml", encoding="utf-8")
                Path(command[command.index("--report") + 1]).write_text("{}", encoding="utf-8")
                Path(command[command.index("--mscz-out") + 1]).write_bytes(b"mscz")
                return 0, ""
            Path(command[command.index("-o") + 1]).write_bytes(b"pdf")
            return 0, ""

        with (
            patch.object(convert_script, "_run", side_effect=fake_run),
            patch.object(convert_script, "_find_musescore", return_value="musescore"),
        ):
            code = convert_script.main(
                [str(source), "--pages", str(pages), "--outdir", str(outdir), "--force"]
            )

        self.assertEqual(code, 0)
        manifest = json.loads((outdir / "delivery.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["ready"])
        self.assertIsNotNone(manifest["artifacts"]["mscz"])
        self.assertIsNotNone(manifest["artifacts"]["pdf"])

    def test_failed_rerun_does_not_report_stale_artifacts(self):
        work = WORK / "convert_stale"
        pages = work / "pages"
        pages.mkdir(parents=True, exist_ok=True)
        source = work / "source.pdf"
        source.write_bytes(b"draft")
        outdir = work / "out"
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / "score.mscz").write_bytes(b"old")
        (outdir / "score.pdf").write_bytes(b"old")

        with (
            patch.object(convert_script, "_run", return_value=(1, "failed")),
            patch.object(convert_script, "_find_musescore", return_value="musescore"),
        ):
            code = convert_script.main(
                [str(source), "--pages", str(pages), "--outdir", str(outdir), "--force"]
            )

        self.assertEqual(code, 1)
        manifest = json.loads((outdir / "delivery.json").read_text(encoding="utf-8"))
        self.assertIsNone(manifest["artifacts"]["mscz"])
        self.assertIsNone(manifest["artifacts"]["pdf"])


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
            if any("review_sheet.py" in part for part in command):
                return 0
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
                    "--no-mechanical",
                    "--no-forced-truncation",
                    "--allow-incomplete-delivery",
                ]
            )

        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 3)  # reviewed pipeline + render + page proof sheets
        self.assertEqual(render_pages.call_count, 2)
        report = json.loads((outdir / "review-report.json").read_text(encoding="utf-8"))
        self.assertFalse(report["ready"])
        self.assertEqual(report["pipeline_exit"], 1)
        self.assertEqual(report["render_exit"], 0)
        self.assertEqual(report["rendered_after"], 1)
        self.assertIn("pdf", report["artifacts"])


class ReviewBaselineFindingTest(unittest.TestCase):
    def test_dirty_mechanical_baseline_does_not_block_the_reviewed_run(self):
        work = WORK / "review_baseline"
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
            if any("review_sheet.py" in part for part in command):
                return 0
            if "scorepipe.cli" in command:
                musicxml = Path(command[command.index("-o") + 1])
                musicxml.parent.mkdir(parents=True, exist_ok=True)
                musicxml.write_text("musicxml", encoding="utf-8")
                Path(command[command.index("--report") + 1]).write_text(
                    json.dumps({"verifier": []}), encoding="utf-8"
                )
                if "--mscz-out" in command:
                    Path(command[command.index("--mscz-out") + 1]).write_bytes(b"mscz")
                # the mechanical baseline is the only run that fails
                return 1 if "mechanical" in command[command.index("-o") + 1] else 0
            Path(command[command.index("-o") + 1]).write_bytes(b"pdf")
            return 0

        with (
            patch.object(review_script, "_pdf_pages", return_value=1),
            patch.object(review_script, "_render_pages", return_value=1),
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

        report = json.loads((outdir / "review-report.json").read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertTrue(report["ready"], report["blockers"])
        self.assertEqual(report["blockers"], [])
        self.assertTrue(any("mechanical baseline" in text for text in report["findings"]))
        self.assertTrue(
            any("--truncate-overfull" in command for command in calls),
            "the forced-truncation tree must still be built when the baseline is dirty",
        )
        self.assertTrue(any(Path(command[command.index("-o") + 1]).name == "score.musicxml" for command in calls if "scorepipe.cli" in command))


class TimingReportTest(unittest.TestCase):
    def test_timing_delta_lists_introduced_and_resolved(self):
        work = WORK / "timing"
        work.mkdir(parents=True, exist_ok=True)
        baseline = work / "baseline.json"
        reviewed = work / "reviewed.json"
        baseline.write_text(
            json.dumps(
                {
                    "verifier": [
                        {"code": "mscx-measure-length", "measure": 16, "detail": "voice 4.5"},
                        {"code": "mscx-measure-length", "measure": 84, "detail": "voice 4.5"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        reviewed.write_text(
            json.dumps(
                {
                    "verifier": [
                        {"code": "mscx-measure-length", "measure": 84, "detail": "voice 4.5"},
                        {"code": "mscx-measure-length", "measure": 122, "detail": "voice 4.2"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        baseline_timing = review_script._timing(baseline)
        reviewed_timing = review_script._timing(reviewed)
        delta = review_script._timing_report(baseline_timing, reviewed_timing)
        self.assertEqual(baseline_timing["count"], 2)
        self.assertEqual(reviewed_timing["count"], 2)
        self.assertEqual([item["measure"] for item in delta["introduced"]], [122])
        self.assertEqual([item["measure"] for item in delta["resolved"]], [16])


if __name__ == "__main__":
    unittest.main()
