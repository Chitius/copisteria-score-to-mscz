"""Per-symbol confidence scoring and suspect classification."""

from __future__ import annotations

from typing import Sequence

HEAD_WEIGHTS = {
    "cls": 2.0,
    "pos": 1.5,
    "voice": 1.0,
    "dots": 0.8,
    "onset_p": 1.0,
    "alter": 0.5,
    "grace": 0.5,
    "tup": 0.5,
}
LOW_P = 0.80
VERY_LOW_P = 0.55
# How much a context override matters depends on the head.  A reassigned voice or a re-read dot
# is routine (the model corrects these constantly and is usually right); a changed class, or a
# symbol the model decided does not exist, is not.
CHANGE_WEIGHT = {
    "cls": 3.0,
    "pos": 2.0,
    "alter": 1.5,
    "tup": 1.5,
    "dots": 1.0,
    "voice": 1.0,
    "grace": 1.0,
    "onset_p": 1.0,
}

COLOURS = {
    "changed": (214, 39, 40),
    "existence": (255, 165, 0),
    "attribute": (255, 196, 0),
    "low": (120, 170, 220),
}
KINDS = ("changed", "existence", "attribute", "low")


def summarise(token: dict) -> dict:
    """Score one symbol from its per-head readings and keep the numbers that produced it."""
    reasons: list[dict] = []
    score = 0.0

    real = token.get("real") or {}
    p_real = real.get("p")
    if isinstance(p_real, float):
        if 0.15 <= p_real <= 0.85:
            score += 2.0
            reasons.append({"head": "real", "value": p_real, "det": real.get("det"), "ev": real.get("ev")})
        elif p_real < 0.5:
            reasons.append({"head": "real", "value": p_real, "det": real.get("det"), "ev": real.get("ev")})

    for head, weight in HEAD_WEIGHTS.items():
        entry = token.get(head)
        if head == "onset_p":
            p = token.get("onset_p")
            det = None
            value = None
            evidence = None
        elif isinstance(entry, dict):
            p = entry.get("p")
            det = entry.get("det")
            value = entry.get("v")
            evidence = entry.get("ev")
        else:
            continue
        if not isinstance(p, float):
            continue
        changed = det is not None and value is not None and det != value
        if changed:
            score += CHANGE_WEIGHT.get(head, 1.0)
        if p < LOW_P:
            score += weight * (1.0 - p / LOW_P)
        if p < VERY_LOW_P:
            score += weight * 0.5
        if changed or p < LOW_P:
            reasons.append(
                {"head": head, "value": value, "p": p, "det": det, "ev": evidence, "changed": changed}
            )

    for head in ("chord", "tie"):
        p = token.get(head)
        if isinstance(p, float) and 0.2 < p < 0.8:
            score += 1.0
            reasons.append({"head": head, "value": p})

    return {"score": round(score, 3), "reasons": reasons}


def classify(score: float, reasons: Sequence[dict]) -> str:
    """Name *why* a symbol is suspect; the order of the tests is the precedence.

    ``changed`` is a real override (the reader's own choice differed from the final one).  A low
    probability on an unchanged attribute is *not* an override -- the old skill keyed on "a ``det``
    value exists", which made every low-probability attribute red and left the amber class empty.
    """
    if any(reason.get("changed") for reason in reasons):
        return "changed"
    if any(reason["head"] == "real" for reason in reasons):
        return "existence"
    if score >= 2.0:
        return "attribute"
    return "low"
