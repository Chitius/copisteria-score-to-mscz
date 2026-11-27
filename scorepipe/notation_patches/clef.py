"""Clef notation patch validation, application, verification, and inspection."""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.document import Document
from .common import CLEF_SIGNS, _positive_integer


def _validate_clef(patch: dict, doc: Document | None, prefix: str) -> list[str]:
    problems: list[str] = []
    if not _positive_integer(patch.get("measure")):
        problems.append(f"{prefix}: measure must be a positive integer")
    elif doc is not None and patch["measure"] > len(doc.measures()):
        problems.append(f"{prefix}: measure exceeds {len(doc.measures())}")
    if not _positive_integer(patch.get("staff")):
        problems.append(f"{prefix}: staff must be a positive integer")
    if patch.get("clef") not in CLEF_SIGNS:
        problems.append(f"{prefix}: clef must be one of G/F/C")
    if not _positive_integer(patch.get("line")) or patch["line"] > 5:
        problems.append(f"{prefix}: line must be 1..5")
    if patch.get("status") != "accepted":
        problems.append(f"{prefix}: status must be accepted")
    from_measure = patch.get("from_measure")
    if from_measure is not None:
        if not _positive_integer(from_measure):
            problems.append(f"{prefix}: from_measure must be a positive integer")
        elif doc is not None and from_measure > len(doc.measures()):
            problems.append(f"{prefix}: from_measure exceeds {len(doc.measures())}")
        elif from_measure == patch.get("measure"):
            problems.append(f"{prefix}: from_measure must differ from measure")
    if not _positive_integer(patch.get("page")):
        problems.append(f"{prefix}: page must be a positive integer")
    if not (patch.get("bbox") or patch.get("crop")):
        problems.append(f"{prefix}: bbox or crop evidence is required")
    if not isinstance(patch.get("evidence"), str) or not patch["evidence"]:
        problems.append(f"{prefix}: evidence is required")
    return problems


def _apply_clef(doc: Document, patch: dict) -> int:
    measures = doc.measures()
    staff = str(patch["staff"])
    changed = 0
    from_measure = patch.get("from_measure")
    if from_measure and 1 <= from_measure <= len(measures):
        # the source put the clef change on another measure; retire that copy first so the
        # redundant-clef pass does not have to guess which one is the real one
        changed += _remove_staff_clefs(measures[from_measure - 1], staff, sign=patch["clef"])
    target = measures[patch["measure"] - 1]
    sign = patch["clef"]
    line = str(patch["line"])
    existing = [clef for clef in target.iter("clef") if (clef.get("number") or "1") == staff]
    if existing:
        for clef in existing:
            if (clef.findtext("sign"), clef.findtext("line")) == (sign, line):
                continue
            for tag, value in (("sign", sign), ("line", line)):
                element = clef.find(tag)
                if element is None:
                    element = ElementTree.SubElement(clef, tag)
                element.text = value
            changed += 1
        return changed
    attributes = target.find("attributes")
    if attributes is None:
        attributes = ElementTree.Element("attributes")
        target.insert(0, attributes)
    clef = ElementTree.SubElement(attributes, "clef")
    if staff != "1":
        clef.set("number", staff)
    ElementTree.SubElement(clef, "sign").text = sign
    ElementTree.SubElement(clef, "line").text = line
    return changed + 1


def _verify_clef(doc: Document, patch: dict, prefix: str) -> list[str]:
    problems: list[str] = []
    clefs = list_clefs(doc)
    staff = str(patch.get("staff"))
    sign = patch.get("clef")
    line = str(patch.get("line"))
    if not any(
        clef["measure"] == patch.get("measure")
        and clef["staff"] == staff
        and clef["sign"] == sign
        and clef["line"] == line
        for clef in clefs
    ):
        problems.append(
            f"{prefix}: clef {sign}/{line} missing at measure {patch.get('measure')} staff {staff}"
        )
    from_measure = patch.get("from_measure")
    if from_measure and any(
        clef["measure"] == from_measure and clef["staff"] == staff and clef["sign"] == sign
        for clef in clefs
    ):
        problems.append(f"{prefix}: the superseded clef at measure {from_measure} is still present")
    return problems


def _remove_staff_clefs(measure, staff: str, sign: str | None = None) -> int:
    removed = 0
    for attributes in list(measure.findall("attributes")):
        for clef in list(attributes.findall("clef")):
            if (clef.get("number") or "1") != staff:
                continue
            if sign is not None and clef.findtext("sign") != sign:
                continue
            attributes.remove(clef)
            removed += 1
        if len(attributes) == 0:
            measure.remove(attributes)
    return removed


def list_clefs(doc: Document) -> list[dict]:
    """Read back the clefs so a review can compare them with the page."""
    result = []
    for number, measure in doc.iter_measures():
        for clef in measure.iter("clef"):
            result.append(
                {
                    "measure": number,
                    "staff": clef.get("number") or "1",
                    "sign": clef.findtext("sign"),
                    "line": clef.findtext("line"),
                }
            )
    return result
