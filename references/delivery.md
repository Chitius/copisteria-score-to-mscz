# Delivery checklist

## Required artifacts

```text
out/score/
  score.musicxml          semantic master (untruncated)
  score.mscz              delivered editable copy (truncated when needed)
  score.pdf               render of score.mscz
  truncation-report.json  when the editable copy trimmed an overfull voice
  review-sheets.pdf       all page comparisons in one A4-landscape PDF at 300 dpi (cover/TOC, footer)
  review/sheets/          per-page measure-level proof sheets
  review/confidence/      per-page symbol heat map
  report.json             phases + trace + verifier
  review-report.json      page coverage + blockers + artifact paths
  timing-report.json      baseline vs delivered measure-length findings
  work/copisteria/        page OMR output, reading JSON, HTML
  semantic/               only when truncated: untruncated reviewed tree
    score.musicxml
    score.mscz
    score.pdf
    report.json
  mechanical/             pipeline output without agent facts/patches
    score.musicxml
    score.mscz
    score.pdf
    report.json
  forced-truncation/      editable copy; semantic_authority=false
    score.musicxml
    score.mscz
    score.pdf
    truncation-report.json
```

The reviewed artifacts are the root files; `mechanical/` is the no-agent-proposal baseline kept for
comparison and audit. `forced-truncation/` is the default overfull-voice repair: when it had to trim
something it *is* the delivery (root `score.mscz`/`score.pdf`), the untruncated reviewed tree is kept
in `semantic/`, and root `score.musicxml` stays the untruncated semantic master because the trim is
an mscx display repair. Do not deliver only one of these trees.

If MuseScore is unavailable, deliver MusicXML + report and state that the `.mscz`/PDF were not
produced. Do not fabricate a render.

A run with `--skip-facts` is a **mechanical-only** delivery: no credits or tempo marks were
injected, `review-report.json` has `facts_skipped: true` and a matching finding, and the reviewed
tree equals the baseline. It is a legitimate first pass for someone exploring the pipeline, but it
must be described as "mechanical, facts not applied", never as a reviewed edition.

## Acceptance

Before saying "done":

- [ ] every phase reports `stable=true`;
- [ ] `report.json` has no verifier violations;
- [ ] both `mechanical/` and the reviewed tree exist, and the mechanical tree contains no agent
      facts/patches;
- [ ] `review-sheets.pdf` exists and has been opened once; every page in it is `aligned: true`
      (or the mismatch is explained in `review-report.json`);
- [ ] when the forced copy trimmed something, `semantic/` is present and `truncation-report.json`
      lists every operation;
- [ ] the first measure / pickup and the final bar have been inspected;
- [ ] at least one dense page and one page seam have been inspected;
- [ ] the output has been compared with a ground truth when one exists;
- [ ] known OMR defects are listed explicitly (with measure numbers), not implied away.

## Interpreting the report

```json
{"phases":[{"phase":"structural","rounds":4,"stable":true}],
 "verifier":[],
 "trace":[...]}
```

When `--mscz-out` is requested, `report.json` combines structural, inject and display phases, traces,
analysis and verifier violations. A failed run may still leave draft MSCZ/PDF artifacts for review;
`delivery.json` records `ready`, `pipeline_exit` and `render_exit`. Draft artifacts do not make a failed
run deliverable.

- `stable=false`: a pass did not reach a fixed point. Do not deliver until understood.
- `verifier` non-empty: structural or display problem. Treat as a blocker unless the user accepts
  the specific defect.
- `analysis` notes such as `measure-length` are diagnostics, even if they do not fail the run.
- `trace` is the audit trail for a regression; keep it with the delivery.

## Reporting known defects

Use a short table:

| Measure | Defect | Evidence | Decision |
|---|---|---|---|
| m30 | OMR reads C8 | raw page XML / crop | keep as OMR defect or explicit correction |

Do not "fix" a pitch by guessing. If a correction is approved, record the correction and re-run
the verifier.

## Known limitations

- The agent/vision facts workflow (`prepare` → agent JSON → `validate`/`merge`) still requires
  per-page review and resolution of `unresolved` claims.
- Same-value beam runs are rebuilt as one run rather than by a full compound-metre grouper.
- OMR octave/ledger errors are preserved; the pipeline does not transpose or silently correct pitch.
