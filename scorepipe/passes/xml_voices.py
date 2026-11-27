"""Canonical voice numbering inside each staff of a measure."""

from __future__ import annotations

from xml.etree import ElementTree

from ..core.document import Document
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase


class NormalizeVoiceNumbers:
    spec = PassSpec(
        name="normalize_voice_numbers",
        phase=Phase.STRUCTURAL,
        kind=Kind.MECHANICAL,
        owns=("voice-numbers",),
        description="number voices per staff by note count with a 4-voice slot per staff",
        measure="voice labels that are not canonical by density",
    )

    def run(self, doc: Document, ctx: Context) -> PassResult:
        changed_notes = 0
        for _part_id, _part, _number, measure in doc.iter_part_measures():
            by_staff: dict[str, dict[str, int]] = {}
            for event in doc.events(measure):
                counts = by_staff.setdefault(event.staff, {})
                counts[event.voice] = counts.get(event.voice, 0) + (0 if event.rest else 1)
            mapping: dict[tuple[str, str], str] = {}
            for staff, counts in by_staff.items():
                ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
                first = 1 + 4 * (int(staff) - 1) if staff.isdigit() else 1
                for position, (voice, _count) in enumerate(ordered, start=first):
                    mapping[(staff, voice)] = str(position)
            if all(old == new for (staff, old), new in mapping.items()):
                continue
            for note in measure.iter("note"):
                staff = note.findtext("staff") or "1"
                voice = note.findtext("voice") or "1"
                new = mapping.get((staff, voice))
                if new is None or new == voice:
                    continue
                element = note.find("voice")
                if element is None:
                    element = ElementTree.SubElement(note, "voice")
                element.text = new
                changed_notes += 1
        return PassResult(changed=changed_notes)


NORMALIZE_VOICES_PASS = NormalizeVoiceNumbers()
