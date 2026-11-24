"""Clefs and key signatures that merely restate the one already in force."""

from __future__ import annotations

from ..core.document import Document
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase


class DropRedundantClefs:
    spec = PassSpec(
        name="drop_redundant_clefs",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("clefs",),
        description="remove a clef that repeats the clef already in force on that staff",
        measure="repeated identical clefs",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        return _drop_repeated(
            doc,
            tag="clef",
            identity=lambda element: (
                element.findtext("sign"),
                element.findtext("line"),
                element.findtext("clef-octave-change"),
            ),
        )


class DropRedundantKeySignatures:
    spec = PassSpec(
        name="drop_redundant_key_signatures",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("key-signatures",),
        description="remove a key signature that repeats the one already in force",
        measure="repeated identical key signatures",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        return _drop_repeated(
            doc,
            tag="key",
            identity=lambda element: (element.findtext("fifths"), element.findtext("mode")),
        )


def _drop_repeated(doc: Document, tag: str, identity) -> PassResult:
    current: dict[str, tuple] = {}
    changed = 0
    for _number, measure in doc.iter_measures():
        for attributes in list(measure.findall("attributes")):
            for element in list(attributes.findall(tag)):
                # MusicXML puts the staff on the clef (<clef number="2">), not on <attributes>
                staff = element.get("number") or attributes.findtext("staff") or "1"
                signature = identity(element)
                if signature == current.get(staff):
                    attributes.remove(element)
                    changed += 1
                    if len(attributes) == 0:
                        measure.remove(attributes)
                    continue
                current[staff] = signature
    return PassResult(changed=changed)


DROP_REDUNDANT_CLEFS = DropRedundantClefs()
DROP_REDUNDANT_KEYS = DropRedundantKeySignatures()
