# Delivery review loop

`scripts/review.py` is the operator entry point for the page-wise review. It combines:

- source page rendering;
- a stable score map;
- agent page facts (`agent-page*.json`);
- optional notation patches;
- the scorepipe run;
- before/after rendering;
- a machine-readable review report.

## Command

```bash
python scripts/review.py score.pdf \
  --pages path/to/omr-pages \
  --facts-dir review/facts \
  --patches review/patches.json \
  --outdir review/score
```

## Blocking policy

The loop writes `review-report.json` and exits 2 without running the pipeline when:

- a page has no `producer.pages` coverage;
- there are `unresolved` claims;
- there are proposed `corrections`;
- the source page count and rendered image count differ;
- a notation patch fails validation.

Explicit overrides for an interim review:

```bash
--allow-unresolved
--allow-corrections
```

Overrides do not remove the items from the report. A `ready: true` report still lists what was
overridden; do not present it as a fully reviewed delivery.

## Report

```text
review/score/
  score-map.json
  facts.json
  facts-corrections.json
  review-report.json
  pages/source-*.png
  score.musicxml
  score.mscz
  score.pdf
  rendered/source-*.png
```

`review-report.json` records page coverage, missing pages, unresolved claims, corrections, patch
count, pipeline/render exit codes and artifact paths.

## Required human checks

- Compare the source and rendered page around every patch, especially 8va extent.
- Resolve or explicitly accept every unresolved/correction.
- Confirm credits and tempo placement in the rendered first page.
- Keep the review directory and the OMR page directory with the delivery.
