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
      "start": {"measure": 30, "beat": 3.5},
      "end": {"measure": 31, "beat": 0},
      "page": 2,
      "bbox": [820, 1260, 1020, 1310],
      "evidence": "8va dashed bracket above the last system",
      "confidence": 0.72
    }
  ]
}
```

`start`/`end` are 1-based measure numbers and 0-based quarter-note beats. Both anchors must exist
and `end` must be after `start`. `page` and `bbox`/`crop` are required evidence fields.

## Workflow

```bash
# 1. Export stable note anchors for the agent.
python scripts/notation_patches.py map \
  --input out/score.musicxml -o review/score-map.json

# 2. Agent looks at page images + score-map and writes patches.json.

# 3. Validate/apply. Either script:
python scripts/notation_patches.py apply \
  --input out/score.musicxml --patches review/patches.json -o out/score.patched.musicxml

# or the pipeline CLI (applies before the structural fixpoint):
python -m scorepipe.cli path/to/pages -o out/score.musicxml --mscz-out out/score.mscz \
  --patches review/patches.json --report out/report.json
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

This is a prototype with `ottava` only. The same operation shape can later cover pedals, hairpins,
slurs, dynamics and tuplets, but each operation needs its own compiler and render regression.
