from __future__ import annotations

import unittest
from pathlib import Path

from scorepipe.core.document import Document
from scorepipe.notation_patches import apply_patches, validate_patches

TINY = Path(__file__).parent / "fixtures" / "tiny.musicxml"


def patch(**overrides):
    value = {
        "op": "ottava",
        "subtype": "8va",
        "staff": 1,
        "start": {"measure": 1, "beat": 0},
        "end": {"measure": 2, "beat": 0},
        "page": 1,
        "bbox": [10, 20, 30, 40],
        "evidence": "8va bracket",
    }
    value.update(overrides)
    return {"patches": [value]}


class NotationPatchesTest(unittest.TestCase):
    def test_ottava_becomes_musicxml_octave_shift(self):
        doc = Document.load(TINY)
        self.assertEqual(validate_patches(patch(), doc), [])
        changed = apply_patches(doc, patch())
        self.assertEqual(changed, 2)
        shifts = list(doc.root.iter("octave-shift"))
        self.assertEqual([shift.get("type") for shift in shifts], ["up", "stop"])
        self.assertEqual(shifts[0].get("size"), "8")
        self.assertEqual(shifts[0].get("number"), "1")

    def test_end_must_be_after_start(self):
        bad = patch(start={"measure": 2, "beat": 0}, end={"measure": 2, "beat": 0})
        self.assertTrue(any("end must be after start" in problem for problem in validate_patches(bad)))

    def test_evidence_is_required(self):
        bad = patch(page=None, bbox=None)
        self.assertTrue(any("evidence is required" in problem for problem in validate_patches(bad)))

    def test_replace_removes_existing_ottava_before_adding(self):
        doc = Document.load(TINY)
        apply_patches(doc, patch())
        replacement = patch(mode="replace", start={"measure": 1, "beat": 2}, end={"measure": 2, "beat": 0})
        apply_patches(doc, replacement)
        shifts = list(doc.root.iter("octave-shift"))
        self.assertEqual([shift.get("type") for shift in shifts], ["up", "stop"])
        self.assertEqual(len(shifts), 2)

    def test_remove_mode_clears_staff_ottava(self):
        doc = Document.load(TINY)
        apply_patches(doc, patch())
        removed = apply_patches(doc, patch(mode="remove"))
        self.assertEqual(removed, 2)
        self.assertEqual(list(doc.root.iter("octave-shift")), [])


if __name__ == "__main__":
    unittest.main()
