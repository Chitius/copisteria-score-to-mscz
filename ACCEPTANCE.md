# Acceptance evidence

Date: 2026-11-20. Commands run from the project root with the system Python.

## Test suite

```
python -m unittest discover -s tests
Ran 174 tests
OK

python -m pytest tests/test_sanity.py tests/test_pass_sanity.py -q -p no:cacheprovider
79 passed
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
| tie/slur confusion reconciliation | `test_tie_slurs.py` |
| adjacent slur-chain merging | `test_slur_chains.py` |
| beam group restoration | `test_beams.py` |
| facts text styling / alignment | `test_facts.py`, `test_display_facts.py` |
| OpenScore Lieder ground-truth corpus | `test_lieder_corpus.py` |
| absolute musical-position contract | `test_positions.py` |
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
| pass sanity framework (79 pytest cases) | `test_sanity.py`, `test_pass_sanity.py` |
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

46 entries: 28 structural (27 mechanical + 1 analysis), 2 inject, 16 display. Every mechanical pass
declares an `owns` property and a monotone measure; `validate_registry` fails the run with exit
code 2 if that is violated.

## Real scores

```
scorepipe laputa.musicxml --check --report laputa.json
```

- `laputa` (63 measures): **verifier clean**. Ties, slurs, rest visibility, duplicate notes,
  clefs, keys and measure lengths all pass after `rebase_measures` split the overlong first-bar
  note that used to make staff 2 end at 6.5 beats.
- `summer` **page directory** (7 pages, 54 raw measures): the old-skill baseline is 55 measures and
  verifier clean, but the pages do not share a division scale (4 / 8 / 24). Before the loader fix
  this produced 14 verifier violations, negative cursors and a 70.78% golden mismatch. `merge_pages`
  now rescales every page to the LCM divisions and the full structural run is stable with **1**
  remaining violation (m54: 6 beats in 4/4) and a 12.97% mismatch. m54 looks like a genuine 4+2
  measure split (old baseline had m54=4, m55=2), not another division error; the showcase summer
  artifacts are now the full-pipeline result, with that one known violation.
- OpenScore Lieder `Gute Nacht` (`tests/corpus/lieder/gute_nacht`): the source MXL is the ground
  truth and a MuseScore-rendered A4 PDF is the synthetic OMR input. Copisteria's output scores
  98.94% (vocal) and 99.0% (piano) on sounding notes (98.24% / 98.38% including rests). The vocal
  part passes the structural pipeline cleanly with the same score; the piano part converges in 2
  rounds with a clean verifier and scores 99.0% on sounding notes (98.64% including rests) after the
  pipeline. The earlier "22 rounds" symptom was
  a meter bug: `merge_staff_voices` defaulted inherited 2/4 measures to 4/4 and padded them to four
  beats; it now uses `Document.effective_time_signature`. The merge also protects a notated sustained
  note when the merge would shorten it into another voice's run (m5 D4), and rest onsets are
  boundaries (m25's eighth rest is no longer deleted). On page runs `sanitize_slurs` is skipped;
  the page slur restoration owns those slurs, and re-pairing there orphaned a valid m54 slur and
  caused a clear/re-add loop. The corpus comparator normalises active divisions and matches
  `(measure ordinal, onset, pitch, duration)` multisets (`test_lieder_corpus.py`).
- Other Lieder OMR runs: `aus_meinen_traenen` 91.38% / 90.10% sounding and `die_wetterfahne`
  98.97% / 97.75%, both verifier-clean and losing no correct sounding event. `der_lindenbaum` P2 is
  the outlier (raw 50.89%); its first pipeline run fell to 34.66% because `merge_staff_voices`
  rebuilt 16th-triplets as fallback quarters and dropped `<time-modification>`. Tuplet measures are
  now skipped by the merge; P2 is 51.44% with 70 display measure-length warnings (raw was 64, previous
  pipeline 86). The raw piano remains poor and is kept as an OMR-comparison case.
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
  rest. The pass now protects every note whose proposed duration, measured against **all original
  onsets**, would cross the 2-beat hollow/filled boundary, merges the rest, and keeps protected notes
  in their own voice with their original duration. Protected notes still reserve their slot in the
  merged timeline (a gap/rest), so they cannot stretch a neighbour and cascade protection. This is the
  rule the old `fill_conflict` was trying to express.
- **Reused slur numbers** (laputa m7–m10): the page writes four starts numbered 1–4 at m7 and reuses
  number 1 at m8/m10. A stack paired m7 G4 with m10 D5, producing a three-bar arc. The shared
  endpoint pairer (`scorepipe/core/pairing.py`) keeps every open start and picks the best valid stop
  match (same pitch/voice first, then shortest span); the mscz now has `m7→m8` (same-pitch G4),
  `m8 C5→m10 D5` (the legitimate phrase), and `m10→m12`, with no m7→m10 arc. Regression pages cover
  both the restored pair and the refused arc (`test_pairing.py`, `test_page_restore.py`).
- **Endpoint order vs XML order** (laputa m35–m36): the page writes the m35 stop in voice 1 before
  the m35 start in voice 2, so document-order pairing left the start open and paired it with the
  m36 stop, creating a long cross-bar slur. `restore_page_slurs` now sorts endpoints by
  `(measure, onset, stop-before-start)`; m35 start 1.5 pairs with its own stop 2.0 and the long
  m35→m36 slur is gone. The short remaining slur was the OMR's tie/slur confusion; `reconcile_tie_slurs`
  now removes a slur whose endpoints already have a tie (m35 E5 keeps the tie, loses the slur).
- **A slur may end on a tied note** (m33→m35): the page has `m33 G5 slur start → m35 E5 slur stop`,
  while E5 also carries a real tie. The page slur pass now skips a copy only when **both** endpoints
  already have ties, so the legitimate m33→m35 slur is restored and the duplicate E5 slur start is
  still suppressed (`test_page_restore.py::test_a_slur_may_end_on_a_tied_note`).
- **Tie/slur reconciliation**: `reconcile_tie_slurs` applies three rules: a tie duplicated by a slur
  wins (slur removed); a tie with another pitch between its endpoints in the same voice becomes a
  slur; a contiguous same-pitch slur with nothing between its endpoints becomes a tie. The page
  restore records tie→slur conversions so the next round does not re-add the tie. "Between" compares
  `(measure, onset)`, not measure-local onsets alone; the old comparison treated a note in m60 as
  lying between m59's D4 tie endpoints and turned a contiguous tie into a slur (`test_tie_slurs.py`).
  m35's E5 tie is kept and its duplicate slur is gone; E4's tie is untouched (`test_tie_slurs.py`).
- **Tie-span duplicate slurs** (laputa m60): the page has `G3 tie m60→m61` plus `G3 slur start →
  E3 slur stop` at the same two positions; the slur endpoint pitch differs, so the exact-endpoint
  rule missed it. `reconcile_tie_slurs` now also removes a slur when it shares the tie's start note
  and its stop is at the tie's stop position, or shares the tie's stop note and starts at the tie's
  start position. Page restoration applies the same check so it does not re-add the slur and
  oscillate. m60 G3 keeps only the tie (`test_tie_slurs.py`, `test_page_restore.py`).
- **Tie propagation respects duration** (laputa m61): OMR has a C4 whole tied across m61→m62, and a
  separate C5 eighth on the same onset. The page chord map used to be pitch-only, so the tie was
  copied onto C5 as well. It now stores `(pitch, duration)` and propagates only to members matching
  the tie endpoints' durations; m61 C5 no longer gets a tie, while m35's E4/E5 (same durations) still
  do (`test_page_restore.py::test_tie_propagation_respects_note_duration`).
- **Pedal cursor** (laputa m29): `restore_page_pedals` advanced its cursor over backups/forwards but
  not over notes, so directions after notes/backups got negative onsets and were rendered at m27/m28.
  It now advances over non-chord note durations; m29's four pedal directions stay in m29 at
  `0, 4, 4, 8` (`test_page_restore.py::test_pedal_cursor_advances_over_notes`).
- **Facts text styling** (laputa m3): `ApplyMarksFacts` used to write only `<words>` text, dropping
  `italic`, `font_size` and `justify`; `ApplyTextFactsStyle` now applies justification as an mscx
  `<align>` and the MusicXML words carry font attributes, so MuseScore imports 8pt italic text.
  The m3 commentary is centered and fits above the staff instead of overflowing to the right
  (`test_facts.py`, `test_display_facts.py`). This is the first-pass style/fit; true width estimation
  for arbitrary boxes is still open.
- **Tempo text / arranger credits** (Sincerely): a fact such as `q = 72` used to produce both a words
  direction and a metronome, which MuseScore rendered as `q = 72 ♩=72`. Tempo-notation text now gets
  one words direction with a `<sound tempo>` and no separate metronome. Arranger/transcriber credits
  are appended to the composer line rather than creating a second overlapping composer `Text`
  (`test_facts.py`, `test_display_facts.py`, `test_credits_display.py`).
- **Absolute musical positions**: `_ties_with_other_pitches_to_slurs` and
  `_tie_shaped_slurs_to_ties` used to compare measure-local onsets across the whole score, so a note
  in m60 could look "between" two m59 D4s. Both now use `scorepipe.core.positions.between`, keyed by
  `(measure, onset)`. An audit of the other passes found their onset comparisons are within one
  measure or already keyed with a measure number (`test_positions.py`, `test_tie_slurs.py`).
- **Slur signature is positional**: `restore_page_slurs` used to compare `id(note)`, so a merge that
  rebuilt XML note elements made every page slur look different and forced a clear/re-add each round.
  The signature is now `(measure, staff, onset, pitch, kind, number)`, so identical music has the
  same signature and the pass can no-op (`test_page_restore.py`).
- **Page slurs own page slurs**: `sanitize_slurs` is skipped when a page model is present. Its
  generic staff/number re-pairing orphaned a valid m54 page slur, which `restore_page_slurs` then
  re-added every round; the page pass already enforces the 6-bar span. With this split, the broad
  sustained-note guard runs on page inputs and laputa is `5 rounds stable, verifier clean`.
- **Adjacent slur chains** (laputa m53–m55): OMR wrote `m53 G4→m54 A4` and `m54 A4→m55 E5` as two
  slurs sharing the A4 note. `restore_page_slurs` joins such unique shared-note chains before
  numbering (and `merge_adjacent_slurs` handles the same shape outside the page path), producing one
  `m53 G4→m55 E5` slur. A note with multiple starts/stops is left alone (`test_slur_chains.py`).
- **Beam groups** (laputa m50–m51): OMR left beams only on some notes (m50: G3 eighths in a
  separate voice; m51: the first eighth had a `begin` and the next note also started a group). After
  merging, the runs had disconnected stems. `restore_beams` (ported from the old skill's
  `restore_missing_beams`) groups consecutive eighth-or-shorter notes per staff/voice and rebuilds
  the whole contiguous run, so a partial source group cannot leave a first note on a separate
  `begin`. m50 bass is one eighth-note group from C3 to G3, and m51 starts with B2→G3 in the same
  group (`test_beams.py`). Mixed eighth/sixteenth runs are now split by the active beat grid, and a
  complete source `begin`/`end` group is a hard boundary; a one-note source begin/end pair is treated
  as an OMR fragment instead of fragmenting the run. An explicit un-beamed eighth between groups of
  16ths is kept out of the surrounding group (Sincerely m3's low B3), so rebuilding does not beam
  across it.
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
- **Range spanners on carrier voices**: m23 had voice 3 = `Spanner HairPin (prev) + Rest measure
  (visible=0)`, the invisible anchor MuseScore creates for a `rit.`/wedge endpoint that does not
  fall on a chord. `normalize_range_spanners` re-anchors `HairPin`, `Pedal`, `GradualTempoChange`,
  `Ottava`, `TextLine` and `Volta` endpoints to voice 1 at the same tick, then drops the now-empty
  rest carrier; Slur/Tie/Trill/Glissando endpoints are left alone because they depend on specific
  notes. m23 now has two voices and the HairPin sits in voice 1 (`test_display.py`).
- **Staff ownership in the source** (m29): `normalize_voice_numbers` used to renumber each staff
  from 1. On the lower staff this produced a third voice that MuseScore imported as a treble
  cross-staff voice (`staff1 voice2 + staffMove=1`), so the real bass A2 looked like treble
  material. Voice slots are now reserved four per staff (staff 1 → 1–4, staff 2 → 5–8), matching the
  OMR page convention; MuseScore then imports m29's A2 into staff 2 normally, with no `staffMove`.
  The mscx has one treble voice and three bass voices (`test_voices.py`).
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
