"""Absolute musical positions for cross-measure comparisons.

Onsets in MusicXML are measure-local.  Comparing two ``onset`` values without the measure number
silently treats notes in different measures as if they shared one timeline (laputa m59: a note in
m60 was considered to lie between two D4 notes of m59).  Use ``between`` whenever a check spans
more than one measure; same-measure grouping can continue to use the raw onset.
"""

from __future__ import annotations

Position = tuple[int, float]


def between(
    number: int,
    onset: float,
    start_measure: int,
    start_onset: float,
    stop_measure: int,
    stop_onset: float,
) -> bool:
    """True when ``(number, onset)`` is strictly inside the span of two positions."""
    epsilon = 1e-6
    if number < start_measure or number > stop_measure:
        return False
    if start_measure == stop_measure:
        return number == start_measure and start_onset + epsilon < onset < stop_onset - epsilon
    if number == start_measure:
        return onset > start_onset + epsilon
    if number == stop_measure:
        return onset < stop_onset - epsilon
    return True
