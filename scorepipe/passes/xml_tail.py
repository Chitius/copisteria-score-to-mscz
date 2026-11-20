"""A trailing measure that only repeats the previous bar's pitches, shorter, is OMR noise."""

from __future__ import annotations

from ..core.document import Document
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase


class DropTrailingDuplicateMeasure:
    spec = PassSpec(
        name="drop_trailing_duplicate_measure",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("measure-list",),
        description="drop a final bar whose pitches repeat the previous bar but which is shorter",
        measure="trailing duplicate final measures",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        if not ctx.options.get("drop_trailing_duplicate", True):
            return PassResult()
        measures = doc.measures()
        if len(measures) < 2:
            return PassResult()
        last = _profile(doc, measures[-1])
        previous = _profile(doc, measures[-2])
        if not last or not previous:
            return PassResult()
        if set(last["pitches"]) != set(previous["pitches"]):
            return PassResult()
        if last["total"] >= previous["total"] - 1e-6:
            return PassResult()
        doc.part.remove(measures[-1])
        return PassResult(changed=1)


def _profile(doc: Document, measure) -> dict:
    pitches: list[str] = []
    total = 0.0
    for event in doc.events(measure):
        total = max(total, event.end)
        pitch = event.element.find("pitch")
        if pitch is not None:
            pitches.append(
                (pitch.findtext("step") or "") + (pitch.findtext("octave") or "")
            )
    return {"pitches": tuple(pitches), "total": total}


DROP_DUPLICATE_TAIL = DropTrailingDuplicateMeasure()
