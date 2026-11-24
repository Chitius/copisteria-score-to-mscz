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

A **dirty mechanical baseline is not a blocker**. It is the comparison tree, and an overfull voice
in it is exactly the condition the forced-truncation tree exists to repair; blocking on it would
prevent that repair from ever running. The baseline's exit code and verifier count are recorded in
`findings`, and `mechanical.ready` stays `false`. The acceptance gate is the *reviewed* run: its
exit code and its own display verifier.

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
paths, plus a `findings` list for non-blocking problems (a dirty baseline, for example).
`timing-report.json` compares `measure-length` / `mscx-measure-length` findings between the
mechanical baseline and the reviewed output, with `introduced` and `resolved` lists. It reports
`available: false` instead of inventing deltas when one of the two runs did not produce a report.

`forced-truncation/` is enabled by default. It is the reviewed score with overfull voices forced to
the bar line so the measure can be opened and edited in MuseScore. It is **not** semantically
authoritative (`semantic_authority: false`); `truncation-report.json` lists every removed or
shortened rest/note and the review report includes the same operations. Shortened elements may use
an explicit `<duration>`; `irregular_durations` lists those operations, and `spanner_risks` lists
removed/shortened chords that carried a Tie/Slur/Spanner. Both must be inspected in the rendered
PDF. The default is to create this forced copy; use `--no-forced-truncation` only for a diagnostic
run that intentionally omits the editable repair tree (the review then records that artifact as
missing). If the forced copy is not verifier-clean or has `UNRESOLVED` operations, the review is
blocked.

If the reviewed pipeline fails after producing an MSCZ, review still renders and rasterises that
draft when possible, then writes the report with `ready: false`; the failed run remains
non-deliverable.

## Confidence heat map (review aid, never a gate)

`scripts/review_confidence.py` reads copisteria's `<page>.reading.json` and paints each scan by
how much the reader doubted each symbol: red where the context rewrote the detector's choice,
orange where the symbol's existence was uncertain, amber where an attribute probability is low.
The page is numbered in review order; the JSON keeps every symbol that scored above zero,
including the ones without a box.

```bash
python scripts/review_confidence.py --work-dir out/song/work        # per-page images + review.md
python scripts/review_confidence.py --pages out/song/work/copisteria \
  --rendered-dir out/song/rendered                                  # put the render beside the scan
```

`review.py` runs it automatically when the page directory has readings (skip with
`--no-confidence`). A missing reading, a page without an image or a broken JSON is reported as
`skipped`/`failed`/`incomplete` and never blocks delivery — the map orders attention, it does not
decide anything. Rendered pages are paired by stem; `--pair-rendered-order` pairs them
positionally and is only correct when the render is paginated like the scan.

## Page proof sheets (measure-level comparison)

`scripts/review_sheet.py` renders **each page's own MusicXML** and puts it beside that page's scan,
with the same bars tinted on both sides and the same global measure number above them. This is the
measure-level companion to the symbol heat map: the heat map says which glyph is doubtful, the
sheet says whether the render and the page agree bar for bar.

```bash
python scripts/review_sheet.py --pages out/song/work/copisteria --report out/song/report.json
python scripts/review_sheet.py --pages review/pages --scan-dir review/scans --musescore "...\MuseScore4.exe"
```

How the two sides are aligned:

- both columns are cut into measures by measured barlines; on the scan the reader's own
  `barLine_*` detections (`<stem>.dets_*.json`) are used when present, with the ink test as a
  fallback;
- the render must detect exactly as many measures as the page MusicXML declares, and the scan
  must detect the same number; a mismatch leaves that column **untinted** and records
  `render_layout_mismatch` / `scan_layout_mismatch`. A tinted wrong bar is worse than a plain one;
- measure numbers are global (page offsets are summed from the earlier pages' measure counts) and
  `≠` marks a bar with a measure-length violation from the scorepipe report;
- a tall-page render spreads its systems over 30 inches, so blank bands taller than 5% of the page
  are collapsed before drawing (the count is recorded as `render_collapsed_bands`); the scan keeps
  its real spacing;
- a sliver cell (a stem read as a barline) is folded into its neighbour, except for the first and
  last bar of a system, which are short for real.

The old tool also *stacked* a page whose MusicXML rendered as several pages; that is kept.

Known limit: the ink test can still over- or under-detect a bar on a dense page. When the counts
disagree the offending column stays plain and the page is reported incomplete -- the same "do not
overlay unless the count verifies" rule, not a silent misalignment.

## Required human checks

- Start from `review/confidence/review.md`: it ranks what to verify first, per page.
- Compare the source and rendered page around every patch, especially 8va extent.
- Resolve or explicitly accept every unresolved/correction.
- Confirm credits and tempo placement in the rendered first page.
- Keep the review directory and the OMR page directory with the delivery.
