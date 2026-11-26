from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import convert as convert_script
from scripts import review as review_script


FIXTURE = Path(__file__).parent / "fixtures" / "tiny.musicxml"


class _TempWorkMixin:
    def _work(self, name: str) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        work = Path(tmp.name) / name
        work.mkdir(parents=True, exist_ok=True)
        return work


class ConvertFailureTest(_TempWorkMixin, unittest.TestCase):
    def test_display_failure_still_renders_and_writes_manifest(self):
        work = self._work("convert")
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
        work = self._work("convert_success")
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
        work = self._work("convert_stale")
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


class ReviewFailureTest(_TempWorkMixin, unittest.TestCase):
    def test_display_failure_still_renders_and_writes_review_report(self):
        work = self._work("review")
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
            patch.object(review_script, "find_musescore", return_value="musescore"),
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

    def test_env_file_supplies_python_and_musescore_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            pages = work / "pages"
            pages.mkdir()
            shutil.copyfile(FIXTURE, pages / "page1.musicxml")
            facts = work / "facts"
            facts.mkdir()
            (facts / "agent-page1.json").write_text(
                json.dumps({"producer": {"name": "agent-visual", "pages": [1]}}),
                encoding="utf-8",
            )
            env_file = work / "env.local.json"
            env_file.write_text(
                json.dumps({"python": "custom-python", "musescore": "custom-mscore"}),
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
                    out = Path(command[command.index("-o") + 1])
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text("musicxml", encoding="utf-8")
                    Path(command[command.index("--report") + 1]).write_text(
                        json.dumps({"verifier": []}), encoding="utf-8"
                    )
                    Path(command[command.index("--mscz-out") + 1]).write_bytes(b"mscz")
                    return 0
                Path(command[command.index("-o") + 1]).write_bytes(b"pdf")
                return 0

            with (
                patch.dict("os.environ", {}, clear=False),
                patch.object(review_script, "_pdf_pages", return_value=1),
                patch.object(review_script, "_render_pages", return_value=1),
                patch.object(review_script, "find_musescore", side_effect=lambda explicit: explicit) as probe,
                patch.object(review_script, "_run", side_effect=fake_run),
            ):
                os_env_backup = {
                    k: review_script.os.environ.pop(k, None)
                    for k in ("SCOREPIPE_PYTHON", "MUSESCORE_EXE")
                }
                try:
                    code = review_script.main(
                        [
                            str(source),
                            "--pages",
                            str(pages),
                            "--facts-dir",
                            str(facts),
                            "--outdir",
                            str(outdir),
                            "--env",
                            str(env_file),
                            "--no-mechanical",
                            "--no-forced-truncation",
                            "--allow-incomplete-delivery",
                        ]
                    )
                finally:
                    for k, v in os_env_backup.items():
                        if v is not None:
                            review_script.os.environ[k] = v

            self.assertEqual(code, 0)
            probe.assert_called_once_with("custom-mscore")
            scorepipe_call = next(cmd for cmd in calls if "scorepipe.cli" in cmd)
            self.assertEqual(scorepipe_call[0], "custom-python")
            self.assertIn("custom-mscore", scorepipe_call)

    def test_forced_truncation_render_error_is_preserved_and_blocks_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            pages = work / "pages"
            pages.mkdir()
            shutil.copyfile(FIXTURE, pages / "page1.musicxml")
            facts = work / "facts"
            facts.mkdir()
            (facts / "agent-page1.json").write_text(
                json.dumps({"producer": {"name": "agent-visual", "pages": [1]}}),
                encoding="utf-8",
            )
            source = work / "source.pdf"
            source.write_bytes(b"draft")
            outdir = work / "out"

            def fake_run(command, cwd):
                if any("review_sheet.py" in part for part in command):
                    return 0
                if "scorepipe.cli" in command:
                    out = Path(command[command.index("-o") + 1])
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text("musicxml", encoding="utf-8")
                    Path(command[command.index("--report") + 1]).write_text(
                        json.dumps({"verifier": []}), encoding="utf-8"
                    )
                    Path(command[command.index("--mscz-out") + 1]).write_bytes(b"mscz")
                    return 0
                Path(command[command.index("-o") + 1]).write_bytes(b"pdf")
                return 0

            def fake_render_pages(pdf, out_pages):
                if "forced-truncation" in str(out_pages):
                    raise RuntimeError("pdftoppm crashed on forced pdf")
                return 1

            with (
                patch.object(review_script, "_pdf_pages", return_value=1),
                patch.object(review_script, "_render_pages", side_effect=fake_render_pages),
                patch.object(review_script, "find_musescore", return_value="musescore"),
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
                        "--allow-incomplete-delivery",
                    ]
                )

            report = json.loads((outdir / "review-report.json").read_text(encoding="utf-8"))
            self.assertNotEqual(code, 0)
            self.assertFalse(report["ready"])
            self.assertFalse(report["forced_truncation"]["ready"])
            self.assertEqual(
                report["forced_truncation"]["render_error"], "pdftoppm crashed on forced pdf"
            )


class ReviewBaselineFindingTest(_TempWorkMixin, unittest.TestCase):
    def test_dirty_mechanical_baseline_does_not_block_the_reviewed_run(self):
        work = self._work("review_baseline")
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
            patch.object(review_script, "find_musescore", return_value="musescore"),
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
        sheet_call = next(cmd for cmd in calls if any("review_sheet.py" in part for part in cmd))
        self.assertIn("--score", sheet_call)
        self.assertEqual(Path(sheet_call[sheet_call.index("--score") + 1]).name, "score.mscz")


class TimingReportTest(_TempWorkMixin, unittest.TestCase):
    def test_timing_delta_lists_introduced_and_resolved(self):
        work = self._work("timing")
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
