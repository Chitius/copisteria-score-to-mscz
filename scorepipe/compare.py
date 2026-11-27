"""Compare two MusicXML files as symbol streams, normalised to beats.

This is the objective quality metric used when a golden score (old skill output or a hand-corrected
score) exists: every note/rest is reduced to (measure, staff, onset, duration, pitch), independent of
divisions and voice layout, and the difference is reported per measure.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from xml.etree import ElementTree


def _events(path: str | Path) -> list[dict]:
    root = ElementTree.parse(str(path)).getroot()
    fallback_divisions = float(root.findtext(".//divisions") or 10080)
    rows: list[dict] = []
    for index, part in enumerate(root.findall("part"), start=1):
        part_id = part.get("id") or f"P{index}"
        divisions = float(part.findtext(".//divisions") or fallback_divisions)
        for measure in part.findall("measure"):
            declared = measure.findtext("attributes/divisions")
            if declared:
                try:
                    value = float(declared)
                except ValueError:
                    value = 0.0
                if value > 0:
                    divisions = value
            cursor = 0
            previous_start = None
            for item in measure:
                if item.tag in ("backup", "forward"):
                    value = int(item.findtext("duration") or 0)
                    cursor += -value if item.tag == "backup" else value
                    previous_start = None
                    continue
                if item.tag != "note":
                    previous_start = None
                    continue
                duration = int(item.findtext("duration") or 0)
                chord = item.find("chord") is not None
                start = previous_start if chord and previous_start is not None else cursor
                if not chord:
                    cursor += duration
                    previous_start = start
                pitch = item.findtext("pitch/step")
                octave = item.findtext("pitch/octave") or ""
                alter = item.findtext("pitch/alter")
                if pitch is not None:
                    name = f"{pitch}{_alter(alter)}{octave}"
                elif item.find("unpitched") is not None:
                    name = (
                        "unpitched:"
                        + (item.findtext("unpitched/display-step") or "")
                        + (item.findtext("unpitched/display-octave") or "")
                    )
                else:
                    name = "rest"
                rows.append(
                    {
                        "part": part_id,
                        "measure": str(measure.get("number")),
                        "staff": item.findtext("staff") or "1",
                        "onset": round(start / divisions, 4),
                        "duration": round(duration / divisions, 4),
                        "pitch": name,
                    }
                )
    return rows


def _alter(text: str | None) -> str:
    if not text:
        return ""
    value = float(text)
    return "" if value == 0 else (f"{value:+g}")


def _counter(rows: list[dict]) -> Counter:
    return Counter(
        (row["part"], row["measure"], row["staff"], row["onset"], row["duration"], row["pitch"])
        for row in rows
    )


def compare(golden: str | Path, candidate: str | Path) -> dict:
    gold = _counter(_events(golden))
    cand = _counter(_events(candidate))
    missing = gold - cand
    extra = cand - gold
    total = sum(gold.values()) + sum(cand.values())
    ratio = (sum(missing.values()) + sum(extra.values())) / total if total else 0.0
    return {
        "golden": str(golden),
        "candidate": str(candidate),
        "golden_symbols": sum(gold.values()),
        "candidate_symbols": sum(cand.values()),
        "missing": sum(missing.values()),
        "extra": sum(extra.values()),
        "ratio": round(ratio, 4),
        "missing_by_measure": Counter(key[1] for key in missing.elements()).most_common(10),
        "extra_by_measure": Counter(key[1] for key in extra.elements()).most_common(10),
        "sample_missing": [list(key) for key in list(missing.elements())[:10]],
        "sample_extra": [list(key) for key in list(extra.elements())[:10]],
    }
