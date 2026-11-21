"""Facts produced by an agent looking at rendered score pages.

The agent is a producer, not a pass.  This module validates and merges its JSON so a visual claim
cannot enter the score without page/evidence fields.  It deliberately does not call a model or
render pages; `scripts/agent_facts.py` owns that workflow.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

CREDIT_TYPES = {"title", "subtitle", "composer", "arranger", "transcriber", "lyricist"}
MARK_KEYS = ("text", "rehearsal", "tempo", "metronome")
_CREDIT_PREFIXES = {
    "composer": (r"original\s+artist\s*:\s*", r"composer\s*:\s*", r"music\s+by\s*:?\s*"),
    "arranger": (r"arranged\s+by\s*:?\s*", r"arranger\s*:\s*"),
    "transcriber": (r"transcribed\s+by\s*:?\s*", r"transcriber\s*:\s*"),
}


def normalize_credit_text(credit_type: str, text: str) -> str:
    """Drop the printed role label from an agent's credit value.

    The page says ``Original Artist:TRUE``; the score credit should be ``TRUE``.  Keep the
    original label in ``evidence``, not in the score.
    """
    value = (text or "").strip()
    for pattern in _CREDIT_PREFIXES.get(credit_type, ()):
        value = re.sub(pattern, "", value, flags=re.IGNORECASE).strip()
    return value


def normalize_agent_facts(payload: dict) -> dict:
    """Normalize labels and legacy unresolved fields without inventing facts."""
    normalized = copy.deepcopy(payload)
    for credit in normalized.get("credits") or []:
        if isinstance(credit, dict) and isinstance(credit.get("text"), str):
            credit["text"] = normalize_credit_text(credit.get("type") or "", credit["text"])
    for item in normalized.get("unresolved") or []:
        if isinstance(item, dict) and not item.get("reason") and item.get("note"):
            item["reason"] = item["note"]
    return normalized


def load_agent_facts(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def validate_agent_facts(
    payload: dict,
    *,
    page_count: int | None = None,
    measure_count: int | None = None,
) -> list[str]:
    """Return human-readable problems for an agent-produced facts object.

    Evidence is required for visual facts: a page number plus either a PDF-coordinate bbox
    ``[x0, y0, x1, y1]`` or a crop path.  Confidence is optional but must be in [0, 1].
    """
    problems: list[str] = []
    if not isinstance(payload, dict):
        return ["facts must be a JSON object"]
    producer = payload.get("producer")
    if producer is not None and not isinstance(producer, dict):
        problems.append("producer must be an object")
    for field in ("credits", "marks", "unresolved", "corrections"):
        value = payload.get(field)
        if value is not None and not isinstance(value, list):
            problems.append(f"{field} must be an array")

    for index, credit in enumerate(payload.get("credits") or []):
        _common_evidence(credit, f"credits[{index}]", problems, page_count)
        credit_type = credit.get("type")
        if credit_type is not None and credit_type not in CREDIT_TYPES:
            problems.append(f"credits[{index}]: unknown type {credit_type!r}")
        if not isinstance(credit.get("text"), str) or not credit["text"].strip():
            problems.append(f"credits[{index}]: text must be a non-empty string")

    for index, mark in enumerate(payload.get("marks") or []):
        prefix = f"marks[{index}]"
        _common_evidence(mark, prefix, problems, page_count)
        if not isinstance(mark.get("measure"), int) or mark["measure"] < 1:
            problems.append(f"{prefix}: measure must be a positive integer")
        elif measure_count is not None and mark["measure"] > measure_count:
            problems.append(f"{prefix}: measure {mark['measure']} exceeds {measure_count}")
        if not any(mark.get(key) for key in MARK_KEYS):
            problems.append(f"{prefix}: empty mark (text/rehearsal/tempo/metronome)")
        if mark.get("placement") not in (None, "above", "below"):
            problems.append(f"{prefix}: placement must be above/below")
        beat = mark.get("beat")
        if beat is not None and (not isinstance(beat, (int, float)) or beat < 0):
            problems.append(f"{prefix}: beat must be a non-negative number")

    for index, correction in enumerate(payload.get("corrections") or []):
        prefix = f"corrections[{index}]"
        _common_evidence(correction, prefix, problems, page_count)
        if not isinstance(correction.get("measure"), int) or correction["measure"] < 1:
            problems.append(f"{prefix}: measure must be a positive integer")
        elif measure_count is not None and correction["measure"] > measure_count:
            problems.append(f"{prefix}: measure {correction['measure']} exceeds {measure_count}")
        old = correction.get("from")
        new = correction.get("to")
        if not isinstance(old, str) or not old.strip():
            problems.append(f"{prefix}: from must be a non-empty pitch")
        if not isinstance(new, str) or not new.strip():
            problems.append(f"{prefix}: to must be a non-empty pitch")
        if old and new and old.strip().upper() == new.strip().upper():
            problems.append(f"{prefix}: from and to are identical")
        if correction.get("status") not in (None, "proposed", "accepted", "rejected"):
            problems.append(f"{prefix}: status must be proposed/accepted/rejected")

    for index, item in enumerate(payload.get("unresolved") or []):
        prefix = f"unresolved[{index}]"
        if not isinstance(item, dict):
            problems.append(f"{prefix}: must be an object")
            continue
        if not item.get("reason"):
            if item.get("note"):
                item["reason"] = item["note"]
            else:
                problems.append(f"{prefix}: reason is required")
        if "page" in item and not isinstance(item["page"], int):
            problems.append(f"{prefix}: page must be an integer")
    return problems


def _common_evidence(item, prefix: str, problems: list[str], page_count: int | None) -> None:
    if not isinstance(item, dict):
        problems.append(f"{prefix}: must be an object")
        return
    page = item.get("page")
    if not isinstance(page, int) or page < 1:
        problems.append(f"{prefix}: page must be a positive integer")
    elif page_count is not None and page > page_count:
        problems.append(f"{prefix}: page {page} exceeds {page_count}")
    if not (item.get("evidence") or "").strip():
        problems.append(f"{prefix}: evidence is required")
    bbox = item.get("bbox")
    crop = item.get("crop")
    if bbox is not None:
        if (
            not isinstance(bbox, (list, tuple))
            or len(bbox) != 4
            or not all(isinstance(value, (int, float)) for value in bbox)
            or bbox[2] <= bbox[0]
            or bbox[3] <= bbox[1]
        ):
            problems.append(f"{prefix}: bbox must be [x0, y0, x1, y1]")
    elif not (isinstance(crop, str) and crop.strip()):
        problems.append(f"{prefix}: bbox or crop is required")
    confidence = item.get("confidence")
    if confidence is not None and (
        not isinstance(confidence, (int, float)) or not 0.0 <= float(confidence) <= 1.0
    ):
        problems.append(f"{prefix}: confidence must be between 0 and 1")


def merge_agent_facts(parts: list[dict]) -> dict:
    """Merge agent page/part outputs, preserving first evidence for duplicate claims."""
    merged = {
        "producer": {"name": "agent-visual", "pages": []},
        "credits": [],
        "marks": [],
        "unresolved": [],
        "corrections": [],
    }
    pages: set[int] = set()
    seen_credits: set[tuple] = set()
    seen_marks: set[tuple] = set()
    seen_corrections: set[tuple] = set()
    for part in parts:
        part = normalize_agent_facts(part)
        producer = part.get("producer") or {}
        for page in producer.get("pages") or []:
            if isinstance(page, int):
                pages.add(page)
        for credit in part.get("credits") or []:
            key = (credit.get("type"), (credit.get("text") or "").strip())
            if key in seen_credits:
                continue
            seen_credits.add(key)
            merged["credits"].append(credit)
        for mark in part.get("marks") or []:
            key = (
                mark.get("measure"),
                round(float(mark.get("beat") or 0), 4),
                (mark.get("text") or "").strip(),
                (mark.get("rehearsal") or "").strip(),
                mark.get("tempo"),
            )
            if key in seen_marks:
                continue
            seen_marks.add(key)
            merged["marks"].append(mark)
        for correction in part.get("corrections") or []:
            key = (
                correction.get("measure"),
                round(float(correction.get("beat") or 0), 4),
                correction.get("staff"),
                correction.get("voice"),
                (correction.get("from") or "").strip().upper(),
                (correction.get("to") or "").strip().upper(),
            )
            if key in seen_corrections:
                continue
            seen_corrections.add(key)
            merged["corrections"].append(correction)
        merged["unresolved"].extend(part.get("unresolved") or [])
    merged["producer"]["pages"] = sorted(pages)
    return merged
