# Acceptance evidence

Date: 2026-11-20. Commands run from the project root with the system Python.

## Test suite

```
python -m unittest discover -s tests
Ran 45 tests
OK
```

Coverage:

| area | tests |
|---|---|
| fixed point + verifiers | `test_pipeline.py` |
| slur sanitation, short-measure padding | `test_passes.py` |
| voice numbering | `test_voices.py` |
| duplicate notes | `test_duplicates.py` |
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

16 entries: 9 structural (8 mechanical + 1 analysis), 1 inject, 6 display. Every mechanical pass
declares an `owns` property and a monotone measure; `validate_registry` fails the run with exit
code 2 if that is violated.

## Real scores

```
scorepipe laputa.musicxml --check --report laputa.json
```

- `laputa` (63 measures): verifier reports 5 `measure-length` violations, all in staff 2 at m1
  (6.5 beats) and m31 (7 beats across four voices). Nothing else: ties, slurs, rest visibility and
  duplicate notes are clean.
- `summer` (55 measures): 8 `measure-length` violations at m36–m40 (4.25–5.5 beats in 4/4),
  matching the known OMR duration drift; no other violations.
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
