# score-pipeline

A compiler-style proofreading and repair pipeline for OMR output (MusicXML) and its
MuseScore display form (`.mscz`).

This is a clean-room rewrite; it does not import anything from the old
`copisteria-to-musicxml` skill.

## Why

Long OMR pipelines accumulate order-dependent fixes: a pass that repairs X can be undone by a
later pass that rebuilds the measure, and a display cleanup can be re-broken by the importer.
The design here treats every single-purpose correction as a **pass** with an explicit contract,
runs the mechanical passes to a **fixed point**, and verifies read-only invariants at the end.

## Pipeline phases

1. **lower** – import/convert to the working IR (non-idempotent, runs once).
2. **structural** – mechanical passes on MusicXML (merge voices, restore ties/slurs, measure
   lengths). Iterated to a fixed point.
3. **facts** – text layer and agent-recognised facts (titles, tempo words, rehearsal marks).
   Produces JSON only; never mutates the score.
4. **inject** – mechanical passes that apply those facts. Iterated together with the structural
   passes so a later rebuild cannot lose them.
5. **display** – mechanical passes on the MuseScore `.mscx` (voice order, hidden rests, tempo
   objects). Iterated to a fixed point; idempotent with respect to re-saving.
6. **verify** – read-only invariant checks. Non-zero violations are reported, never auto-fixed
   inside the verifier.

The runner may loop `structural → facts → inject` if a verifier reports a repairable violation,
bounded by `max_outer_rounds`.

## Pass contract

Every pass declares:

- `name`, `phase`, `description`
- `owns`: the score properties it is allowed to write (one owner per property)
- `kind`: `mechanical` | `analysis` | `fact`
- `run(doc, ctx) -> PassResult(changed, notes)`

Mechanical passes must be **monotone** on a stated measure (e.g. "hidden rests", "dangling
endpoints", "measure-length violations"): a run may reduce it or leave it unchanged, never grow
it. The runner records per-pass change counts and a document hash per round; a round with no
changes is the fixed point.

## Status

Skeleton + mechanical passes + verifiers + tests. The port of the old skill's passes happens
incrementally, one pass per commit, each with a regression fixture.

Implemented passes:

| pass | phase | owns | monotone measure |
|---|---|---|---|
| `dedupe_ties` | structural | `tie-elements` | duplicate tie elements |
| `drop_redundant_time_signatures` | structural | `time-signatures` | repeated time signatures |
| `unhide_rests` | structural | `rest-visibility` | hidden rests |
| `sanitize_slurs` | structural | `slur-endpoints` | unmatched / >N-bar endpoints |
| `fill_short_measures` | structural | `rest-padding` | voices ending before the barline |

Run:

```
python -m scorepipe.cli score.musicxml --trace -o out.musicxml
python -m unittest discover -s tests
```

Round 1 output on the fixture:

```
structural r1 dedupe_ties                        2
structural r1 drop_redundant_time_signatures     1
structural r1 unhide_rests                       1
structural: rounds=2 changes=4 stable=True
verifier: clean
```

