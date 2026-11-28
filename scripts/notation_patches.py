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

from scorepipe.console import harden_stdout  # noqa: E402
from scorepipe.core.document import Document  # noqa: E402
from scorepipe.corrections import (  # noqa: E402
    apply_corrections,
    load_corrections,
    save_corrections,
    validate_corrections,
    verify_corrections,
)
from scorepipe.notation_patches import (  # noqa: E402
    apply_patches,
    load_patches,
    score_map,
    validate_patches,
    verify_patches,
)

harden_stdout()


def make_map(doc: Document) -> dict:
    return score_map(doc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Map/apply constrained notation patches and corrections")
    sub = parser.add_subparsers(dest="command", required=True)
    mapping = sub.add_parser("map", help="write note anchors for an agent")
    mapping.add_argument("--input", required=True)
    mapping.add_argument("-o", "--output", required=True)
    apply = sub.add_parser("apply", help="apply a patch or corrections file to MusicXML")
    apply.add_argument("--input", required=True)
    apply_group = apply.add_mutually_exclusive_group(required=True)
    apply_group.add_argument("--patches", help="notation patches JSON")
    apply_group.add_argument("--corrections", help="facts.json or corrections JSON")
    apply.add_argument("--dry-run", action="store_true", help="validate and report changes without writing")
    apply.add_argument("-o", "--output", required=True)
    accept = sub.add_parser("accept", help="promote proposed patches or corrections to accepted")
    accept_group = accept.add_mutually_exclusive_group(required=True)
    accept_group.add_argument("--patches", help="notation patches JSON")
    accept_group.add_argument("--corrections", help="facts.json or corrections JSON")
    accept.add_argument("--musicxml", required=True)
    accept.add_argument("--indices", nargs="+", type=int, required=True)
    accept.add_argument("--reviewer", required=True)
    accept.add_argument("-o", "--output", required=True)
    args = parser.parse_args(argv)

    if args.command == "accept":
        doc = Document.load(args.musicxml) if args.musicxml else None
        if args.corrections:
            items, envelope = load_corrections(args.corrections)
            for index in args.indices:
                if not 0 <= index < len(items):
                    print(f"correction index out of range: {index}")
                    return 1
                items[index]["status"] = "accepted"
                items[index]["accepted_by"] = args.reviewer
            accepted_subset = [items[index] for index in args.indices]
            problems = validate_corrections(accepted_subset, doc, require_acceptance=True)
            if problems:
                for problem in problems:
                    print(problem)
                return 1
            save_corrections(args.output, items, envelope)
            print(f"wrote {args.output}")
            return 0
        payload = load_patches(args.patches)
        patches = payload.get("patches") or []
        for index in args.indices:
            if not 0 <= index < len(patches):
                print(f"patch index out of range: {index}")
                return 1
            patch = patches[index]
            if patch.get("op") not in ("tuplet", "ottava", "clef", "pedal", "wedge", "dynamic"):
                print(f"patches[{index}] has unsupported op {patch.get('op')!r}")
                return 1
            patch["status"] = "accepted"
            patch["accepted_by"] = args.reviewer
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
    if args.corrections:
        items, _envelope = load_corrections(args.corrections)
        accepted = [item for item in items if item.get("status") == "accepted"]
        problems = validate_corrections(accepted, doc, require_acceptance=True)
        if problems:
            for problem in problems:
                print(problem)
            return 1
        target = (
            Document(ElementTree.fromstring(ElementTree.tostring(doc.root)))
            if args.dry_run
            else doc
        )
        changed = apply_corrections(target, accepted)
        verify_problems = verify_corrections(target, accepted)
        if verify_problems:
            for problem in verify_problems:
                print(problem)
            return 1
        if args.dry_run:
            print(f"dry-run: {changed} correction(s); {args.output} not written")
            return 0
        target.save(args.output)
        print(f"wrote {args.output} ({changed} correction(s))")
        return 0

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
    verify_problems = verify_patches(doc, payload)
    if verify_problems:
        for problem in verify_problems:
            print(problem)
        return 1
    doc.save(args.output)
    print(f"wrote {args.output} ({changed} patch changes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
