"""Compare an OMR/exported MusicXML with the OpenScore ground-truth score.

Both inputs may contain several parts (Lieder normally has a vocal part and a piano part).
Notes are matched as a multiset of (measure, onset, pitch, duration) inside each part, so voice
renumbering, chord layout and XML element order do not matter.  Rests are represented by a pitch of
``None``; they are counted separately from sounding notes.
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
    for measure in part.findall("measure"):
        number = int(measure.get("number") or 0)
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
        missing_total = sum(missing.values())
        extra_total = sum(extra.values())
        total = sum(expected.values())
        result["parts"][part_id] = {
            "notes": expected_notes,
            "rests": expected_rests,
            "candidate_notes": actual_notes,
            "candidate_rests": actual_rests,
            "missing": missing_total,
            "extra": extra_total,
            "match": round(1 - (missing_total + extra_total) / max(total, 1), 4),
            "missing_examples": [list(row) + [count] for row, count in missing.most_common(5)],
            "extra_examples": [list(row) + [count] for row, count in extra.most_common(5)],
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
