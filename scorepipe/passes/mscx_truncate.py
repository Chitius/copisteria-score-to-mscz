"""Exact tick-level trimming and duration normalization for the display mscx.

The old pass reasoned in beats, ignored ``<location>`` deltas and protected
tuplets with a flat bracket counter.  It now shares the exact voice model in
:mod:`scorepipe.core.musescore_ticks`; a voice is edited only when the trimmed
result ends on the measure's tick length.  If the tail is protected (inside a
tuplet, or the excess is unreachable), the voice is left untouched and the
operation is reported as ``UNRESOLVED``.
"""

from __future__ import annotations

from fractions import Fraction
from xml.etree import ElementTree

from ..core.mscx import MsxcDocument
from ..core.mscx_invariants import iter_measures_with_meter
from ..core.musescore_ticks import duration_parts, voice_timeline
from .mscx_canonical import canonicalize, fix_dots_order, make_voice_exact
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase


class TruncateOverfullMscx:
    spec = PassSpec(
        name="truncate_overfull_mscx",
        phase=Phase.DISPLAY,
        kind=Kind.MECHANICAL,
        owns=("overfull-mscx-voice-durations",),
        description="trim overfull mscx voices from the tail for manual repair",
        measure="mscx voices longer than the active time signature",
    )

    def run(self, doc: MsxcDocument, ctx: Context) -> PassResult:
        changed = 0
        notes: list[str] = []
        for staff, index, measure, meter in iter_measures_with_meter(doc):
            staff_label = staff.get("id") or "?"
            target = Fraction(measure.get("len")) if measure.get("len") else meter
            if target > meter:
                # A stale irregular length longer than the nominal signature.
                measure.attrib.pop("len", None)
                target = meter
            for voice in doc.voices(measure):
                if not voice.findall("Chord") and not voice.findall("Rest"):
                    continue
                before = voice_timeline(voice, target)
                if before.end <= target:
                    continue
                if before.overlaps:
                    # Canonicalization owns overlap repair (usually stale hidden
                    # padding around a negative location).
                    notes.append(
                        f"DEFERRED m{index} staff {staff_label}: "
                        "overlapping Chord/Rest; canonicalization owns the repair"
                    )
                    continue
                if before.invalid_tuplets:
                    # Canonicalization owns tuplet retiming/filling.
                    notes.append(
                        f"DEFERRED m{index} staff {staff_label}: "
                        "tuplet is not full; canonicalization will retime it"
                    )
                    continue
                actions: list[tuple[str, object, Fraction, Fraction | None]] = []
                edits, reason = make_voice_exact(
                    voice, target, allow_pad=False, log=actions
                )
                if reason is not None:
                    notes.append(
                        f"UNRESOLVED m{index} staff {staff_label}: {reason}; "
                        "tuplet/positional-rest tail is protected"
                    )
                    continue
                if not edits:
                    continue
                changed += edits
                detail = "; ".join(_action_text(action) for action in actions)
                notes.append(
                    f"m{index} staff {staff_label}: {float(before.end) * 4:g}->"
                    f"{float(target) * 4:g} beats; {detail}"
                )
            for voice in measure.findall("voice"):
                if not list(voice):
                    measure.remove(voice)
        return PassResult(changed=changed, notes=notes)


def _action_text(action: tuple[str, object, Fraction, Fraction | None]) -> str:
    kind, element, old, new = action
    if kind == "remove":
        return f"remove {float(old) * 4:g}{_describe_element(element)}"
    return (
        f"shorten {float(old) * 4:g}->{float(new) * 4:g}{_describe_element(element)}"
    )


def _describe_element(element) -> str:
    risky = [
        child.tag
        for child in element.iter()
        if child.tag in ("Tie", "Slur", "Spanner")
    ]
    suffix = f" [spanner-risk:{','.join(sorted(set(risky)))}]" if risky else ""
    if element.find("duration") is not None and element.findtext("durationType") != "measure":
        suffix += " [explicit-duration]"
    if element.tag != "Chord":
        return suffix
    pitches = []
    for note in element.findall("Note"):
        pitch = note.find("pitch")
        if pitch is not None:
            pitches.append(str(pitch.text or ""))
    return (f" [{','.join(pitches)}]" if pitches else "") + suffix


def normalize_explicit_durations(doc: MsxcDocument) -> tuple[int, list[str]]:
    """Make explicit ``<duration>`` values consistent with legal note values.

    ``<duration>`` is always the *written* duration, inside a tuplet too.  When
    it equals a legal note value (with up to two dots) it is converted to
    ``durationType``/``dots``; otherwise it is kept verbatim and stale type/dot
    children are removed so MuseScore reads the exact fraction.
    """
    changed = 0
    for _staff, _index, measure in doc.iter_measures():
        for voice in measure.findall("voice"):
            for element in list(voice):
                if element.tag not in ("Chord", "Rest"):
                    continue
                explicit = element.findtext("duration")
                if explicit:
                    try:
                        written = Fraction(explicit)
                    except (ValueError, ZeroDivisionError):
                        continue
                    values = duration_parts(written)
                    for tag in ("durationType", "dots"):
                        for node in element.findall(tag):
                            element.remove(node)
                    if values is not None:
                        name, dots = values
                        element.remove(element.find("duration"))
                        _insert_duration_type(element, name, dots)
                    changed += 1
                dots = int(element.findtext("dots") or 0)
                note_dots = element.findall("NoteDot")
                if dots:
                    for dot in note_dots:
                        for visible in dot.findall("visible"):
                            dot.remove(visible)
                    if not note_dots:
                        ElementTree.SubElement(element, "NoteDot")
                else:
                    for dot in note_dots:
                        element.remove(dot)
                fix_dots_order(element)
        for voice in measure.findall("voice"):
            if voice.findall("Chord") or voice.findall("Rest"):
                continue
            if not any(
                child.tag in ("Expression", "StaffText", "SystemText", "Tempo")
                for child in voice
            ):
                continue
            rest = ElementTree.SubElement(voice, "Rest")
            ElementTree.SubElement(rest, "durationType").text = "measure"
            ElementTree.SubElement(rest, "visible").text = "0"
            changed += 1
    notes: list[str] = []
    changed += canonicalize(doc, notes)
    return changed, notes


def _insert_duration_type(element, name: str, dots: int) -> None:
    if dots:
        ElementTree.SubElement(element, "dots").text = str(dots)
    ElementTree.SubElement(element, "durationType").text = name


TRUNCATE_OVERFULL_MSCX = TruncateOverfullMscx()
