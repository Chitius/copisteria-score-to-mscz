from __future__ import annotations

import unittest
from xml.etree import ElementTree

from scorepipe.core.document import Document
from scorepipe.core.pass_base import Context
from scorepipe.passes.xml_slur_chains import MergeAdjacentSlurs

PART = """
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>t</part-name></score-part></part-list>
  <part id="P1">{measures}</part>
</score-partwise>
"""


def note(step, *, slurs=(), voice="1"):
    tags = "".join(f'<slur type="{kind}" number="{number}"/>' for kind, number in slurs)
    notations = f"<notations>{tags}</notations>" if tags else ""
    return (
        f"<note><pitch><step>{step}</step><octave>4</octave></pitch>"
        f"<duration>16</duration><voice>{voice}</voice>{notations}</note>"
    )


def measure(number, body):
    return (
        f'<measure number="{number}"><attributes><divisions>4</divisions>'
        "<time><beats>4</beats><beat-type>4</beat-type></time></attributes>"
        f"{body}</measure>"
    )


def build(body):
    return Document(ElementTree.fromstring(PART.format(measures=body)))


def slurs(doc):
    return [slur for _number, measure in doc.iter_measures() for slur in measure.iter("slur")]


class MergeAdjacentSlursTest(unittest.TestCase):
    def test_two_slurs_meeting_on_one_note_become_one(self):
        doc = build(
            measure(1, note("G", slurs=[("start", "1")]))
            + measure(2, note("A", slurs=[("stop", "1"), ("start", "2")]))
            + measure(3, note("E", slurs=[("stop", "2")]))
        )
        result = MergeAdjacentSlurs().run(doc, Context())
        self.assertEqual(result.changed, 1)
        remaining = slurs(doc)
        self.assertEqual(len(remaining), 2)
        self.assertEqual(remaining[0].get("type"), "start")
        self.assertEqual(remaining[1].get("type"), "stop")
        self.assertEqual(MergeAdjacentSlurs().run(doc, Context()).changed, 0)

    def test_a_note_with_two_starts_is_not_merged(self):
        doc = build(
            measure(1, note("G", slurs=[("start", "1")]))
            + measure(2, note("A", slurs=[("stop", "1"), ("start", "2"), ("start", "3")]))
            + measure(3, note("E", slurs=[("stop", "2")]))
        )
        self.assertEqual(MergeAdjacentSlurs().run(doc, Context()).changed, 0)


if __name__ == "__main__":
    unittest.main()
