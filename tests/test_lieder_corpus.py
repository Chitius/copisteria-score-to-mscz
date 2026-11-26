from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

CORPUS = Path(__file__).parent / "corpus" / "lieder"
CASES = {
    "gute_nacht": 105,
    "die_wetterfahne": 52,
    "der_lindenbaum": 82,
    "aus_meinen_traenen": 18,
}


def load_comparator():
    spec = importlib.util.spec_from_file_location("lieder_compare", CORPUS / "compare_parts.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class LiederCorpusTest(unittest.TestCase):
    def test_case_files_are_present(self):
        for name, measures in CASES.items():
            case = CORPUS / name
            self.assertTrue((case / "input.pdf").exists(), name)
            self.assertTrue((case / "ground_truth.musicxml").exists(), name)
            self.assertTrue((case / f"{name}.mxl").exists(), name)

    def test_ground_truth_is_the_full_two_part_song(self):
        from xml.etree import ElementTree

        for name, measures in CASES.items():
            root = ElementTree.parse(CORPUS / name / "ground_truth.musicxml").getroot()
            parts = root.findall("part")
            self.assertEqual([part.get("id") for part in parts], ["P1", "P2"], name)
            self.assertEqual([len(part.findall("measure")) for part in parts], [measures, measures], name)

    def test_comparator_is_consistent_on_identical_scores(self):
        """Fixture-integrity check for the comparator, not a pipeline regression."""
        comparator = load_comparator()
        for name in CASES:
            ground_truth = CORPUS / name / "ground_truth.musicxml"
            result = comparator.compare(ground_truth, ground_truth)
            self.assertEqual(set(result["parts"]), {"P1", "P2"}, name)
            for part in result["parts"].values():
                self.assertEqual(part["match"], 1.0, name)
                self.assertEqual(part["missing"], 0, name)
                self.assertEqual(part["extra"], 0, name)

    def test_rest_only_difference_does_not_lower_the_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            template = (
                '<?xml version="1.0" encoding="UTF-8"?><score-partwise version="4.0">'
                '<part-list><score-part id="P1"><part-name>t</part-name></score-part></part-list>'
                '<part id="P1"><measure number="1"><attributes><divisions>4</divisions>'
                "<time><beats>4</beats><beat-type>4</beat-type></time></attributes>{body}"
                "</measure></part></score-partwise>"
            )
            ground_truth = work / "gt.musicxml"
            candidate = work / "candidate.musicxml"
            ground_truth.write_text(
                template.format(
                    body="<note><rest/><duration>8</duration><voice>1</voice></note>"
                    '<note><pitch><step>C</step><octave>4</octave></pitch>'
                    "<duration>8</duration><voice>1</voice></note>"
                ),
                encoding="utf-8",
            )
            candidate.write_text(
                template.format(
                    body="<note><rest/><duration>4</duration><voice>1</voice></note>"
                    "<note><rest/><duration>4</duration><voice>1</voice></note>"
                    '<note><pitch><step>C</step><octave>4</octave></pitch>'
                    "<duration>8</duration><voice>1</voice></note>"
                ),
                encoding="utf-8",
            )
            result = load_comparator().compare(ground_truth, candidate)["parts"]["P1"]
        self.assertEqual(result["match"], 1.0)
        self.assertLess(result["overall_match"], 1.0)
        self.assertGreater(result["rest_missing"] + result["rest_extra"], 0)


if __name__ == "__main__":
    unittest.main()
