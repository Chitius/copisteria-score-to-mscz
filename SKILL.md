---
name: score-omr
description: >
  Turn a printed score PDF into a reviewed MusicXML/MuseScore delivery. Use when the user asks
  for PDF-to-MusicXML, PDF-to-MIDI, OMR, score recognition, or proofreading of OMR output with
  copisteria/copista. Covers environment setup, page-wise OMR, the scorepipe repair pipeline,
  facts injection, visual verification, and delivery.
metadata:
  version: "0.2.0"
---

# Score OMR

This skill is an **operator wrapper** around the `scorepipe` pipeline. `scorepipe` is the
mechanical submodule; the skill owns environment setup, OMR invocation, evidence gathering,
visual review, and delivery.

## Non-negotiables

- Do not claim a score is delivered because a command exited 0. Require a clean verifier and,
  for a visual delivery, a rendered check.
- OMR is a draft. Keep the source PDF and the page output; never overwrite them.
- OMR pitch/rhythm errors are not silently "corrected" by the pipeline. Facts and manual
  corrections must be explicit and reviewable.
- A PDF text layer is not ground truth. If it is absent or garbled, use the agent/vision facts
  path (see `references/facts.md`).
- Do not download model weights, install system packages, or request admin rights without the
  user's decision. `scripts/preflight.py` reports choices instead.

## Fast path

```bash
# 1. Check the environment once per host. It prints missing items and ready-to-run commands.
python scripts/preflight.py --save env.local.json

# 2. OMR + repair + MuseScore + PDF, using the saved environment.
python scripts/convert.py "score.pdf" --env env.local.json --outdir "out/score" \
  --title "Title" --composer "Composer"

# 3. Inspect the report and the rendered pages before delivering.
```

If `scripts/convert.py` is not usable because the user has another OMR front-end, run that
front-end yourself and pass its **page directory** to:

```bash
python -m scorepipe.cli path/to/pages -o out/score.musicxml --mscz-out out/score.mscz \
  --report out/report.json
```

## What the skill produces

| Output | Meaning |
|---|---|
| `score.musicxml` | repaired, merged MusicXML (the semantic master) |
| `score.mscz` | MuseScore container after the display fixpoint |
| `score.pdf` | rendered review copy (when MuseScore is available) |
| `report.json` | phases, pass trace, analysis notes, verifier violations |
| `work/copisteria/` | per-page OMR MusicXML, reading JSON, HTML; keep for audit |
| `facts.json` | explicit text/visual facts, when a facts producer is used |

Never deliver only the `.mscz`: the MusicXML is what the repair pipeline owns.

## Workflow

### 0. Configure

Read `references/environment.md`, then run `preflight.py`. The required pieces are:

- Python 3.10+ with this repository importable;
- an OMR environment containing copisteria and music21 (usually a separate venv);
- copisteria source checkout and its model weights;
- MuseScore 4 for `.mscz` / PDF display (optional for MusicXML-only work);
- poppler (`pdfinfo`, `pdftoppm`) for page work and visual review.

`preflight.py --save env.local.json` records paths; do not commit that file.

### 1. Understand the input

- Confirm the PDF is the intended edition and note its page count.
- Record title/composer/arranger and any known pickup, repeats, or transposing instruments.
- Keep a copy under the delivery work directory before running OMR.

### 2. Run OMR

`scripts/convert.py` invokes the external copisteria converter, then the scorepipe pipeline on
the per-page output. It intentionally does **not** use the old converter's final merged file as
the pipeline input: page context is required for page-level tie/slur/pedal restoration.

See `references/omr.md` for the page contract and troubleshooting.

### 3. Repair and verify

The pipeline runs structural → inject → display fixpoints and read-only verifiers. Read
`report.json`:

- `stable=true` for every phase;
- `verifier` empty;
- no unexplained `measure-length` or hidden-rest findings;
- compare against a ground truth if one exists (`--compare-golden` or the Lieder comparator).

### 4. Facts and visual review

The text layer can supply title, composer, tempo words, rehearsal marks and commentary. The
current producer is mechanical; the agent/vision facts path is the next delivery-stage work.
Read `references/facts.md` before adding facts. Facts are data: they never mutate the score until
an inject pass applies them, and every applied fact must be traceable.

For a visual check, render the `.mscz` to PDF, rasterize pages, and inspect at least:

- first/last system and page joins;
- pickup and measure numbering;
- dense piano systems and ledger-line octaves;
- slurs/ties across page breaks;
- text/credits placement.

Do not mark a visual issue as fixed without a new render.

### 5. Deliver

Use `references/delivery.md`. Deliver the MusicXML + `.mscz` + PDF + report, state the verifier
result and any known OMR defects, and keep the work directory.

## Repository map

```text
SKILL.md                 this operator contract
scripts/preflight.py     environment probe; no installs
scripts/convert.py       PDF -> OMR pages -> scorepipe -> mscz/pdf
schemas/                 facts JSON schema
scorepipe/               the Python pipeline (submodule)
tests/                   regression suite and Lieder corpus
docs/                    architecture, delivery, archive
references/              short operational references for the skill
ACCEPTANCE.md            historical acceptance evidence
SANITY.md                pass-contract audit
```

## Current status (2026-11)

- `unittest`: 178 tests; `pytest`: 258 tests.
- Gute Nacht: 98.94% / 99.0% sounding notes (vocal/piano), verifier clean.
- `aus_meinen_traenen`: 91.38% / 90.10%; `die_wetterfahne`: 98.97% / 97.75%.
- `der_lindenbaum` P2 remains an OMR-quality outlier (~51%).
- Known delivery-stage gap: agent visual facts extraction is not implemented yet; the text-layer
  producer and manual `--facts` path are available.
