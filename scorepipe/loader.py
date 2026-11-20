"""Front-end loaders: turn page-level output into one score before the passes run.

copisteria writes one MusicXML per scanned page with per-page measure numbering. Merging them is
just concatenation plus renumbering; the structural passes (redundant time/clef/key, voice numbers,
barline repair) run afterwards and are idempotent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

from .core.document import Document


@dataclass
class MergedPages:
    document: Document
    pages: list[str] = field(default_factory=list)
    measure_counts: list[int] = field(default_factory=list)

    def page_of_measure(self, measure_number: int) -> int:
        """1-based page for a global measure number (for page-level restoration passes)."""
        running = 0
        for page, count in enumerate(self.measure_counts, start=1):
            running += count
            if measure_number <= running:
                return page
        raise ValueError(f"measure {measure_number} is outside the merged score")


def merge_pages(paths: list[str | Path]) -> MergedPages:
    if not paths:
        raise ValueError("merge_pages needs at least one page")
    first = ElementTree.parse(str(paths[0])).getroot()
    part_list = first.find("part-list")
    if part_list is None:
        raise ValueError("page MusicXML has no part-list")
    root = ElementTree.Element("score-partwise", {"version": first.get("version") or "4.0"})
    root.append(ElementTree.fromstring(ElementTree.tostring(part_list)))
    part = ElementTree.SubElement(root, "part", {"id": part_list.find("score-part").get("id") or "P1"})

    measure_counts: list[int] = []
    number = 0
    for path in paths:
        page_root = ElementTree.parse(str(path)).getroot()
        page_part = page_root.find("part")
        measures = [] if page_part is None else page_part.findall("measure")
        for measure in measures:
            number += 1
            copy = ElementTree.fromstring(ElementTree.tostring(measure))
            copy.set("number", str(number))
            part.append(copy)
        measure_counts.append(len(measures))
    if number == 0:
        raise ValueError("pages contain no measures")
    return MergedPages(
        document=Document(root),
        pages=[str(path) for path in paths],
        measure_counts=measure_counts,
    )


def load_pages(directory: str | Path, pattern: str = "*.musicxml") -> MergedPages:
    paths = sorted(Path(directory).glob(pattern))
    return merge_pages(paths)
