# Acceptance evidence

Date: 2026-11-20. Commands run from the project root with the system Python.

## Test suite

```
python -m unittest discover -s tests
Ran 102 tests
OK
```

Coverage:

| area | tests |
|---|---|
| fixed point + verifiers | `test_pipeline.py` |
| slur sanitation, short-measure padding | `test_passes.py` |
| voice numbering | `test_voices.py` |
| duplicate notes | `test_duplicates.py` |
| redundant clefs and key signatures | `test_clefs.py` |
| overflow notes repeating the next barline | `test_overflow.py` |
| trailing duplicate measure | `test_tail.py` |
| overflow notes and barline-crossing splits | `test_overflow.py`, `test_rebase.py` |
| aligned voice merging | `test_merge.py` |
| page merging and page-directory CLI | `test_loader.py` |
| page-level tie/slur/pedal restoration | `test_page_restore.py` |
| page-level arpeggio/articulation/wedge restoration | `test_page_notation.py` |
| external OMR command front-end | `test_omr.py` |
| PDF text layer, measure-box assignment | `test_pdf_producer.py` |
| MusicXML -> mscz -> display combined driver | `test_mscz_export.py` |
| display text and pedal dedupe | `test_display_dedupe.py` |
| anacrusis (pickup) detection | `test_pickup.py` |
| credits injection and idempotence | `test_credits.py`, `test_credits_display.py` |
| mscx tie spanner restoration | `test_mscx_ties.py` |
| chord member duration conflicts | `test_mscx_fragments.py` |
| fragmented measures rebuilt as voice layers | `test_layers.py` |
| short-voice padding keeps the next staff aligned | `test_fill.py` |
| chord/cursor semantics verifier | `test_semantics.py` |
| empty staff measure rests | `test_empty_staves.py` |
| golden-score comparison | `test_compare.py` |
| multi-voice staff retiming / fill conflict | `test_voice_merge.py` |
| mscx display passes | `test_display.py` |
| mscz archive roundtrip + re-open idempotence | `test_archive.py` |
| facts injection idempotence | `test_facts.py` |
| tempo / gradual tempo facts | `test_display_facts.py`, `test_gradual.py` |
| CLI, `--check`, `--list-passes` | `test_cli.py` |
| JSON run report | `test_report.py` |
| registry validation | `test_registry.py` |
| fact producers | `test_producers.py` |

## Registry

```
scorepipe --list-passes
```

39 entries: 24 structural (23 mechanical + 1 analysis), 2 inject, 13 display. Every mechanical pass
declares an `owns` property and a monotone measure; `validate_registry` fails the run with exit
code 2 if that is violated.

## Real scores

```
scorepipe laputa.musicxml --check --report laputa.json
```

- `laputa` (63 measures): **verifier clean**. Ties, slurs, rest visibility, duplicate notes,
  clefs, keys and measure lengths all pass after `rebase_measures` split the overlong first-bar
  note that used to make staff 2 end at 6.5 beats.
- `summer` (55 measures): **verifier clean**. The former m36–m40 block (4.25–5.5 beats in 4/4) was
  repaired: notes starting past the barline moved into the next bar as a new voice, and notes
  crossing the barline were split with a tie.
- `laputa` **page directory** (copisteria output: 3 files, 26 / 23 / 14 measures): merged to one
  63-measure score by `merge_pages`, then verifier clean. On this run `restore_page_pedals`
  reported 36 adjustments and `restore_page_wedges` 20; the structural phase converged in 3 rounds.
  Ties, slurs, arpeggios and articulations needed no restoration because the merged file already
  carried them.
- `laputa.mscz`: display pipeline runs to a fixed point with **0 changes** and a clean mscx
  verifier — the display invariants hold on a real MuseScore file.
- Credited real run: `scorepipe laputa.musicxml --title Innocent --composer "Joe Hisaishi" --check`
  injects both credits (before `<part-list>`) and still verifies clean.
- **Whole chain**: `scorepipe laputa.musicxml --mscz-out laputa_pipeline.mscz` produced a 68 KB
  mscz; the display phase converged in 2 rounds (72 changes) and the mscx verifier was clean. This
  is the `structural -> MuseScore conversion -> display` chain end to end on a real score.
- **Chord ties and duration conflicts** (laputa, after the showcase review): the root cause was
  the OMR layout, not the converter. copisteria wrote m2's chord as three same-voice blocks
  separated by backups and put F6 (a dotted quarter) at the same onset as a whole-note chord;
  MuseScore merges such blocks into one chord, which loses ties and coerces durations.
  `rebuild_voice_layers` now rebuilds such measures as non-overlapping voices (chord whole +
  F6 dotted quarter in its own voice + the eighth/half run), and `restore_page_ties` propagates a
  page tie between two chords to every shared pitch, as the old skill did. Result: mscx m1 has
  7 tie spanners and m2 6, F6 is a filled dotted quarter, and the big chords are tied across the
  barline.
- **Fidelity against the old skill** (laputa, normalised pitch/onset/duration multiset, voice
  ignored): the symbol mismatch is **4.17%** (23 missing + 26 extra), down from 18.35% at the start
  of this review. The last fix was `merge_staff_voices`, the old skill's aggressive pass: when a
  staff has several voices and their notehead fills agree, the measure is rebuilt as one line,
  each chord lasting until the next onset (fill conflicts are still skipped). Remaining differences
  are concentrated in m30–m32 (one ambiguous bass measure where OMR gives a whole note and a
  quarter line) and isolated single symbols in m42–m47 and m61–m62.
- **MuseScore's incomplete-measure warnings** (mscx `measure_lengths` verifier): the laputa mscz
  went from 12 flagged measures to **1** (m33, a measure whose OMR source carries two overlapping
  rests in one voice: 2+1+1 beats of rest). The display passes now move text-only voices into the
  chord voice and remove zero-length/empty voice slots, which were the other eleven warnings.

These are baseline reports, not failures of the pipeline: they show the verifiers catching the
same problems the old ad-hoc pipeline found, with stable codes.

## Known gaps (documented, not hidden)

- Voice merging beyond exact alignment is not ported; the pass refuses anything that needs a
  retiming decision.
- Credits cover title/subtitle/composer/lyricist styles and are moved into the mscx title frame;
  finer title-frame layout (font size, spacing) is left to MuseScore's own styles.
- The old review-sheet / diagnostics HTML generator is not ported; the JSON run report is the
  machine-readable equivalent.
- The OMR front-end runs an external command; a ready-made copisteria command line and its
  environment setup are not bundled in this project.
- The display phase only runs through the `--mscz-out` chain (or on an existing `.mscz`); it is not
  a pass phase inside the MusicXML-only run.
- The PDF producer handles digital PDFs (text layer + layout); the laputa scan has no text layer
  and yields zero words, which is why scanned scores still need the agent/vision path for marks.
- `rebase_measures` refuses to push an overflow that would itself land past the next barline; such
  a case is still reported by the verifier rather than cascaded further.
