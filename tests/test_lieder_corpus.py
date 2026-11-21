from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

CORPUS = Path(__file__).parent / "corpus" / "lieder"
CASE = CORPUS / "gute_nacht"
GROUND_TRUTH = CASE / "ground_truth.musicxml"


def load_comparator():
    spec = importlib.util.spec_from_file_location("lieder_compare", CORPUS / "compare_parts.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class LiederCorpusTest(unittest.TestCase):
    def test_case_files_are_present(self):
        self.assertTrue((CASE / "gute_nacht.mxl").exists())
        self.assertTrue((CASE / "input.pdf").exists())
        self.assertTrue(GROUND_TRUTH.exists())

    def test_ground_truth_is_the_full_two_part_song(self):
        from xml.etree import ElementTree

        root = ElementTree.parse(GROUND_TRUTH).getroot()
        parts = root.findall("part")
        self.assertEqual([part.get("id") for part in parts], ["P1", "P2"])
        self.assertEqual([len(part.findall("measure")) for part in parts], [105, 105])

    def test_score_matches_itself(self):
        result = load_comparator().compare(GROUND_TRUTH, GROUND_TRUTH)
        self.assertEqual(set(result["parts"]), {"P1", "P2"})
        for part in result["parts"].values():
            self.assertEqual(part["match"], 1.0)
            self.assertEqual(part["missing"], 0)
            self.assertEqual(part["extra"], 0)


if __name__ == "__main__":
    unittest.main()
