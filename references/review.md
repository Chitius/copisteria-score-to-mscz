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

The loop writes `review-report.json` and exits 2 without running the **reviewed** pipeline when:

- a page has no `producer.pages` coverage;
- there are `unresolved` claims;
- there are proposed `corrections`;
- the source page count and rendered image count differ;
- a notation patch fails validation.

A mechanical baseline (no agent facts, no patches) is still produced first when it is enabled, so
the delivery keeps a clean comparison even when the reviewed version is blocked.

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
  timing-report.json
  pages/source-*.png
  score.musicxml
  score.mscz
  score.pdf
  rendered/source-*.png
  mechanical/
    score.musicxml
    score.mscz
    score.pdf
    report.json
    rendered/source-*.png
  forced-truncation/
    score.musicxml
    score.mscz
    score.pdf
    report.json
    truncation-report.json
    rendered/source-*.png
```

`mechanical/` is the pipeline output without agent facts or patches. It is the comparison/baseline
artifact, not an alternative final delivery. `review-report.json` records page coverage, missing
pages, unresolved claims, corrections, patch count, the mechanical baseline exits and artifact
paths. `timing-report.json` compares `measure-length` / `mscx-measure-length` findings between the
mechanical baseline and the reviewed output, with `introduced` and `resolved` lists.

`forced-truncation/` is enabled by default. It is the reviewed score with overfull voices forced to
the bar line so the measure can be opened and edited in MuseScore. It is **not** semantically
authoritative (`semantic_authority: false`); `truncation-report.json` lists every removed or
shortened rest/note and the review report includes the same operations. The default is to create
this forced copy; use `--no-forced-truncation` only for a diagnostic run that intentionally omits
the editable repair tree (the review then records that artifact as missing). If the forced copy is
not verifier-clean or has `UNRESOLVED` operations, the review is blocked.

If the reviewed pipeline fails after producing an MSCZ, review still renders and rasterises that
draft when possible, then writes the report with `ready: false`; the failed run remains
non-deliverable.

## Required human checks

- Compare the source and rendered page around every patch, especially 8va extent.
- Resolve or explicitly accept every unresolved/correction.
- Confirm credits and tempo placement in the rendered first page.
- Keep the review directory and the OMR page directory with the delivery.
