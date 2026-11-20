"""Display-layer duplicates: identical pedal spanners and identical text objects."""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.mscx import MsxcDocument
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase


class DedupePedalSpanners:
    spec = PassSpec(
        name="dedupe_pedal_spanners",
        phase=Phase.DISPLAY,
        kind=Kind.MECHANICAL,
        owns=("pedal-spanners",),
        description="remove byte-identical pedal spanners inside one voice",
        measure="duplicate pedal spanners",
    )

    def run(self, doc: MsxcDocument, ctx: Context) -> PassResult:
        removed = 0
        for _staff, _index, measure in doc.iter_measures():
            for voice in doc.voices(measure):
                seen: set[str] = set()
                for child in list(voice):
                    if child.tag != "Spanner" or child.get("type") != "Pedal":
                        continue
                    signature = _signature(child)
                    if signature in seen:
                        voice.remove(child)
                        removed += 1
                    else:
                        seen.add(signature)
        return PassResult(changed=removed)


class DedupeTextObjects:
    spec = PassSpec(
        name="dedupe_text_objects",
        phase=Phase.DISPLAY,
        kind=Kind.MECHANICAL,
        owns=("display-text-duplicates",),
        description="remove a second text object with the same words in the same measure",
        measure="duplicate text objects in a measure",
    )

    def run(self, doc: MsxcDocument, ctx: Context) -> PassResult:
        text_tags = {"StaffText", "SystemText", "Expression", "Tempo"}
        removed = 0
        for _staff, _index, measure in doc.iter_measures():
            seen: set[str] = set()
            for voice in doc.voices(measure):
                for child in list(voice):
                    if child.tag not in text_tags:
                        continue
                    text = (child.findtext("text") or "").strip()
                    if not text:
                        continue
                    signature = (child.tag, text)
                    if signature in seen:
                        voice.remove(child)
                        removed += 1
                    else:
                        seen.add(signature)
        return PassResult(changed=removed)


DISPLAY_DEDUPE_PASSES = [DedupePedalSpanners(), DedupeTextObjects()]


def _signature(element) -> tuple:
    """Structure + attributes + text, ignoring tail whitespace."""
    return (
        element.tag,
        tuple(sorted(element.attrib.items())),
        (element.text or "").strip(),
        tuple(_signature(child) for child in element),
    )
