# Environment setup

`preflight.py` is read-only: it reports what is present and what is missing. It never installs
model weights, packages, or system tools. Ask the user before changing their environment.

## Required

| Piece | Why | Probe |
|---|---|---|
| Python 3.10+ | runs `scorepipe` | `python --version` |
| `scorepipe` checkout | pipeline | `python -c "import scorepipe"` |
| OMR Python env | copisteria + music21 | `--omr-python` or `COPISTERIA_PYTHON` |
| copisteria source | OMR engine | `--repo` or `COPISTERIA_REPO` |
| MuseScore 4 | `.mscz`, PDF render | `MUSESCORE_EXE` or common paths |
| poppler | PDF page count/raster; required by `scripts/review.py`, optional for a `--pages` pipeline-only run | `pdfinfo`, `pdftoppm` |

Optional: `pdftotext` (PDF text layer), `xmllint` (schema debugging), a LaTeX/office renderer for
delivery packets.

## Configure once

```bash
python scripts/preflight.py
python scripts/preflight.py --save env.local.json
```

`env.local.json` contains local paths only. Do not commit it or ship it with a delivery.

The equivalent environment variables are:

```text
SCOREPIPE_PYTHON      interpreter that can import scorepipe
COPISTERIA_PYTHON     interpreter that can import copisteria/music21
COPISTERIA_REPO       copisteria source checkout
COPISTERIA_CONVERTER  path to the copisteria-to-musicxml/scripts/convert.py wrapper
MUSESCORE_EXE         MuseScore executable
```

## Manual setup sketch

Use the user's own package manager/venv. A typical setup is:

```bash
# 1. Python environment for this repository
python -m venv .venv
.venv/Scripts/python -m pip install -e .

# 2. Separate OMR environment
python -m venv .venv-copisteria
.venv-copisteria/Scripts/python -m pip install -e path/to/copisteria_src
.venv-copisteria/Scripts/python -m pip install -r path/to/copisteria-to-musicxml/requirements.txt

# 3. Put copisteria weights in its source tree's models/ directory.
#    Check the copisteria README for the exact filenames; do not download them silently.
```

MuseScore 4 and poppler are system installs. If they are unavailable, deliver MusicXML only and
say that the `.mscz`/PDF review was not produced.

## Why a separate OMR interpreter

copisteria pins torch/onnx/music21 versions that are not the pipeline's dependencies. Keeping it
separate avoids breaking the pipeline tests and makes the boundary explicit.
