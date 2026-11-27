"""Measure counting, suspicion scoring, length violation lookup, and score title reading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence
from xml.etree import ElementTree

from ..confidence import summarise
from .models import CONTENT_HEADS


def page_measure_count(musicxml: Path) -> int:
    root = ElementTree.parse(str(musicxml)).getroot()
    part = root.find("part")
    return len(part.findall("measure")) if part is not None else 0


def score_measure_count(score_path: Path) -> int:
    """Total measures in a delivered ``.mscz`` or ``.musicxml`` score."""
    path = Path(score_path)
    if path.suffix.lower() == ".mscz":
        from ..core.mscz import MsczArchive

        archive = MsczArchive.open(path)
        staves = archive.document.staves()
        return len(staves[0].findall("Measure")) if staves else 0
    return page_measure_count(path)


def _dropped_trailing_measures(report_path: Path | None) -> int:
    if report_path is None or not Path(report_path).is_file():
        return 0
    try:
        data = json.loads(Path(report_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    return sum(
        int(entry.get("changed") or 0)
        for entry in data.get("trace") or []
        if entry.get("pass") == "drop_trailing_duplicate_measure"
    )


def reconcile_page_measure_counts(
    raw_counts: Sequence[int],
    delivered_total: int,
    report_path: Path | None = None,
) -> tuple[list[int] | None, list[str]]:
    """Map delivered measures onto the original scan pages.

    Normally the delivered score has the exact same measure count as the sum of the raw OMR pages.
    When ``drop_trailing_duplicate_measure`` removed trailing duplicate bar(s) on the last page,
    only the last page shrinks by that amount; any unexplained count difference is refused so page
    boundaries are never guessed silently.
    """
    counts = [int(count) for count in raw_counts]
    raw_total = sum(counts)
    if delivered_total == raw_total:
        return counts, []
    diff = raw_total - delivered_total
    if diff > 0 and counts:
        dropped = _dropped_trailing_measures(report_path)
        if dropped == diff and counts[-1] > diff:
            adjusted = list(counts)
            adjusted[-1] -= diff
            return adjusted, [
                f"pipeline removed {diff} trailing duplicate measure(s); "
                f"last page aligned to {adjusted[-1]} delivered measure(s)"
            ]
    return None, [
        f"delivered score has {delivered_total} measure(s) but raw OMR pages declare {raw_total}; "
        "cannot map scan page boundaries safely"
    ]


def measure_scores(
    reading: Path,
    systems: Sequence[tuple[int, int]],
    offsets: Sequence[int],
    *,
    origin: tuple[int, int] = (0, 0),
    system_counts: Sequence[int] | None = None,
) -> tuple[dict[int, dict], int]:
    """Page measure (1-based) -> score bucket, plus how many suspects could not be placed.

    A change record carries the symbol's ``staff`` and ``bar``, and ``bar`` is **system-local**
    (measured on the Schubert page: 0..8 across five systems), so the bar has to be placed in its
    system first -- by the symbol's own y -- and only then added to the measures of the systems
    above it.  A bar index past the end of its system means the geometry and the OMR disagree; such
    a symbol is counted as unplaced rather than tinting a neighbouring bar.

    Two scores are kept per measure.  ``score`` is every suspect symbol (it orders the written
    priority list).  ``content_score`` keeps only symbols whose doubt can change the *content* --
    class, position, accidental, tuplet, existence -- because ``voice``/``dots`` reassignments are
    routine and the reader is usually right: on a dense piano page they occur on nearly every
    eighth note and made 33 of 40 bars tint (First Step page 2).  The sheet tints by
    ``content_score``; the heat map still shows every routine symbol.
    """
    data = json.loads(Path(reading).read_text(encoding="utf-8"))
    tokens = data.get("tokens") or {}
    changes = {int(entry["sym"]): entry for entry in data.get("changes") or []}
    counts = list(system_counts) if system_counts is not None else None
    scores: dict[int, dict] = {}
    unplaced = 0
    origin_y = origin[1]
    for key, token in tokens.items():
        result = summarise(token)
        if result["score"] <= 0:
            continue
        change = changes.get(int(key))
        if change is None or change.get("bar") is None or not change.get("box"):
            unplaced += 1
            continue
        _, y0, _, y1 = change["box"]
        center_y = (y0 + y1) / 2 - origin_y
        system = next(
            (index for index, (top, bottom) in enumerate(systems) if top - 6 <= center_y <= bottom + 6),
            None,
        )
        if system is None:
            unplaced += 1
            continue
        bar = int(change["bar"])
        if counts is not None and bar >= counts[system]:
            unplaced += 1
            continue
        measure = offsets[system] + bar + 1
        bucket = scores.setdefault(
            measure,
            {"measure": measure, "score": 0.0, "symbols": 0, "values": [], "content": []},
        )
        bucket["values"].append(result["score"])
        bucket["symbols"] += 1
        if _content_change(result["reasons"]):
            bucket["content"].append(result["score"])
    for bucket in scores.values():
        bucket["score"] = _tier_score(bucket.pop("values"))
        bucket["content_score"] = _tier_score(bucket.pop("content"))
    return scores, unplaced


def _content_change(reasons: Sequence[dict]) -> bool:
    return any(reason.get("head") in CONTENT_HEADS for reason in reasons)


def _tier_score(values: Sequence[float]) -> float:
    """One strong symbol is the signal; a second one in the same bar only backs it up a little."""
    if not values:
        return 0.0
    ranked = sorted(values, reverse=True)
    return round(ranked[0] + (min(1.0, 0.4 * ranked[1]) if len(ranked) > 1 else 0.0), 3)


def length_measures(report_path: Path | None, offset: int, page_measures: int) -> list[int]:
    """Global measures with a measure-length violation that fall on this page."""
    if report_path is None or not Path(report_path).is_file():
        return []
    data = json.loads(Path(report_path).read_text(encoding="utf-8"))
    found = set()
    for violation in data.get("verifier") or []:
        if violation.get("code") not in ("measure-length", "mscx-measure-length"):
            continue
        measure = violation.get("measure")
        if not isinstance(measure, int):
            continue
        if 1 <= measure - offset <= page_measures:
            found.add(measure)
    return sorted(found)


def read_score_title(musicxml: Path | str | None) -> str | None:
    """The ``title`` credit of a MusicXML or ``.mscz`` score, if it has one."""
    if musicxml is None:
        return None
    path = Path(musicxml)
    if not path.is_file():
        return None
    if path.suffix.lower() == ".mscz":
        try:
            from ..core.mscz import MsczArchive

            root = MsczArchive.open(path).document.root
        except Exception:  # noqa: BLE001 - title lookup is best-effort
            return None
        for node in root.iter("Text"):
            if (node.findtext("style") or "").strip() != "title":
                continue
            text = node.find("text")
            if text is not None:
                value = "".join(text.itertext()).strip()
                if value:
                    return value
        return None
    try:
        root = ElementTree.parse(str(path)).getroot()
    except ElementTree.ParseError:
        return None
    for credit in root.findall("credit"):
        if (credit.findtext("credit-type") or "").strip() != "title":
            continue
        words = credit.find("credit-words")
        if words is not None and (words.text or "").strip():
            return words.text.strip()
    return None
