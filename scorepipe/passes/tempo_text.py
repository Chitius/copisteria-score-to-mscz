"""Printed metronome notation: recognise it, and expand the ASCII beat-unit shorthand.

Facts document the shorthand (``q = 72``) because a JSON claim should not have to carry a music
glyph, but MuseScore prints a ``<words>`` text verbatim: a delivery therefore showed a literal
"q = 135" where the source had a quarter note (Gurenge page 1).  Expanding the shorthand before the
text is written gives MuseScore the character it prints with its own music font.
"""

from __future__ import annotations

import re

#: ASCII beat-unit shorthand -> the glyph MuseScore prints.  Measured on MuseScore 4.6.5: plain
#: ``<words>`` elements carrying ♩ / ♪ / 𝅗𝅥 / ♩. all render as real note symbols.
BEAT_UNIT_GLYPHS = {"q": "♩", "e": "♪", "h": "𝅗𝅥", "w": "𝅝"}

_SHORTHAND = re.compile(r"(?<![A-Za-z])([qehw])(\.?)(?=\s*=)")


def looks_like_tempo_text(text: str) -> bool:
    """True for ``q = 72``-style notation (and for text that already carries the glyph)."""
    lowered = (text or "").lower()
    return "=" in text or "♩" in text or "♪" in text or lowered.startswith(("q ", "q."))


def normalize_tempo_text(text: str) -> str:
    """Replace a beat-unit shorthand with its glyph: ``q = 72`` -> ``♩ = 72``."""
    if not text:
        return text
    return _SHORTHAND.sub(
        lambda match: BEAT_UNIT_GLYPHS[match.group(1)] + match.group(2), text
    )
