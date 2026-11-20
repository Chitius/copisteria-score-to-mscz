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
| `drop_redundant_clefs` | structural | `clefs` | repeated clefs per staff |
| `drop_redundant_key_signatures` | structural | `key-signatures` | repeated key signatures |
| `unhide_rests` | structural | `rest-visibility` | hidden rests |
| `sanitize_slurs` | structural | `slur-endpoints` | unmatched / >N-bar endpoints |
| `normalize_voice_numbers` | structural | `voice-numbers` | voice labels not 1..n by density |
| `fill_short_measures` | structural | `rest-padding` | voices ending before the barline |
| `drop_text_voice_rests` | display | `text-voice-rests` | rests inside text-only voices |
| `unhide_real_rests` | display | `rest-visibility` | hidden non-measure rests |
| `drop_padding_voices` | display | `padding-voices` | rest-only voices next to a chord voice |
| `canonical_voice_order` | display | `voice-order` | voice slots out of canonical order |
| `measure_length_report` | structural | – | analysis only (notes, never mutates) |
| `drop_trailing_duplicate_measure` | structural | `measure-list` | trailing duplicate final bars |
| `drop_duplicate_notes` | structural | `duplicate-notes` | duplicate notes at one position |
| `drop_overflow_duplicates` | structural | `overflow-notes` | overflow notes repeating the next barline |
| `rebase_measures` | structural | `measure-content` | overflow beats beyond the barline |
| `merge_aligned_voices` | structural | `voice-merge` | mergeable secondary voices |
| `upgrade_tempo_texts` | display | `tempo-objects` | tempo words still plain staff text |
| `upgrade_gradual_texts` | display | `gradual-spanners` | rit./rall./accel. words needing a paired spanner |

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
inject: rounds=2 changes=4 stable=True
verifier: clean
```

## MuseScore container

`scorepipe.core.mscz.MsczArchive` opens a `.mscz` zip, finds the main `.mscx` through
`META-INF/container.xml`, exposes it as an `MsxcDocument`, and writes it back while preserving
every other entry (styles, settings). Display passes run on that document through the same
fixed-point runner; `MSCX_VERIFIERS` checks hidden non-measure rests, text-voice rests, padding
voices and voice order.

## Facts

`scorepipe.facts.load_facts` reads a JSON file produced by the text layer or by the agent.
`scorepipe.producers` adds a `Producer` protocol: `JsonProducer`, `TextLayerProducer` (tab-separated
`measure<TAB>beat<TAB>placement<TAB>text` sidecar) and `CompositeProducer`; the CLI picks one by
file suffix. The `apply_marks_facts` inject pass turns marks into words / rehearsal / metronome
directions and is idempotent (a text already present in the measure is skipped). Facts never edit
the score directly; they are data.

```
python -m scorepipe.cli score.musicxml --facts marks.json --trace -o out.musicxml
python -m scorepipe.cli score.mscz --trace -o out.mscz     # display pipeline
python -m scorepipe.cli score.musicxml --report run.json   # machine-readable trace
```

Analysis passes (`kind=ANALYSIS`) run once after the mechanical loop; their notes land in the
report. If an analysis pass mutates the score, the report marks it `mutated` — a programming
error, not a feature.

Registry checks run on every invocation: duplicate pass names, a pass registered under the wrong
phase, a mechanical pass without a monotone measure, or two passes claiming the same property are
reported and the run exits with code 2. `--list-passes` prints the registry:

```
python -m scorepipe.cli --list-passes
python -m scorepipe.cli score.mscz --check          # verify without writing
```


