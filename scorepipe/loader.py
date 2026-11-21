"""Front-end loaders: turn page-level output into one score before the passes run.

copisteria writes one MusicXML per scanned page with per-page measure numbering and possibly a
page-local ``<divisions>`` resolution. Merging rescales all durations to one common divisions
(the LCM), renumbers measures globally, and leaves the structural passes to clean the join.
"""

from __future__ import annotations

import math
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
    roots = [ElementTree.parse(str(path)).getroot() for path in paths]
    first = roots[0]
    part_list = first.find("part-list")
    if part_list is None:
        raise ValueError("page MusicXML has no part-list")
    divisions = _target_divisions(roots)
    root = ElementTree.Element("score-partwise", {"version": first.get("version") or "4.0"})
    root.append(ElementTree.fromstring(ElementTree.tostring(part_list)))
    part = ElementTree.SubElement(root, "part", {"id": part_list.find("score-part").get("id") or "P1"})

    measure_counts: list[int] = []
    number = 0
    for page_root in roots:
        page_part = page_root.find("part")
        measures = [] if page_part is None else page_part.findall("measure")
        active = divisions
        for measure in measures:
            number += 1
            declared = _declared_divisions(measure)
            if declared is not None:
                active = declared
            copy = ElementTree.fromstring(ElementTree.tostring(measure))
            factor = divisions / active
            _rescale_measure(copy, factor)
            _set_divisions(copy, divisions)
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


def _target_divisions(roots: list[ElementTree.Element]) -> int:
    values: set[int] = set()
    for root in roots:
        part = root.find("part")
        if part is None:
            continue
        active = None
        for measure in part.findall("measure"):
            declared = _declared_divisions(measure)
            if declared is not None:
                active = declared
            if active is not None:
                values.add(active)
    if not values:
        return 4
    target = 1
    for value in sorted(values):
        target = math.lcm(target, value)
    return target


def _declared_divisions(measure) -> int | None:
    text = measure.findtext("attributes/divisions")
    if text is None:
        return None
    try:
        value = int(text)
    except ValueError:
        return None
    return value if value > 0 else None


def _rescale_measure(measure, factor: float) -> None:
    if abs(factor - 1.0) < 1e-9:
        return
    for duration in measure.iter("duration"):
        if duration.text:
            duration.text = str(int(round(int(duration.text) * factor)))
    for offset in measure.iter("offset"):
        if offset.text:
            offset.text = str(int(round(int(offset.text) * factor)))


def _set_divisions(measure, divisions: int) -> None:
    attributes = measure.find("attributes")
    if attributes is None:
        attributes = ElementTree.Element("attributes")
        measure.insert(0, attributes)
    element = attributes.find("divisions")
    if element is None:
        element = ElementTree.SubElement(attributes, "divisions")
        element.text = str(divisions)
    else:
        element.text = str(divisions)


def load_pages(directory: str | Path, pattern: str = "*.musicxml") -> MergedPages:
    paths = sorted(Path(directory).glob(pattern))
    return merge_pages(paths)
