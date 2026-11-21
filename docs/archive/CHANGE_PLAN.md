# Change plan (archived 2026-11-21)

This is the working plan used during the port and the Sincerely investigation. Completed items are
kept because they explain the current code; open items are the hand-off list for later work.

## Completed

| Change | Result |
|---|---|
| Page divisions normalized to LCM | page merge no longer produces uneven measures |
| `merge_staff_voices` uses effective time signature | inherited 2/4 bars no longer padded as 4/4 |
| Rest onsets are merge boundaries | intentional rests are not deleted |
| Sustained-note protection | a notated quarter is not shortened into another voice's run |
| Page-slur restoration owns page scores | no clear/re-add loop with sanitize |
| Positional slur signatures | voice moves do not destroy valid page slurs |
| Tuplet measures skipped by voice merge | no triplet-to-quarter destruction; P2 no longer falls to 34.66% |
| Beat/source-aware beam grouping | mixed 8th/16th runs use the beat grid; complete source begin/end groups are hard boundaries |
| Tempo text is written once | no `q = 72 ♩=72` duplicate |
| Arranger credit merges with composer | no overlapping second credit |
| Padded pickup moved to bar end | Sincerely A4 sits at the end of the first bar |
| First courtesy time signature deleted | no grey 4/4 when Show Invisible is on |
| Stray post-barline rests dropped | m24 no longer cascades into m25/m26 and deletes their second halves |
| `drop_overflow_rests` cleanup | late padding rests no longer fail measure-length verification |
| Skill packaging | SKILL.md, preflight, end-to-end wrapper, references |
| Agent visual facts | page packet, evidence validation, page coverage, corrections review |
| Constrained notation patches | `ottava` prototype compiles 8va/8vb to MusicXML octave-shift; render verified |
| Delivery review loop | `scripts/review.py` blocks incomplete coverage/unresolved/corrections, runs pipeline and writes before/after review report |

## Deferred / next

| Item | Why it is deferred |
|---|---|
| Agent/vision facts extraction | workflow exists (prepare/validate/merge/coverage/corrections); page-by-page review and resolution UX are the remaining delivery work |
| Full `BeamGrouper` | same-value runs still rebuild as one run; compound metre and source boundaries need a dedicated model |
| Tuplet-preserving voice merge | current safe behavior skips tuplet measures; proper ratios/nested tuplets are a separate design |
| Lindenbaum P2 | raw OMR is ~51%; pipeline currently ~51.4%; not a converter regression |
| OMR octave/ledger corrections | pipeline must not invent pitches; needs explicit review/correction facts |
| Delivery packet format | current wrapper emits MusicXML/MSCZ/PDF/report; visual facts and acceptance sheet are next |

## Decision log

- Keep copisteria external; do not vendor its dependencies.
- Feed the pipeline the per-page directory, not the old final MusicXML.
- A pass is not trusted until it has a contract and a fixture.
- Verifier violations are blockers unless the user explicitly accepts the defect.
- Do not "fix" an OMR pitch by guessing; record evidence and require an explicit correction.
