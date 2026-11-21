# OpenScore Lieder corpus cases

These cases use the public [OpenScore Lieder](https://github.com/OpenScore/Lieder) transcriptions as
**ground truth**.  The original `.mxl` is kept unchanged; `ground_truth.musicxml` is its root
MusicXML extracted from the MXL container; `input.pdf` is rendered by MuseScore 4 and is the
synthetic OMR input.  This is a clean-render benchmark, not a scan benchmark: it tests the symbolic
pipeline and OMR on ideal engraving, not paper noise or skew.

The OpenScore score page for Gute Nacht says "OpenScore (CC0)"; check the upstream repository's
current licence before redistributing a larger corpus.

## Cases

| case | source | parts | measures | PDF pages |
|---|---|---|---:|---:|
| `gute_nacht` | Schubert, Winterreise D.911 No.1 | vocal + piano | 105 | 4 |
| `die_wetterfahne` | Schubert, Winterreise D.911 No.2 | vocal + piano | 52 | 4 |
| `der_lindenbaum` | Schubert, Winterreise D.911 No.5 | vocal + piano | 82 | 6 |
| `aus_meinen_traenen` | Schumann, Dichterliebe Op.48 No.2 | vocal + piano | 18 | 2 |

Each case directory contains `{case}.mxl`, `ground_truth.musicxml` and `input.pdf`.

## Gute Nacht (Schubert, Winterreise D.911 No.1)

- source: `lc5015378.mxl` from OpenScore Lieder
- score: 2 parts (vocal + piano), 105 measures
- files:
  - `gute_nacht.mxl` — original compressed MusicXML
  - `ground_truth.musicxml` — extracted source MusicXML
  - `input.pdf` — 4-page A4 render used as OMR input

Baseline comparison from one copisteria run of `input.pdf` (old converter exits after writing the
MusicXML because the vocal part has no `<voice>` elements; the partial output is still readable):

| part | notes | missing | extra | match |
|---|---:|---:|---:|---:|
| P1 vocal | 340 | 3 | 3 | 98.24% |
| P2 piano | 1911 | 14 | 17 | 98.38% |

A shorter additional run on `aus_meinen_traenen` gives a raw OMR baseline of 85.51% (vocal) and
82.04% (piano); its source has a pickup measure numbered 0, which the comparator aligns by measure
ordinal rather than by the printed number.

The P1 pipeline (`scorepipe .../P1.musicxml`) is verifier-clean and keeps the same 98.24% note
match.  The P2 piano part also converges (2 rounds, clean verifier) and matches the ground truth at
97.44% after the pipeline; the remaining gap is the padding-rest/extra-event cleanup.

## Rebuild

```powershell
python tests/corpus/lieder/build_case.py path/to/lc5015378.mxl tests/corpus/lieder/gute_nacht
python tests/corpus/lieder/compare_parts.py \
  tests/corpus/lieder/gute_nacht/ground_truth.musicxml omr-output.musicxml
```

The comparator normalises each part to beats and matches notes by
`(measure, onset, pitch, duration)`, so chord layout and voice numbering do not affect the score.
