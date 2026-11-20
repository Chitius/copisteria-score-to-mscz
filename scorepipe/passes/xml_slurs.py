"""Slur endpoint sanitation: unmatched endpoints and accidental long spans."""

from __future__ import annotations

from ..core.document import Document
from ..core.pairing import Endpoint, pair_endpoints
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase


class SanitizeSlurs:
    spec = PassSpec(
        name="sanitize_slurs",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("slur-endpoints",),
        description="drop unmatched slur endpoints and pairs that span more than N bars",
        measure="unmatched or overlong slur endpoints",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        max_bars = int(ctx.options.get("max_slur_bars", 6))
        endpoints: list[Endpoint] = []
        for number, measure in doc.iter_measures():
            for event in doc.events(measure):
                for slur in event.element.findall("notations/slur"):
                    kind = slur.get("type")
                    if kind not in ("start", "stop"):
                        continue
                    endpoints.append(
                        Endpoint(
                            key=(event.staff, slur.get("number") or "1"),
                            position=(number, round(event.onset, 4)),
                            kind=kind,
                            payload=(event.element, slur),
                        )
                    )
        pairing = pair_endpoints(endpoints, max_span=max_bars)
        orphans = 0
        for endpoint in pairing.orphans:
            note, slur = endpoint.payload
            _remove(note, slur)
            orphans += 1
        return PassResult(changed=orphans)


def _remove(note, slur) -> None:
    notations = note.find("notations")
    if notations is None:
        return
    if slur in list(notations):
        notations.remove(slur)
    if len(notations) == 0:
        note.remove(notations)


SLUR_PASS = SanitizeSlurs()
