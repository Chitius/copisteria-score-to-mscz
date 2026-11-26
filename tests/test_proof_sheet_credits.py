from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree

from scorepipe.proof_sheet import copy_header

SOURCE = """<?xml version="1.0"?>
<score-partwise version="4.0">
  <credit page="1"><credit-type>title</credit-type><credit-words>First Step</credit-words></credit>
  <credit page="1"><credit-type>subtitle</credit-type><credit-words>Interstellar OST</credit-words></credit>
  <credit page="1"><credit-type>composer</credit-type><credit-words>Hans Zimmer</credit-words></credit>
  <credit page="1"><credit-type>arranger</credit-type><credit-words>PianiCast</credit-words></credit>
  <part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
  <part id="P1"><measure number="1"/></part>
</score-partwise>
"""

PAGE = """<?xml version="1.0"?>
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
  <part id="P1"><measure number="1"/></part>
</score-partwise>
"""


class CreditHeaderTest(unittest.TestCase):
    def test_composer_and_arranger_are_joined_into_one_credit(self):
        # MuseScore puts both right-justified credits on the same baseline, so a separate arranger
        # credit printed on top of the composer one on the sheet's first page.
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            source = work / "score.musicxml"
            page = work / "page1.musicxml"
            target = work / "with-title.musicxml"
            source.write_text(SOURCE, encoding="utf-8")
            page.write_text(PAGE, encoding="utf-8")
            added = copy_header(source, page, target)
            self.assertEqual(
                added,
                [("title", "First Step"), ("subtitle", "Interstellar OST"),
                 ("composer", "Hans Zimmer\nPianiCast")],
            )
            root = ElementTree.parse(target).getroot()
            types = [credit.findtext("credit-type") for credit in root.findall("credit")]
            self.assertEqual(types, ["title", "subtitle", "composer"])


if __name__ == "__main__":
    unittest.main()
