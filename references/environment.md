# Environment setup

`preflight.py` is read-only: it reports what is present and what is missing. It never installs
model weights, packages, or system tools. Ask the user before changing their environment.

## Required

| Piece | Why | Probe |
|---|---|---|
| Python 3.10+ | runs `scorepipe` | `python --version` |
| `scorepipe` checkout | pipeline | `python -c "import scorepipe"` |
| OMR Python env | upstream `copisteria` (Python 3.12+) | `--omr-python` or `COPISTERIA_PYTHON` |
| copisteria source | upstream OMR engine & `models/` weights | `--repo` or `COPISTERIA_REPO` |
| MuseScore 4 | `.mscz`, PDF render | `MUSESCORE_EXE` or common paths |
| poppler | PDF page extraction, count & raster (`pdfinfo`, `pdftoppm`, `pdfimages`) | `pdfinfo`, `pdftoppm`, `pdfimages` |

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
COPISTERIA_PYTHON     interpreter that can import copisteria
COPISTERIA_REPO       upstream copisteria source checkout (contains models/)
MUSESCORE_EXE         MuseScore executable
```

## Manual setup sketch

Use the user's own package manager/venv. A typical setup is:

```bash
# 1. Python environment for this repository
python -m venv .venv
.venv/Scripts/python -m pip install -e .

# 2. Separate OMR environment (upstream kobimusic/copisteria)
python -m venv .venv-copisteria
.venv-copisteria/Scripts/python -m pip install -e path/to/copisteria

# 3. Put copisteria weights in its source tree's models/ directory
#    (e.g. models/evidence-2m.pt and models/small/v7_obj-recall-30m_best.pt).
#    Check the copisteria README for the exact download commands; do not download them silently.
```

MuseScore 4 and poppler are system installs. If they are unavailable, deliver MusicXML only and
say that the `.mscz`/PDF review was not produced.

## Why a separate OMR interpreter

copisteria pins Python 3.12+ and torch/opencv/scipy versions that are not the pipeline's
dependencies. Keeping it separate avoids breaking the pipeline tests and makes the boundary
explicit.
