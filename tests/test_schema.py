from __future__ import annotations

import unittest
from pathlib import Path

try:
    from lxml import etree
except ImportError:  # pragma: no cover - optional dependency
    etree = None

FIXTURES = Path(__file__).parent / "fixtures"
SCHEMA = FIXTURES / "musicxml" / "sanity_schema.xsd"
SAMPLE = FIXTURES / "tiny.musicxml"


@unittest.skipIf(etree is None, "lxml is not installed")
class MusicXmlSchemaTest(unittest.TestCase):
    def test_sample_musicxml_validates(self):
        schema = etree.XMLSchema(etree.parse(str(SCHEMA)))
        document = etree.parse(str(SAMPLE))
        self.assertTrue(schema.validate(document), schema.error_log)


if __name__ == "__main__":
    unittest.main()
