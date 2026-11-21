from __future__ import annotations

import importlib.util
import sys
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

    def test_every_score_matches_itself(self):
        comparator = load_comparator()
        for name in CASES:
            ground_truth = CORPUS / name / "ground_truth.musicxml"
            result = comparator.compare(ground_truth, ground_truth)
            self.assertEqual(set(result["parts"]), {"P1", "P2"}, name)
            for part in result["parts"].values():
                self.assertEqual(part["match"], 1.0, name)
                self.assertEqual(part["missing"], 0, name)
                self.assertEqual(part["extra"], 0, name)


if __name__ == "__main__":
    unittest.main()
