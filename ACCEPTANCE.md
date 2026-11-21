# Acceptance evidence

Date: 2026-11-20. Commands run from the project root with the system Python.

## Test suite

```
python -m unittest discover -s tests
Ran 136 tests
OK

python -m pytest tests/test_sanity.py tests/test_pass_sanity.py -q -p no:cacheprovider
75 passed
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
| endpoint pairing with reused slur numbers | `test_pairing.py`, `test_page_restore.py` |
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
| redundant secondary voice removal | `test_redundant_voices.py` |
| per-note fill protection when retiming | `test_voice_merge.py` |
| empty staff measure rests | `test_empty_staves.py` |
| golden-score comparison | `test_compare.py` |
| pass sanity framework (74 pytest cases) | `test_sanity.py`, `test_pass_sanity.py` |
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

41 entries: 25 structural (24 mechanical + 1 analysis), 2 inject, 14 display. Every mechanical pass
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
  ignored): the symbol mismatch is now **4.55%** (20 missing + 34 extra). It was 1.20% before the
  per-note fill protection, but that lower number came from copying an old-skill mistake: the old
  aggressive merge retimed legitimate sustained notes into quarters. The current merge protects any
  note whose retimed duration would change its filled/hollow notehead, so m25's E♭3 stays a whole
  note in its own voice and m27's C3 whole note survives (the old output had both as quarters).
  `drop_redundant_voices` still removes the duplicate bass voice that MuseScore stored as cross-staff
  notes on the treble staff. Remaining differences are concentrated in m25–m32 and m42–m45.
- **Per-note fill protection** (`merge_staff_voices`): the old `fill_conflict` test skipped or
  allowed a whole measure based on whether a *primary note* overlapped; it missed a long note over a
  rest. The pass now iteratively protects every note whose proposed retimed duration would cross the
  2-beat hollow/filled boundary, merges the rest, and keeps protected notes in their own voice with
  their original duration. This is the rule the old `fill_conflict` was trying to express.
- **Reused slur numbers** (laputa m7–m10): the page writes four starts numbered 1–4 at m7 and reuses
  number 1 at m8/m10. A stack paired m7 G4 with m10 D5, producing a three-bar arc. The shared
  endpoint pairer (`scorepipe/core/pairing.py`) keeps every open start and picks the best valid stop
  match (same pitch/voice first, then shortest span); the mscz now has `m7→m8` (same-pitch G4),
  `m8 C5→m10 D5` (the legitimate phrase), and `m10→m12`, with no m7→m10 arc. Regression pages cover
  both the restored pair and the refused arc (`test_pairing.py`, `test_page_restore.py`).
- **Arpeggios belong to a chord**: `restore_page_arpeggios` used to copy the page mark to every
  note; after `merge_staff_voices` split F6 out of laputa m1's big chord, MuseScore promoted the
  mark on that single note and left the chord without an `Arpeggio`. The pass now collapses page
  marks per `(measure, staff, onset)`, chooses the merged chord with at least two notes, writes one
  mark on its base note, and removes marks from single-note fragments. The m1 mscx now has
  `Arpeggio = True` on the 7-note chord and none on F6 (`test_page_restore.py`,
  `test_page_notation.py`).
- **Secondary-voice rests** (display): voice 1 defines the bar, so rests on later voices are
  redundant glyphs. `drop_secondary_voice_rests` replaces a secondary rest before a later chord with
  a `<location>` gap (timing unchanged) and removes rests after the last chord. The old skill had the
  narrower `hide_covered_rests`, which only hid a rest fully covered by another voice's sound; m29's
  trailing bass rest was outside that rule. The generated m29 now matches the hand-edited mscz:
  voice 2 is `<location>1/4</location> + chord`, no rest (`test_display.py`).
- **MuseScore's incomplete-measure warnings** (mscx `measure_lengths` verifier): the laputa mscz
  now reports **0** flagged measures. It started at 12: eleven were text-only/empty voice slots
  (moved into the chord voice or removed) and the last was m33's overlapping rests, which the
  `rebuild_voice_layers` duplicate detection now folds away. Voices whose `<location>` carries a
  gap are skipped by the verifier because that fraction arithmetic belongs to MuseScore.

These are baseline reports, not failures of the pipeline: they show the verifiers catching the
same problems the old ad-hoc pipeline found, with stable codes.

## Known gaps (documented, not hidden)

- `SANITY.md` remains the audit snapshot. The open structural violations are fixed and pinned by
  tests: `rebase_measures` shrinks the closing backup and numbers overflow voices uniquely
  (`test_rebase.py`); `drop_overflow_duplicates` removes chord members with their base
  (`test_overflow.py`); `drop_trailing_duplicate_measure` no longer eats a run of short bars
  (`test_tail.py`); `pad_empty_staves` uses the real cursor length and skips pickups
  (`test_empty_staves.py`); `split_chord_fragments` pads by the measure's own time signature and
  keeps the moved note's other children (`test_mscx_fragments.py`); `drop_duplicate_notes` keeps the
  longer duplicate (`test_duplicates.py`); `merge_aligned_voices` no longer doubles a pitch already
  in the chord (`test_merge.py`). `merge_staff_voices` keeps other staves' `<forward>` gaps and the
  laputa m31 sustained chord, and preserves tie/slur/articulation children when the duration is
  unchanged (`test_voice_merge.py`); a retimed note still drops them, to be restored by the page
  passes when `Context.pages` exists.
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
