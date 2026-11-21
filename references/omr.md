# OMR stage

## Page contract

The OMR step must leave **one MusicXML per PDF page** in a directory, plus its reading/debug
files. The scorepipe page loader uses those files to:

- merge page-local measure numbering into a global score;
- normalize differing `<divisions>` across pages;
- restore page-level ties, slurs, pedals, wedges, arpeggios and articulations.

Do not feed the OMR tool's final merged MusicXML to the pipeline: it has already lost the page
context needed by the restoration passes, and the old converter may have applied its own
voice-merge heuristics.

Typical copisteria layout:

```text
work/
  copisteria/
    input_<hash>_p01.musicxml
    input_<hash>_p02.musicxml
    input_<hash>_p01.reading.json
    input_<hash>_p01.html
  pages/
    input_<hash>_p01.png
```

`scripts/convert.py` locates the directory containing the page `*.musicxml` files and passes that
directory to `scorepipe`.

## Wrapper

```bash
python scripts/convert.py score.pdf --outdir out/score --env env.local.json \
  --title "Title" --composer "Composer"
```

It runs:

1. the external copisteria converter with a work directory;
2. `scorepipe` on `work/copisteria`;
3. MuseScore conversion and PDF render, if available.

The converter may exit non-zero **after** writing valid page files (known copisteria behavior).
The wrapper checks for page files and continues with a warning rather than discarding good output.
It does not treat the old converter's merged MusicXML as the review master.

## OMR failures that are not pipeline failures

Keep these in the report, do not hide them:

- a note on the wrong side of a barline (pickup placement);
- an octave/ledger-line hallucination (e.g. C8 where the page has a lower note);
- a whole voice/beam missing because the detector did not see it;
- page seams with duplicated or missing measures.

The pipeline can repair structure, but it must not invent a missing pitch. Use explicit facts or
manual corrections, and show the page evidence.

## Page count checks

Before accepting an OMR run, compare:

```text
pdfinfo pages  ==  number of page MusicXML files
```

and inspect at least the first and last page. If a page is missing, stop; do not deliver a score
with a silent gap.
