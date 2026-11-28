from __future__ import annotations

import json
import unittest
from pathlib import Path

try:
    from lxml import etree
except ImportError:  # pragma: no cover - optional dependency
    etree = None

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - optional dependency
    Draft202012Validator = None

from scorepipe.agent_facts import CREDIT_TYPES, GRADUAL_TYPES, validate_agent_facts
from scorepipe.instruments import INSTRUMENT_KEYS
from scorepipe.notation_patches import (
    CLEF_SIGNS,
    DYNAMIC_MARKS,
    OTTAAVA_SUBTYPES,
    WEDGE_SUBTYPES,
    validate_patches,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
SCHEMA = FIXTURES / "musicxml" / "sanity_schema.xsd"
SAMPLE = FIXTURES / "tiny.musicxml"
FACTS_SCHEMA = ROOT / "schemas" / "facts.schema.json"
PATCHES_SCHEMA = ROOT / "schemas" / "notation-patches.schema.json"


@unittest.skipIf(etree is None, "lxml is not installed")
class MusicXmlSchemaTest(unittest.TestCase):
    def test_sample_musicxml_validates(self):
        schema = etree.XMLSchema(etree.parse(str(SCHEMA)))
        document = etree.parse(str(SAMPLE))
        self.assertTrue(schema.validate(document), schema.error_log)


class JsonSchemaContractTest(unittest.TestCase):
    def test_facts_schema_enums_stay_in_sync_with_code(self):
        schema = json.loads(FACTS_SCHEMA.read_text(encoding="utf-8"))
        props = schema["properties"]
        self.assertEqual(
            set(props["credits"]["items"]["properties"]["type"]["enum"]), CREDIT_TYPES
        )
        self.assertEqual(
            set(props["marks"]["items"]["properties"]["gradual"]["enum"]), GRADUAL_TYPES
        )
        self.assertEqual(
            set(props["parts"]["items"]["properties"]["instrument"]["enum"]), set(INSTRUMENT_KEYS)
        )
        self.assertIn("producer", props)
        self.assertIn("unresolved", props)

    def test_patches_schema_enums_stay_in_sync_with_code(self):
        schema = json.loads(PATCHES_SCHEMA.read_text(encoding="utf-8"))
        defs = schema["$defs"]
        self.assertEqual(
            set(defs["ottava-patch"]["allOf"][1]["properties"]["subtype"]["enum"]),
            set(OTTAAVA_SUBTYPES),
        )
        self.assertEqual(
            set(defs["clef-patch"]["allOf"][1]["properties"]["clef"]["enum"]),
            CLEF_SIGNS,
        )
        self.assertEqual(
            set(defs["wedge-patch"]["allOf"][1]["properties"]["subtype"]["enum"]),
            set(WEDGE_SUBTYPES),
        )
        self.assertEqual(
            set(defs["dynamic-patch"]["allOf"][1]["properties"]["mark"]["enum"]),
            set(DYNAMIC_MARKS),
        )

    @unittest.skipIf(Draft202012Validator is None, "jsonschema is not installed")
    def test_facts_payload_passes_both_json_schema_and_validator(self):
        schema = json.loads(FACTS_SCHEMA.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        payload = {
            "producer": {"name": "agent-visual", "pages": [1]},
            "credits": [
                {
                    "type": "title",
                    "text": "Sincerely",
                    "page": 1,
                    "bbox": [200, 20, 400, 60],
                    "evidence": "top title",
                    "confidence": 0.99,
                }
            ],
            "marks": [
                {
                    "measure": 1,
                    "beat": 0,
                    "placement": "above",
                    "text": "rit.",
                    "gradual": "ritardando",
                    "length_measures": 2,
                    "page": 1,
                    "bbox": [50, 80, 120, 100],
                    "evidence": "rit. above m1",
                    "confidence": 0.95,
                }
            ],
            "parts": [
                {
                    "part": "P1",
                    "name": "Acoustic Guitar",
                    "abbreviation": "Guit.",
                    "instrument": "acoustic-guitar",
                    "page": 1,
                    "bbox": [20, 80, 90, 110],
                    "evidence": "staff 1 label: Acoustic Guitar",
                    "confidence": 0.98,
                }
            ],
            "corrections": [
                {
                    "measure": 3,
                    "beat": 1.5,
                    "staff": 1,
                    "voice": "1",
                    "from": "C8",
                    "to": "C7",
                    "status": "proposed",
                    "page": 1,
                    "bbox": [10, 20, 30, 40],
                    "evidence": "ledger line too high",
                }
            ],
            "unresolved": [{"page": 1, "measure": 2, "reason": "smudged dynamic"}],
        }
        errors = list(validator.iter_errors(payload))
        self.assertEqual(errors, [], [e.message for e in errors])
        self.assertEqual(validate_agent_facts(payload, page_count=1, measure_count=10), [])

    @unittest.skipIf(Draft202012Validator is None, "jsonschema is not installed")
    def test_patches_payload_passes_both_json_schema_and_validator(self):
        schema = json.loads(PATCHES_SCHEMA.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        payload = {
            "patches": [
                {
                    "op": "ottava",
                    "part": "P2",
                    "subtype": "8vb",
                    "staff": 2,
                    "start": {"measure": 1, "beat": 0},
                    "end": {"measure": 6, "beat": 3},
                    "status": "accepted",
                    "page": 1,
                    "bbox": [10, 20, 100, 40],
                    "evidence": "8vb bracket under bass",
                },
                {
                    "op": "pedal",
                    "part": "P2",
                    "staff": 2,
                    "start": {"measure": 1, "beat": 0},
                    "changes": [{"measure": 2, "beat": 0}],
                    "end": {"measure": 2, "beat": 3},
                    "status": "accepted",
                    "page": 1,
                    "bbox": [10, 20, 100, 40],
                    "evidence": "pedal line across m1-m2",
                },
                {
                    "op": "wedge",
                    "subtype": "crescendo",
                    "staff": 1,
                    "start": {"measure": 1, "beat": 1},
                    "end": {"measure": 2, "beat": 2},
                    "status": "accepted",
                    "page": 1,
                    "bbox": [10, 20, 100, 40],
                    "evidence": "cresc hairpin",
                },
                {
                    "op": "dynamic",
                    "measure": 1,
                    "beat": 0,
                    "staff": 1,
                    "mark": "mf",
                    "status": "accepted",
                    "page": 1,
                    "bbox": [10, 20, 40, 40],
                    "evidence": "mf at m1",
                },
                {
                    "op": "clef",
                    "measure": 5,
                    "staff": 2,
                    "clef": "G",
                    "line": 2,
                    "from_measure": 4,
                    "status": "accepted",
                    "page": 1,
                    "crop": "crops/clef.png",
                    "evidence": "treble clef at m5",
                },
            ]
        }
        errors = list(validator.iter_errors(payload))
        self.assertEqual(errors, [], [e.message for e in errors])
        self.assertEqual(validate_patches(payload, require_acceptance=True), [])


if __name__ == "__main__":
    unittest.main()
