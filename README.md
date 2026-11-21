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
| `mark_pickup` | structural | `pickup-marking` | short opening bar that is an anacrusis |
| `pad_empty_staves` | structural | `empty-staff-rests` | silent staff without a measure rest |
| `rebuild_voice_layers` | structural | `voice-layers` | fragmented same-voice blocks MuseScore would coerce |
| `merge_staff_voices` | structural | `staff-line` | multi-voice staff whose durations drift |
| `drop_redundant_voices` | structural | `redundant-voices` | secondary voice that only repeats the primary |
| `unhide_rests` | structural | `rest-visibility` | hidden rests |
| `sanitize_slurs` | structural | `slur-endpoints` | unmatched / >N-bar endpoints |
| `normalize_voice_numbers` | structural | `voice-numbers` | voice labels not canonical by density (1–4, 5–8, … per staff) |
| `fill_short_measures` | structural | `rest-padding` | voices ending before the barline |
| `drop_text_voice_rests` | display | `text-voice-rests` | rests inside text-only voices |
| `unhide_real_rests` | display | `rest-visibility` | hidden non-measure rests |
| `drop_padding_voices` | display | `padding-voices` | rest-only voices next to a chord voice |
| `drop_secondary_voice_rests` | display | `secondary-voice-rests` | rests on voices other than voice 1 |
| `normalize_range_spanners` | display | `range-spanner-anchors` | HairPin/Pedal/GradualTempoChange anchored on a carrier voice |
| `apply_text_facts_style` | display | `text-display-style` | fact text without its alignment |
| `canonical_voice_order` | display | `voice-order` | voice slots out of canonical order |
| `dedupe_pedal_spanners` | display | `pedal-spanners` | duplicate pedal spanners |
| `dedupe_text_objects` | display | `display-text-duplicates` | duplicate text objects in a measure |
| `merge_text_voices` | display | `text-voice-slots` | zero-length voice holding only text |
| `drop_empty_voices` | display | `empty-voices` | voice slot with no notes/rests/spanners |
| `apply_credits_display` | display | `display-credits` | title/composer missing from the mscx title frame |
| `restore_mscx_ties` | display | `mscx-ties` | ties the MuseScore importer dropped |
| `split_chord_fragments` | display | `mscx-chord-fragments` | chord members whose duration the importer coerced |
| `measure_length_report` | structural | – | analysis only (notes, never mutates) |
| `drop_trailing_duplicate_measure` | structural | `measure-list` | trailing duplicate final bars |
| `drop_duplicate_notes` | structural | `duplicate-notes` | duplicate notes at one position |
| `drop_overflow_duplicates` | structural | `overflow-notes` | overflow notes repeating the next barline |
| `rebase_measures` | structural | `measure-content` | overflow beats beyond the barline |
| `merge_aligned_voices` | structural | `voice-merge` | mergeable secondary voices |
| `restore_page_ties` | structural | `page-ties` | page ties missing from the merged score |
| `restore_page_slurs` | structural | `page-slurs` | page slurs missing from the merged score |
| `reconcile_tie_slurs` | structural | `tie-slur-reconciliation` | ties/slurs that OMR confused |
| `merge_adjacent_slurs` | structural | `slur-chains` | two slurs meeting on one note |
| `restore_beams` | structural | `beams` | unbeamed or partially beamed eighth-note runs |
| `restore_page_pedals` | structural | `page-pedals` | pedal directions that differ from the page |
| `restore_page_arpeggios` | structural | `page-arpeggios` | page arpeggio marks missing from the merged score |
| `restore_page_articulations` | structural | `page-articulations` | page articulations missing from the merged score |
| `restore_page_wedges` | structural | `page-wedges` | wedge directions that differ from the page |
| `upgrade_tempo_texts` | display | `tempo-objects` | tempo words still plain staff text |
| `upgrade_gradual_texts` | display | `gradual-spanners` | rit./rall./accel. words needing a paired spanner |
| `apply_credits_facts` | inject | `credits` | title/composer credits from facts |

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
voices and voice order. On the MusicXML side `VERIFIERS` checks duplicate ties, redundant time
signatures, hidden rests, chord/cursor semantics (an orphan `<chord/>` or a negative cursor is an
error an XSD cannot see) and per-voice measure lengths.

## Sanity contracts for passes

A pass is not trusted because it was migrated; it is trusted when it obeys a declared contract.
[`scorepipe/sanity.py`](scorepipe/sanity.py) snapshots a document (measure, staff, voice, rest, pitch,
onset, duration, chord, ties, time signature) and diffs two snapshots. `PassContract` declares which
effects are allowed (add/remove notes, move onsets, retime, change pitch, add/remove measures, change
voices); everything else is a violation. Every run also checks idempotence, chord/cursor structure,
"a healthy measure stays healthy", "no new verifier violations" and "no unique sounding pitch
disappears".

[`tests/test_pass_sanity.py`](tests/test_pass_sanity.py) parameterises every registered mechanical
pass over a synthetic fixture and its contract, and a coverage test fails when a new pass is added
without a fixture and contract. [`SANITY.md`](SANITY.md) is the full 39-pass audit: category,
contract, adversarial fixtures and the currently known violations.

```
python -m pytest tests/test_sanity.py tests/test_pass_sanity.py -q -p no:cacheprovider
```

## Comparing against a golden score

`scorepipe.compare.compare(golden, candidate)` reduces both files to (measure, staff, onset, duration,
pitch) symbols, ignoring divisions and voice layout, and reports missing/extra symbols with a ratio
and the worst measures. The CLI wires it to `--compare-golden`:

```
scorepipe pages/ -o out.musicxml --compare-golden golden.musicxml
compare: 8.35% mismatch (missing 37, extra 63)
```

Use it after every pass change; it is the objective replacement for eyeballing a render.

## Loaders

`scorepipe.loader.merge_pages(paths)` concatenates per-page MusicXML (with per-page measure
numbering) into one score, renumbers measures globally and keeps `measure_counts` so later passes
can map a measure back to its page (`MergedPages.page_of_measure`). Pages may declare different
`<divisions>`; the loader picks their LCM and rescales every duration, backup, forward and offset to
that common resolution before concatenating. `load_pages(dir)` sorts the directory. The CLI accepts
a directory as input and runs the structural pipeline on the merged score; page-join duplicates
(time signatures, clefs, keys) are cleaned by the normal passes.

When the input is a page directory, the loader model is put on `Context.pages`, which enables the
page-restoration passes: `restore_page_ties`, `restore_page_slurs` (all open starts per staff/number
are kept and a stop picks the best same-pitch/voice, shortest-span candidate, with a 6-bar guard),
`restore_page_pedals` and `restore_page_wedges` (page-accurate onsets, existing directions replaced
only when they differ), `restore_page_arpeggios` (page marks are collapsed per chord and written once
on the chord's base note; a single split note no longer carries an arpeggio) and
`restore_page_articulations` (marks attached to the merged note by position).

## OMR front-end

The converter itself stays external; the pipeline runs a command with two placeholders and then
loads whatever page MusicXML it wrote:

```
scorepipe scan.pdf --omr 'python -m copisteria.cli {pdf} {outdir}' --omr-dir out/ --check
```

`scorepipe.omr.run_omr` fails loudly if the command exits non-zero or writes no pages; on success
the directory is merged exactly like `--omr` pages / a page directory, and the page model is
available to the restoration passes.

## OpenScore Lieder corpus

`tests/corpus/lieder` holds an OpenScore Lieder case with both directions of the test:

- `gute_nacht.mxl` / `ground_truth.musicxml` — the human-transcribed source score;
- `input.pdf` — a MuseScore 4 render of that source, used as synthetic OMR input;
- `build_case.py` — extract the MXL rootfile and render the PDF;
- `compare_parts.py` — compare multi-part OMR output to the ground truth by
  `(measure ordinal, onset, pitch, duration)`, with active-division normalisation and pickup
  numbering alignment.

Gute Nacht is two parts (vocal + piano, 105 measures). Copisteria's partial output matches it at
98.24% / 98.38% by part; the vocal part is also verifier-clean after the structural pipeline. The
piano part still makes the structural fixed point unstable at its last measure, so it remains an
OMR-comparison case. See `tests/corpus/lieder/README.md` for provenance and rebuild commands.

## Combined driver

`--mscz-out` runs the whole chain in one command: structural fixpoint on MusicXML, MuseScore
conversion, then the display fixpoint on the resulting `.mscz`. The conversion is a boundary, not a
pass; `mscz_export.export_and_display` owns it and re-saves the archive.

```
scorepipe score.musicxml --mscz-out score.mscz
```

## Endpoint pairing

Slurs and ties are written as separate start/stop marks, and OMR files reuse numbers. A plain stack
pairs the oldest open start with a much later stop (the laputa m7→m10 three-bar slur). 
Page endpoints are first sorted by musical position `(measure, onset, stop-before-start)`, so XML
voice-block order cannot create a long arc. [`scorepipe/core/pairing.py`](scorepipe/core/pairing.py)
then keeps **all open starts per key** and, when a stop arrives, chooses the best valid one: an
optional scorer prefers the same pitch/voice, otherwise
the shortest span wins, with the latest start as tie-break. A start that is after the stop, or a pair
longer than `max_span`, is rejected; unpaired endpoints become orphans instead of deleting a whole
cluster. This restores laputa m8 C5→m10 D5 while still refusing the old m7→m10 arc. It is shared by
`restore_page_slurs`, `restore_page_ties`, `sanitize_slurs` and the MusicXML→mscx tie export.
Tie propagation from a printed chord only applies to notes with the same duration at both endpoints,
so a different rhythmic voice at the same onset does not inherit the tie.
`reconcile_tie_slurs` then removes a slur duplicated by a tie (including when it shares the tie
start/stop timing but lands on another chord member), converts a tie that has another pitch
between its endpoints into a slur, and converts a contiguous same-pitch slur into a tie.
`merge_adjacent_slurs` joins two slurs whose stop note is the next slur's start note.
`restore_beams` runs after the voice merge and rebuilds beam groups for consecutive
eighth-or-shorter notes, rebuilding the whole contiguous run so a partial source group cannot
leave a first note on a separate `begin`.

## Facts

`scorepipe.facts.load_facts` reads a JSON file produced by the text layer or by the agent.
`scorepipe.producers` adds a `Producer` protocol: `JsonProducer`, `TextLayerProducer` (tab-separated
`measure<TAB>beat<TAB>placement<TAB>text` sidecar), `PdfTextProducer` (poppler `pdftotext -bbox`
plus a measure-box layout) and `CompositeProducer`; the CLI picks one by file suffix. The
`apply_marks_facts` inject pass turns marks into words / rehearsal / metronome directions and is
idempotent (a text already present in the measure is skipped). Facts never edit the score
directly; they are data. Marks may carry `italic`, `font_size` and `justify`; the words element gets
the font attributes and `apply_text_facts_style` applies `justify` as an mscx `align`, so imported
commentary is smaller, italic and centred instead of using the default StaffText layout.

A PDF layout file gives each measure's box in PDF points:

```json
{"pages": [{"page": 1, "measures": [{"number": 9, "x0": 80, "y0": 690, "x1": 260, "y1": 730}]}]}
```

Words are assigned to the measure whose box contains their centre; without a layout the producer
still returns the words but no marks. A scanned PDF has no text layer and yields zero words — that
is the agent/vision path, not this producer.

```
python -m scorepipe.cli score.musicxml --facts marks.json --trace -o out.musicxml
python -m scorepipe.cli score.mscz --trace -o out.mscz     # display pipeline
python -m scorepipe.cli pages_dir/ --check                 # merge per-page MusicXML first
python -m scorepipe.cli score.musicxml --mscz-out out.mscz # + MuseScore conversion + display phase
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


