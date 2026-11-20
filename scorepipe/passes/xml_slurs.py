"""Slur endpoint sanitation: unmatched endpoints and accidental long spans."""

from __future__ import annotations

from ..core.document import Document
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
        stacks: dict[tuple[str, str], list[tuple[int, float, object, object]]] = {}
        pairs: list[tuple] = []
        orphans = 0
        for number, measure in doc.iter_measures():
            for event in doc.events(measure):
                for slur in event.element.findall("notations/slur"):
                    key = (event.staff, slur.get("number") or "1")
                    kind = slur.get("type")
                    if kind == "start":
                        stacks.setdefault(key, []).append((number, event.onset, event.element, slur))
                    elif kind == "stop":
                        stack = stacks.get(key) or []
                        if not stack:
                            _remove(event.element, slur)
                            orphans += 1
                            continue
                        start_number, _start_onset, start_note, start_slur = stack.pop()
                        if number - start_number > max_bars:
                            _remove(start_note, start_slur)
                            _remove(event.element, slur)
                            orphans += 2
                            continue
                        pairs.append((key, start_number, number))
        for stack in stacks.values():
            for _number, _onset, note, slur in stack:
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
