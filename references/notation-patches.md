# Notation patches

Facts describe metadata. Long-tail score symbols are better handled by a **constrained notation
patch** than by one facts channel per symbol.

The agent proposes an operation at musical anchors; the compiler writes standard MusicXML, and
MuseScore builds the real object. The agent never writes mscx ids or location fractions. The JSON
shape is in `schemas/notation-patches.schema.json`.

## Ottava (`8va` / `8vb`)

`8va` / `8vb` is compiled to MusicXML `<octave-shift>` directions; MuseScore turns them into an
Ottava spanner.

```json
{
  "patches": [
    {
      "op": "ottava",
      "subtype": "8va",
      "staff": 1,
      "start": {"measure": 31, "beat": 1},
      "end": {"measure": 31, "beat": 4},
      "page": 2,
      "bbox": [820, 1260, 1020, 1310],
      "evidence": "8va dashed bracket covers the last five notes of m31",
      "confidence": 0.72
    }
  ]
}
```

`start`/`end` are 1-based measure numbers and 0-based quarter-note beats. Both anchors must exist;
`end` must be at or after `start` (same-beat `start == end` is supported for single-chord `8va`/`8vb`
marks). `page` and `bbox`/`crop` are required evidence fields.

## Modes

`mode` is optional; the default is `add`.

| mode | behavior |
|---|---|
| `add` | add a new spanner |
| `replace` | remove all octave shifts on the target staff, then add this one |
| `remove` | remove all octave shifts on the target staff |

For a wrong OMR 8va on the bass staff, use `remove` on staff 2 and `add` on staff 1. Do not let a
single patch silently move a spanner between staves.

## Clef placement

A clef change that copisteria put on the wrong bar is one patch, not a hand edit. It writes a
standard MusicXML `<clef>` at the anchor measure and, when `from_measure` is given, retires the
clef the OMR placed there. There is no `beat`: a clef belongs to the barline.

```json
{
  "patches": [
    {
      "op": "clef",
      "measure": 56,
      "staff": 2,
      "clef": "F",
      "line": 4,
      "from_measure": 58,
      "status": "accepted",
      "page": 4,
      "bbox": [178, 138, 193, 163],
      "evidence": "bass clef is printed at the end of m55; copisteria read it at m58"
    }
  ]
}
```

`clef` is `G`, `F` or `C`; `line` is 1–5. The patch runs before the structural fixpoint, so the
redundant-clef pass can also drop a duplicate that follows. `status` must be `accepted` and
`page` + `bbox`/`crop` are required, like the other operations.

## Tuplet rhythm corrections

`tuplet` retimes an existing, complete run of pitched notes in one measure/staff/voice. It is for OMR
runs whose notes exist but whose ratios or internal forward gaps are wrong. It never creates pitches,
turns rests into notes, merges voices, crosses a barline, or nests tuplets.

```json
{
  "op": "tuplet",
  "measure": 122,
  "staff": 1,
  "voice": "1",
  "start": {"measure": 122, "beat": 1, "pitch": "C#5"},
  "end": {"measure": 122, "beat": 1.8333333333333333, "pitch": "F#6"},
  "actual_notes": 5,
  "normal_notes": 4,
  "note_count": 5,
  "span_beats": 1,
  "status": "accepted",
  "page": 6,
  "bbox": [340, 675, 405, 725],
  "bbox_space": "image-px",
  "evidence": "one printed 5 bracket covers these five notes",
  "confidence": 0.98
}
```

`actual_notes/normal_notes` define only the ratio. `note_count` independently counts base-note onsets;
a chord counts once. `span_beats` is the source-backed sounding extent in quarter beats. These values
must agree with the note types and dots, but the compiler must never infer a ratio from a bad bar length.
`end` is the last included note's onset, not the exclusive end of the bracket.

The patch must be explicitly `accepted` after reviewing the source evidence. Proposed or incomplete
patches are rejected. The compiler removes forward gaps inside the evidenced contiguous run, but rejects
rests, backup, other voices, missing/extra anchors, nested or boundary-crossing old tuplets, overlapping
patches, non-integer ticks and any mismatch with `note_count` or `span_beats`.

Tuplet patches apply before the structural fixpoint; ottava patches retain their post-pipeline timing.
Re-run both MusicXML and MSCX verifiers and inspect the rendered bracket after every application.

## Workflow

```bash
# 1. Export stable note anchors for the agent.
python scripts/notation_patches.py map \
  --input out/score/score.musicxml -o review/score-map.json

# 2. Agent looks at page images + score-map and writes patches.json.

# 3. Promote a reviewed tuplet proposal to accepted.
python scripts/notation_patches.py accept \
  --patches review/patches.json --musicxml out/score/score.musicxml \
  --indices 0 --reviewer "reviewer-name" -o review/patches.accepted.json

# 4. Validate/apply. Either script:
python scripts/notation_patches.py apply \
  --input out/score/score.musicxml --patches review/patches.accepted.json \
  -o out/score/score.patched.musicxml

# or the pipeline CLI (tuplet before structural, ottava after inject):
python -m scorepipe.cli path/to/pages -o out/score/score.musicxml --mscz-out out/score/score.mscz \
  --patches review/patches.accepted.json --report out/report.json
```

## Pedal, wedge (hairpin), and dynamic patches

- **`pedal`**: writes MusicXML `<pedal>` directions between `start` and `end` (with optional `changes` anchors, `line` boolean, `placement`, and `mode`: `add`/`replace`/`remove`).
- **`wedge`**: writes MusicXML `<wedge>` crescendo/diminuendo hairpins (`subtype`: `crescendo` | `diminuendo`, optional `niente` boolean, `placement`, and `mode`).
- **`dynamic`**: writes a MusicXML `<dynamics>` mark at `measure`, `beat`, and `staff` (`mark` in standard dynamic symbols such as `pp`..`ff`, `mp`, `mf`, `sfz`, `fp`, etc., with optional `placement` and `mode`).

All three support optional `part` targeting (defaulting to the first part) and require `page` + `bbox`/`crop` + `evidence`.

## 8va range safety

The range is the risky part. The patch has one `staff` field; the compiler enforces:

- end is at or after start (same-beat single-chord ottava is allowed; end before start is rejected);
- measures exist;
- the octave-shift start/stop directions share the expected number and size;
- evidence and a bbox/crop are present in the schema.

The delivery loop must then:

1. render the patched `.mscz`;
2. inspect the start/end systems and the bracket extent;
3. if the end is ambiguous, keep it `unresolved` or revise the anchors;
4. never let the agent silently extend the spanner to "look plausible".

Pixel coordinates are evidence only; the applied range comes from musical anchors, not bbox.

## Scope

The supported patch operations are `ottava` (including single-chord same-beat), `clef`, constrained same-voice `tuplet`, `pedal`, `wedge`, and `dynamic`. Controlled pitch/octave/duration `corrections` share the same `scripts/notation_patches.py accept/apply` CLI via `--corrections`. Cross-voice or missing-note rhythm repair still requires dedicated compilers and render regressions.
