# Migration plan (archived)

Status: **completed 2026-11-21**. This file is kept for provenance; it is not an active roadmap.

## Goal

Replace the monolithic `copisteria-to-musicxml` post-processing with a pass-based pipeline that is
testable, idempotent, and independently verifiable, while keeping copisteria as the external OMR
engine.

## Phases

| Phase | Content | Status |
|---|---|---|
| 0 | repository, IR, pass contract, fixed-point runner, trace, verifier | done |
| 1 | structural passes: ties, time/key/clef dedupe, voice rebuild, merge, measure fill/rebase | done |
| 2 | page merge and page-level tie/slur/pedal/wedge/arpeggio/articulation restoration | done |
| 3 | `.mscz` display passes, MuseScore conversion boundary, display verifiers | done |
| 4 | facts producers and idempotent inject passes (credit/marks/tempo/style) | done |
| 5 | external OMR front-end and page-directory loading | done |
| 6 | skill packaging: SKILL.md, preflight, end-to-end wrapper, references, delivery contract | done |

## Deliberately not migrated

- The old `convert.py` monolith and its internal `music21` rewrite path.
- The old aggressive voice merge as the default; scorepipe owns structural repair and can skip
  unsafe merges.
- Old text-layer assumptions; facts are explicit JSON and never silently mutate the score.
- The old "one command writes everything" delivery claim; the skill now requires verifier and
  visual evidence.

## Remaining migration gaps

Tracked in [`CHANGE_PLAN.md`](CHANGE_PLAN.md), not in this archived plan:

- agent/vision facts extraction for delivery;
- full beam-group model for same-value runs and compound metre;
- tuplet-preserving voice merge;
- Lindenbaum P2 OMR-quality work.

## History

The old skill is at `musicxml_skill_dev/copisteria-to-musicxml`. Its page output is still used by
the new pipeline, but its final merged MusicXML is not: page context is required for page-level
restoration. The new pipeline was built and accepted against Gute Nacht, Aus meinen Tränen,
Die Wetterfahne, Der Lindenbaum, Laputa, and Sincerely.
