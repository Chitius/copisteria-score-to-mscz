# Troubleshooting

## MuseScore crashes while importing MusicXML

A schema-valid file can still crash MuseScore's importer. Reproduce outside the pipeline:

```bash
MuseScore4.exe -o out.mscz score.musicxml
```

A non-zero exit means the file is not importable, even if `xmllint` says it validates.

### Known importer traps

- **A `<forward>` that fills the rest of a bar and is followed by `<backup>`** with a duration not
  on a quarter-beat grid. Example: 26040 ticks at 10080 divisions (`31/12` beats). The
  `normalize_forward_durations` pass rounds it down and shortens the following backup.
- **A tuplet rest whose duration is not representable as a plain rest**, e.g. a 1680-tick 16th
  rest with `<time-modification>3:2</time-modification>`. The `normalize_tuplet_rests` pass makes
  it a plain grid rest and removes the time-modification.
- **A grace note MuseScore will not keep as a grace.** MuseScore 4.6 imports `<grace/>` +
  `<type>eighth</type>` as a *real* eighth note, and a tie between two grace notes as a real note
  too, so the bar grows by the grace's written value (Gurenge m111/m112, +0.5 beat each). Its own
  export writes acciaccaturas as 16th graces; `normalize_grace_notes` rewrites the type and
  `reconcile_tie_slurs` drops grace-to-grace ties. Symptoms: `mscx-measure-length` in bars that
  the MusicXML verifier calls clean.
- A missing `id` on `<part>` is invalid and can also terminate the import; check the skeleton when
  bisecting.

### Bisect a crashing file

Make prefixes of the score (`first 8`, `16`, `32`, ... measures), import each, and find the first
failing prefix. Then dump that measure and remove one construct at a time (forward, backup, tuplet
rest, chord member). Keep the failing prefix as a regression fixture.

This is how the 前前前世 10-page file was isolated to m16/m84 (`forward`) and m115 (tuplet rest).

### After the crash is fixed

A file can import but still have display measure-length warnings. Those are separate structural
issues; do not call the score delivered just because MuseScore opens it. Run the full verifier and
inspect the rendered pages.

## `UnicodeEncodeError` from an operator script

On a Windows console whose code page is GBK (936), printing a character outside that code page
raises `UnicodeEncodeError` and aborts the script mid-table. `preflight.py` hit this because its
probe decodes subprocess output with `errors="replace"`, which can produce U+FFFD. Every operator
script calls `scorepipe.console.harden_stdout()` before it prints anything; if you add a script,
call it too (`tests/test_console.py` enforces this). The encoding is left untouched on purpose, so
Chinese paths stay readable on a Chinese console instead of turning into mojibake.

## CJK filenames print as boxes in the proof-sheet cover

`scorepipe.proof_sheet.compose._font` picks a CJK face from the script the text uses. Malgun Gothic
is a Korean face: it loads fine but draws simplified Chinese as `.notdef` boxes, so it must not win
for Han text. `_covers` renders each non-Latin character and compares it with the font's `.notdef`
box, so a loaded-but-glyphless candidate is skipped.

