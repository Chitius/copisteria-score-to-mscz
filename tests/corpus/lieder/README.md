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

| part | notes | missing | extra | sounding match | overall (incl. rests) |
|---|---:|---:|---:|---:|---:|
| P1 vocal | 340 | 3 | 3 | 98.94% | 98.24% |
| P2 piano | 1911 | 14 | 17 | 99.0% | 98.38% |

The corpus comparator's primary `match` scores sounding notes only; rest layout is reported
separately (`rest_missing` / `rest_extra` / `overall_match`) because secondary-voice rests may be
hidden by the display layer.

A shorter run on `aus_meinen_traenen` gives raw OMR sounding matches of 91.38% (vocal) and 89.58%
(piano); after the pipeline they are 91.38% and 90.10% with clean verifiers and no correct sounding
event lost. Its source has a pickup measure numbered 0, which the comparator aligns by measure ordinal
rather than by the printed number.

`die_wetterfahne` gives raw OMR 98.97% (vocal) and 97.75% (piano); the pipeline keeps both scores,
is verifier-clean, and loses no correct sounding event (P2 adds two hidden rests).

`der_lindenbaum` is the outlier: raw OMR is 99.51% (vocal) but only 50.89% (piano). The first P2
pipeline run dropped to 34.66% because `merge_staff_voices` rebuilt tuplet measures: a 16th-triplet
(duration 1680/10080) got the fallback type `quarter` and lost its `<time-modification>`, so MuseScore
laid the measure out as 4.875 beats instead of 3. The merge now skips any staff with tuplets; P2
settles at 51.44% (slightly above raw OMR) with 70 display measure-length warnings instead of 86.
The raw piano is still poor; use `lindenbaum_omr_raw.mscz` for inspection.

The P1 pipeline (`scorepipe .../P1.musicxml`) is verifier-clean and keeps the same 98.94% sounding
match.  The P2 piano part also converges (2 rounds, clean verifier) and matches the ground truth at
98.64% overall / 99.0% on sounding notes after the pipeline; `merge_staff_voices` protects a notated
sustained note when merging would shorten it into another voice's run (m5 D4), and treats rest onsets
as merge boundaries so an intentional rest is not deleted (m25). Page runs skip `sanitize_slurs`;
the page slur restoration is authoritative for those scores.

## Rebuild

```powershell
python tests/corpus/lieder/build_case.py path/to/lc5015378.mxl tests/corpus/lieder/gute_nacht
python tests/corpus/lieder/compare_parts.py \
  tests/corpus/lieder/gute_nacht/ground_truth.musicxml omr-output.musicxml
```

The comparator normalises each part to beats and matches notes by
`(measure, onset, pitch, duration)`, so chord layout and voice numbering do not affect the score.
