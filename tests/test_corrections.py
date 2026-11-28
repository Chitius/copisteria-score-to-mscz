from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

from scripts import notation_patches as patch_script
from scripts import review as review_script
from scorepipe.cli import main as cli_main
from scorepipe.core.document import Document
from scorepipe.core.pass_base import Context
from scorepipe.core.pipeline import run_pipeline
from scorepipe.corrections import apply_corrections, validate_corrections, verify_corrections
from scorepipe.passes import STRUCTURAL_PASSES


def _doc(measures_xml: str, *, extra_part: str = "") -> Document:
    part_list = '<score-part id="P1"><part-name>P1</part-name></score-part>'
    if extra_part:
        part_list += '<score-part id="P2"><part-name>P2</part-name></score-part>'
    return Document(
        ElementTree.fromstring(
            f"""<score-partwise version="4.0">
  <part-list>{part_list}</part-list>
  <part id="P1">{measures_xml}</part>
  {extra_part}
</score-partwise>"""
        )
    )


def _note(
    step: str,
    octave: int,
    *,
    alter: int = 0,
    duration: int = 4,
    note_type: str = "quarter",
    voice: str = "1",
    staff: int = 1,
    chord: bool = False,
) -> str:
    alter_xml = f"<alter>{alter}</alter>" if alter else ""
    acc = {1: "sharp", -1: "flat"}.get(alter)
    acc_xml = f"<accidental>{acc}</accidental>" if acc else ""
    chord_xml = "<chord/>" if chord else ""
    return (
        f"<note>{chord_xml}<pitch><step>{step}</step>{alter_xml}<octave>{octave}</octave></pitch>"
        f"<duration>{duration}</duration><voice>{voice}</voice><type>{note_type}</type>"
        f"{acc_xml}<staff>{staff}</staff></note>"
    )


def _correction(**overrides) -> dict:
    item = {
        "measure": 1,
        "beat": 0,
        "staff": 1,
        "from": "C8",
        "to": "C7",
        "status": "accepted",
        "page": 1,
        "bbox": [10, 20, 30, 40],
        "evidence": "ledger line one octave too high",
    }
    item.update(overrides)
    return item


class CorrectionsCoreTest(unittest.TestCase):
    def test_ambiguous_anchor_is_rejected_and_voice_disambiguates(self):
        doc = _doc(
            '<measure number="1"><attributes><divisions>4</divisions>'
            "<time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
            + _note("C", 8, voice="1")
            + "<backup><duration>4</duration></backup>"
            + _note("C", 8, voice="2")
            + "</measure>"
        )
        ambiguous = [_correction()]
        problems = validate_corrections(ambiguous, doc, require_acceptance=True)
        self.assertTrue(any("ambiguous anchor" in p for p in problems), problems)
        with self.assertRaises(ValueError):
            apply_corrections(doc, ambiguous)

        specific = [_correction(voice="2")]
        self.assertEqual(validate_corrections(specific, doc, require_acceptance=True), [])
        self.assertEqual(apply_corrections(doc, specific), 1)
        self.assertEqual(verify_corrections(doc, specific), [])
        octaves = [
            (n.findtext("voice"), n.findtext("pitch/octave"))
            for n in doc.measures()[0].findall("note")
        ]
        self.assertEqual(octaves, [("1", "8"), ("2", "7")])

    def test_pitch_accidental_and_duration_corrections(self):
        doc = _doc(
            '<measure number="1"><attributes><divisions>4</divisions>'
            "<time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
            + _note("F", 4, alter=0, duration=4, note_type="quarter")
            + _note("G", 4, alter=1, duration=4, note_type="quarter")
            + _note("A", 4, alter=0, duration=4, note_type="quarter")
            + "</measure>"
        )
        items = [
            _correction(beat=0, **{"from": "F4", "to": "F#4", "kind": "pitch"}),
            _correction(beat=1, **{"from": "G#4", "to": "G4", "kind": "pitch"}),
            _correction(beat=2, **{"from": "quarter", "to": "eighth.", "kind": "duration"}),
        ]
        self.assertEqual(validate_corrections(items, doc, require_acceptance=True), [])
        self.assertEqual(apply_corrections(doc, items), 3)
        self.assertEqual(verify_corrections(doc, items), [])
        notes = doc.measures()[0].findall("note")
        self.assertEqual(notes[0].findtext("pitch/alter"), "1")
        self.assertEqual(notes[0].findtext("accidental"), "sharp")
        self.assertIsNone(notes[1].find("pitch/alter"))
        self.assertIsNone(notes[1].find("accidental"))
        self.assertEqual(notes[2].findtext("duration"), "3")
        self.assertEqual(notes[2].findtext("type"), "eighth")
        self.assertEqual(len(notes[2].findall("dot")), 1)

    def test_octave_kind_rejects_step_change_and_proposed_status(self):
        doc = _doc(
            '<measure number="1"><attributes><divisions>4</divisions></attributes>'
            + _note("C", 4)
            + "</measure>"
        )
        bad_kind = [_correction(**{"from": "C4", "to": "D3", "kind": "octave"})]
        self.assertTrue(
            any("preserve step" in p for p in validate_corrections(bad_kind, doc, require_acceptance=True))
        )
        proposed = [_correction(**{"from": "C4", "to": "C5", "status": "proposed"})]
        self.assertTrue(
            any("accepted before apply" in p for p in validate_corrections(proposed, doc, require_acceptance=True))
        )

    def test_correction_survives_pipeline_voice_renumbering(self):
        doc = _doc(
            '<measure number="1"><attributes><divisions>4</divisions>'
            "<time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
            + _note("C", 8, duration=16, note_type="whole", voice="3")
            + "</measure>"
        )
        items = [_correction(voice="3")]
        self.assertEqual(apply_corrections(doc, items), 1)
        run_pipeline(doc, Context(), structural=STRUCTURAL_PASSES, verifiers=[])
        # normalize_voice_numbers renumbered voice "3" -> "1"; verification still succeeds
        self.assertEqual(doc.measures()[0].find("note").findtext("voice"), "1")
        self.assertEqual(verify_corrections(doc, items), [])


class CorrectionsScriptsAndReviewTest(unittest.TestCase):
    def _work(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def test_notation_patches_accept_and_apply_corrections_with_dry_run(self):
        work = self._work()
        xml_in = work / "score.musicxml"
        doc = _doc(
            '<measure number="1"><attributes><divisions>4</divisions>'
            "<time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
            + _note("C", 8, duration=16, note_type="whole")
            + "</measure>"
        )
        doc.save(xml_in)
        facts_in = work / "facts.json"
        facts_in.write_text(
            json.dumps({"corrections": [_correction(status="proposed")]}),
            encoding="utf-8",
        )
        facts_accepted = work / "facts-accepted.json"
        self.assertEqual(
            patch_script.main(
                [
                    "accept",
                    "--corrections",
                    str(facts_in),
                    "--musicxml",
                    str(xml_in),
                    "--indices",
                    "0",
                    "--reviewer",
                    "alice",
                    "-o",
                    str(facts_accepted),
                ]
            ),
            0,
        )
        accepted_payload = json.loads(facts_accepted.read_text(encoding="utf-8"))
        self.assertEqual(accepted_payload["corrections"][0]["status"], "accepted")
        self.assertEqual(accepted_payload["corrections"][0]["accepted_by"], "alice")

        xml_out = work / "corrected.musicxml"
        self.assertEqual(
            patch_script.main(
                [
                    "apply",
                    "--input",
                    str(xml_in),
                    "--corrections",
                    str(facts_accepted),
                    "--dry-run",
                    "-o",
                    str(xml_out),
                ]
            ),
            0,
        )
        self.assertFalse(xml_out.exists())

        self.assertEqual(
            patch_script.main(
                [
                    "apply",
                    "--input",
                    str(xml_in),
                    "--corrections",
                    str(facts_accepted),
                    "-o",
                    str(xml_out),
                ]
            ),
            0,
        )
        out_doc = Document.load(xml_out)
        self.assertEqual(out_doc.measures()[0].find("note").findtext("pitch/octave"), "7")

    def test_cli_applies_accepted_corrections_from_facts_json(self):
        work = self._work()
        xml_in = work / "score.musicxml"
        _doc(
            '<measure number="1"><attributes><divisions>4</divisions>'
            "<time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
            + _note("C", 8, duration=16, note_type="whole")
            + "</measure>"
        ).save(xml_in)
        facts = work / "facts.json"
        facts.write_text(
            json.dumps(
                {
                    "corrections": [
                        _correction(status="accepted"),
                        _correction(beat=2, status="proposed", **{"from": "D4", "to": "D5"}),
                    ]
                }
            ),
            encoding="utf-8",
        )
        xml_out = work / "out.musicxml"
        self.assertEqual(
            cli_main([str(xml_in), "--facts", str(facts), "-o", str(xml_out)]),
            0,
        )
        out_doc = Document.load(xml_out)
        self.assertEqual(out_doc.measures()[0].find("note").findtext("pitch/octave"), "7")

    def test_review_unblocks_accepted_corrections_and_blocks_proposed_or_bad_anchors(self):
        work = self._work()
        pages = work / "pages"
        pages.mkdir()
        shutil.copyfile(Path(__file__).parent / "fixtures" / "tiny.musicxml", pages / "page1.musicxml")
        source = work / "source.pdf"
        source.write_bytes(b"draft")

        def run_with_corrections(items):
            facts = work / "facts"
            facts.mkdir(exist_ok=True)
            (facts / "agent-page1.json").write_text(
                json.dumps({"producer": {"name": "agent-visual", "pages": [1]}, "corrections": items}),
                encoding="utf-8",
            )
            outdir = work / f"out_{len(list(work.glob('out_*')))}"

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
                    if "--mscz-out" in command:
                        Path(command[command.index("--mscz-out") + 1]).write_bytes(b"mscz")
                    return 0
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
            return code, json.loads((outdir / "review-report.json").read_text(encoding="utf-8"))

        # tiny.musicxml has C4 half note at m1 beat 2 staff 1
        code_ok, report_ok = run_with_corrections(
            [
                _correction(beat=2, status="accepted", **{"from": "C4", "to": "C5"}),
                _correction(status="rejected", **{"from": "D4", "to": "D5"}),
            ]
        )
        self.assertEqual(code_ok, 0)
        self.assertTrue(report_ok["ready"], report_ok["blockers"])
        self.assertEqual(report_ok["corrections_summary"], {"proposed": 0, "accepted": 1, "rejected": 1})

        code_proposed, report_proposed = run_with_corrections(
            [_correction(status="proposed", **{"from": "C4", "to": "C5"})]
        )
        self.assertNotEqual(code_proposed, 0)
        self.assertFalse(report_proposed["ready"])
        self.assertIn("1 proposed correction(s)", report_proposed["blockers"])

        code_bad, report_bad = run_with_corrections(
            [_correction(status="accepted", **{"from": "G9", "to": "G8"})]
        )
        self.assertNotEqual(code_bad, 0)
        self.assertFalse(report_bad["ready"])
        self.assertTrue(any(b.startswith("correction:") for b in report_bad["blockers"]))


if __name__ == "__main__":
    unittest.main()
