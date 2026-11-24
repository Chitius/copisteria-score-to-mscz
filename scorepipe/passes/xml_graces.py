"""Normalize grace-note notation to the spelling MuseScore's MusicXML importer round-trips.

MuseScore 4.6 imports ``<grace/>`` + ``<type>eighth</type>`` as a *real* eighth note: the grace
becomes time in the bar.  On the Gurenge scan that lengthened m111 and m112 by half a beat each
(``mscx-measure-length``).  MuseScore's own MusicXML export writes every acciaccatura as a 16th
grace, so rewriting the type is the importer-compatible spelling rather than a rhythmic change:
a grace note has no ``<duration>`` and never advances the cursor.

``<dot>`` and ``<time-modification>`` inside a grace are dropped for the same reason: they make
the importer disagree with the grace value it can represent.
"""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.document import Document
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase

GRACE_TYPE = "16th"

# MusicXML orders <type> after these elements; MuseScore accepts a conventional order only.
_BEFORE_TYPE = ("grace", "chord", "pitch", "rest", "voice", "instrument")


class NormalizeGraceNotes:
    spec = PassSpec(
        name="normalize_grace_notes",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("grace-note-type",),
        description="write grace notes with MuseScore's own 16th grace value",
        measure="grace note type/dot/time-modification",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        changed = 0
        for _number, measure in doc.iter_measures():
            for note in measure.iter("note"):
                if note.find("grace") is None:
                    continue
                changed += _normalize(note)
        return PassResult(changed=changed)


def _normalize(note: ElementTree.Element) -> int:
    changed = 0
    for tag in ("dot", "time-modification"):
        for child in list(note.findall(tag)):
            note.remove(child)
            changed += 1
    type_node = note.find("type")
    if type_node is None:
        type_node = _insert_type(note)
        changed += 1
    if (type_node.text or "") != GRACE_TYPE:
        type_node.text = GRACE_TYPE
        changed += 1
    return changed


def _insert_type(note: ElementTree.Element) -> ElementTree.Element:
    children = list(note)
    position = 0
    for index, child in enumerate(children):
        if child.tag in _BEFORE_TYPE:
            position = index + 1
    element = ElementTree.Element("type")
    note.insert(position, element)
    return element


NORMALIZE_GRACES = NormalizeGraceNotes()
