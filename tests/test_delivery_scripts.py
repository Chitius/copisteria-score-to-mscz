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


class ReviewLengthToleranceTest(_TempWorkMixin, unittest.TestCase):
    """A reviewed tree that only complains about length is repaired by the editable copy.

    Gurenge m42/m76 produced a one-voice overfull bar *and* a short tuplet inside it; the forced
    copy trims/retimes both, so the delivery must not be blocked and the reviewed exit must stay
    visible in its own field.
    """

    TRUNCATION_NOTE = "m12 staff 1: 4.25->4 beats; remove 0.25"

    def _run(self, reviewed_verifier):
        work = self._work("review_length")
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

        def fake_run(command, cwd):
            if any("review_sheet.py" in part for part in command):
                return 0
            if "scorepipe.cli" in command:
                musicxml = Path(command[command.index("-o") + 1])
                musicxml.parent.mkdir(parents=True, exist_ok=True)
                musicxml.write_text("musicxml", encoding="utf-8")
                report_path = Path(command[command.index("--report") + 1])
                if "--truncate-overfull" in command:
                    report_path.write_text(
                        json.dumps(
                            {
                                "verifier": [],
                                "trace": [
                                    {
                                        "pass": "truncate_overfull_mscx",
                                        "notes": [self.TRUNCATION_NOTE],
                                    }
                                ],
                            }
                        ),
                        encoding="utf-8",
                    )
                    Path(command[command.index("--mscz-out") + 1]).write_bytes(b"mscz")
                    return 0
                report_path.write_text(
                    json.dumps({"verifier": reviewed_verifier}), encoding="utf-8"
                )
                if "--mscz-out" in command:
                    Path(command[command.index("--mscz-out") + 1]).write_bytes(b"mscz")
                return 1
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
        delivery = json.loads((outdir / "delivery.json").read_text(encoding="utf-8"))
        return code, report, delivery

    def test_measure_and_tuplet_length_findings_are_tolerated(self):
        code, report, delivery = self._run(
            [
                {"code": "mscx-measure-length", "measure": 42, "detail": "voice 4.3 beats"},
                {"code": "mscx-tuplet-length", "measure": 42, "detail": "tuplet 0.5/0.75"},
                {"code": "mscx-tuplet-length", "measure": 76, "detail": "tuplet 0.5/0.75"},
            ]
        )

        self.assertEqual(code, 0)
        self.assertTrue(report["ready"], report["blockers"])
        self.assertEqual(report["blockers"], [])
        # the shipped artifacts come from the forced copy, but the reviewed failure stays visible
        self.assertEqual(report["pipeline_exit"], 0)
        self.assertEqual(report["reviewed_pipeline_exit"], 1)
        self.assertEqual(delivery["reviewed_pipeline_exit"], 1)
        self.assertEqual(
            report["reviewed_verifier_codes"], ["mscx-measure-length", "mscx-tuplet-length"]
        )
        finding = next(text for text in report["findings"] if "length complaints" in text)
        self.assertIn("mscx-measure-length", finding)
        self.assertIn("mscx-tuplet-length", finding)

    def test_a_non_length_finding_still_blocks_and_keeps_both_exits(self):
        code, report, delivery = self._run(
            [
                {"code": "mscx-measure-length", "measure": 42, "detail": "voice 4.3 beats"},
                {"code": "duplicate-tie", "measure": 12, "detail": "2x tie start"},
            ]
        )

        self.assertNotEqual(code, 0)
        self.assertFalse(report["ready"])
        self.assertEqual(report["blockers"], ["reviewed pipeline exited 1"])
        self.assertEqual(report["pipeline_exit"], 0)
        self.assertEqual(report["reviewed_pipeline_exit"], 1)
        self.assertEqual(delivery["reviewed_pipeline_exit"], 1)


class ReviewAcceptVerifierTest(_TempWorkMixin, unittest.TestCase):
    def _run_case(
        self,
        *,
        reviewed_verifier: list[dict],
        forced_verifier: list[dict] | None = None,
        forced_notes: list[str] | None = None,
        extra_args: list[str] | None = None,
    ):
        work = self._work("accept_verifier")
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
                report_path = Path(command[command.index("--report") + 1])
                if "--truncate-overfull" in command:
                    ver = forced_verifier if forced_verifier is not None else []
                    trace = (
                        [{"pass": "truncate_overfull_mscx", "notes": forced_notes}]
                        if forced_notes
                        else []
                    )
                    report_path.write_text(
                        json.dumps({"verifier": ver, "trace": trace}),
                        encoding="utf-8",
                    )
                    Path(command[command.index("--mscz-out") + 1]).write_bytes(b"mscz")
                    return 1 if ver else 0
                if "mechanical" in str(musicxml):
                    report_path.write_text(json.dumps({"verifier": []}), encoding="utf-8")
                    if "--mscz-out" in command:
                        Path(command[command.index("--mscz-out") + 1]).write_bytes(b"mscz")
                    return 0
                report_path.write_text(
                    json.dumps({"verifier": reviewed_verifier}), encoding="utf-8"
                )
                if "--mscz-out" in command:
                    Path(command[command.index("--mscz-out") + 1]).write_bytes(b"mscz")
                return 1 if reviewed_verifier else 0
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
                    *(extra_args or []),
                ]
            )
        report = json.loads((outdir / "review-report.json").read_text(encoding="utf-8"))
        delivery = json.loads((outdir / "delivery.json").read_text(encoding="utf-8"))
        return code, report, delivery, calls

    def test_accepted_known_finding_allows_ready_and_is_recorded(self):
        finding = {
            "code": "measure-length",
            "measure": 130,
            "detail": "voice 1 ends at 3.0 beats, expected 4.0",
        }
        code, report, delivery, _calls = self._run_case(
            reviewed_verifier=[finding],
            forced_verifier=[finding],
            extra_args=[
                "--accept-verifier",
                "m130:measure-length",
                "--accept-reason",
                "printed bass G#4 lacks a dot; MuseScore pads a rest",
            ],
        )
        self.assertEqual(code, 0)
        self.assertTrue(report["ready"], report["blockers"])
        self.assertTrue(delivery["ready"])
        self.assertEqual(report["accepted_verifier_specs"], ["130:measure-length"])
        self.assertEqual(delivery["accepted_verifier_specs"], ["130:measure-length"])
        self.assertEqual(len(report["accepted_findings"]), 2)
        self.assertEqual({item["stage"] for item in report["accepted_findings"]}, {"reviewed", "forced"})
        self.assertEqual(
            report["accepted_findings"][0]["reason"],
            "printed bass G#4 lacks a dot; MuseScore pads a rest",
        )
        self.assertTrue(any("m130:measure-length" in text for text in report["findings"]))

    def test_accepting_one_finding_does_not_hide_unaccepted_findings(self):
        code, report, _delivery, _calls = self._run_case(
            reviewed_verifier=[
                {"code": "measure-length", "measure": 130, "detail": "short voice"},
                {"code": "duplicate-tie", "measure": 12, "detail": "2x tie start"},
            ],
            extra_args=["--accept-verifier", "130:measure-length"],
        )
        self.assertNotEqual(code, 0)
        self.assertFalse(report["ready"])
        self.assertIn("reviewed pipeline exited 1", report["blockers"])

    def test_accepted_finding_coexists_with_forced_truncation_tolerance(self):
        m130 = {"code": "measure-length", "measure": 130, "detail": "short voice"}
        m42 = {"code": "mscx-measure-length", "measure": 42, "detail": "voice 4.25 beats"}
        code, report, delivery, _calls = self._run_case(
            reviewed_verifier=[m130, m42],
            forced_verifier=[m130],
            forced_notes=["m42 staff 1: 4.25->4 beats; remove 0.25"],
            extra_args=["--accept-verifier", "130:measure-length"],
        )
        self.assertEqual(code, 0)
        self.assertTrue(report["ready"], report["blockers"])
        self.assertTrue(delivery["ready"])
        self.assertEqual(len(report["accepted_findings"]), 2)
        self.assertTrue(any("length complaints" in text for text in report["findings"]))

    def test_pad_last_measure_forwards_to_reviewed_and_forced_cli(self):
        code, report, _delivery, calls = self._run_case(
            reviewed_verifier=[],
            extra_args=["--pad-last-measure"],
        )
        self.assertEqual(code, 0)
        self.assertTrue(report["ready"])
        cli_calls = [cmd for cmd in calls if "scorepipe.cli" in cmd]
        reviewed_and_forced = [cmd for cmd in cli_calls if "--facts" in cmd]
        self.assertEqual(len(reviewed_and_forced), 2)
        for cmd in reviewed_and_forced:
            self.assertIn("--pad-last-measure", cmd)

    def test_invalid_accept_verifier_syntax_fails_argument_parsing(self):
        with self.assertRaises(SystemExit) as raised:
            review_script.main(
                [
                    "dummy.pdf",
                    "--pages",
                    "pages",
                    "--outdir",
                    "out",
                    "--accept-verifier",
                    "130",
                ]
            )
        self.assertNotEqual(raised.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
