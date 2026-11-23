"""Agent-facing helpers for constrained notation patches.

`map` gives the agent a stable anchor list; `apply` validates and writes MusicXML. The scorepipe CLI
also accepts the same patch file with `--patches`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scorepipe.core.document import Document  # noqa: E402
from scorepipe.notation_patches import (  # noqa: E402
    apply_patches,
    load_patches,
    score_map,
    validate_patches,
)


def make_map(doc: Document) -> dict:
    return score_map(doc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Map/apply constrained notation patches")
    sub = parser.add_subparsers(dest="command", required=True)
    mapping = sub.add_parser("map", help="write note anchors for an agent")
    mapping.add_argument("--input", required=True)
    mapping.add_argument("-o", "--output", required=True)
    apply = sub.add_parser("apply", help="apply a patch file to MusicXML")
    apply.add_argument("--input", required=True)
    apply.add_argument("--patches", required=True)
    apply.add_argument("--dry-run", action="store_true", help="validate and report changes without writing")
    apply.add_argument("-o", "--output", required=True)
    accept = sub.add_parser("accept", help="promote proposed tuplet patches to accepted")
    accept.add_argument("--patches", required=True)
    accept.add_argument("--musicxml", required=True)
    accept.add_argument("--indices", nargs="+", type=int, required=True)
    accept.add_argument("--reviewer", required=True)
    accept.add_argument("-o", "--output", required=True)
    args = parser.parse_args(argv)

    if args.command == "accept":
        payload = load_patches(args.patches)
        patches = payload.get("patches") or []
        for index in args.indices:
            if not 0 <= index < len(patches):
                print(f"patch index out of range: {index}")
                return 1
            patch = patches[index]
            if patch.get("op") not in ("tuplet", "ottava"):
                print(f"patches[{index}] is not a tuplet/ottava patch")
                return 1
            patch["status"] = "accepted"
            patch["accepted_by"] = args.reviewer
        doc = Document.load(args.musicxml) if args.musicxml else None
        problems = validate_patches(payload, doc, require_acceptance=True)
        if problems:
            for problem in problems:
                print(problem)
            return 1
        Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {args.output}")
        return 0

    if args.command == "map":
        doc = Document.load(args.input)
        payload = make_map(doc)
        Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {args.output}")
        return 0

    doc = Document.load(args.input)
    payload = load_patches(args.patches)
    problems = validate_patches(payload, doc, require_acceptance=True)
    if problems:
        for problem in problems:
            print(problem)
        return 1
    if args.dry_run:
        preview = Document(ElementTree.fromstring(ElementTree.tostring(doc.root)))
        changed = apply_patches(preview, payload)
        print(f"dry-run: {changed} patch change(s); {args.output} not written")
        return 0
    changed = apply_patches(doc, payload)
    doc.save(args.output)
    print(f"wrote {args.output} ({changed} patch changes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
