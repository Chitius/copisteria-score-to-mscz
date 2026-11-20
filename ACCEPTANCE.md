# Acceptance evidence

Date: 2026-11-20. Commands run from the project root with the system Python.

## Test suite

```
python -m unittest discover -s tests
Ran 55 tests
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

20 entries: 13 structural (12 mechanical + 1 analysis), 1 inject, 6 display. Every mechanical pass
declares an `owns` property and a monotone measure; `validate_registry` fails the run with exit
code 2 if that is violated.

## Real scores

```
scorepipe laputa.musicxml --check --report laputa.json
```

- `laputa` (63 measures): the verifier reports **1** `measure-length` violation, staff 2 voice 1 at
  m1 (6.5 beats); ties, slurs, rest visibility, duplicate notes, clefs and keys are clean. This is
  the first bar, where there is no previous measure to rebase into (a pickup/overfull opening).
- `summer` (55 measures): **2** `measure-length` violations left, m38 staff 2 (4.5) and m39 staff 2
  (4.25); the earlier m36–m40 block was repaired by `rebase_measures`, which moved the overflow
  notes into the next bar. The remaining two are cases where the *next* bar is also overfull, so
  the pass refuses to push the problem forward.
- `laputa.mscz`: display pipeline runs to a fixed point with **0 changes** and a clean mscx
  verifier — the display invariants hold on a real MuseScore file.

These are baseline reports, not failures of the pipeline: they show the verifiers catching the
same problems the old ad-hoc pipeline found, with stable codes.

## Known gaps (documented, not hidden)

- No `rebase_measures` pass yet, so the `measure-length` violations above are reported, not
  repaired.
- Voice merging, page-level tie/slur restoration and pedal-line deduplication from the old skill
  are not ported yet.
- No copisteria/OMR front-end: the loader expects MusicXML already produced by an OMR step.
- The display layer runs after MuseScore conversion of a `.mscz`; a combined
  `musicxml -> mscz -> display` driver is not wired into the CLI yet.
