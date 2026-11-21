# copisteria-to-mscz

`copisteria-to-mscz` is a skill for turning a printed score PDF into a reviewed MusicXML/MuseScore
delivery.

The mechanical work lives in the `scorepipe` Python package: it merges per-page OMR output,
repairs structure to a fixed point, applies explicit facts, produces a `.mscz`, and verifies both
the MusicXML and the display score. The skill wrapper owns the part around it: environment
preflight, OMR invocation, evidence collection, visual review, and delivery.

Start with [`SKILL.md`](SKILL.md). The operational references are in
[`references/`](references/); historical plans are in [`docs/archive/`](docs/archive/).

## Quick start

```bash
# Environment probe: reports what is missing; never installs or downloads.
python scripts/preflight.py --save env.local.json

# End-to-end: PDF -> copisteria page output -> scorepipe -> mscz + review PDF.
python scripts/convert.py "score.pdf" --env env.local.json --outdir "out/score" \
  --title "Title" --composer "Composer"

# Pipeline only: use an existing page directory.
python -m scorepipe.cli path/to/pages -o out/score.musicxml --mscz-out out/score.mscz \
  --report out/report.json
```

If MuseScore is unavailable, use `--no-mscz`/`--no-pdf`; deliver MusicXML plus the report and say
that display review was not produced.

## What the skill produces

| Artifact | Meaning |
|---|---|
| `score.musicxml` | repaired, merged MusicXML; the semantic master |
| `score.mscz` | MuseScore container after the display fixpoint |
| `score.pdf` | rendered review copy |
| `report.json` | phase rounds, pass trace, analysis, verifier violations |
| `delivery.json` | commands, paths and artifact manifest from `scripts/convert.py` |
| `work/copisteria/` | per-page OMR MusicXML, reading JSON and HTML |

Keep the page directory. It is the audit trail for page-level ties/slurs and for OMR defects.

## Workflow

1. **Configure** — `scripts/preflight.py` checks the pipeline interpreter, the separate
   copisteria/music21 environment, the converter wrapper, MuseScore and poppler. See
   [`references/environment.md`](references/environment.md).
2. **OMR** — run the external copisteria converter over the PDF. Feed scorepipe the per-page
   directory, not the old converter's final merged MusicXML. See
   [`references/omr.md`](references/omr.md).
3. **Repair** — scorepipe runs structural → inject → display fixed points and read-only
   verifiers. A non-empty verifier is a blocker, not a cosmetic warning.
4. **Facts** — apply explicit title/composer/marks facts. The text layer is a producer, not
   ground truth. The agent/vision producer has a prepared page packet and evidence-checking workflow;
   see [`references/facts.md`](references/facts.md).
5. **Review** — render the `.mscz` to PDF, rasterize pages, and check the first/last systems,
   page joins, pickup, dense piano pages, ledger-line octaves, and text placement.
6. **Deliver** — follow [`references/delivery.md`](references/delivery.md). Report known OMR
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
afterwards. See [`docs/DESIGN.md`](docs/DESIGN.md) for the architecture and
[`SANITY.md`](SANITY.md) for the pass-contract audit.

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
python scripts/agent_facts.py validate --facts review/facts/agent-page1.json --pages 2
python scripts/agent_facts.py merge --parts review/facts/agent-page*.json -o review/facts/facts.json
python scripts/convert.py score.pdf --pages path/to/omr-pages \
  --facts review/facts/facts.json --outdir out/score
```

Every agent credit/mark must carry `page`, `evidence`, and `bbox`/`crop`; ambiguous items go in
`unresolved`. `merge` strips printed role labels (`Original Artist:TRUE` → `TRUE`) and keeps the
original wording in evidence. See [`references/facts.md`](references/facts.md).

## Current status (2026-11-21)

Tests:

```text
python -m unittest discover -s tests   # 187 tests
python -m pytest tests -q              # 267 tests
```

Corpus (sounding-note match; rests excluded from the primary score):

| Case | Vocal / P1 | Piano / P2 | Notes |
|---|---:|---:|---|
| Gute Nacht | 98.94% | 99.0% | verifier clean |
| Aus meinen Tränen | 91.38% | 90.10% | verifier clean |
| Die Wetterfahne | 98.97% | 97.75% | verifier clean |
| Der Lindenbaum | 99.51% | 51.44% | raw OMR is the limiting factor |
| Sincerely | — | — | no ground truth; structural/display verifier clean |

Recent Sincerely-specific fixes:

- padded pickup is moved to the end of the first bar, and its display rest is hidden;
- the initial courtesy 4/4 is deleted from the display score, not merely made invisible;
- stray post-barline rests no longer cascade through m24/m25/m26 and delete their second halves;
- mixed 8th/16th beam runs follow the beat grid, while complete source groups are hard boundaries.

## Known limitations

- Agent/vision fact extraction has page preparation, coverage checking, evidence validation, merge,
  and a separate corrections review; real delivery still needs per-page review and resolving
  `unresolved`/`corrections`.
- Same-value beam runs are still rebuilt as one group; a full compound-metre `BeamGrouper` is
  future work.
- Voice merge skips tuplet measures rather than preserving nested ratios.
- OMR octave/ledger errors are preserved. For example, Sincerely m30 has a raw C8; the pipeline
  reports the draft, it does not silently correct the pitch.
- `der_lindenbaum` P2 remains an OMR-quality outlier, not a delivery showcase.
- Text layers can be garbled (Sincerely's credits were); do not trust extracted metadata without a
  visual check.

## Repository map

```text
SKILL.md                 skill operator contract
scripts/preflight.py     read-only environment probe
scripts/convert.py       PDF -> OMR pages -> scorepipe -> mscz/pdf
scripts/agent_facts.py   prepare/validate/merge agent visual facts
schemas/                 facts JSON schema
scorepipe/               the Python pipeline
references/              setup, OMR, facts, delivery references
docs/                    architecture, acceptance evidence, archived plans
docs/archive/            completed migration/change plans (provenance)
tests/                   regression suite and Lieder corpus
SANITY.md                pass-contract audit
```

## Development

```bash
python -m unittest discover -s tests
python -m pytest tests -q -p no:cacheprovider
```

The test suite covers pass contracts, fixed-point convergence, MusicXML/mscx verifiers, page
restoration, facts injection, pickup/beam/measure regressions, and the OpenScore Lieder corpus.
When adding a mechanical pass, add its fixture and contract in `tests/test_pass_sanity.py`.
