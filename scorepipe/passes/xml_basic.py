"""Mechanical MusicXML passes: the first three, used to prove the runner."""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.document import Document
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase


class DedupeTies:
    spec = PassSpec(
        name="dedupe_ties",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("tie-elements",),
        description="one <tie>/<tied> per type per note; duplicates draw a second arc",
        measure="duplicate tie elements",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        changed = 0
        for _number, measure in doc.iter_measures():
            for note in measure.iter("note"):
                changed += _dedupe(note.findall("tie"), note)
                notations = note.find("notations")
                if notations is not None:
                    changed += _dedupe(notations.findall("tied"), notations)
        return PassResult(changed=changed)


def _dedupe(elements: list[ElementTree.Element], parent: ElementTree.Element) -> int:
    seen: set[str] = set()
    removed = 0
    for element in list(elements):
        kind = element.get("type") or ""
        if kind in seen:
            parent.remove(element)
            removed += 1
        else:
            seen.add(kind)
    return removed


class DropRedundantTimeSignatures:
    spec = PassSpec(
        name="drop_redundant_time_signatures",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("time-signatures",),
        description="remove a time signature that repeats the one already in force",
        measure="repeated identical time signatures",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        changed = 0
        current: tuple[float, float] | None = None
        for _number, measure in doc.iter_measures():
            signature = doc.time_signature(measure)
            if signature is None:
                continue
            if signature == current:
                for attributes in measure.findall("attributes"):
                    time = attributes.find("time")
                    if time is not None:
                        attributes.remove(time)
                        if len(attributes) == 0:
                            measure.remove(attributes)
                        changed += 1
                        break
                continue
            current = signature
        return PassResult(changed=changed)


class UnhideRests:
    spec = PassSpec(
        name="unhide_rests",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("rest-visibility",),
        description="a hidden rest is drawn grey in MuseScore; make it real notation",
        measure="hidden rests",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        changed = 0
        for _number, measure in doc.iter_measures():
            for note in measure.iter("note"):
                if note.find("rest") is None:
                    continue
                if note.get("print-object") == "no":
                    note.attrib.pop("print-object", None)
                    changed += 1
        return PassResult(changed=changed)


STRUCTURAL_PASSES = [DedupeTies(), DropRedundantTimeSignatures(), UnhideRests()]
