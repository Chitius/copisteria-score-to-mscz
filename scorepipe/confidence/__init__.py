"""Where the OMR reader was unsure: rank the symbols, paint the page, compare with the render.

copisteria's ``<page>.reading.json`` records, per symbol and per attribute, the detector's own
choice (``det``), the choice the context settled on (``v``), a probability (``p``) and how many
nats of evidence the context added (``ev``).  :func:`summarise` turns those numbers into a
"look here first" score, :func:`build_page` paints the scan with boxes coloured by *why* a symbol
is suspect, and a rendered page can be put beside it as a comparison.

Two rules keep this honest:

* the score orders a human's attention, it is not a calibrated error probability;
* a context override is not an error.  The context usually repairs the detector, so an override
  means "worth checking", not "wrong".  That is why the red class is named ``changed`` and not
  ``bad``.

The colours are stable across pages so a reader learns them once: red ``changed`` (the context
rewrote the detector's choice), orange ``existence`` (the reader was unsure the symbol is there
at all), amber ``attribute`` (an attribute probability is low), blue ``low`` (read normally, kept
only as a position reference).
"""

from __future__ import annotations

from .report import (
    PageJob,
    build_page,
    load_reading,
    overall_status,
    plan,
    render_markdown,
    review,
)
from .scoring import (
    CHANGE_WEIGHT,
    COLOURS,
    HEAD_WEIGHTS,
    KINDS,
    LOW_P,
    VERY_LOW_P,
    classify,
    summarise,
)

__all__ = [
    "CHANGE_WEIGHT",
    "COLOURS",
    "HEAD_WEIGHTS",
    "KINDS",
    "LOW_P",
    "PageJob",
    "VERY_LOW_P",
    "build_page",
    "classify",
    "load_reading",
    "overall_status",
    "plan",
    "render_markdown",
    "review",
    "summarise",
]
