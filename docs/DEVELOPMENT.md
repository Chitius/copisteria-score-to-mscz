# 开发指南 / Development guide

> 这份文档是面向开发者的技术总览，原先放在仓库根目录的 `README.md`；根目录现在的
> [`README.md`](../README.md) 面向第一次使用的普通用户。两份内容互补，不是互相替代。
>
> This is the developer-facing overview that used to live in the repository root. The root
> [`README.md`](../README.md) is now the user-facing guide.

`copisteria-score-to-mscz` is a skill for turning a printed score PDF into a reviewed
MusicXML/MuseScore delivery.

The mechanical work lives in the `scorepipe` Python package: it merges per-page OMR output,
repairs structure to a fixed point, applies explicit facts, produces a `.mscz`, and verifies both
the MusicXML and the display score. The skill wrapper owns the part around it: environment
preflight, OMR invocation, evidence collection, visual review, and delivery.

Start with [`../SKILL.md`](../SKILL.md). The operational references are in
[`../references/`](../references/).

## Quick start

```bash
# Environment probe: reports what is missing; never installs or downloads.
python scripts/preflight.py --save env.local.json

# End-to-end pipeline draft: PDF -> copisteria page output -> scorepipe -> mscz + review PDF.
python scripts/convert.py "score.pdf" --env env.local.json --outdir "out/score" \
  --title "Title" --composer "Composer"

# Final delivery: page review + facts/patches + mechanical/reviewed/forced trees.
python scripts/review.py "score.pdf" --pages out/score/work/copisteria \
  --facts-dir review/facts --outdir "review/score"

# Pipeline only: use an existing page directory.
python -m scorepipe.cli path/to/pages -o out/score/score.musicxml --mscz-out out/score/score.mscz \
  --report out/report.json
```

`scripts/convert.py` is a pipeline draft; its `delivery.json` has `reviewed: false`. Use
`scripts/review.py` for the final delivery tree and acceptance checks.

### Operational flags

| Script | Flag | Meaning |
|---|---|---|
| `review.py` | `--no-mechanical` | omit the no-agent baseline (blocked unless `--allow-incomplete-delivery`) |
| `review.py` | `--no-forced-truncation` | omit the forced editable tree (same gate) |
| `review.py` | `--no-sheets` | skip the measure-level page proof sheets (`review/sheets/`) |
| `review.py` | `--allow-incomplete-delivery` | explicit interim override; still records `artifacts_missing` |
| `review.py` | `--title` / `--composer` | inject manual credits before review |
| `review.py` | `--compare-golden` | compare the reviewed MusicXML with a golden file |
| `review.py` | `--allow-unresolved` / `--allow-corrections` | interim override; recorded as `overrides` |
| `review.py` | `--skip-facts` | no per-page facts yet: skip the coverage gate, deliver the mechanical tree (`facts_skipped: true` + finding) |
| `convert.py` | `--force` | replace existing draft artifacts |
| `convert.py` | `--no-mscz` / `--no-pdf` | stop before/without render (draft only) |
| `scorepipe.cli` | `--truncate-overfull` | explicit forced-repair pass; requires `--mscz-out` |
| `notation_patches.py` | `apply --dry-run` | validate and report changes without writing |
| `notation_patches.py` | `accept --reviewer NAME` | promote selected ottava/tuplet/clef patches |

## What the skill produces

| Artifact | Meaning |
|---|---|
| `score.musicxml` | repaired, merged MusicXML; the semantic master (untruncated) |
| `score.mscz` | delivered editable MuseScore container (truncated when the forced copy repaired a bar) |
| `score.pdf` | render of `score.mscz` — the file the comparison shows |
| `report.json` | phase rounds, pass trace, analysis, verifier violations |
| `delivery.json` | final review manifest (convert writes `reviewed:false` draft) |
| `semantic/` | only when truncated: the untruncated reviewed tree |
| `mechanical/` | no-agent-facts/no-patches comparison tree |
| `forced-truncation/` | the editable overfull-voice repair; `semantic_authority:false` |
| `work/copisteria/` | per-page OMR MusicXML, reading JSON and HTML |
| `review/confidence/` | per-page scan painted by OMR doubt, `review.md` in review order |
| `review/sheets/` | per-page measure-level proof sheet: this page's render beside its scan |
| `review-sheets.pdf` | all comparison pages in one A4-landscape PDF (300 dpi, cover/TOC, per-page footer) |

Keep the page directory. It is the audit trail for page-level ties/slurs and for OMR defects.

## Workflow

1. **Configure** — `scripts/preflight.py` checks the pipeline interpreter, the separate
   upstream copisteria environment/checkout/weights, MuseScore and poppler. See
   [`references/environment.md`](../references/environment.md).
2. **OMR** — `scripts/convert.py` uses the built-in `scorepipe.copisteria` adapter to extract page
   PNGs into `work/pages/` and invoke `python -m copisteria.pipeline` into `work/copisteria/`. Feed
   scorepipe that per-page directory. See [`references/omr.md`](../references/omr.md).
3. **Repair** — scorepipe runs structural → inject → display fixed points and read-only
   verifiers. A non-empty verifier is a blocker, not a cosmetic warning.
4. **Facts** — apply explicit title/composer/marks facts. The text layer is a producer, not
   ground truth. The agent/vision producer has a prepared page packet and evidence-checking workflow;
   see [`references/facts.md`](../references/facts.md).
5. **Review** — start from `review/confidence/review.md`: it paints each scan by how much the OMR
   reader doubted each symbol (`scripts/review_confidence.py`, run by `review.py`), so the pages
   worth checking come first. Then run `scripts/review_sheet.py` for the measure-level view: each
   page's own render beside its scan, the same bars tinted and numbered on both. Finally render
   the `.mscz` to PDF, rasterize pages, and check the first/last systems, page joins, pickup, dense
   piano pages, ledger-line octaves, and text placement.
6. **Deliver** — follow [`references/delivery.md`](../references/delivery.md). Report known OMR
   defects by measure; do not silently transpose or invent notes.

## Pipeline shape

```text
per-page MusicXML
  -> loader: LCM divisions, global measures, page context
  -> structural fixpoint: voice/measure/beam/tie/slur/page restoration
  -> facts (JSON only) -> inject fixpoint
  -> MusicXML master
  -> MuseScore import -> display fixpoint on .mscx
  -> MusicXML verifier + mscx verifier
  -> report / render / delivery
```

The pipeline is a compiler-style fixed point: each mechanical pass declares what it owns and a
monotone measure; the runner repeats until a full round changes nothing; read-only verifiers run
afterwards. See [`DESIGN.md`](DESIGN.md) for the architecture and global pass invariants.

Useful commands:

```bash
python -m scorepipe.cli --list-passes
python -m scorepipe.cli score.musicxml --trace -o out.musicxml
python -m scorepipe.cli score.musicxml --mscz-out out.mscz --report out/report.json
python -m scorepipe.cli score.mscz --check
python -m scorepipe.cli pages/ --check
```

## Facts

Facts are JSON data, never direct edits:

```json
{
  "credits": [
    {"type": "title", "text": "Sincerely"},
    {"type": "composer", "text": "TRUE"}
  ],
  "marks": [
    {"measure": 1, "beat": 0, "placement": "above", "text": "q = 72", "tempo": 72}
  ]
}
```

Tempo notation is written once with a `<sound tempo>`; arranger/transcriber credits append to the
composer line. A PDF text layer can be used through the producers; a scanned PDF with no usable
text layer still needs the agent/vision facts path.

### Agent visual facts

```bash
python scripts/agent_facts.py prepare --pdf score.pdf --outdir review/facts
python scripts/agent_facts.py validate --facts review/facts/agent-page01.json --pages 2
python scripts/agent_facts.py merge --parts review/facts/agent-page*.json --pages 2 -o review/facts/facts.json
python scripts/convert.py score.pdf --pages path/to/omr-pages \
  --facts review/facts/facts.json --outdir out/score
```

Every agent credit/mark must carry `page`, `evidence`, and `bbox`/`crop`; ambiguous items go in
`unresolved`. `merge` strips printed role labels (`Original Artist:TRUE` → `TRUE`) and keeps the
original wording in evidence. See [`references/facts.md`](../references/facts.md).

### Constrained notation patches

Long-tail symbols are not forced into facts. The prototype supports `ottava` (`8va`/`8vb`),
constrained `tuplet`, and `clef` patches as musical-anchor operations; the compiler writes MusicXML
`<octave-shift>` / tuplet notation / `<clef>` and MuseScore builds the spanner/bracket:

```bash
python scripts/notation_patches.py map --input out/score/score.musicxml -o review/score-map.json
python -m scorepipe.cli pages/ -o out/score/score.musicxml --mscz-out out/score/score.mscz \
  --patches review/patches.json
```

See [`references/notation-patches.md`](../references/notation-patches.md). The patch compiler enforces
start/end staff and order; the rendered bracket still needs visual confirmation.

### Delivery review

```bash
python scripts/review.py score.pdf --pages path/to/omr-pages \
  --facts-dir review/facts --patches review/patches.json --outdir review/score
```

The review stops before the pipeline when pages are missing, unresolved claims or proposed
corrections remain. `--allow-unresolved` / `--allow-corrections` are explicit interim overrides;
the report still lists what was overridden. A no-facts/no-patches baseline is written to
`mechanical/`; the root `score.*` files are the reviewed version. Keep both. `timing-report.json`
compares measure-length findings between the two. The default `forced-truncation/` tree trims
overfull voices so MuseScore can edit them; it is marked `semantic_authority: false` and records
every operation in `truncation-report.json`. When that trim actually happens it becomes the
delivery: root `score.mscz`/`score.pdf` are the truncated copy (so `rendered/` shows what ships),
the untruncated reviewed tree moves to `semantic/`, and root `score.musicxml` stays the untruncated
semantic master. The measure-level page comparison is built last, from the delivered tree:
`review/sheets/` holds the per-page images and `review-sheets.pdf` at the delivery root binds them
into one A4-landscape file (`--no-sheets` skips it; a failure is a finding, not a blocker).
See [`references/review.md`](../references/review.md).

## Known limitations

- Agent/vision facts support page preparation, coverage checks, evidence validation and corrections
  review; delivery still requires per-page review and resolving `unresolved`/`corrections`.
- The notation-patch compiler supports `ottava`, constrained `tuplet` and `clef`; pedal, hairpin and
  general dynamic operations are not covered.
- Same-value beam runs are rebuilt as one group rather than by a full compound-metre `BeamGrouper`.
- Voice merge skips tuplet measures rather than preserving nested ratios.
- OMR octave/ledger errors are preserved and reported, not silently corrected.
- MuseScore can crash on schema-valid but importer-hostile XML. Reproduce crashes with the MuseScore
  CLI and bisect them; see [`references/troubleshooting.md`](../references/troubleshooting.md).
- PDF text layers can be garbled; verify extracted metadata against the page image.

## Repository map

```text
SKILL.md                 skill operator contract
scripts/preflight.py     read-only environment probe
scripts/convert.py       PDF -> OMR pages -> scorepipe -> mscz/pdf
scripts/agent_facts.py   prepare/validate/merge agent visual facts
scripts/notation_patches.py  map anchors / apply constrained notation patches
scripts/review.py        page review -> pipeline -> render report
schemas/                 facts and notation-patch JSON schemas
scorepipe/               the Python pipeline
references/              setup, OMR, facts, delivery references
docs/                    architecture and developer guide
tests/                   regression suite and Lieder corpus
```

## Development

```bash
python -m unittest discover -s tests
python -m pytest tests -q -p no:cacheprovider
```

The test suite covers pass contracts, fixed-point convergence, MusicXML/mscx verifiers, page
restoration, facts injection, pickup/beam/measure regressions, and the OpenScore Lieder corpus.
When adding a mechanical pass, add its fixture and contract in `tests/test_pass_sanity.py`.
