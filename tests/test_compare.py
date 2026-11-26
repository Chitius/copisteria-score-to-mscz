from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree

from scorepipe.compare import compare

FIXTURE = Path(__file__).parent / "fixtures" / "tiny.musicxml"


class CompareTest(unittest.TestCase):
    def test_identical_scores_match(self):
        result = compare(FIXTURE, FIXTURE)
        self.assertEqual(result["ratio"], 0.0)
        self.assertEqual(result["missing"], 0)
        self.assertEqual(result["extra"], 0)

    def test_a_changed_pitch_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = ElementTree.parse(FIXTURE)
            first = tree.getroot().find(".//note/pitch/step")
            first.text = "D" if first.text != "D" else "E"
            candidate = Path(tmp) / "changed.musicxml"
            tree.write(candidate, encoding="utf-8", xml_declaration=True)
            result = compare(FIXTURE, candidate)
        self.assertGreater(result["ratio"], 0)
        self.assertEqual(result["missing"], 1)
        self.assertEqual(result["extra"], 1)


if __name__ == "__main__":
    unittest.main()
