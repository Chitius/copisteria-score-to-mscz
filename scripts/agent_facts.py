"""Agent visual-facts workflow: prepare page images, validate claims, merge page outputs.

The model is intentionally outside this script.  It inspects the prepared page images and writes
one JSON file per page (or a combined file); this tool only makes the packet and checks the
evidence, so no visual claim can reach the score without a page/evidence trail.
"""

from __future__ import annotations

import argparse
import glob
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scorepipe.agent_facts import (  # noqa: E402
    load_agent_facts,
    merge_agent_facts,
    normalize_agent_facts,
    validate_agent_facts,
)


def _pdf_pages(pdf: Path) -> int | None:
    binary = shutil.which("pdfinfo")
    if not binary:
        return None
    completed = subprocess.run(
        [binary, str(pdf)], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    for line in completed.stdout.splitlines():
        if line.lower().startswith("pages:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError:
                return None
    return None


def _render(pdf: Path, outdir: Path, dpi: int) -> list[Path]:
    binary = shutil.which("pdftoppm")
    if not binary:
        raise RuntimeError("pdftoppm not found; install poppler or pass --images")
    outdir.mkdir(parents=True, exist_ok=True)
    prefix = outdir / "page"
    completed = subprocess.run(
        [binary, "-png", "-r", str(dpi), str(pdf), str(prefix)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"pdftoppm failed: {(completed.stderr or '').strip()[:500]}")
    return sorted(outdir.glob("page-*.png"))


def _instructions(payload: dict) -> str:
    images = "\n".join(f"- `{image['path']}` (page {image['page']})" for image in payload["images"])
    return f"""# Agent visual facts packet

你正在校对一份 OMR 乐谱的**原始 PDF 页面**。不要根据音乐常识猜测；只记录页面上确实看得见的内容。

## 输入

{images}

## 输出

写一个 JSON 文件，结构如下（只写你确认的事实；不确定的放入 `unresolved`）：

```json
{{
  "producer": {{"name": "agent-visual", "pages": [1]}},
  "credits": [
    {{"type": "title", "text": "Title", "page": 1, "bbox": [x0, y0, x1, y1],
     "evidence": "top centre title", "confidence": 0.98}}
  ],
  "marks": [
    {{"measure": 1, "beat": 0, "placement": "above", "text": "q = 72", "tempo": 72,
     "page": 1, "bbox": [x0, y0, x1, y1], "evidence": "tempo at top left", "confidence": 0.95}}
  ],
  "unresolved": [
    {{"page": 1, "measure": 3, "reason": "text is clipped; cannot decide whether it is a tempo term"}}
  ],
  "corrections": [
    {{"measure": 30, "beat": 3.5, "staff": 1, "from": "C8", "to": "C7",
     "page": 1, "bbox": [x0, y0, x1, y1], "evidence": "ledger-line octave looks one too high",
     "confidence": 0.4, "status": "proposed"}}
  ]
}}
```

要求：

- 每个 credit/mark/correction 必须有 `page`、`evidence`，以及 PDF 坐标 `bbox` 或裁图 `crop`；
- `confidence` 是 0–1 的小数；
- `measure` 从 1 开始，`beat` 从 0 开始；
- `rit.`/`rall.`/`accel.`/`string.`/`allarg.` 这类渐慢/渐快术语，除 `text` 外必须加
  `"gradual": "ritardando" | "rallentando" | "accelerando" | "stringendo" | "allargando"`，
  否则只会被注入成纯文字 `StaffText`，不会变成真正的 `GradualTempoChange` 连线；
  跨度用 `length_measures`（默认 1）/ `length_fractions` 指定；
- 不存在的标记不要编造；看不清就放 `unresolved`；
- 音高疑点只能放 `corrections`，不要写进 `marks`；默认 `status="proposed"`，不要自行声称已批准；
- 每一页都要在 `producer.pages` 中声明；`merge --pages N` 默认要求全部页覆盖。

## 命令

```bash
python scripts/agent_facts.py validate --facts agent-page01.json --pages {payload['page_count']}
python scripts/agent_facts.py merge --parts agent-page*.json -o facts.json
python scripts/convert.py score.pdf --pages path/to/omr-pages --facts facts.json
```
"""


def prepare(args: argparse.Namespace) -> int:
    pdf = Path(args.pdf).resolve()
    outdir = Path(args.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    if args.images:
        source = Path(args.images).resolve()
        images = sorted(source.glob("*.png"))
        if not images:
            raise RuntimeError(f"no PNG images in {source}")
        page_count = len(images)
    else:
        if not pdf.is_file():
            raise RuntimeError(f"PDF not found: {pdf}")
        page_count = _pdf_pages(pdf) or 0
        images = _render(pdf, outdir, args.dpi)
    if not images:
        raise RuntimeError("no page images were produced")
    payload = {
        "source": str(pdf),
        "page_count": len(images),
        "images": [
            {"page": index, "path": str(image)}
            for index, image in enumerate(images, start=1)
        ],
    }
    (outdir / "manifest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (outdir / "instructions.md").write_text(_instructions(payload), encoding="utf-8")
    print(f"prepared {len(images)} page image(s) in {outdir}")
    print(f"instructions: {outdir / 'instructions.md'}")
    return 0 if page_count == 0 or len(images) == page_count else 1


def validate(args: argparse.Namespace) -> int:
    payload = load_agent_facts(args.facts)
    problems = validate_agent_facts(
        payload, page_count=args.pages, measure_count=args.measures
    )
    for problem in problems:
        print(problem)
    print(f"agent facts: {len(payload.get('credits') or [])} credits, "
          f"{len(payload.get('marks') or [])} marks, "
          f"{len(payload.get('corrections') or [])} corrections, "
          f"{len(payload.get('unresolved') or [])} unresolved")
    return 0 if not problems else 1


def expand_parts(values: list[str]) -> tuple[list[Path], list[str]]:
    """Expand a directory or a shell-style pattern; PowerShell does not expand globs itself.

    The documented call is ``merge --parts review/facts/agent-page*.json``.  On Windows the
    literal pattern reaches argparse, so a plain ``Path`` would fail with "file not found".
    A directory is accepted too because that is what the review workflow already has.
    """
    expanded: list[Path] = []
    unmatched: list[str] = []
    for value in values:
        path = Path(value)
        if path.is_dir():
            found = sorted(path.glob("agent-page*.json")) or sorted(path.glob("*.json"))
            if found:
                expanded.extend(found)
            else:
                unmatched.append(value)
        elif any(token in value for token in "*?["):
            matches = sorted(Path(match) for match in glob.glob(value))
            if matches:
                expanded.extend(matches)
            else:
                unmatched.append(value)
        else:
            expanded.append(path)
    unique: list[Path] = []
    for path in expanded:
        if path not in unique:
            unique.append(path)
    return unique, unmatched


def merge(args: argparse.Namespace) -> int:
    if args.pages is None and not args.allow_missing_pages:
        print("merge requires --pages N unless --allow-missing-pages is explicit")
        return 1
    paths, unmatched = expand_parts(args.parts)
    if unmatched:
        for value in unmatched:
            print(f"no file matched: {value}")
        return 1
    if not paths:
        print("no agent page files to merge")
        return 1
    parts = []
    for path in paths:
        payload = normalize_agent_facts(load_agent_facts(path))
        problems = validate_agent_facts(payload, page_count=args.pages, measure_count=args.measures)
        if problems:
            for problem in problems:
                print(f"{path}: {problem}")
            return 1
        parts.append(payload)
    merged = merge_agent_facts(parts)
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

    covered = sorted(merged["producer"].get("pages") or [])
    missing_pages = []
    if args.pages:
        missing_pages = [page for page in range(1, args.pages + 1) if page not in covered]
    corrections_path = destination.with_name(destination.stem + "-corrections.json")
    corrections_path.write_text(
        json.dumps(merged.get("corrections") or [], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report = {
        "expected_pages": args.pages,
        "covered_pages": covered,
        "missing_pages": missing_pages,
        "credits": len(merged.get("credits") or []),
        "marks": len(merged.get("marks") or []),
        "unresolved": merged.get("unresolved") or [],
        "corrections": merged.get("corrections") or [],
        "complete": not missing_pages and not merged.get("unresolved"),
    }
    report_path = destination.with_name(destination.stem + "-report.json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {destination}")
    print(f"corrections: {corrections_path}")
    print(f"review report: {report_path}")
    if missing_pages:
        print(f"missing reviewed pages: {missing_pages}")
        if not args.allow_missing_pages:
            print("refusing incomplete page coverage (use --allow-missing-pages to override)")
            return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare/validate/merge agent visual facts")
    sub = parser.add_subparsers(dest="command", required=True)

    prep = sub.add_parser("prepare", help="render source PDF pages and write instructions")
    prep.add_argument("--pdf", required=True)
    prep.add_argument("--outdir", required=True)
    prep.add_argument("--images", help="use an existing PNG directory instead of rendering")
    prep.add_argument("--dpi", type=int, default=150)
    prep.set_defaults(func=prepare)

    check = sub.add_parser("validate", help="check page/evidence fields")
    check.add_argument("--facts", required=True)
    check.add_argument("--pages", type=int)
    check.add_argument("--measures", type=int)
    check.set_defaults(func=validate)

    combine = sub.add_parser("merge", help="merge page/part JSON files")
    combine.add_argument("--parts", nargs="+", required=True)
    combine.add_argument("-o", "--output", required=True)
    combine.add_argument("--pages", type=int)
    combine.add_argument("--measures", type=int)
    combine.add_argument("--allow-missing-pages", action="store_true")
    combine.set_defaults(func=merge)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
