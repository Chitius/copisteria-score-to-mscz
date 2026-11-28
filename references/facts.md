# Facts and visual review

Facts are data extracted from the PDF or from an agent's inspection of the page. They are never
edits to the score; an inject pass applies them mechanically.

## Current schema

```json
{
  "credits": [
    {"type": "title", "text": "Sincerely"},
    {"type": "subtitle", "text": "Violet Evergarden OP"},
    {"type": "composer", "text": "TRUE"},
    {"type": "arranger", "text": "Arranger"}
  ],
  "marks": [
    {
      "measure": 1,
      "beat": 0,
      "placement": "above",
      "text": "q = 72",
      "tempo": 72,
      "beat_unit": "quarter"
    },
    {
      "measure": 9,
      "beat": 0,
      "placement": "above",
      "rehearsal": "A",
      "text": "Allegro"
    },
    {
      "measure": 75,
      "beat": 0,
      "placement": "above",
      "text": "rit.",
      "gradual": "ritardando",
      "length_measures": 2
    }
  ],
  "parts": [
    {
      "part": "P1",
      "name": "Acoustic Guitar",
      "abbreviation": "Guit.",
      "instrument": "acoustic-guitar"
    },
    {
      "part": "P4",
      "name": "Drumset",
      "abbreviation": "D. Set",
      "instrument": "drumset"
    }
  ]
}
```

`measure` is 1-based; `beat` is 0-based in quarter-note beats within the measure. `placement` is
`above` or `below`. Tempo-notation text such as `q = 72` is injected once with a `<sound tempo>`,
not duplicated as a metronome glyph. The beat-unit shorthand is expanded to the printed glyph
before the text is written (`q = 72` → `♩ = 72`, `q. = 72` → `♩. = 72`; also `e`, `h`, `w`),
because MuseScore prints a `<words>` text verbatim and a delivery would otherwise show a literal
`q`. Text that already carries the glyph is left alone, and a tempo word beside the number
(`Allegro q = 72`) keeps its words. For multi-`<part>` scores (experimental), `marks` accepts an
optional `"part"` ID (defaults to the first part) and `parts` injects per-part `<part-name>`,
`<part-abbreviation>`, `<instrument-sound>`, and GM `<midi-program>` / `<midi-channel>` (using a
preset `"instrument"` key from `schemas/facts.schema.json` or explicit `"sound"` /
`"midi_program"` / `"midi_channel"`; percussion parts preserve per-drum `<midi-unpitched>` bindings).

`gradual` marks a printed `rit.`/`rall.`/`accel.`/`string.`/`allarg.` word. Without it the word is
injected as plain staff text; with it the display pass `upgrade_gradual_texts` replaces the text
with a real paired `GradualTempoChange` spanner (`beginText` keeps the printed word). Values:
`ritardando`, `rallentando`, `accelerando`, `stringendo`, `allargando`. The spanner ends
`length_measures` measures after the fact measure (default 1); `length_fractions` (e.g. `-1/8`)
moves the end backwards from that measure start. Quote the printed word exactly — the text match
is literal, including italics.

The JSON Schema is [`schemas/facts.schema.json`](../schemas/facts.schema.json).

## Producers

| Producer | Input | Status |
|---|---|---|
| `JsonProducer` | explicit `facts.json` | available |
| `TextLayerProducer` | TSV `measure/beat/placement/text` | available |
| `PdfTextProducer` | PDF text layer + measure boxes | available; garbled on some PDFs |
| agent/vision | rendered page + explicit transcript | available via `scripts/agent_facts.py` |

The text layer is not automatically correct. Sincerely's PDF text layer produced spaced/garbled
tokens; do not trust it without checking the rendered page. The agent hand-off rules (per-page
coverage, proposal status, no direct score edits) are in [`agent-review.md`](agent-review.md).

## Agent visual facts

The agent inspects **source PDF pages**, not the repaired score. It writes JSON claims with page,
evidence and bbox/crop; the pipeline never receives an unverified "I saw a tempo" statement.

### 1. Prepare a page packet

```bash
python scripts/agent_facts.py prepare \
  --pdf "score.pdf" --outdir "review/facts"
```

This renders `page-*.png` and writes `instructions.md` plus `manifest.json`. Give the agent the
page images and instructions. Each claim must include:

```json
{
  "producer": {"name": "agent-visual", "pages": [1]},
  "credits": [
    {"type": "title", "text": "Sincerely", "page": 1,
     "bbox": [240, 20, 360, 60],
     "evidence": "top centre title", "confidence": 0.98}
  ],
  "marks": [
    {"measure": 1, "beat": 0, "placement": "above", "text": "q = 72", "tempo": 72,
     "page": 1, "bbox": [60, 70, 110, 95],
     "evidence": "tempo above the first system", "confidence": 0.95}
  ],
  "unresolved": [
    {"page": 1, "measure": 3, "reason": "text is clipped; cannot decide"}
  ]
}
```

`bbox` is in PDF points `[x0, y0, x1, y1]`; `crop` may replace it. If the agent measures the
rendered image, add `"bbox_space": "image-px"`; otherwise omit it and use PDF points. `evidence`
is mandatory for agent facts (manual facts may omit it).

### 2. Validate and merge

```bash
python scripts/agent_facts.py validate --facts review/facts/agent-page01.json --pages 2 --measures 31
python scripts/agent_facts.py merge --parts review/facts/agent-page*.json --pages 2 -o review/facts/facts.json
```

Invalid evidence fails; it is not silently dropped. Duplicate claims are de-duplicated and the
first evidence is kept. `merge` also strips printed role labels from credit values
(`Original Artist:TRUE` → `TRUE`, `Arranged by X` → `X`) while keeping the original wording in
`evidence`.

### 3. Apply and re-check

```bash
python scripts/convert.py score.pdf --pages path/to/omr-pages \
  --facts review/facts/facts.json --outdir out/score
```

`merge` writes three files:

- `facts.json` — credits/marks for injection (corrections are also retained for audit);
- `facts-corrections.json` — a separate pitch/rhythm correction review;
- `facts-report.json` — covered pages, missing pages, unresolved claims and counts.

Pitch/octave/duration corrections are **never injected automatically**. A correction has `from`, `to`, page,
bbox and evidence; it starts as `"status": "proposed"`. Review it with a human before applying
anything. Once accepted, apply it in a controlled step at unique note anchors and re-render:

```bash
python scripts/notation_patches.py accept --corrections review/facts/facts-corrections.json \
  --musicxml out/score/score.musicxml --indices 0 --reviewer "reviewer-name" \
  -o review/facts/facts-corrections.accepted.json
python scripts/notation_patches.py apply --input out/score/score.musicxml \
  --corrections review/facts/facts-corrections.accepted.json -o out/score/score.corrected.musicxml
```

`--allow-corrections` in `review.py` only records an explicit override and never changes the pitch.

### 4. Page coverage

`merge --pages N` refuses incomplete coverage by default. Use `--allow-missing-pages` only for a
partial/interim review, and keep `missing_pages` in the report.

### 5. Correction review

A visible pitch/rhythm anomaly belongs in a separate `corrections` array, never in `marks`:

```json
{
  "measure": 30,
  "beat": 3.5,
  "staff": 1,
  "from": "C8",
  "to": "C7",
  "status": "proposed",
  "page": 2,
  "bbox": [100, 900, 140, 940],
  "evidence": "ledger-line octave looks one too high",
  "confidence": 0.4
}
```

`merge` writes `facts-corrections.json`. It is a review queue: it is not injected into the score
automatically, and `status` must remain `proposed` until a human accepts or rejects it (via `scripts/notation_patches.py accept --corrections ...`).

Re-render after injection. A fact is not finished until the credit/mark appears in the expected
place. Keep unresolved claims in the report; do not turn them into guessed facts.

## Rules

1. One fact per visible mark; do not infer a mark from musical expectations.
2. Keep page and bbox/crop so a human can verify the claim.
3. Unknown or ambiguous marks go in `unresolved`, never silently into `marks`.
4. A visual pass may propose pitch corrections, but must record the page evidence and must not
   apply them without an explicit correction step.
5. Re-render and re-check after injection.
