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
    }
  ]
}
```

`measure` is 1-based; `beat` is 0-based in quarter-note beats within the measure. `placement` is
`above` or `below`. Tempo-notation text such as `q = 72` is injected once with a `<sound tempo>`,
not duplicated as a metronome glyph.

## Producers

| Producer | Input | Status |
|---|---|---|
| `JsonProducer` | explicit `facts.json` | available |
| `TextLayerProducer` | TSV `measure/beat/placement/text` | available |
| `PdfTextProducer` | PDF text layer + measure boxes | available; garbled on some PDFs |
| agent/vision | rendered page + explicit transcription | planned delivery stage |

The text layer is not automatically correct. Sincerely's PDF text layer produced spaced/garbled
tokens; do not trust it without checking the rendered page.

## Visual facts (next stage)

The delivery agent should inspect rendered pages and write a separate, auditable facts file rather
than editing the MusicXML. Record enough evidence to review each fact:

```json
{
  "page": 1,
  "measure": 1,
  "bbox": [80, 120, 500, 220],
  "kind": "credit|tempo|rehearsal|articulation|text",
  "text": "q = 72",
  "confidence": 0.0,
  "evidence": "short description of what is visible"
}
```

Rules:

1. One fact per visible mark; do not infer a mark from musical expectations.
2. Keep page/bbox or a crop path so a human can verify it.
3. Unknown or ambiguous marks go in `unresolved`, never silently into `marks`.
4. A visual pass may propose pitch corrections, but must record the page evidence and must not
   apply them without an explicit correction step.
5. Re-render and re-check after injection; a fact is not done until the display shows it in the
   expected place.
