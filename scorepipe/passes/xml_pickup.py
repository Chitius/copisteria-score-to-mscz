"""Anacrusis: the first bar may be shorter than the metre, if it is clearly a pickup."""

from __future__ import annotations

from ..core.document import Document
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase


class MarkPickup:
    spec = PassSpec(
        name="mark_pickup",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("pickup-marking",),
        description="mark a short opening bar as an anacrusis (implicit) instead of padding it",
        measure="unnormalised pickup bars",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        measures = doc.measures()
        if not measures:
            return PassResult()
        first = measures[0]
        if first.get("implicit") == "yes":
            return PassResult()
        meter = doc.time_signature(first) or (4.0, 4.0)
        bar = meter[0] * 4.0 / meter[1]
        events = doc.events(first)
        if not events:
            return PassResult()
        if all(event.rest for event in events):
            return PassResult()
        if min(event.onset for event in events) > 1e-6:
            return PassResult()  # starts with a rest: not a pickup
        end = max(event.end for event in events)
        if end >= bar - 1e-6:
            return PassResult()
        first.set("implicit", "yes")
        return PassResult(changed=1)


MARK_PICKUP = MarkPickup()
