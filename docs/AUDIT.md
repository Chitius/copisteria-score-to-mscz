# Audit register — 2026-11-23

This is the working register for the self-audit of the OMR → MusicXML/MuseScore skill. It records
the findings from the code, test and documentation reviews, the decisions made about them, and the
batch in which each one is fixed.

Status values: **open**, **in progress**, **fixed**, **deferred**, **wontfix**.

## Baseline

- `python -m pytest tests -q -p no:cacheprovider`: 306 passed.
- `python -m unittest discover -s tests`: 224 OK.
- Registry: 51 passes (30 structural mechanical + 1 analysis, 2 inject, 18 display).
- Plain `pytest` from the repository root fails collection because of ACL-denied
  `.pytest_cache` / `pytest-cache-files-*` directories.
- No checked-in XSD validation, no MuseScore import/render round-trip in the suite, and no full
  OMR → merge → pipeline → delivery end-to-end test.
- The audit was read-only; this document starts the repair phase.

## Severity

- **P0** — can delete/shift music, report a destructive result as ready, or silently bypass an
  acceptance/coverage gate.
- **P1** — high risk, hidden failure, or a workflow/documentation contradiction that makes the
  advertised path invalid.
- **P2** — missing test/UX/reporting quality; no immediate data loss.
- **P3** — polish, naming, stale prose.

## A. Forced truncation and pipeline safety

| ID | Sev | Finding | Evidence | Fix / test | Status |
|---|---|---|---|---|---|
| A1 | P0 | Tuplet members are edited with un-ratioed durations. Excess is computed with tuplet ratios, but `_shorten`/removal use `_beats(child, meter)` without the ratio. MuseScore writes flat `<Tuplet>…<endTuplet/>` markers, so tuplet chords are in the candidate list. | `scorepipe/passes/mscx_truncate.py:44-104`; `scorepipe/core/mscx_invariants.py:101-107`; real forced mscz has `<duration>` inside tuplets (m86, m222) | Use one precomputed contribution per event; never edit inside a `Tuplet…endTuplet` range; single-run fixpoint; flat-marker fixture | fixed (batch1) |
| A2 | P0 | It removes/shortens positional rests anywhere, not only at the tail. `[Rest(1), Chord(4)]` in 4/4 loses the leading rest and the chord moves from beat 1 to 0. | `mscx_truncate.py:50-65`; test `tests/test_mscx_truncate.py:30-35` enshrines this | Trim only trailing rests after the last chord, then shorten the last chord; assert onsets survive | fixed (batch1) |
| A3 | P0 | Unresolved truncations are not recorded. The pass appends an `unresolved` note but not `changed`; the runner only writes trace on `changed`, so an overfull tuplet-only voice can produce `operations=[]`, `verifier=[]`, `ready=true`. | `mscx_truncate.py:82-84`; `scorepipe/core/pipeline.py:68`; `scorepipe/mscz_export.py:82-102` | Add explicit unresolved status; always emit trace/report; make ready require no unresolved | fixed (batch1) |
| A4 | P0 | The staff in the report is an Element repr with a memory address. | `mscx_truncate.py:41,83,86`; `scorepipe/core/mscx.py:47-50`; `zen_forced/forced-truncation/truncation-report.json` | Use staff index + `staff.get("id")`; machine-readable ints, no formatted floats | fixed (batch1) |
| A5 | P0 | `--truncate-overfull` is a no-op without `--mscz-out`, and review still reports a ready forced copy. With `--no-mscz`, forced MusicXML is identical to reviewed. | `scorepipe/cli.py:129`; `scorepipe/mscz_export.py:79`; `scripts/review.py:341-402`; `references/review.md:84-86` | Reject the flag without an mscz output, or implement it structurally; report applied/skipped/failed explicitly | fixed (batch1) |
| A6 | P0 | Display-final reports hardcoded `rounds=1`, `stable=True`, `TraceEntry(round=1)` even when two rounds ran; dead `final_result`. | `scorepipe/mscz_export.py:84-105` | Accumulate real rounds; stable only after a zero-change, zero-unresolved round | fixed (batch1) |
| A7 | P1 | `_shorten` keeps the original `durationType` and `dots` while adding an explicit `<duration>`, producing inconsistent notation (dotted 32nd lasting 1/6 beat; half rest lasting 2.75). No MuseScore round-trip proof. | `mscx_truncate.py:107-115`; forced mscz m75/m222 | Emit valid notation or a documented irregular representation; add a MuseScore re-import/render assertion | open |
| A8 | P1 | Chord deletion reports only “removed chord N beats”; no pitches/onsets; can leave dangling ties/slurs/spanners. | `mscx_truncate.py:66-81` | Report deleted pitches/onsets; prune/flag spanners; prefer shortening over deletion | in progress (batch2) |
| A9 | P1 | The intermediate MusicXML path can overwrite and then delete a user file: `destination.with_suffix(".musicxml")` is unlinked when `work_musicxml` is not passed. | `scorepipe/mscz_export.py:68,111-113` | Use an isolated temp directory; only delete files the function created | fixed (batch1) |
| A10 | P1 | Meter model ignores `Measure@len`/pickup metadata and keys signatures only by measure index across all staves. | `mscx_truncate.py:28-42`; `mscx_invariants.py:125-141` | Read `Measure@len`/pickup, keep meter per staff, add pickup fixture | in progress (batch2) |

## B. Verifiers and patch validation

| ID | Sev | Finding | Evidence | Fix / test | Status |
|---|---|---|---|---|---|
| B1 | P0 | `verify_patches` accepts drift: ottava only checks any start/stop; tuplet only checks anchor pitch and global modified count. Size 8→15, end moved, duration changed, bracket removed, or one note lost + one cloned all still return clean. | `scorepipe/notation_patches.py:510-568`; tests only delete time-modification at `tests/test_notation_patches.py:131-142` | Verify number/size/type/order/span, per-note onsets/durations, brackets; add five negative tests | fixed (batch2) |
| B2 | P0 | Patch-verification failure is erased from CLI exit status: `status=1` at the patch check is overwritten by the verifier assignment. | `scorepipe/cli.py:145-166`; `tests/test_cli.py:109-149` | Keep `patch_failed` separate, include it in report, OR into exit; add integration test | fixed (batch1) |
| B3 | P1 | MSCX `measure_lengths` checks only the first chord voice; an overfull secondary voice returns clean. Truncation edits every voice. | `mscx_invariants.py:156-157,169-175`; `mscx_truncate.py:41-87` | Check all voices; add overfull-secondary test | fixed (batch2) |
| B4 | P1 | `<Rest><visible>1</visible>` is reported as hidden because only presence is checked. | `mscx_invariants.py:12-23` | Treat `0/false` as hidden; table-test all six verifiers | fixed (batch2) |
| B5 | P1 | MusicXML invariants miss empty measures, overfull `implicit` bars, broken second parts, and grace notes (no duration). | `scorepipe/core/invariants.py:93-116`; `scorepipe/core/document.py:53-54,64-103` | Add negative tests; reject multi-part or check every part; account for grace notes | open |
| B6 | P1 | New-violation detection keys only `(code, measure)`, so a second identical violation or worse detail is invisible. | `scorepipe/sanity.py:574-597` | Key by `(code, measure, detail)` or Counter; add same-code/worse-detail tests | fixed (batch2) |
| B7 | P1 | Five of six MSCX verifiers have no direct tests; only `measure_lengths` is covered. | `tests/test_mscx_invariants.py` | Positive/negative table tests for hidden rests, text-voice rests, padding voices, voice order, empty voices | fixed (batch2) |

## C. Tests and pass-sanity framework

| ID | Sev | Finding | Evidence | Fix / test | Status |
|---|---|---|---|---|---|
| C1 | P0 | Pass-sanity never asserts an effect. Replacing all 32 structural/inject passes with no-ops still gives ok=True; 8 fixtures are already `changed=0`. | `tests/test_pass_sanity.py:343-357`; fixtures at `:74-119,259-264` | Assert exact `changed` and element postconditions; add a meta no-op mutation test; fix the eight fixtures | fixed (batch2) |
| C2 | P0 | Idempotence and contracts cannot see unreported or non-note mutation: only `second.changed` is checked; snapshots cover notes only, not slurs/ties/beams/text. | `scorepipe/sanity.py:651-661,268-307,492-531` | Compare state hash after the second run; add element inventory; negative mutation tests | fixed (batch2) |
| C3 | P0 | Display mechanical passes (18) and the analysis pass have no pass contract/idempotence coverage. | `tests/test_pass_sanity.py:330-340` | Add a display/analysis contract registry or explicit exemption list, plus mutation tests | in progress (batch2) |
| C4 | P1 | `test_mscx_truncate` uses nested `<Tuplet>` (not MuseScore's flat shape) and has a tautological `assertGreaterEqual(changed, 0)`; no idempotence/unresolved/multi-voice/pickup/ties tests. | `tests/test_mscx_truncate.py:30-61` | Rewrite with flat fixtures; exact changed/notes; one-run fixpoint; unresolved test | in progress (batch1) |
| C5 | P1 | Delivery tests are stateful/mocked, skip forced truncation, and have no success/stale-artifact/`--no-mscz` matrices. | `tests/test_delivery_scripts.py:13-14,98`; `scripts/convert.py:218-224` | Use tmp_path; assert artifacts from this run; test forced success/failure/skip | open |
| C6 | P1 | `test_cli` asserts exit 0 where the real patch verifier should fail; it enshrines B2. | `tests/test_cli.py:109-149` | Integration test: clean verifier + failed patch verify => exit 1 | fixed (batch2) |
| C7 | P1 | Lieder corpus tests compare ground truth to itself; no pipeline run. | `tests/test_lieder_corpus.py:42-51` | Add one end-to-end threshold case or label as fixture-integrity only | open |
| C8 | P1 | Plain pytest fails on ACL-denied cache dirs; tests write into repo `.runs` and rely on CWD. | repo root `.pytest_cache`, `pytest-cache-files-*`; `test_delivery_scripts.py:13-14`; `from scripts import` | Add `conftest.py`/`testpaths`, tmp_path, sys.path fixture; clean cache dirs | open |
| C9 | P1 | No XSD validation and no MuseScore import/render round-trip in tests. | `tests/`; `tests/test_mscz_export.py` is skipped without MuseScore | Add an opt-in MuseScore integration test and XSD validation for a fixture | open |
| C10 | P2 | `run_pipeline` `repairable` outer-round path is dead; analysis `mutated` and non-convergence are untested. | `scorepipe/core/pipeline.py:84-98,137-153`; `scorepipe/cli.py:129` | Enable/test a repairable pass; assert stable=False on cap; test analysis mutation | open |

## D. Workflow, acceptance and readiness

| ID | Sev | Finding | Evidence | Fix / test | Status |
|---|---|---|---|---|---|
| D1 | P0 | proposed vs accepted contradiction: agent docs say write `status: proposed`; tuplet validation requires `accepted`; ottava ignores status entirely; SKILL 4c passes `patches.json`. | `SKILL.md:177-179`; `references/agent-review.md:25-27`; `scorepipe/notation_patches.py:161-191`; `scripts/notation_patches.py:57-59` | Define one state machine; require accepted+accepted_by for ottava and tuplet; update examples | fixed (batch3) |
| D2 | P0 | Corrections are a dead queue: no consumer, and `--allow-corrections` only suppresses the blocker; it never applies `to`. | `scorepipe/agent_facts.py:97-113,198-210`; `scripts/review.py:196-209` | Add accept-correction + constrained applier, or document manual-only and drop the claim | fixed (batch3) |
| D3 | P0 | Coverage gate turns off when `pdfinfo` is missing: page_count falls back to facts count. Two reviewed pages of a ten-page PDF can pass. | `scripts/review.py:172-174,200` | Fail closed or require `--page-count`; mark pdfinfo required for review | fixed (batch1) |
| D4 | P0 | `merge` without `--pages` performs no coverage check, and every example omits it. | `scripts/agent_facts.py:181-206`; docs commands | Require `--pages` or explicit `--allow-missing-pages`; update examples | fixed (batch3) |
| D5 | P0 | Advertised quick path (`convert.py`) bypasses review: no facts/page coverage, no mechanical/forced trees, but `delivery.json.ready` can be true. | `SKILL.md:29-38`; `README.md:14-30`; `scripts/convert.py:205-224` | Make review mandatory or label output `reviewed:false`; align delivery checklist | fixed (batch3) |
| D6 | P1 | Failed mechanical baseline does not block `ready`. | `scripts/review.py:242-253,266` | Add blocker/`artifacts_missing` when mechanical fails | fixed (batch3) |
| D7 | P1 | `--no-mechanical` / `--no-forced-truncation` / `--no-pdf` can yield ready with required artifacts absent and no warning. | `scripts/review.py:157-162,340-402` | Record missing artifacts and set `interim:true`/`ready:false` unless explicitly allowed | fixed (batch3) |
| D8 | P1 | Forced-truncation warning is weak/backwards; CLI help does not say notes/rests may be deleted; review.md says the flag is for when the overfull copy is wanted. | `scorepipe/cli.py:48-52`; `references/review.md:84-86` | State deletion clearly; correct wording; print operations before writing | in progress (batch1) |
| D9 | P1 | `accept` can record acceptance with an empty reviewer. | `scripts/notation_patches.py:45,60-62`; `references/agent-review.md:75` | Require non-empty `--reviewer`; record timestamp | fixed (batch3) |
| D10 | P1 | No canonical delivery tree; convert uses `out/score`, review uses `review/score`, delivery.md requires one root with both trees. No command produces it; review does not write `delivery.json`. | `SKILL.md:34`; `references/review.md:16-21`; `references/delivery.md:3-28`; `scripts/review.py` | Pick one root and one sequence; make review write `delivery.json` or document convert as draft | fixed (batch3) |
| D11 | P1 | Review/convert accept stale artifacts by existence; failed reruns can report old mscz/pdf. | `scripts/review.py:382-386`; `scripts/convert.py:218-224` | Clear/stamp outputs; include run id/time/hash; only report files created this run | fixed (batch3) |
| D12 | P1 | Review cannot carry manual title/composer or compare to ground truth; MuseScore discovery differs from convert. | `scripts/review.py:171,288-303`; `scorepipe/cli.py:34,153-165` | Add `--title/--composer/--compare-golden`; reuse `_find_musescore` | fixed (batch3) |
| D13 | P1 | OMR wrapper does not enforce `pdfinfo pages == page count`; a dropped page silently shortens the score. | `references/omr.md:61-70`; `scripts/convert.py:142-147` | Compare page counts before merge; abort with both numbers | fixed (batch3) |
| D14 | P1 | Review does not clear old `source-*.png`; `_render_pages` counts stale pages and can fake coverage. | `scripts/review.py:73-87,178` | Remove old `source-*.png` before rendering; use page hashes | fixed (batch1) |
| D15 | P2 | Timing comparison uses a set, losing duplicate `(measure, detail)` findings. | `scripts/review.py:102-126`; `tests/test_delivery_scripts.py:113-147` | Use Counter or list-aware diff | fixed (batch3) |

## E. Documentation and UX

| ID | Sev | Finding | Evidence | Fix | Status |
|---|---|---|---|---|---|
| E1 | P2 | SANITY/ACCEPTANCE are presented as current but are stale snapshots: SANITY says 39 passes vs actual 51; ACCEPTANCE says 178/79 tests vs 224/306. | `docs/SANITY.md:3-13`; `docs/ACCEPTANCE.md:9-13,71-72` | Mark historical, regenerate counts/links, or move to archive | open |
| E2 | P2 | README says notation patches support only ottava; SKILL/schema/code support tuplets. | `README.md:186-187`; `SKILL.md:141-148`; `scorepipe/notation_patches.py:194` | Say ottava + constrained tuplet | open |
| E3 | P2 | `out/score.musicxml` (file) and `out/score/` (directory) are mixed; patch commands then point at a missing file. | `SKILL.md:34,136-138`; `references/agent-review.md:63`; `references/notation-patches.md:93-110` | Normalize to `out/score/score.musicxml` everywhere | open |
| E4 | P2 | Preflight docs name `--python` for the OMR interpreter; the flag is `--omr-python`; poppler is required in docs but optional in preflight. | `references/environment.md:12,15`; `scripts/preflight.py:152-154,162-163` | Correct flag and required/optional status | open |
| E5 | P3 | Agent file naming is inconsistent: `agent-pageNN`, `agent-page01`, `agent-page1`. | `SKILL.md:111,174`; `references/agent-review.md:32,59`; `README.md:115` | Standardize two-digit names and update all commands | open |
| E6 | P2 | `merge` writes facts/report before refusing incomplete coverage; consumers can use them. | `scripts/agent_facts.py:175-206` | Write `.partial`/`ready:false` or gate before writing | open |
| E7 | P3 | Label-stripping docs say the printed label stays in `evidence`; code only strips it. | `README.md:122-123`; `references/facts.md:100-103`; `scorepipe/agent_facts.py:24-33` | Append original label or correct docs | open |
| E8 | P2 | Ottava docs claim start/end staff enforcement; schema has one staff field and implementation never compares. Docs also say page alone is enough. | `references/notation-patches.md:115-119`; `schemas/notation-patches.schema.json:37-40,60`; `notation_patches.py:161-191` | Require evidence+bbox/crop; remove/reword staff claim | open |
| E9 | P2 | Destructive `replace/remove` have no dry-run or itemized deleted spanners; script prints only a count. | `references/notation-patches.md:40-47`; `scripts/notation_patches.py:87-89` | Add `--dry-run` and itemized report; require reviewer/force | open |
| E10 | P2 | Blocked review has two schemas/exit codes: validation errors use `errors`/1; normal blockers use `blockers`/2. | `scripts/review.py:188-191,265-286`; `references/review.md:25` | Unify schema; document 1 vs 2 | open |
| E11 | P2 | `--allow-unresolved`/`--allow-corrections` leave `ready:true` with no `interim`/`overrides` field. | `scripts/review.py:206-209,266` | Add `interim` and overrides; print INTERIM | open |
| E12 | P2 | `validate_facts` rejects metronome-only marks though schema/agent validation allow them. | `scorepipe/facts.py:34`; `schemas/facts.schema.json:38,51-56` | Include `metronome` | open |
| E13 | P3 | Lieder corpus README points at missing files/commands. | `tests/corpus/lieder/README.md:57-59` | Correct paths or remove | open |
| E14 | P3 | Undocumented flags: `--no-mechanical`, `--mechanical-dir`, `--forced-dir`, `--images`, `--dpi`, `--max-rounds`, `--truncate-overfull`. | scripts/review.py, agent_facts.py, convert.py, cli.py | Add a per-script flag table | open |
| E15 | P1 | Facts are not bound to the PDF/score: one `agent-page-all.json` can claim all pages; no PDF hash recorded. | `scorepipe/agent_facts.py:174-212`; shipped Zenzenzense facts | Require per-page files/markers; record PDF SHA-256; reject mismatches | in progress (batch3) |
| E16 | P1 | `convert.py` overwrites prior artifacts and arranger facts without warning; manifest omits facts.json. | `scripts/convert.py:149-150,171-186,218-225`; `SKILL.md:20` | Refuse without `--force`; separate arranger facts; include in manifest | open |

## Batch plan

### Batch 1 — stop destructive false-ready behavior

Scope: A1, A2, A3, A4, A5, A6, A9, B2, D8.

- Rewrite the mscx tail repair so it computes each contribution once and never edits inside a
  tuplet range.
- Remove only trailing rests; shorten the final chord when needed.
- Record unresolved operations and make `ready` require zero unresolved.
- Report staff ids, real round counts and real stability.
- Reject/disable `--truncate-overfull` without `--mscz-out`; report skipped/applied/failed.
- Preserve patch-verification failure in the CLI exit status.
- Add flat-tuplet, positional-rest, unresolved, idempotence and CLI integration tests.
- Decision: keep forced-truncation enabled only if all Batch 1 tests pass; otherwise default it off.

**Batch 1 result (2026-11-23):** A1/A2/A3/A4/A5/A6/A9/B2/D3/D14 fixed. The pass plans from the
tail, preserves positional rests, never edits inside flat tuplets, reports `UNRESOLVED` without
partial mutation, uses staff ids, records real rounds/stability, and rejects `--truncate-overfull`
without `--mscz-out`. The intermediate MusicXML is isolated. C4/D8 remain in progress. Verification:
240 unittest / 324 pytest; Zenzenzense forced copy: 20 edits, 2 rounds, verifier clean; Sincerely
unchanged with no forced operations.

### Batch 2 — verifier and pass-sanity integrity

Scope: B1, B3–B7, C1–C4, C6, C9, A7, A8, A10.

**Progress 2026-11-23:** B1, B3–B7, C1, C2, C6 fixed; C3/C4 in progress; C9/A7/A8/A10 remain.
`verify_patches` now checks ottava type/size/measure/number and tuplet onset span, bracket and
duration; MSCX length checks all overfull voices while allowing short secondary voices; explicit
`<visible>1</visible>` is no longer treated as hidden; pass fixtures now assert an actual effect and
the sanity framework compares state hashes and verifier details/multiplicity; display pass inventory
is explicit; truncation has multi-voice/3-4 tests. Verification: 240 unittest / 324 pytest.

- Strengthen `verify_patches` and add five drift tests.
- Check every voice; fix hidden-rest semantics; add empty/implicit/multipart/grace cases.
- Add expected-effect and no-op mutation tests for pass sanity, including display passes.
- Add a MuseScore round-trip fixture and an XSD check.

### Batch 3 — workflow, coverage and readiness

Scope: D1–D7, D9–D15, E15, E16.

**Progress 2026-11-23:** D1/D2/D4/D5/D6/D7/D9/D10/D11/D12/D13/D15 fixed; E15/E16 remain.
The CLI/review now require an accepted patch (legacy patches without a status remain readable),
`accept` handles ottava and requires `--reviewer`, `merge` requires `--pages` unless explicitly
overridden, review writes `delivery.json` with a PDF SHA-256 and blocks failed/mechanical/skipped
artifacts, and convert is labeled `reviewed:false`. Stale outputs are removed before reruns;
title/composer/compare-golden and the shared MuseScore resolver are wired into review.

- One proposed→accepted state machine; require `accepted_by`; make ottava and tuplet consistent.
- Require `--pages` for merge unless explicitly overridden.
- Fail closed when page count is unknown; record PDF hash and per-page coverage.
- Make review write one delivery manifest and only report run-created artifacts.
- Add title/composer/compare-golden and reuse the MuseScore resolver.
- Add blocked/interim/overrides semantics.

### Batch 4 — documentation and UX

Scope: C7, C8, C10, E1–E14.

- Mark historical docs; regenerate pass/test counts.
- Normalize score paths and artifact names.
- Document all flags and the single delivery sequence.
- Update corpus README and agent file naming.
- Add the audit register to the docs index.

## Acceptance criteria for closing the audit

- Every P0 finding has a regression test that fails before the fix and passes after it.
- No test passes by using a tautology or a no-op fixture.
- A deliberate no-op replacement of any registered pass makes its contract test fail.
- Forced truncation is idempotent, never edits inside a tuplet, never removes a rest that precedes
  a later chord, and reports every operation with a real staff id.
- A clean verifier plus failed patch verification exits non-zero.
- A 2-page review of a 10-page PDF cannot become ready when `pdfinfo` is missing.
- The documented quick path is either the real delivery path or explicitly labeled a draft.
- `pytest` runs from the repository root without ACL workarounds.
