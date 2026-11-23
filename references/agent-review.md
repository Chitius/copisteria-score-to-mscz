# Agent review and proposal protocol

This is the operational contract for an agent doing the visual review. The agent is a
**producer**: it reads page images and writes review JSON. It does not edit MusicXML, mscx or the
score in place.

## Inputs

- `prepare` output: `pages/page-*.png`, `instructions.md`, `manifest.json`;
- `score-map.json` from `scripts/notation_patches.py map`;
- optional text-layer facts.

Do not use the repaired `.mscz` as the only source of truth for printed marks; compare with the
source PDF page.

## Per-page procedure

For every page in `manifest.json`:

1. Inspect the page at readable resolution; use crops for dense systems.
2. Record only clearly visible credits, tempo/rehearsal/expression text. Each claim needs:
   `page`, `evidence`, `bbox` or `crop`, and `confidence`.
3. Put unclear text/marks in `unresolved`; do not guess.
4. For pitch/rhythm suspicion, write a **correction proposal**, not a fact and not a score edit.
5. For 8va/tuplet, write a **notation patch proposal** using musical anchors from
   `score-map.json`; do not use pixel bbox as the range.
6. Set `status: "proposed"` for corrections/patches. Never mark `accepted` yourself.

## Output files

```text
review/facts/agent-page01.json
review/facts/agent-page02.json
...
```

Each file declares `producer.pages` containing the page it actually reviewed. The merge step
rejects missing coverage.

## Proposal shapes

Correction (pitch/rhythm review):

```json
{"measure": 30, "beat": 3.5, "staff": 1, "from": "C8", "to": "C7",
 "status": "proposed", "page": 2, "bbox": [820, 1260, 1020, 1310],
 "evidence": "ledger-line octave looks one too high", "confidence": 0.4}
```

Notation patch (8va/tuplet): see [`notation-patches.md`](notation-patches.md). The start/end must
name a real measure/beat and, for tuplets, the first/last note pitch. Include `note_count` and
`span_beats` only when they are visibly supported, never inferred from a bad bar length.

## Hand-off and acceptance

Run:

```bash
python scripts/agent_facts.py validate --facts review/facts/agent-page01.json --pages N
python scripts/agent_facts.py merge --parts review/facts/agent-page*.json --pages N \
  -o review/facts/facts.json
python scripts/notation_patches.py accept --patches review/patches.json \
  --musicxml out/score.musicxml --indices 0 --reviewer "name" \
  -o review/patches.accepted.json
```

`merge` writes `facts-corrections.json` and a coverage report. A missing page, unresolved item or
proposed correction blocks the default review. Acceptance is an explicit human step; then run
`scripts/review.py` and inspect `rendered/` and `score.pdf`.

## Hard stops

- Do not edit `.musicxml`, `.mscz` or `.mscx` directly.
- Do not turn a correction into a note/rest edit.
- Do not set `status: accepted` without a reviewer.
- Do not claim a visual fix without a new render.
- If an anchor/range is ambiguous, leave it unresolved rather than expanding it to look plausible.
