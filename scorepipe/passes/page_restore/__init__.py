"""Page-level notation restoration: ties, slurs and pedals that OMR only wrote per page.

The page MusicXML files keep their own local measure numbering; `Context.pages` is the
`MergedPages` model from the loader, which maps every local measure to the merged score.
"""

from __future__ import annotations

from .marks import (
    RestorePageArpeggios,
    RestorePageArticulations,
    RestorePagePedals,
    RestorePageWedges,
)
from .slurs import (
    MAX_SLUR_BARS,
    RestorePageSlurs,
    _musical_order as _musical_order,
    _slur_signature as _slur_signature,
)
from .ties import RestorePageTies

RESTORE_PAGE_TIES = RestorePageTies()
RESTORE_PAGE_SLURS = RestorePageSlurs()
RESTORE_PAGE_PEDALS = RestorePagePedals()
RESTORE_PAGE_ARPEGGIOS = RestorePageArpeggios()
RESTORE_PAGE_ARTICULATIONS = RestorePageArticulations()
RESTORE_PAGE_WEDGES = RestorePageWedges()

__all__ = [
    "MAX_SLUR_BARS",
    "RESTORE_PAGE_ARPEGGIOS",
    "RESTORE_PAGE_ARTICULATIONS",
    "RESTORE_PAGE_PEDALS",
    "RESTORE_PAGE_SLURS",
    "RESTORE_PAGE_TIES",
    "RESTORE_PAGE_WEDGES",
    "RestorePageArpeggios",
    "RestorePageArticulations",
    "RestorePagePedals",
    "RestorePageSlurs",
    "RestorePageTies",
    "RestorePageWedges",
]
