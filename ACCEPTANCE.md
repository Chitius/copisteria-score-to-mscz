# Acceptance evidence

Date: 2026-11-20. Commands run from the project root with the system Python.

## Test suite

```
python -m unittest discover -s tests
Ran 62 tests
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

21 entries: 14 structural (13 mechanical + 1 analysis), 1 inject, 6 display. Every mechanical pass
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
  63-measure score by `merge_pages`, then verifier clean — the loader works on real per-page OMR
  output, not only on already-merged MusicXML.
- `laputa.mscz`: display pipeline runs to a fixed point with **0 changes** and a clean mscx
  verifier — the display invariants hold on a real MuseScore file.

These are baseline reports, not failures of the pipeline: they show the verifiers catching the
same problems the old ad-hoc pipeline found, with stable codes.

## Known gaps (documented, not hidden)

- Voice merging, page-level tie/slur restoration and pedal-line deduplication from the old skill
  are not ported yet.
- No copisteria/OMR front-end: the loader expects MusicXML already produced by an OMR step.
- The display layer runs after MuseScore conversion of a `.mscz`; a combined
  `musicxml -> mscz -> display` driver is not wired into the CLI yet.
- `rebase_measures` refuses to push an overflow that would itself land past the next barline; such
  a case is still reported by the verifier rather than cascaded further.
