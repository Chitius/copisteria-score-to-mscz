# SANITY — per-pass contracts and sanity-check design

Audit of `scorepipe/passes/*.py` at commit state of 2026-11-20. Read-only audit: no code or test was
changed; `SANITY.md` is the only file added.

**Method.** Every registered pass was read in full, the registry was confirmed by running
`--list-passes` (39 entries: 24 structural — 23 mechanical + 1 analysis —, 2 inject, 13 display,
matching `ACCEPTANCE.md:58`), and the suspicious behaviours below were reproduced by running single
passes on synthetic in-memory fixtures (no files written). Evidence is tagged:

- `[code]` — read from the source;
- `[probe]` — reproduced on a synthetic fixture during this audit;
- `[real]` — observed on the checked-in `tests/.runs/showcase/laputa.*` fixtures.

**Why a contract per pass.** The pipeline runs each mechanical pass to a phase-local fixed point
(`core/pipeline.py:54-80`) and relies on "a full round with no change and no hash move" as
termination, plus a read-only verifier that only knows five structural codes
(`core/invariants.py:119-125`) and six mscx codes (`core/mscx_invariants.py:125-132`). Neither
verifier knows what a *given* pass is allowed to do. The checks below are per-pass deltas, so
"healthy stays healthy" is expressed as a diff with an explicit whitelist.

> Note, for coordination only: while this audit ran, `scorepipe/sanity.py` (untracked/modified in
> the working tree, not touched by the audit) appeared with the primitives these checks need —
> `snapshot`/`diff_snapshots`/`PassContract`/`run_contract`. The eight checks below are the
> specification those primitives should satisfy; the doc does not depend on that module's API.

---

## 1. The eight checks

Each column of the matrix in §4 is one comparator run before/after a single pass invocation. All of
them work on the same walkers the passes use (`Document.events`, `Document.iter_measures`) so the
harness never measures something different from what the pass mutates.

| # | check | compares | how |
|---|---|---|---|
| 1 | **idem** | `hash(doc)` and the returned `changed` | `h0=h(d)`; `r1=run(d)`; `h1=h(d)`; `r2=run(d)`; `h2=h(d)`. Require `h1==h2`, `r2.changed==0`, **and** `r1.changed>0 ⟺ h1!=h0`. The last clause is not cosmetic: `upgrade_tempo_texts` mutates the tree and returns `changed=0` `[probe]`, so a hash-only or count-only check misses it. |
| 2 | **struct** | the block/cursor layout | MusicXML: reuse `invariants.chord_semantics` (negative cursor, orphan `<chord>`, chord after a different voice/staff/rest) **plus** a block model: for each `(staff, voice)` exactly one contiguous run of children, each run starts when the cursor is 0, and the run after it starts at 0 again. In OMR output the `<backup>` that closes a run equals the run's length (that is exactly the assumption `fill_short_measures` relies on, `tests/test_fill.py:29-35`), so the checker should assert that convention, not only "cursor ≥ 0". mscx: `mscx_invariants.empty_voices` plus "`<eid>` first, then `<voice>`; inside a voice `Clef/KeySig/TimeSig` precede text and chords" (that is MuseScore's own order in `laputa.mscz` `[real]`). |
| 3 | **len** (measure health) | per `(measure, staff, voice)` voice length | `invariants.measure_lengths` (XML) / `mscx_invariants.measure_lengths` (mscx) diffed before/after. Rules: any slot healthy before stays healthy; the pass's declared target may become healthy; **no voice may end at a negative onset**; an `implicit="yes"` measure is excluded only while it stays implicit. |
| 4 | **note** (inventory) | multiset of pitched notes | `(measure, staff, voice, onset, duration, pitch)`; `compare._events`/`compare._counter` (`compare.py:15-64`) already produces exactly this, filter `pitch != "rest"`. Rests counted separately. Deltas must match the per-pass whitelist (e.g. `fill` may add rests only). |
| 5 | **onset** | where a pitch sounds | map `(measure, staff, pitch)` → sorted list of onsets; equal unless the pass is a retiming/rebase pass. Catches the class of bug where a note survives but lands on another beat. |
| 6 | **dur** | how long a pitch sounds | map `(measure, staff, pitch, onset)` → multiset of durations; equal unless retiming. |
| 7 | **voices** | voice slots | per `(measure, staff)`: ordered list of voice labels and the number of contiguous blocks per label. Annotation passes: identical. Rebuild passes: labels must be exactly `1..n`, one block each. |
| 8 | **ties** | tie/slur graph | XML: per `(staff, voice, pitch)` in document order, `start`/`stop` must alternate and the document must end closed; deleting a note may not orphan the other endpoint. Slurs: pair `start`/`stop` **by number globally across the score** (MuseScore resolves slur numbers document-wide, `page_restore.py:214-216`), a pair may not cross staves, and no more than 16 may be open at once (`page_restore.py:556`). mscx: every `<Spanner type="Tie">` with `<next>` has exactly one `<prev>` at the stated `measures/notes` location and vice versa; `<eid>` unique. |

**Global rules that every pass must satisfy**, whatever its contract says:

- **G1** no pass may change a pitch value (`step`/`alter`/`octave`) of a note that survives; no pass
  owns "pitch" in the registry, and none writes one `[code]`.
- **G2** no pass may move a note to a different staff.
- **G3** no pass may leave a negative cursor or an orphan `<chord>` (`invariants.chord_semantics`).
- **G4** any pass that mutates the tree must return `changed > 0`.
- **G5** the harness must run with a **populated** `Context`: 6 passes are no-ops without
  `ctx.pages` (`restore_page_*`, `page_restore.py:99-104`), 5 without `ctx.facts`
  (`apply_marks_facts`, `apply_credits_facts`, `upgrade_tempo_texts`, `upgrade_gradual_texts`,
  `apply_credits_display`), `rebase`/`fill` read `ctx.options`, `restore_mscx_ties` needs
  `ctx.options["ties"]`, `split_chord_fragments` needs `ctx.options["chord_fragments"]`. A pass that
  returns 0 because its context was empty must be reported **vacuous**, not green.
- **G6** passes are order-dependent (`fill` after `merge_staff_voices`; page restores after
  `rebase`). Per-pass checks must run on a healthy fixture, not inside pipeline order.
- **G7** the real fixture does **not** exercise the structural passes any more: running
  `laputa.musicxml` through `STRUCTURAL_PASSES` today gives one trace entry (`sanitize_slurs`,
  changed=2) and a clean verifier `[real]`. Regression coverage must come from pass-level fixtures.

---

## 2. Pass inventory and contracts

Legend for the effect columns: `=` must not change · `+` intentionally adds · `−` intentionally
removes · `~` may change under the stated rule · `?` intent unclear from the code.
`±meas` = adds/removes `<measure>`. All names are the registry names (`PassSpec.name`).

### 2.1 Structural (24)

| pass | kind | class | purpose (from spec.description) | notes | onset | dur | ±meas | pitch | voice/staff | ties |
|---|---|---|---|---|---|---|---|---|---|---|
| `dedupe_ties` | mechanical | pure-annotation | one `<tie>`/`<tied>` per type per note | = | = | = | = | = | = | ~ removes duplicate endpoints, never a pair |
| `drop_redundant_time_signatures` | mechanical | pure-annotation | remove a time signature that repeats the one in force | = | = | = | = | = | = | = |
| `unhide_rests` | mechanical | pure-annotation | a hidden rest is drawn grey; make it real notation | = | = | = | = | = | = | = |
| `drop_redundant_clefs` | mechanical | pure-annotation | remove a clef that repeats the clef in force on that staff | = | = | = | = | = | = | = |
| `drop_redundant_key_signatures` | mechanical | pure-annotation | remove a key signature that repeats the one in force | = | = | = | = | = | = | = |
| `drop_duplicate_notes` | mechanical | cleanup | remove repeated notes with the same staff, voice, onset and pitch | − | = | = | = | = | = | ~ must not orphan an endpoint |
| `drop_trailing_duplicate_measure` | mechanical | cleanup | drop a final bar whose pitches repeat the previous bar but which is shorter | − | = | = | −1 | = | = | ~ must not leave a dangling tie start |
| `drop_overflow_duplicates` | mechanical | cleanup | drop a note past the barline when the next bar starts with the same pitch there | − | = | = | = | = | = | ~ must not orphan an endpoint |
| `mark_pickup` | mechanical | pure-annotation | mark a short opening bar as an anacrusis (`implicit`) instead of padding it | = | = | = | = | = | = | = |
| `pad_empty_staves` | mechanical | structural-rebuild | insert a measure rest for a staff with no note in the measure | + rests | = | = | = | = | + voice 1 on that staff | = |
| `rebuild_voice_layers` | mechanical | structural-rebuild | rebuild a fragmented measure as non-overlapping voices, keeping durations and ties | ~ rests dropped, gaps re-rested | = (per pitch) | = (per pitch) | = | = | ~ re-layered, labels `1..n` | = (elements are reused) |
| `merge_staff_voices` | mechanical | retiming | rebuild a multi-voice staff as one retimed line (skips fill conflicts) | ~ unisons deduped, rests dropped | ~ | ~ | = | = | ~ one voice "1" per rebuilt staff | ~ rebuilt notes carry no ties; restorers must re-add |
| `rebase_measures` | mechanical | structural-rebuild | move notes starting past the barline, split notes crossing it, into a new voice | = pitched, +1 split remainder | ~ | ~ split | = | = | ~ new voice in target | ~ rewrites ties on split notes |
| `merge_aligned_voices` | mechanical | structural-rebuild | fold a secondary voice into the primary chords when every note aligns exactly | = | = (aligned) | = (aligned) | = | = | ~ −1 voice, survivor may be voice 2 | ~ clones copy endpoints |
| `normalize_voice_numbers` | mechanical | pure-annotation | number voices 1..n per staff by note count | = | = | = | = | = | ~ labels only | = |
| `sanitize_slurs` | mechanical | cleanup | drop unmatched slur endpoints and pairs longer than N bars | = | = | = | = | = | = | ~ endpoints |
| `fill_short_measures` | mechanical | structural-rebuild | append a rest when a voice stops before the barline (pickup/last bar excluded) | + rests | = | = | = | = | = | = |
| `restore_page_ties` | mechanical | injection | re-attach ties written per page to the merged score | = | = | = | = | = | = | + endpoints |
| `restore_page_slurs` | mechanical | injection | re-attach slurs per page, renumbered globally | = | = | = | = | = | = | ~ clear all, rebuild |
| `restore_page_pedals` | mechanical | injection | replace pedal directions with the page-accurate ones | = | = | = | = | = | = | = |
| `restore_page_arpeggios` | mechanical | injection | re-attach arpeggiate / non-arpeggiate marks | = | = | = | = | = | = | = |
| `restore_page_articulations` | mechanical | injection | re-attach page articulations | = | = | = | = | = | = | = |
| `restore_page_wedges` | mechanical | injection | replace wedge directions with the page-accurate ones | = | = | = | = | = | = | = |
| `measure_length_report` | analysis | analysis (read-only) | report voices whose content does not fill the metre | = | = | = | = | = | = | = |

### 2.2 Inject (2)

| pass | kind | class | purpose | notes | onset | dur | ±meas | pitch | voice/staff | ties |
|---|---|---|---|---|---|---|---|---|---|---|
| `apply_marks_facts` | mechanical | injection | insert words/rehearsal/metronome directions from a facts file | = | = | = | = | = | = | = |
| `apply_credits_facts` | mechanical | injection | insert title/composer credits before `<part-list>` | = | = | = | = | = | = | = |

### 2.3 Display (13)

| pass | kind | class | purpose | notes | onset | dur | ±meas | pitch | voice/staff | ties |
|---|---|---|---|---|---|---|---|---|---|---|
| `drop_text_voice_rests` | mechanical | display-cleanup | remove the imported whole-measure rest of a text-only voice | − rests | = | = | = | = | = (may empty a slot) | = |
| `unhide_real_rests` | mechanical | display-cleanup | remove `<visible>` from non-measure rests | = | = | = | = | = | = | = |
| `drop_padding_voices` | mechanical | display-cleanup | remove a rest-only voice next to a chord voice | − | = | = | = | = | − slot | ~ a Spanner-only voice is removed too |
| `canonical_voice_order` | mechanical | display-cleanup | densest chord voice first, text voices after | = | = | = | = | = | ~ order only | = |
| `split_chord_fragments` | mechanical | structural-rebuild | give a chord member with a conflicting duration its own voice | = (member moved) | = | ~ intended duration | = | = | + voice | − ties on the moved note |
| `restore_mscx_ties` | mechanical | injection | attach tie spanners the MuseScore importer dropped | = | = | = | = | = | = | + spanners |
| `dedupe_pedal_spanners` | mechanical | display-cleanup | remove byte-identical pedal spanners inside one voice | = | = | = | = | = | = | ~ must keep start/stop paired |
| `dedupe_text_objects` | mechanical | display-cleanup | remove a second text object with the same words in the same measure | = | = | = | = | = | = | = |
| `merge_text_voices` | mechanical | display-cleanup | move text objects out of their zero-length voice into the first chord voice | = | = | = | = | = | − slot | ~ deletes other children of that voice |
| `drop_empty_voices` | mechanical | display-cleanup | remove voice slots with no chord, rest or spanner | = | = | = | = | = | − slot | ~ may delete a solo `<BarLine>` |
| `upgrade_tempo_texts` | mechanical | injection | a StaffText matching a tempo fact becomes a `<Tempo>` | = | = | = | = | = | = | ~ deletes glyph-only Tempo nodes |
| `upgrade_gradual_texts` | mechanical | injection | a rit./rall./accel. word becomes a GradualTempoChange spanner | = | = | = | = | = | = | = |
| `apply_credits_display` | mechanical | injection | put credits into the MuseScore title frame | = | = | = | = | = | = | = |

**No pass is a generator.** The OMR/facts *production* step is not a pass:
`producers/*.py` and `omr.py` return data and never touch the document (`DESIGN.md:122-124`), so the
"generation (OMR/facts)" category has zero rows in the matrix. `measure_length_report` is the only
`Kind.ANALYSIS` pass.

---

## 3. Adversarial cases by contract category

Fixture notation: `n(PITCH, ticks, staff=sN, voice=vN)` is a `<note>` with `<duration>` in divisions
(so `divisions=4`, 4/4 → a bar is 16 ticks); `bk(t)` is `<backup><duration>t`, `fw(t)` is
`<forward><duration>t`; `rest(t)` is a `<note><rest/>`. Every fixture is a *healthy* document before
the pass runs (the point of "healthy stays healthy").

### 3.1 pure-annotation (`dedupe_ties`, `drop_redundant_*`, `unhide_rests`, `mark_pickup`, `normalize_voice_numbers`)

Shape: one bar, two voices, a tie start/stop on a chord member, a repeated `<time>`/`<key>`/`<clef>`
in the middle of the piece.

- **`dedupe_ties` — duplicate endpoints:** a duplicate `<tie type="start">` on a note whose paired
  stop is in the next bar; assert exactly one start remains and the pair still closes (check 8).
- **`normalize_voice_numbers`:** bar with `v1` = 3 notes and `v2` = 5 notes; the labels must swap but
  every onset, duration and tie endpoint must be byte-identical (checks 5, 6, 8). Then add a **grace
  note** (a `<note>` with no `<duration>`, `<voice>2</voice>`): it is invisible to the density count
  (`doc.events` skips notes without `<duration>`) but is still relabelled by
  `for note in measure.iter("note")` (`xml_voices.py:35`). Assert the grace note's label stays
  consistent with the stream it belongs to and is never left as the only note on a stale label.
- **`normalize_voice_numbers` cross-bar:** assert voice numbers are recomputed per bar and therefore
  *may* differ between bars (this is legitimate; a checker that compares voice labels across the
  whole piece will false-fail).
- **`mark_pickup`:** 3/4 first bar containing one 2-beat note. Assert `implicit` appears, no note
  moves, and the mscx/XML measure-length checker now tolerates the short bar (check 3 must be
  re-derived from the post-state, not compared against the pre-state).
- **`drop_redundant_*`:** a bar whose `<attributes>` holds both a redundant `<time>` **and** a real
  `<clef change>`; removing the `<time>` must not remove the `<attributes>` element with it
  (`xml_basic.py:66-69`, `xml_clefs.py:60-62` remove the parent when it becomes empty).

### 3.2 cleanup (`drop_duplicate_notes`, `drop_overflow_duplicates`, `drop_trailing_duplicate_measure`, `sanitize_slurs`)

- **`drop_duplicate_notes` — duration-blind dedupe.** Same voice, same onset, same pitch, different
  durations (the fragmented-block shape `rebuild_voice_layers` exists for):
  `n(C4,8,v1) bk(8) n(C4,16,v1)`. The key is `(staff, voice, onset, pitch)` with no duration
  (`xml_duplicates.py:35`), so the *second* occurrence is deleted regardless of which is right —
  here the whole note goes and the eighth survives. Assert: the surviving note keeps the longer
  duration, or the pass refuses the case. Note the ordering: `drop_duplicate_notes` is registered
  **before** `rebuild_voice_layers` (`passes/__init__.py:57` vs `:62`), so the fragmented measure is
  deduped before it is re-layered — the fix would be to move the rebuild earlier.
- **`drop_duplicate_notes` — chord base.** A real duplicate `<chord>` member may be removed; a base
  followed by chord members may not (`_removable`, `xml_duplicates.py:46-58`). Fixture: `C4-E4-G4`
  chord plus a duplicate `G4` chord member; assert `G4` disappears, the base and the other members
  survive, and no `<chord>` is orphaned.
- **`drop_overflow_duplicates` — chord base deleted. `[probe]`** Fixture: bar 1 = `n(C5,16,v1)` +
  overflow chord `n(G4,8,v1)` + `n(B4,8,v1,chord)`, bar 2 starts `n(G4,8,v1)`. The pass removes the
  G4 base only (`xml_overflow.py:32-42` has no `_removable` guard). Result: `G4` is deleted and the
  surviving `<chord/>` `B4` attaches to the *previous* chord (`C5`), i.e. `B4` moves from beat 3 to
  beat 1 and `chord_semantics` reports **nothing**. Assert: removing an overflow note must remove
  its chord members too (or refuse); note inventory `−1` is allowed, an **onset change of a
  surviving note is not** (check 5).
- **`drop_overflow_duplicates` — ties.** Overflow note carries `<tie type="start">`/`<notations><slur
  type="start">` and the next bar repeats the pitch: dropping the note must also drop/repair the
  upstream stop; assert no dangling endpoint (check 8).
- **`drop_trailing_duplicate_measure` — cascade. `[probe]`** Three closing bars with the same pitch
  set and strictly decreasing totals (`n(C4,12)`, `n(C4,8)`, `n(C4,4)`): two runs delete **two
  bars**, leaving one measure. Assert: at most one measure per invocation, and only when the last bar
  is shorter *and* is a genuine duplicate (also compare staff/voice/rests/durations, not just the
  pitch set — `xml_tail.py:29-32` compares `set(pitches)` and the max end only). Because it deletes
  measures it is the one mechanical pass whose idempotence is **not** required (`—` in the matrix).
- **`drop_trailing_duplicate_measure` — ties.** The removed bar may be the stop of a tie started in
  the new last bar; assert the remaining score has no open tie (check 8).
- **`sanitize_slurs`:** nested slurs with the same number (`start 1`, `start 1`, `stop 1`) — LIFO
  pairing (`xml_slurs.py:37`) pairs the inner start with the first stop; assert the surviving
  single-slur case is all that is produced, or that pairing is documented. Add a scenario where the
  slur start is 7 bars before the stop (`max_slur_bars=6`, `xml_slurs.py:19`) and assert **both**
  endpoints are removed, never one.
- **`sanitize_slurs` — grace notes:** a slur on a note without `<duration>` is invisible to
  `doc.events`; assert the checker does not claim "clean" for a document with a slur on a grace note.

### 3.3 structural-rebuild (`fill_short_measures`, `pad_empty_staves`, `rebuild_voice_layers`, `rebase_measures`, `merge_staff_voices`, `merge_aligned_voices`, `split_chord_fragments`)

- **`fill_short_measures` — the laputa m8 bug.** Fixture (exactly `tests/test_fill.py:29-35`):
  `n(C5,16,s1,v1) bk(16) n(E5,12,s1,v2) bk(12) n(G3,16,s2,v1)`. Voice 2 stops one beat short; the
  padding rest must be inserted **and** the following `<backup>` lengthened from 12 to 16
  (`xml_measures.py:64-77`), otherwise staff 2 starts a beat late. Assert: staff-2 onset 0, duration
  4, all other onsets unchanged, measure lengths clean. *This is the fixture that pins the bug.*
  Second case: a voice whose block is followed by a *full-bar* backup is invalid input; assert the
  harness never feeds it (check 2 would fail before the pass).
- **`fill_short_measures` — note type.** A voice short by **1.5 beats** (and 3.0) gets
  `<duration>6</duration>` with **no `<type>` and no `<dot>`** `[probe]` (`_TYPE_BY_DURATION` covers
  only 4/2/1/0.5/0.25/0.125, `xml_measures.py:10-17`). Assert every added rest carries
  `duration + type + dot`, or is split into representable rests.
- **`pad_empty_staves` — short bar. `[probe]`** 3/4 bar with `n(A4,8,s1)` and staff 2 appearing only
  in bar 2: the pass appends `bk(12)` + `rest(12, measure=yes)` (`xml_empty_staves.py:43-52`), so the
  measure-rest starts at onset **−1** and `chord_semantics` reports `negative-cursor`. Assert:
  the backup is the length actually consumed by the preceding content, and no voice starts below 0.
- **`pad_empty_staves` — pickup.** `implicit="yes"` 3/4 opening bar plus a staff that appears later;
  the pass has no `implicit` guard (`fill_short_measures` does), so a pickup gets a full-measure
  rest. Assert: no padding rest in an implicit measure.
- **`rebuild_voice_layers`:** bar with the same voice at the same onset twice (`n(C4,8,v1) n(E4,4,v1)`
  in two fragmented blocks) plus a rest; assert every pitched note keeps `(onset, duration, pitch,
  tie endpoints)` (checks 4-6, 8) and that rests are only *replaced* (gaps become rests), and that
  the output has one block per voice.
- **`rebase_measures` — source measure must stay healthy. `[probe]`** Fixture:
  bar 1 = `n(C4,16,v1) n(D4,8,v1) bk(24) n(E4,16,v2) n(F4,8,v2)`, bar 2 = `n(G4,16,v1)`. Both
  voices overflow. After the pass, bar 1 keeps `bk(24)` although `D4` was removed
  (`xml_rebase.py:77-80` removes notes but never the backup), so `E4` starts at onset **−2** and the
  verifier reports `measure-length m1 staff 1 voice 2: 2 beats, metre 4`. Assert: removing overflow
  from a block shrinks the following `<backup>` to the new block length; **all voices in the source
  measure keep their pre-pass onsets** (`E4` must stay at 0), except the removed tail itself.
- **`rebase_measures` — one new voice per measure. `[probe]`** Same fixture: the two overflow groups
  `(staff 1, v1)` and `(staff 1, v2)` each call `_next_voice` before either block is inserted
  (`xml_rebase.py:66-70, 128-187`), so **both fragments get voice "2"**; bar 2 then holds two voice-2
  chunks (`D4 rest | bk | F4 rest | bk | G4`) and the verifier is silent because `measure_lengths`
  only takes the max end per `(staff, voice)`. Assert: the number of contiguous blocks per
  `(staff, voice)` is exactly 1, and the new voice numbers are distinct.
- **`rebase_measures` — ties.** Note crossing the barline that already carries a `<tie type="start">`
  (tied into the following bar): the split adds another start (`xml_rebase.py:113-125`), producing two
  starts on one note; `dedupe_ties` then deletes one at random. Assert: at most one start and one
  stop per pitch, and the split pair is the one that survives. Also assert the truncated part keeps
  a `<type>` (the code drops it, `xml_rebase.py:84-88, 108-111`) and keeps `<time-modification>`
  (tuplets) — otherwise the notehead is wrong in MuseScore.
- **`merge_staff_voices` — other staff's `<forward>` dropped. `[probe]`** 2-staff bar, staff 1 has two
  voices (`n(C4,16,v1) bk(16) fw(8) n(E4,8,v2)`), staff 2 = `fw(8) n(D3,8,s2,v3)`. `_replace_staff`
  keeps only `<note>` children of the other staff (`xml_voice_merge.py:130-136`) and re-adds
  `<backup>bar</backup>` between blocks (`:144-151`), so staff 2's `D3` moves from **beat 3 to beat
  1**. Assert: every other staff's onsets are unchanged (check 5), and the other staff's measure
  length stays healthy (check 3 — it also becomes 2 beats).
- **`merge_staff_voices` — notation loss.** Rebuilt notes are constructed from scratch
  (`_note`, `xml_voice_merge.py:162-179`) and carry only chord/pitch/duration/voice/type/dots/staff:
  ties, slurs, lyrics, articulations, `<accidental>`, beams and `<time-modification>` are gone.
  Assert: if the pass is allowed to drop notations, the whitelist must name them (`ties`, `lyrics`,
  `articulations`) and a restoring pass must follow; today only page ties/slurs/articulations are
  restored, and only when `ctx.pages` is present `[code]`. A run without page context must be
  reported as losing notation, not as clean.
- **`merge_staff_voices` — laputa m31 shape.** Two voices where one is a sustained chord and the
  other a run: `n(C4,16,v1) + chord` and `n(E4,4,v2) x4`. Assert: after the rebuild the measure has
  exactly one voice block, a `<backup>` before every following block, each block filling the bar,
  the sustained pitch still at its original onset (it must not end up at beat 4 and be pushed out by
  `rebase` in the next pass), and total content per voice = bar.
- **`merge_aligned_voices` — duplicate pitch.** Primary chord already contains `G4`, the aligned
  secondary voice also plays `G4`: `_clone` copies it unconditionally (`xml_merge.py:129-138`), so
  the merged chord holds `G4` twice (by inspection; not reproduced). Assert note inventory is
  exactly preserved, not "preserved up to duplicates". Also assert the surviving voice number is
  allowed to be 2: with equal note counts `max(..., (count, voice))` picks the **highest** voice
  (`:47`), so the merged line may keep label "2" and voice "1" disappears `[probe]` — a check that
  requires "voice 1 survives" will false-fail.
- **`merge_aligned_voices` — backup removal.** `_remove_block` deletes the *preceding* backup
  (`:121-124`). That is only safe because `_aligned` forces both blocks to the same length, so the
  following backup has the same duration. Assert the precondition explicitly: before the pass,
  `backup before block == block length == backup after block`; a fixture that violates it is not a
  fair test of the pass.
- **`split_chord_fragments` — hard-coded 4/4. `[probe]`** 3/4 bar, fragment at onset 1 with duration
  2: `_new_voice` pads with `remaining = 4.0 - onset - duration` (`mscx_fragments.py:104`), creating a
  voice of **4 beats in a 3-beat bar** and `mscx_invariants.measure_lengths` reports
  `voice 4 beats, metre 3`. Assert: the new voice's total equals the measure's time signature, and
  every measure in the file keeps its length (check 3).
- **`split_chord_fragments` — notation loss.** Only `pitch` and `tpc` are copied to the new voice
  (`:100-103`); assert a moved member keeps its tie/articulation or that the whitelist says it may
  not.

### 3.4 retiming (`merge_staff_voices`; the split branch of `rebase_measures`)

Retiming is the only category where onset and duration checks are `—`, so the contract must be
stated as *conservation* rather than *equality*:

- **Order preserved:** the sequence of pitches at increasing onsets must be identical (no reordering,
  no note inserted between two existing onsets).
- **Bar total preserved:** sum of durations per `(measure, staff)` must equal the metre; no note may
  be lengthened past the barline.
- **Fill-conflict refusal:** the `quarters + whole-note-in-second-voice` fixture
  (`tests/test_voice_merge.py:56-62`) must be left alone; assert voice 2 still exists.
- **Unison/overlap collapse:** two voices sounding the same pitch at overlapping times must become
  one chord member *at the same onset*, and the number of attacks per pitch must not increase.
- **No retiming across a tie:** if a note carries a tie stop/start, retiming must keep the tie pair
  adjacent in time; assert the tie graph stays closed (check 8).
- **Split conservation:** for `rebase`, `duration(first part) + duration(remainder) == original`, and
  `onset(first part) == original onset`.

### 3.5 injection (`apply_marks_facts`, `apply_credits_facts`, `restore_page_*`, `restore_mscx_ties`, `upgrade_tempo_texts`, `upgrade_gradual_texts`, `apply_credits_display`)

- **Idempotence by construction:** run twice; the second run must return 0 **and** the hash must not
  move. `apply_marks_facts`/`apply_credits_facts` gate on presence (`xml_facts.py:40-54`,
  `xml_credits.py:33`); `restore_page_slurs` compares a signature before clearing
  (`page_restore.py:218-220`); `restore_page_pedals`/`wedges` compare sorted signatures
  (`:286-301`, `:451-466`).
- **`apply_marks_facts` placement:** direction inserted before the first `<note>`/`<forward>`
  (`xml_facts.py:97-102`) with `<offset>` in ticks; assert the direction's *effective* position is
  the same whether or not the measure starts with `<attributes>`/`<print>`, and that a second mark
  with the same text in a different voice is not swallowed by the measure-wide presence check.
- **`apply_credits_facts`:** a second credit with the same text but a different `type` must be
  inserted; a credit must land before `<part-list>` and after nothing that breaks schema order;
  `credit-type` values outside `title/subtitle/composer/rights` are invalid MusicXML — assert the
  producer validates them (`facts.py`) or the checker flags them.
- **`restore_page_ties`:** tie that starts in the **last measure of one page** and stops in the
  **first measure of the next** — `open_ties` is reset per page (`page_restore.py:129`), so this pair
  is never restored. Assert either restoration or an explicit "cannot restore across pages" report;
  a silent loss is the bug.
- **`restore_page_slurs` (laputa m29-30):** two staves, page 1 has a treble slur `number=1`
  m1→m2 and a bass slur `number=1` m3→m4. Assert: after the pass every slur number is used by
  exactly one pair **document-wide**, each stop is on the same staff as its start, both pairs exist,
  and no old slur survived (`_clear_slurs`, `:579-588`). Second case: 17 concurrent slurs — the
  allocator silently drops the 17th (`:556-558`); assert a report/whitelist, not silent loss.
- **`restore_page_slurs`/`_ties` after retiming:** lookups are `(measure, staff, onset, pitch)`
  (`:84-95`, `:140-141`); if `rebase`/`merge_staff_voices` changed the onset, the slur/tie is
  silently not restored. Assert the harness runs injection on a document whose onsets have NOT been
  retimed (or that the pass reports misses).
- **`restore_page_arpeggios`/`_articulations`:** pitch lookup falls back to "first note at that
  onset" (`:350-353`, `:381-385`); fixture: chord `C4-E4-G4` with an arpeggio on `G4` and a retimed
  duplicate at the same onset — assert the mark never lands on a different pitch.
- **`restore_page_pedals`/`_wedges`:** markup is rebuilt only for measures that have at least one
  page entry; assert a pedal direction that exists in the merged score but not on any page is *not*
  deleted (it is not, by construction) and that a measure rebuilt twice (two rounds) is byte-equal.
- **`restore_mscx_ties`:** `<Spanner type="Tie">` is added to `<Note>` children with `<prev>`/`<next>`
  location; assert every added spanner has a partner at `measures/notes` distance, `<eid>` values are
  unique, and an existing tie is not doubled (`mscx_ties.py:56`). Assert the pitch index
  (`_note_index`, `:88-105`) is consistent with `mscx_invariants.measure_lengths` on a 3/4 file
  (it assumes `durationType == "measure"` is 4 beats, `:108-117`).
- **`upgrade_tempo_texts` — silent deletion and wrong count. `[probe]`** A measure holding only a
  glyph-only `<Tempo>` (`<text><sym>metNoteQuarterUp</sym> = 120</text>`, no letters) and **no**
  matching StaffText: the pass removes the Tempo in the pre-pass (`mscx_facts.py:50-54`) and adds
  nothing, returning `changed=0`. Assert (a) the tree may only change when `changed>0`;
  (b) a glyph-only tempo must not be deleted unless a replacement was actually written.
- **`upgrade_tempo_texts` — voice order:** the `<Tempo>` replaces the StaffText *in place*
  (`:73-74`) and lands wherever the text was; assert no other object moved.
- **`upgrade_gradual_texts`:** span longer than the remaining file — start spanner written, end
  skipped (`:288-300`), leaving a dangling spanner. Assert either both endpoints or neither.
- **`apply_credits_display`:** a VBox that holds a credit text **and** other frames is moved to the
  front of the first staff (`:144-158`); assert frame order is stable across two runs and that no
  frame is lost, and that `Text` nodes' `style` mutation is idempotent.

### 3.6 display-cleanup (`drop_text_voice_rests`, `unhide_real_rests`, `drop_padding_voices`, `canonical_voice_order`, `drop_empty_voices`, `merge_text_voices`, `dedupe_*`)

Shapes are real MuseScore 4 mscx: `<Measure><eid/><voice><Clef/><KeySig/><TimeSig/><StaffText/>
<Chord><durationType>quarter</durationType><Note><pitch>60</pitch></Note></Chord></voice>…</Measure>`
`[real]`.

- **`merge_text_voices` — spanner deleted. `[probe]`** A voice holding `<StaffText>dolce</StaffText>`
  **and** `<Spanner type="Slur">…`: the text is moved and the whole voice removed
  (`mscx_dedupe.py:116-135`), so the slur vanishes. Assert: a voice may only be removed when it holds
  nothing but the text objects that were moved. Also assert the moved text does not end up before
  `Clef/KeySig/TimeSig` in the target voice (the code `insert(0, text)`, `:132`; MuseScore's own
  order is `Clef, KeySig, TimeSig, StaffText, Chord`) `[real]`.
- **`drop_empty_voices` — solo BarLine lost. `[probe]`** `<Measure><voice><BarLine/></voice>
  <voice>chord</voice></Measure>`: the empty slot is at position 0, so the BarLine is not relocated
  (`:83-89`) and is deleted with the voice. Assert the BarLine survives somewhere.
- **`drop_padding_voices` — Spanner-only voice.** The guard is `if voice.findall("Chord") or
  has_text(voice)`, with **no** requirement that the voice contains a Rest (`mscx_display.py:72-76`),
  so a voice holding only a `<Spanner>` (pedal/ottava) is deleted. Assert: only voices whose content
  is rests (or truly empty) are removed; a spanner-only voice must be kept or its spanner moved.
- **`canonical_voice_order` — sibling order. `[probe]`** A measure with a measure-level sibling
  (synthetic `<BarLine/>`, or the real `<eid/>`): re-appending every voice moves them after all
  remaining siblings (`mscx_display.py:105-108`). Real files put `<eid>` first and have no
  measure-level BarLine `[real]`, so the practical risk is limited — but assert `<eid>` stays first
  and a re-save through MuseScore is byte-stable.
- **`dedupe_text_objects`:** two *legitimate* identical words in one measure in different voices
  (e.g. "p" in voice 1 and voice 3) — one is deleted. Assert the whitelist says "same words in the
  same voice" or the pass is narrowed.
- **`dedupe_pedal_spanners`:** two identical pedal *ends* in one voice with only one start; assert
  start/stop pairing survives.
- **`drop_text_voice_rests`:** text voice that also holds a real (visible) rest; assert the voice is
  left with no negative-length content and that no measure length changes for chord voices.

### 3.7 generation (OMR/facts) — no registered passes

`producers/*.py` and `omr.py` produce JSON, never edits (`DESIGN.md:122-124`). The sanity suite has
nothing to check here beyond the schema gate `facts.validate_facts`; the checks that matter for the
pipeline are the inject passes in §3.5, which must be idempotent on *produced* facts.

---

## 4. Matrix

Rows: all 39 registered passes, registry order. Columns: the eight checks of §1.

Legend: **✓** = checker must require this property (must be preserved); **⚠** = required and
currently **violated** (reproduced with a probe, or by construction where noted below);
**✓\*** = required, believed to hold, with a known unverified risk described in §3;
**—** = the pass legitimately changes this dimension, the checker must whitelist it.

| pass | idem | struct | len | note | onset | dur | voices | ties |
|---|---|---|---|---|---|---|---|---|
| `dedupe_ties` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| `drop_redundant_time_signatures` | ✓ | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `unhide_rests` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `drop_redundant_clefs` | ✓ | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `drop_redundant_key_signatures` | ✓ | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `drop_duplicate_notes` | ✓ | — | ✓ | — | ✓ | ✓ | ✓ | ✓ |
| `drop_trailing_duplicate_measure` | — | — | — | — | ✓ | ✓ | ✓ | ✓\* |
| `drop_overflow_duplicates` | ✓ | — | ✓ | — | ⚠ | ✓ | ✓ | ✓\* |
| `mark_pickup` | ✓ | ✓ | — | ✓ | ✓ | ✓ | ✓ | ✓ |
| `pad_empty_staves` | ✓ | — | — | — | ⚠ | ✓ | — | ✓ |
| `rebuild_voice_layers` | ✓ | — | ✓ | ✓ | ✓ | ✓ | — | ✓ |
| `merge_staff_voices` | ✓ | — | ⚠ | — | ⚠ | — | — | — |
| `rebase_measures` | ✓ | — | ⚠ | ✓ | ⚠ | — | ⚠ | — |
| `merge_aligned_voices` | ✓ | — | ✓ | ✓\* | ✓ | ✓ | — | ✓\* |
| `normalize_voice_numbers` | ✓ | — | ✓ | ✓ | ✓ | ✓ | — | ✓ |
| `sanitize_slurs` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| `fill_short_measures` | ✓ | — | ✓ | — | ✓ | ✓ | ✓ | ✓ |
| `restore_page_ties` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| `restore_page_slurs` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| `restore_page_pedals` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `restore_page_arpeggios` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `restore_page_articulations` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `restore_page_wedges` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `measure_length_report` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `apply_marks_facts` | ✓ | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `apply_credits_facts` | ✓ | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `drop_text_voice_rests` | ✓ | — | ✓ | — | ✓ | ✓ | — | ✓ |
| `unhide_real_rests` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `drop_padding_voices` | ✓ | — | — | — | ✓ | ✓ | — | ⚠ |
| `canonical_voice_order` | ✓ | — | ✓ | ✓ | ✓ | ✓ | — | ✓ |
| `split_chord_fragments` | ✓ | — | ⚠ | ✓ | ✓ | — | — | — |
| `restore_mscx_ties` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| `dedupe_pedal_spanners` | ✓ | — | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| `dedupe_text_objects` | ✓ | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `merge_text_voices` | ✓ | — | ✓ | ✓ | ✓ | ✓ | — | ⚠ |
| `drop_empty_voices` | ✓ | ⚠ | ✓ | ✓ | ✓ | ✓ | — | ✓ |
| `upgrade_tempo_texts` | ⚠ | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `upgrade_gradual_texts` | ✓ | — | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| `apply_credits_display` | ✓\* | — | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

Notes on individual ⚠ cells:

- `drop_overflow_duplicates` / onset ⚠ — a surviving chord member is re-attached to the previous
  chord (§3.2, reproduced).
- `merge_staff_voices` / len ⚠, onset ⚠ — the other staff loses its `<forward>`: onset beat 3 → beat 1
  and that staff's measure becomes 2 of 4 beats (reproduced).
- `rebase_measures` / len ⚠, onset ⚠, voices ⚠ — source measure's backup not shrunk (voice at −2
  beats), and two overflow voices both labelled "2" (reproduced).
- `pad_empty_staves` / onset ⚠ — measure rest at −1 in a short 3/4 bar (reproduced).
- `split_chord_fragments` / len ⚠ — 4-beat voice in a 3/4 bar (reproduced).
- `drop_padding_voices` / ties ⚠, `merge_text_voices` / ties ⚠ — spanner lost with the voice
  (reproduced for `merge_text_voices`; `[code]` for `drop_padding_voices`).
- `drop_empty_voices` / struct ⚠ — solo `<BarLine>` deleted (reproduced).
- `upgrade_tempo_texts` / idem ⚠ — fails the **accounting** clause: deletes a Tempo, returns 0
  (reproduced). Its fixed-point clause (second run: no change) holds.
- `upgrade_gradual_texts` / ties `—` — allowed to change, but the end spanner is skipped when the
  span runs past the last measure (`mscx_facts.py:288-300`), so the start dangles; the checker must
  flag that instead of expecting a closed pair.
- `apply_credits_display` / idem ✓\* — frame reordering is stable in the cases inspected, but a VBox
  containing extra frames is moved wholesale; needs a two-run byte comparison on a real mscz.

---

## 5. Known bug patterns and the fixture that pins each

| # | pattern | regression fixture (assert what must NOT change) | owner |
|---|---|---|---|
| 1 | padding a short voice without lengthening the following `<backup>`; later staves shift (laputa m8 G3 → beat 1) | `n(C5,16,s1,v1) bk(16) n(E5,12,s1,v2) bk(12) n(G3,16,s2,v1)`; staff-2 onset must stay 0 (`tests/test_fill.py:29-35`) | `xml_measures.py:64-77` |
| 2 | rebuilt staff block without a `<backup>` between voices; a sustained chord lands at beat 4 and is then rebased away (laputa m31) | two-voice bar, sustained chord + quarter run; exactly one block per voice, a `<backup>` before every block after the first, sustained pitch keeps its onset | `xml_voice_merge.py:144-151` |
| 3 | slur numbers are global in MuseScore, page numbers are per staff; old slurs must be cleared and renumbered globally or a treble slur pairs with a bass stop (laputa m29-30) | two staves, both with slur `number=1` on one page; each number used once document-wide, stop staff == start staff, both pairs present | `page_restore.py:214-225, 547-565, 579-588` |
| 4 | rebase moving overflow must preserve ties and must not shift unrelated notes | overflow in a *non-final* voice (`n(C4,16) n(D4,8) bk(24) n(E4,16,v2) n(F4,8,v2)`); `E4` stays at onset 0, source measure stays 4 beats, tie starts/stops stay paired | `xml_rebase.py:66-80, 113-125, 128-187` |
| 5 | `merge_aligned_voices` / `drop_*` deleting the wrong chord member or pitch | duplicate-pitch merge (`G4` in both voices) and an overflow **chord base** repeated in the next bar; note inventory preserved, no `<chord>` re-attached to a previous chord | `xml_merge.py:129-138`, `xml_overflow.py:32-42`, `xml_duplicates.py:35, 46-58` |
| 6 | display mscx: no empty/text-only voices left, no measure-length change, text preserved | text+Spanner voice, solo-BarLine voice, 3/4 fragment split; spanner survives, BarLine survives, new voice totals 3 beats, text multiset preserved | `mscx_dedupe.py:116-135, 79-91`, `mscx_fragments.py:104` |

Two more reproduced patterns worth pinning even though they were not on the original list:
`drop_trailing_duplicate_measure` deleting two bars in one fixpoint (`xml_tail.py:19-34`), and
`upgrade_tempo_texts` deleting a glyph-only tempo while reporting `changed=0`
(`mscx_facts.py:50-54, 76-80`).

---

## 6. The five most suspicious passes (test first)

1. **`rebase_measures`** — `xml_rebase.py:66-80` removes overflow notes without shrinking the
   `<backup>` that closed their block, so every remaining voice of the source measure starts at a
   negative onset (probe: `E4` at −2 beats, verifier `measure-length m1 staff 1 voice 2: 2 beats`);
   `_next_voice` (`:179-187`) is called for each overflow group before insertion, so two groups in
   one measure both get voice "2" and bar 2 ends up with two voice-2 chunks that the verifier cannot
   see; the split path drops `<type>` and duplicates existing tie starts (`:50-61, 113-125`).
   It is the only pass whose failure corrupts **another measure** than the one it edits.
2. **`merge_staff_voices`** — `_replace_staff` (`:124-151`) keeps only `<note>` children of the other
   staves, so their `<forward>` gaps vanish (probe: `D3` beat 3 → beat 1 and staff 2 drops to 2 of 4
   beats); rebuilt notes are generated from scratch (`:162-179`) and lose ties, slurs, lyrics,
   articulations, accidentals, beams and tuplet `<time-modification>`; `<harmony>`/`<figured-bass>`
   are dropped with the old children, and every `<direction>` is hoisted to the head of the measure.
3. **`restore_page_slurs`** — the laputa m29-30 failure mode is fixed by the global renumbering
   (`:214-225, 547-565`), but the pass clears **all** slurs in the document and rebuilds only what
   the page model yields (`:220`), silently drops a pair when >16 are open (`:556-558`), and its
   `(measure, staff, onset, pitch)` lookups miss whenever `rebase`/`merge_staff_voices` retimed a
   note. Any of those is a silent slur loss with a clean verifier.
4. **`drop_overflow_duplicates`** — `xml_overflow.py:32-42` removes a note without its chord members
   and without a `_removable` guard (probe: base `G4` deleted, the surviving `B4` re-attached to the
   previous chord, i.e. moved a beat earlier, and `chord_semantics` reports nothing). The same pass
   is the only cleanup that can orphan a tie/slur endpoint.
5. **`drop_trailing_duplicate_measure`** — `xml_tail.py:19-34` compares only `set(pitches)` and the
   max end, ignores staff/voice/rests/durations, removes a whole measure, and repeats at every
   fixpoint round (probe: 12/8/4-tick bars → two bars deleted, one measure left). It is the only
   pass whose contract is deliberately **not** idempotent, and the only one that can delete real
   music in bulk.

Next tier, same evidence quality: `pad_empty_staves` (negative-onset measure rest in a short bar,
no `implicit` guard, `xml_empty_staves.py:33-52`), `split_chord_fragments` (hard-coded 4/4,
`mscx_fragments.py:104`), `merge_text_voices` / `drop_empty_voices` / `drop_padding_voices`
(spanner and BarLine loss), `upgrade_tempo_texts` (deletes a tempo and reports 0), and
`drop_duplicate_notes` (duration-blind key, `xml_duplicates.py:35`).

---

## 7. Mismatches and open questions

- **Doc/code drift in `DESIGN.md:42-53`:** the ownership table names `hoist_time_signature`,
  `upgrade_tempo_marks`, `upgrade_gradual_spanners`, which do not exist; the registered names are
  `restore_mscx_ties`, `upgrade_tempo_texts`, `upgrade_gradual_texts`. `DESIGN.md:65` cites
  `unhide_real_rests` for the structural phase, but the structural pass is `unhide_rests`.
- **`rest-visibility` is owned twice** (`unhide_rests` structural, `unhide_real_rests` display).
  `validate_registry` only checks ownership per phase (`core/registry.py:21-27`), so this is legal
  but the same property is written in two phases — worth an explicit "phase-local ownership" note in
  the contract of both passes.
- **Intent unclear / unstated:**
  - `drop_padding_voices` is described as "rest-only voice" but never checks for a rest
    (`mscx_display.py:72-76`); its contract against spanners is undefined.
  - `merge_aligned_voices` can duplicate a pitch already present in the primary chord; whether that
    is "fold" or "double" is not documented.
  - `rebuild_voice_layers` drops every `<rest>` element (`xml_layers.py:76-80, 135-141`) and re-adds
    rests only at the ends of layers; rests in the middle of a voice are not modelled, so a pass
    result can show fewer rests than the input (allowed, but not stated).
  - `apply_credits_facts` accepts `credit-type` values that MusicXML forbids (`subtitle`,
    `lyricist` map through `ApplyCreditsDisplay.STYLES`, `mscx_facts.py:93-98`) — schema validity is
    not checked anywhere.
- **Not exercised by the checked-in real score:** running `laputa.musicxml` through the structural
  passes gives one trace entry (`sanitize_slurs`, changed=2) and a clean verifier `[real]`. The
  rebase/merge/layers paths therefore have no real-file coverage; all contracts above must be pinned
  by synthetic fixtures.

---

## 8. Status after the first fix round (2026-11-20)

Pinned by tests and fixed:

- `rebase_measures`: the source block's closing `<backup>` is recomputed from the remaining notes,
  and overflow groups get distinct voice numbers (`tests/test_rebase.py`).
- `drop_overflow_duplicates`: removing a chord base also removes its `<chord/>` members
  (`tests/test_overflow.py`).
- `drop_trailing_duplicate_measure`: only a complete penultimate bar may own a truncated duplicate
  tail, so a run of short bars is no longer eaten one bar per round (`tests/test_tail.py`).
- `pad_empty_staves`: backup equals the actual cursor, and implicit pickup bars are skipped
  (`tests/test_empty_staves.py`).
- `split_chord_fragments`: the new voice is padded by the measure's own time signature instead of
  hard-coded 4/4 (`tests/test_mscx_fragments.py`).
- `merge_staff_voices`: other staves keep their `<forward>` gaps, so laputa m31's sustained chord
  survives (`tests/test_voice_merge.py`); laputa fidelity is 2.04% against the old output.
- `restore_page_slurs`: global 1..16 numbering and dropped reversed pairs remove the m29-m30
  cross-staff slur (`tests/test_page_restore.py`).

Still open (see sections above): notation loss in `merge_staff_voices`/`split_chord_fragments`,
display spanner/BarLine deletions, `upgrade_tempo_texts` change accounting, `drop_duplicate_notes`
duration-blind key, `merge_aligned_voices` duplicate chord member, and the design/doc drift.
