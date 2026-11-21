"""Compare an OMR/exported MusicXML with the OpenScore ground-truth score.

Both inputs may contain several parts (Lieder normally has a vocal part and a piano part).
The primary score matches sounding notes as a multiset of (measure ordinal, onset, pitch, duration)
inside each part, so voice renumbering, chord layout and XML element order do not matter.  Rests
(``<rest>``, pitch ``None``) are reported separately as ``rest_missing`` / ``rest_extra`` but are not
part of ``match``: secondary-voice rests can be intentionally hidden by the display layer, so a
rest-only difference is not a visible notation error.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree

PITCH = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def part_events(part) -> tuple[Counter, int, int]:
    """Return (event multiset, sounding notes, rests) for one part."""
    events: Counter = Counter()
    sounding = 0
    rests = 0
    divisions = 4
    for ordinal, measure in enumerate(part.findall("measure"), start=1):
        number = ordinal
        declared = measure.findtext("attributes/divisions")
        if declared:
            divisions = int(declared)
        cursor = 0
        last_onset = None
        for child in measure:
            if child.tag == "backup":
                cursor -= int(child.findtext("duration") or 0)
            elif child.tag == "forward":
                cursor += int(child.findtext("duration") or 0)
            elif child.tag == "note":
                duration = int(child.findtext("duration") or 0)
                if child.find("chord") is not None:
                    onset = last_onset if last_onset is not None else cursor
                else:
                    onset = cursor
                    cursor += duration
                last_onset = onset
                step = child.findtext("pitch/step")
                octave = child.findtext("pitch/octave")
                if step and octave:
                    alter = int(child.findtext("pitch/alter") or 0)
                    pitch = (PITCH[step] + alter) + 12 * (int(octave) + 1)
                    sounding += 1
                else:
                    pitch = None
                    rests += 1
                events[(number, round(onset / divisions, 4), pitch, round(duration / divisions, 4))] += 1
    return events, sounding, rests


def compare(ground_truth: Path, candidate: Path) -> dict:
    gt_root = ElementTree.parse(ground_truth).getroot()
    candidate_root = ElementTree.parse(candidate).getroot()
    gt_parts = {part.get("id"): part for part in gt_root.findall("part")}
    candidate_parts = {part.get("id"): part for part in candidate_root.findall("part")}
    result = {"ground_truth": str(ground_truth), "candidate": str(candidate), "parts": {}}
    for part_id in sorted(gt_parts):
        if part_id not in candidate_parts:
            result["parts"][part_id] = {"error": "missing part"}
            continue
        expected, expected_notes, expected_rests = part_events(gt_parts[part_id])
        actual, actual_notes, actual_rests = part_events(candidate_parts[part_id])
        missing = expected - actual
        extra = actual - expected
        overall_missing = sum(missing.values())
        overall_extra = sum(extra.values())
        overall_total = sum(expected.values())
        sounding_expected = Counter({row: count for row, count in expected.items() if row[2] is not None})
        sounding_actual = Counter({row: count for row, count in actual.items() if row[2] is not None})
        sounding_missing = sounding_expected - sounding_actual
        sounding_extra = sounding_actual - sounding_expected
        sounding_missing_total = sum(sounding_missing.values())
        sounding_extra_total = sum(sounding_extra.values())
        sounding_total = sum(sounding_expected.values())
        rest_expected = Counter({row: count for row, count in expected.items() if row[2] is None})
        rest_actual = Counter({row: count for row, count in actual.items() if row[2] is None})
        rest_missing = rest_expected - rest_actual
        rest_extra = rest_actual - rest_expected
        result["parts"][part_id] = {
            "notes": expected_notes,
            "rests": expected_rests,
            "candidate_notes": actual_notes,
            "candidate_rests": actual_rests,
            "missing": sounding_missing_total,
            "extra": sounding_extra_total,
            "match": round(
                1 - (sounding_missing_total + sounding_extra_total) / max(sounding_total, 1), 4
            ),
            "overall_missing": overall_missing,
            "overall_extra": overall_extra,
            "overall_match": round(
                1 - (overall_missing + overall_extra) / max(overall_total, 1), 4
            ),
            "rest_missing": sum(rest_missing.values()),
            "rest_extra": sum(rest_extra.values()),
            "rest_missing_examples": [
                list(row) + [count] for row, count in rest_missing.most_common(5)
            ],
            "rest_extra_examples": [list(row) + [count] for row, count in rest_extra.most_common(5)],
            "missing_examples": [
                list(row) + [count] for row, count in sounding_missing.most_common(5)
            ],
            "extra_examples": [list(row) + [count] for row, count in sounding_extra.most_common(5)],
        }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("ground_truth", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    result = compare(args.ground_truth, args.candidate)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.json:
        args.json.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
