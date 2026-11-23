# Delivery checklist

## Required artifacts

```text
out/score/
  score.musicxml          semantic master
  score.mscz              MuseScore review copy
  score.pdf               rendered check
  report.json             phases + trace + verifier
  work/copisteria/        page OMR output, reading JSON, HTML
```

If MuseScore is unavailable, deliver MusicXML + report and state that the `.mscz`/PDF were not
produced. Do not fabricate a render.

## Acceptance

Before saying "done":

- [ ] every phase reports `stable=true`;
- [ ] `report.json` has no verifier violations;
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

## Current limitations (2026-11)

- The agent/vision facts workflow exists (`prepare` → agent JSON → `validate`/`merge`), but real
  delivery still requires per-page review and resolving `unresolved` claims.
- `der_lindenbaum` piano remains a low-quality OMR case; do not use it as a delivery showcase.
- Same-value beam runs are still rebuilt as one run (laputa m50 behavior).
- OMR octave/ledger errors are preserved; the pipeline does not transpose.
