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
    part_ids: list[str] = field(default_factory=list)

    def page_of_measure(self, measure_number: int) -> int:
        """1-based page for a global measure number (for page-level restoration passes)."""
        running = 0
        for page, count in enumerate(self.measure_counts, start=1):
            running += count
            if measure_number <= running:
                return page
        raise ValueError(f"measure {measure_number} is outside the merged score")


def _page_part_entries(
    page_root: ElementTree.Element, path: str | Path
) -> list[tuple[str, ElementTree.Element]]:
    parts = page_root.findall("part")
    if not parts:
        raise ValueError(f"{path}: page MusicXML has no <part>")
    entries: list[tuple[str, ElementTree.Element]] = []
    seen: set[str] = set()
    for index, part in enumerate(parts, start=1):
        part_id = part.get("id") or f"P{index}"
        if part_id in seen:
            raise ValueError(f"{path}: duplicate <part id={part_id!r}> in page MusicXML")
        seen.add(part_id)
        entries.append((part_id, part))
    return entries


def merge_pages(paths: list[str | Path]) -> MergedPages:
    if not paths:
        raise ValueError("merge_pages needs at least one page")
    roots = [ElementTree.parse(str(path)).getroot() for path in paths]
    first = roots[0]
    part_list = first.find("part-list")
    if part_list is None:
        raise ValueError("page MusicXML has no part-list")

    page_parts: list[list[tuple[str, ElementTree.Element]]] = []
    expected_part_ids: list[str] | None = None
    for path, page_root in zip(paths, roots):
        entries = _page_part_entries(page_root, path)
        part_ids = [part_id for part_id, _part in entries]
        if expected_part_ids is None:
            expected_part_ids = part_ids
        elif part_ids != expected_part_ids:
            raise ValueError(
                f"{path}: page parts {part_ids} do not match first page parts {expected_part_ids}"
            )
        counts = {part_id: len(part.findall("measure")) for part_id, part in entries}
        unique_counts = set(counts.values())
        if len(unique_counts) > 1:
            raise ValueError(
                f"{path}: parts disagree on measure count ({counts}); cannot align page safely"
            )
        page_parts.append(entries)

    assert expected_part_ids is not None
    divisions = _target_divisions(roots)
    root = ElementTree.Element("score-partwise", {"version": first.get("version") or "4.0"})
    root.append(ElementTree.fromstring(ElementTree.tostring(part_list)))
    merged_parts = {
        part_id: ElementTree.SubElement(root, "part", {"id": part_id})
        for part_id in expected_part_ids
    }

    measure_counts: list[int] = []
    running_number = 0
    for entries in page_parts:
        page_measure_count = len(entries[0][1].findall("measure"))
        for part_id, page_part in entries:
            measures = page_part.findall("measure")
            target_part = merged_parts[part_id]
            active = divisions
            for local_index, measure in enumerate(measures, start=1):
                declared = _declared_divisions(measure)
                if declared is not None:
                    active = declared
                copy = ElementTree.fromstring(ElementTree.tostring(measure))
                factor = divisions / active
                _rescale_measure(copy, factor)
                _set_divisions(copy, divisions)
                copy.set("number", str(running_number + local_index))
                target_part.append(copy)
        running_number += page_measure_count
        measure_counts.append(page_measure_count)
    if running_number == 0:
        raise ValueError("pages contain no measures")
    return MergedPages(
        document=Document(root),
        pages=[str(path) for path in paths],
        measure_counts=measure_counts,
        part_ids=expected_part_ids,
    )


def _target_divisions(roots: list[ElementTree.Element]) -> int:
    values: set[int] = set()
    for root in roots:
        for part in root.findall("part"):
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
