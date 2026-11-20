from __future__ import annotations

import unittest
import zipfile
from pathlib import Path

from scorepipe.core.mscz import MsczArchive
from scorepipe.core.mscx_invariants import MSCX_VERIFIERS
from scorepipe.core.pass_base import Context, Phase
from scorepipe.core.pipeline import run_phase
from scorepipe.passes import DISPLAY_PASSES

SCORE = """<?xml version="1.0" encoding="UTF-8"?>
<museScore version="4.4">
  <Score>
    <Staff id="1">
      <Measure>
        <voice>
          <Chord><durationType>whole</durationType><Note><pitch>60</pitch></Note></Chord>
        </voice>
        <voice>
          <Rest><visible>0</visible><durationType>measure</durationType></Rest>
        </voice>
      </Measure>
    </Staff>
  </Score>
</museScore>
"""

CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<container><rootfiles><rootfile full-path="score.mscx"/></rootfiles></container>
"""


class MsczArchiveTest(unittest.TestCase):
    def _make_archive(self, path: Path) -> None:
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("META-INF/container.xml", CONTAINER)
            archive.writestr("score.mscx", SCORE)
            archive.writestr("style.mss", "<museScore/>")

    def test_roundtrip_keeps_other_files_and_applies_passes(self):
        work = Path(__file__).parent / ".runs" / "archive"
        work.mkdir(parents=True, exist_ok=True)
        source = work / "in.mscz"
        destination = work / "out.mscz"
        self._make_archive(source)

        bundle = MsczArchive.open(source)
        run_phase(bundle.document, DISPLAY_PASSES, Context(), Phase.DISPLAY)
        bundle.save(destination)

        with zipfile.ZipFile(destination) as archive:
            names = archive.namelist()
            self.assertIn("style.mss", names)
            score = archive.read("score.mscx").decode("utf-8")
        self.assertNotIn("<visible>0</visible>", score)
        self.assertEqual(score.count("<voice>"), 1)

        reopened = MsczArchive.open(destination)
        self.assertEqual(len(reopened.document.staves()[0].findall("Measure")[0].findall("voice")), 1)

        # re-running the display passes on the reopened archive must be a no-op
        again = run_phase(reopened.document, DISPLAY_PASSES, Context(), Phase.DISPLAY)
        self.assertEqual(again.changes, 0)
        for verifier in MSCX_VERIFIERS:
            self.assertEqual(verifier(reopened.document, Context()), [], verifier.__name__)


if __name__ == "__main__":
    unittest.main()
