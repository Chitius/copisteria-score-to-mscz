# Notation patches (prototype)

Facts describe metadata. Long-tail score symbols are better handled by a **constrained notation
patch** than by one facts channel per symbol.

The agent proposes an operation at musical anchors; the compiler writes standard MusicXML, and
MuseScore builds the real object. The agent never writes mscx ids or location fractions. The JSON
shape is in `schemas/notation-patches.schema.json`.

## Current operation: ottava

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

`start`/`end` are 1-based measure numbers and 0-based quarter-note beats. Both anchors must exist
and `end` must be after `start`. `page` and `bbox`/`crop` are required evidence fields.

## Modes

`mode` is optional; the default is `add`.

| mode | behavior |
|---|---|
| `add` | add a new spanner |
| `replace` | remove all octave shifts on the target staff, then add this one |
| `remove` | remove all octave shifts on the target staff |

For a wrong OMR 8va on the bass staff, use `remove` on staff 2 and `add` on staff 1. Do not let a
single patch silently move a spanner between staves.

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
  --input out/score.musicxml -o review/score-map.json

# 2. Agent looks at page images + score-map and writes patches.json.

# 3. Promote a reviewed tuplet proposal to accepted.
python scripts/notation_patches.py accept \
  --patches review/patches.json --musicxml out/score.musicxml \
  --indices 0 --reviewer "reviewer-name" -o review/patches.accepted.json

# 4. Validate/apply. Either script:
python scripts/notation_patches.py apply \
  --input out/score.musicxml --patches review/patches.accepted.json \
  -o out/score.patched.musicxml

# or the pipeline CLI (tuplet before structural, ottava after inject):
python -m scorepipe.cli path/to/pages -o out/score.musicxml --mscz-out out/score.mscz \
  --patches review/patches.accepted.json --report out/report.json
```

## 8va range safety

The range is the risky part. The compiler enforces:

- start and end are in the same staff;
- end is strictly after start;
- measures exist;
- the resulting octave-shift directions are present exactly once.

The delivery loop must then:

1. render the patched `.mscz`;
2. inspect the start/end systems and the bracket extent;
3. if the end is ambiguous, keep it `unresolved` or revise the anchors;
4. never let the agent silently extend the spanner to "look plausible".

Pixel coordinates are evidence only; the applied range comes from musical anchors, not bbox.

## Scope

The supported operations are `ottava` and the constrained same-voice `tuplet` correction above. Other
symbols and cross-voice/missing-note rhythm repair still need their own compilers and render regressions.
