# Design

## Shape of the pipeline

We borrow three ideas from an optimising compiler:

1. **An IR with a stable hash.** Two states are equal iff their canonical serialisation is equal.
   The runner never relies on "the last pass said it changed nothing" alone.
2. **Passes with a declared ownership.** One property, one writer. If two passes can write voice
   order, the pipeline is non-confluent and will oscillate.
3. **Fixed-point iteration plus a verifier.** Mechanical passes run until a full round leaves the
   hash unchanged; a read-only verifier then states what is still wrong.

```
           ┌──────────── structural fixpoint ─────────────┐
load ──► IR │ merge · restore · rebase · dedupe · sanitise │
           └──────────────────────┬───────────────────────┘
                                  ▼
                        facts (text layer / agent)  ── produces JSON, not edits
                                  ▼
           ┌──────────────────── inject fixpoint ─────────┐
           │ apply marks · credits · pickup · metadata    │
           └──────────────────────┬───────────────────────┘
                                  ▼
                        lower to .mscx (MuseScore import)
                                  ▼
           ┌───────────────── display fixpoint ───────────┐
           │ voice order · padding · rests · tempo objects│
           └──────────────────────┬───────────────────────┘
                                  ▼
                            verify (read only)
                                  ▼
                          report / deliver
```

`lower` is not a pass: MuseScore's import is not idempotent with respect to our invariants (it
re-creates hidden measure rests, text voices and irregular bar lengths). Treating it as a boundary
keeps the display invariants honest.

## Ownership table

| Property | Owner pass |
|---|---|
| voice order within a measure | `canonical_voice_order` |
| redundant rest-only voices | `drop_padding_voices` |
| rest visibility | `unhide_real_rests` |
| rests inside text voices | `drop_text_voice_rests` |
| time signature placement | `hoist_time_signature` |
| tempo objects | `upgrade_tempo_marks` |
| gradual tempo spanners | `upgrade_gradual_spanners` |
| measure durations | `rebase_measures` |
| tie elements | `dedupe_ties` |
| slur endpoints | `sanitize_slurs` |

Any pass not listed must not touch these fields. This is the rule that would have prevented the
"reorder re-added the deleted voice" bug: `drop_padding_voices` removes; `canonical_voice_order`
only reorders what is present.

## Monotone measures

Each mechanical pass names the counter it must not increase:

| Pass | Measure |
|---|---|
| `dedupe_ties` | duplicate tie elements per note |
| `drop_redundant_time_signatures` | repeated identical time signatures |
| `unhide_real_rests` | hidden non-measure rests |
| `drop_padding_voices` | rest-only voices next to a chord voice |
| `rebase_measures` | measures whose content ≠ metre |
| `sanitize_slurs` | unmatched slur endpoints and >N-bar pairs |

The runner can therefore stop safely: a full round without a hash change means every pass is at
its local fixpoint, and because each pass is monotone over the same well-founded domain, the whole
system is.

## External facts

The text layer and the agent are *fact producers*:

```json
{"marks": [{"measure": 9, "beat": 0, "placement": "above", "rehearsal": "A",
            "text": "Allegro", "tempo": 110, "beat_unit": "quarter"}]}
```

The inject passes are mechanical and idempotent: a fact already present is skipped. Facts never
cause a rebuild that could undo a structural pass, because injection is part of the same fixpoint
loop and structural passes must preserve injected elements or be re-run after them.

## Verifier

Read-only. Reports violations with a stable code, measure and detail. The runner treats a
violation as:

- repairable and a pass owns it → schedule another outer round (bounded);
- unrepairable → hand to the agent with the trace.

## Migration plan

1. Core: document, pass base, runner, trace, verifier. (this commit)
2. Port structural passes one by one, each with a fixture that fails before and passes after.
3. Port display passes onto `.mscx`, with a re-save idempotence test.
4. Port fact producers (text layer, agent JSON).
5. Only then port the OMR conversion front-end (copisteria invocation) as the loader.
