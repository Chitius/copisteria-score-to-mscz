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
`findings`, and `mechanical.ready` stays `false`. The acceptance gate is the **delivered** run: the
editable copy when it had to trim an overfull voice, otherwise the reviewed run.

The loop runs the forced-truncation copy **after** the reviewed one, and that copy is what ships
when it had to trim something: the root `score.mscz`/`score.pdf` become the truncated editable
copy, `rendered/` is rasterised again from it, and the untruncated reviewed tree moves to
`semantic/` (root MusicXML stays the untruncated semantic master). A reviewed failure is tolerated
only when every finding is a measure-length complaint and the editable copy repairs it; any other
verifier finding still blocks. This keeps the page comparison byte-identical to the file the user
opens.

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
  score.musicxml            semantic master (untruncated)
  score.mscz                delivered editable copy (truncated when needed)
  score.pdf                 render of score.mscz
  truncation-report.json    only when the editable copy trimmed something
  rendered/source-*.png     raster of score.pdf
  review-sheets.pdf         all page comparisons in one A4-landscape PDF
  review/sheets/            per-page proof sheets + review_sheet.md + the same PDF
  review/confidence/        per-page symbol heat map
  semantic/                 only when truncated: untruncated reviewed tree
    score.musicxml
    score.mscz
    score.pdf
    report.json
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

When the forced copy actually trimmed something, it becomes the delivery: the root `score.mscz`/
`score.pdf` are the truncated copy, `truncation-report.json` sits at the root, `rendered/` is
rasterised from that PDF, and the untruncated reviewed tree is kept under `semantic/`. Root
`score.musicxml` stays the untruncated semantic master — the trim is an mscx display repair and is
not reflected in MusicXML — and `review-report.json` records that split in `delivery_note`.


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

`scripts/review_sheet.py` renders the **delivered score** (`--score score.mscz`, falling back to
repaired `score.musicxml` when no `.mscz` exists), paginated with forced page breaks to match the
scan pages, and puts each page beside its original scan with the same bars tinted and the same
global measure number above them. Pass `--raw-pages` only when debugging raw per-page OMR output.
This is the measure-level companion to the symbol heat map: the heat map says which glyph is
doubtful, the sheet says whether the delivered score and the scan agree bar for bar. `review.py`
runs it automatically after the delivery is chosen (passing the delivered `score.mscz`) and writes
`review/sheets/` (skip with `--no-sheets`); a failure is recorded as a finding, never a blocker.

```bash
python scripts/review_sheet.py --pages out/song/work/copisteria --score out/song/score.mscz --report out/song/report.json
python scripts/review_sheet.py --pages review/pages --scan-dir review/scans --musescore "...\MuseScore4.exe"
```

What gets tinted: a bar's score is its strongest **content-doubt** symbol -- class, position,
accidental, tuplet or existence. Routine `voice`/`dots`/`onset` fixes are numerous on dense piano
pages (they occur on nearly every eighth note) and the reader is usually right, so they stay in the
symbol heat map and in `score` but do not tint a bar; tinting by all suspects painted 33 of 40 bars
on First Step page 2, versus 11 after the split. Tiers stay absolute (`red >= 3.0`,
`yellow >= 1.5`) and the priority list is ranked across the whole score.

How the two sides are aligned:

- every page is analyzed first, then built; the tiers are absolute (`red >= 3.0`, `yellow >= 1.5`,
  the same heads and weights everywhere) so a score means the same thing on every page, and the
  priority list is ranked across the whole score;
- the **render side reads MuseScore's own SVG export**: `<polyline class="BarLine">` elements carry
  exact vector geometry, so barlines and systems are measured, not guessed. Both staves of a grand
  staff emit overlapping barline segments, which is how systems are grouped, and a double barline
  drawn as two near-coincident polylines is folded into the cell on its left
  (`render_source: "svg"` in the `.compare.json`). The raster ink test (`render_source: "ink"`) is
  only a fallback for a MuseScore build that writes no SVG;
- the scan is a raster, so it keeps the reader's own `barLine_*` detections
  (`<stem>.dets_*.json`) when present, with the ink test as a fallback. When the reader missed a
  barline, the reader's change records still give the true bar count for that system: a missing
  **final** barline is closed at the staff's right edge (where that barline stands, so it is not a
  guess); a missing **internal** barline splits the widest cell and both halves are marked
  `scan_cells_inferred` and left untinted. Everything after the repair keeps its measured boundary,
  so one missed barline no longer throws away the page;
- the render and the scan should each detect as many measures as the page MusicXML declares. A
  final double barline emits a second stroke on the staff edge, so a trailing cell narrower than
  20% of its system's median is folded into the bar on its left (`trailing_slivers_folded`) and the
  page still aligns completely. If the counts still disagree, the sheet tints the sturdy prefix:
  systems are compared in order and the tint stops at the first system whose two counts differ, so
  a wrong bar is never painted. The action is recorded in `render_layout_mismatch` /
  `scan_layout_mismatch` with the number of bars it could tint. `aligned` is true only when both
  columns were overlaid in full; otherwise `partial` / `tinted_measures` say how far it got, and
  the cover shows "partial k/m" (or "scan only" for a MusicXML-only run);
- measure numbers are global (page offsets are summed from the earlier pages' measure counts; use
  `--no-offset` to number every page from 1) and `≠` marks a bar with a measure-length violation
  from the scorepipe report;
- both sides get the same colour and the same filled badge; a tall-page render spreads its systems
  over 30 inches, so blank bands taller than 5% of the page are collapsed before drawing (the count
  is recorded as `render_collapsed_bands`), while the scan keeps its real spacing;
- the legend (red/yellow rows, the `≠` row when there are length errors, and a footnote) sits in
  the caption band under both columns, never over the music;
- the first page's render gets the title/credit block of the merged score (`--title-from`, default
  `<pages>/../score.musicxml` or `<pages>/score.musicxml`), because a page file carries notes but no
  title; the credits are positioned like the previous skill's `write_credits` (title centred near
  the top, composer right-aligned), since MuseScore otherwise stacks them at the bottom of the page.
  Both columns then show the same title block, which is what makes the first page readable at a
  glance. The copy is written next to the render, never over the OMR page file.

Known limit: the scan side depends on the reader's barline detections. A missed final barline is
closed at the staff edge (measured: First Step page 1); a missed internal barline splits the widest
cell, and both halves of that split are marked `scan_cells_inferred` and left untinted so a guessed
boundary never paints a bar. The render column stays exact either way.


Outputs, named after the previous skill: `<page>.compare.png`, `<page>.compare.json`,
`review-sheets.pdf` (every page bound into one A4-landscape 300-dpi file, in page order, opened by a
cover/TOC page that lists page number, OMR page stem, measure count, red/yellow count and alignment;
each comparison page carries a footer with the score name, the source file name and `page i/N`),
`review_sheet.md` (the score-wide priority list: objective length errors first, then by score) and
`review_sheet_summary.json` (three-state status, red/yellow/length counts, exit 1 when incomplete).
`review.py` copies `review-sheets.pdf` to the delivery root as well and records it in
`review-report.json` / `delivery.json`, so the human-facing file sits next to `score.pdf`.
`_render/` under `review/sheets/` is the per-page render cache (the exact MusicXML/PDF/SVG the sheet
used); it is evidence, not an output.

A sliver cell (a stem read as a barline) is folded into its neighbour, except for the first and
last bar of a system, which are short for real.

The old tool also *stacked* a page whose MusicXML rendered as several pages; that is kept.

Known limit: the ink test can still over- or under-detect a bar on a dense page. When the counts
disagree the sheet tints only the prefix both columns agree on and records the mismatch, so the
page stays useful without ever painting a bar it could not verify.

## Required human checks

- Start from `review/confidence/review.md`: it ranks what to verify first, per page.
- Open `review-sheets.pdf` and work through `review/sheets/review_sheet.md` in order: each tinted
  bar is tinted in the same colour and the same number on both columns.
- Compare the source and rendered page around every patch, especially 8va extent.
- Resolve or explicitly accept every unresolved/correction.
- Confirm credits and tempo placement in the rendered first page.
- Keep the review directory and the OMR page directory with the delivery.
