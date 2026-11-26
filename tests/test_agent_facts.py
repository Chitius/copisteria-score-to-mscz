from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scorepipe.agent_facts import (
    merge_agent_facts,
    normalize_agent_facts,
    validate_agent_facts,
)
from scorepipe.facts import load_facts


def payload(**extra):
    base = {
        "producer": {"name": "agent-visual", "pages": [1]},
        "credits": [
            {
                "type": "title",
                "text": "Sincerely",
                "page": 1,
                "bbox": [240, 20, 360, 60],
                "evidence": "top centre title",
                "confidence": 0.98,
            }
        ],
        "marks": [
            {
                "measure": 1,
                "beat": 0,
                "placement": "above",
                "text": "q = 72",
                "tempo": 72,
                "page": 1,
                "bbox": [60, 70, 110, 95],
                "evidence": "tempo above the first system",
                "confidence": 0.95,
            }
        ],
        "unresolved": [],
    }
    base.update(extra)
    return base


class AgentFactsTest(unittest.TestCase):
    def test_valid_evidence_is_accepted(self):
        self.assertEqual(validate_agent_facts(payload(), page_count=1, measure_count=31), [])

    def test_missing_evidence_and_crop_are_rejected(self):
        bad = payload()
        del bad["marks"][0]["evidence"]
        del bad["marks"][0]["bbox"]
        problems = validate_agent_facts(bad)
        self.assertTrue(any("evidence is required" in problem for problem in problems))
        self.assertTrue(any("bbox or crop is required" in problem for problem in problems))

    def test_page_and_measure_bounds_are_checked(self):
        bad = payload()
        bad["marks"][0]["page"] = 3
        bad["marks"][0]["measure"] = 40
        problems = validate_agent_facts(bad, page_count=2, measure_count=31)
        self.assertTrue(any("exceeds 2" in problem for problem in problems))
        self.assertTrue(any("exceeds 31" in problem for problem in problems))

    def test_valid_correction_is_accepted_but_not_a_mark(self):
        data = payload(
            corrections=[
                {
                    "measure": 30,
                    "beat": 3.5,
                    "staff": 1,
                    "from": "C8",
                    "to": "C7",
                    "page": 1,
                    "bbox": [1, 2, 3, 4],
                    "evidence": "ledger-line octave looks one too high",
                    "confidence": 0.4,
                    "status": "proposed",
                }
            ]
        )
        self.assertEqual(validate_agent_facts(data, page_count=1, measure_count=31), [])
        merged = merge_agent_facts([data])
        self.assertEqual(len(merged["corrections"]), 1)
        self.assertEqual(len(merged["marks"]), 1)

    def test_identical_pitch_correction_is_rejected(self):
        data = payload(
            corrections=[
                {
                    "measure": 30,
                    "from": "C8",
                    "to": "C8",
                    "page": 1,
                    "bbox": [1, 2, 3, 4],
                    "evidence": "no change",
                }
            ]
        )
        problems = validate_agent_facts(data)
        self.assertTrue(any("identical" in problem for problem in problems))

    def test_merge_deduplicates_same_claim(self):
        merged = merge_agent_facts([payload(), payload()])
        self.assertEqual(len(merged["credits"]), 1)
        self.assertEqual(len(merged["marks"]), 1)
        self.assertEqual(merged["producer"]["pages"], [1])

    def test_agent_labels_are_stripped_from_credit_values(self):
        data = payload(
            credits=[
                {"type": "composer", "text": "Original Artist:TRUE", "page": 1,
                 "bbox": [1, 2, 3, 4], "evidence": "credit"},
                {"type": "arranger", "text": "Arranged by Someone", "page": 1,
                 "bbox": [1, 2, 3, 4], "evidence": "credit"},
                {"type": "transcriber", "text": "Transcribed by Skzynic", "page": 1,
                 "bbox": [1, 2, 3, 4], "evidence": "credit"},
            ]
        )
        normalized = normalize_agent_facts(data)
        self.assertEqual(
            [credit["text"] for credit in normalized["credits"]],
            ["TRUE", "Someone", "Skzynic"],
        )

    def test_legacy_unresolved_note_becomes_reason(self):
        data = payload(unresolved=[{"page": 1, "note": "too small"}])
        self.assertEqual(validate_agent_facts(normalize_agent_facts(data)), [])

    def test_facts_loader_normalizes_agent_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "facts.json"
            path.write_text(
                json.dumps(
                    payload(
                        credits=[
                            {
                                "type": "composer",
                                "text": "Original Artist:TRUE",
                                "page": 1,
                                "bbox": [1, 2, 3, 4],
                                "evidence": "credit",
                            }
                        ]
                    )
                ),
                encoding="utf-8",
            )
            loaded = load_facts(path)
        self.assertEqual(loaded["credits"][0]["text"], "TRUE")


if __name__ == "__main__":
    unittest.main()
