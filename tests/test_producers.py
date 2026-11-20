from __future__ import annotations

import unittest
from pathlib import Path

from scorepipe.producers import CompositeProducer, JsonProducer, TextLayerProducer, resolve

WORK = Path(__file__).parent / ".runs" / "producers"


class ProducerTest(unittest.TestCase):
    def setUp(self):
        WORK.mkdir(parents=True, exist_ok=True)

    def test_json_producer(self):
        path = WORK / "marks.json"
        path.write_text('{"marks":[{"measure":1,"text":"Tempo rubato"}]}', encoding="utf-8-sig")
        result = JsonProducer(path).produce(Path("unused.musicxml"))
        self.assertEqual(len(result.marks), 1)
        self.assertEqual(result.marks[0]["text"], "Tempo rubato")

    def test_text_layer_producer(self):
        path = WORK / "marks.txt"
        path.write_text(
            "# measure\tbeat\tplacement\ttext\n"
            "9\t0\tabove\tAllegro\n"
            "55\t3\tabove\trit.\n",
            encoding="utf-8",
        )
        result = TextLayerProducer(path).produce(Path("unused.musicxml"))
        self.assertEqual([mark["text"] for mark in result.marks], ["Allegro", "rit."])
        self.assertEqual(result.marks[1]["beat"], 3.0)

    def test_composite_merges_sources(self):
        first = WORK / "a.json"
        second = WORK / "b.json"
        first.write_text('{"marks":[{"measure":1,"text":"one"}]}', encoding="utf-8")
        second.write_text('{"marks":[{"measure":2,"text":"two"}]}', encoding="utf-8")
        result = CompositeProducer([JsonProducer(first), JsonProducer(second)]).produce(Path("x"))
        self.assertEqual([mark["text"] for mark in result.marks], ["one", "two"])

    def test_resolve_by_suffix(self):
        self.assertIsInstance(resolve(WORK / "x.txt"), TextLayerProducer)
        self.assertIsInstance(resolve(WORK / "x.json"), JsonProducer)
        self.assertIsNone(resolve(None))


if __name__ == "__main__":
    unittest.main()
