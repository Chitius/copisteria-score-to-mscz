"""Make mscx voices tick-exact against MuseScore's reader semantics.

The old implementation treated ``<location>`` as an absolute offset and filled
short voices with hidden tuplets.  Both assumptions were wrong: locations are
relative deltas and an arbitrary tick remainder cannot be written as a legal
tuplet.  This module now works from :mod:`scorepipe.core.musescore_ticks` and
only commits an edit when the resulting voice is *provably* exact:

* no overlapping Chord/Rest in the voice,
* every tuplet contains exactly ``baseNote * actualNotes`` of written duration,
* the last Chord/Rest ends on the measure's inherited tick length.

If those conditions cannot be reached, the voice is left byte-for-byte
unchanged and an ``UNRESOLVED`` note is handed back to the caller.
"""

from __future__ import annotations

import copy
from fractions import Fraction
from xml.etree import ElementTree

from ..core.mscx import MsxcDocument
from ..core.musescore_ticks import (
    BASE_WHOLE,
    TICKS_PER_WHOLE,
    TupletSpan,
    duration_parts,
    element_written,
    is_grace,
    legal_ticks_parts,
    measure_expected_fraction,
    voice_timeline,
)

# Legal written values, largest first, used when a padding gap must be split.
_LEGAL_REST_PARTS = (
    ("whole", 0, 1920),
    ("half", 1, 1440),
    ("half", 0, 960),
    ("quarter", 1, 720),
    ("quarter", 0, 480),
    ("eighth", 1, 360),
    ("eighth", 0, 240),
    ("16th", 1, 180),
    ("16th", 0, 120),
    ("32nd", 1, 90),
    ("32nd", 0, 60),
    ("64th", 1, 45),
    ("64th", 0, 30),
    ("128th", 0, 15),
)


def canonicalize(doc: MsxcDocument, notes: list[str] | None = None) -> int:
    """Canonicalize every note-bearing mscx voice; return the edit count."""
    changed = 0
    meters: dict[int, Fraction] = {}
    for staff, index, measure in doc.iter_measures():
        meter = meters.get(id(staff), Fraction(4, 4))
        for time in measure.iter("TimeSig"):
            try:
                meter = Fraction(int(time.findtext("sigN") or 4), int(time.findtext("sigD") or 4))
            except (ValueError, ZeroDivisionError):
                pass
        meters[id(staff)] = meter
        expected = measure_expected_fraction(measure, meter)
        voices = measure.findall("voice")
        for slot, voice in enumerate(list(voices), start=1):
            if not voice.findall("Chord"):
                continue
            edited, reason = canonicalize_voice(voice, expected)
            changed += edited
            if reason is not None and notes is not None:
                notes.append(
                    f"UNRESOLVED m{index} staff {staff.get('id') or '?'} voice {slot}: {reason}"
                )
        # Drop voices that only contained our hidden padding.
        for voice in list(measure.findall("voice")):
            if list(voice):
                continue
            measure.remove(voice)
            changed += 1
    return changed


def canonicalize_voice(voice: ElementTree.Element, expected: Fraction) -> tuple[int, str | None]:
    """Return ``(edits, unresolved_reason)``; commit only a fully exact voice."""
    working = copy.deepcopy(voice)
    before = ElementTree.tostring(working)
    edits = fix_dots_order(working)
    edits += strip_padding(working)
    normalized, reason = normalize_tuplets(working, expected)
    edits += normalized
    if reason is not None:
        return 0, reason
    trimmed, reason = make_voice_exact(working, expected, allow_pad=True)
    edits += trimmed
    if reason is not None:
        return 0, reason

    timeline = voice_timeline(working, expected)
    if timeline.end != expected:
        return 0, f"voice ends at {float(timeline.end):g} whole notes, expected {float(expected):g}"
    if timeline.overlaps:
        return 0, "overlapping Chord/Rest remains"
    if any(not span.valid for span in timeline.spans):
        return 0, "a tuplet is still not full"

    if ElementTree.tostring(working) != before:
        voice[:] = list(working)
    return edits, None


def fix_dots_order(voice: ElementTree.Element) -> int:
    """Move ``<dots>`` before ``<durationType>`` where the reader needs it.

    MuseScore's reader fixes ticks when it sees ``<durationType>``; a later
    ``<dots>`` only changes the dot count.  The canonical writer order is
    ``dots`` then ``durationType``.
    """
    changed = 0
    for element in voice.iter():
        if element.tag not in ("Chord", "Rest"):
            continue
        types = [index for index, child in enumerate(element) if child.tag == "durationType"]
        dots = [index for index, child in enumerate(element) if child.tag == "dots"]
        if not types or not dots or dots[0] < types[0]:
            continue
        dot = element[dots[0]]
        element.remove(dot)
        type_node = element.find("durationType")
        if type_node is not None:
            element.insert(list(element).index(type_node), dot)
            changed += 1
    return changed


def strip_padding(voice: ElementTree.Element) -> int:
    """Remove hidden padding rests and padding-only tuplets from ``voice``."""
    children = list(voice)
    if not children:
        return 0

    padding_rest = {
        id(child): _is_padding_rest(child) for child in children if child.tag == "Rest"
    }
    remove = [False] * len(children)
    stack: list[dict] = []
    ranges: list[dict] = []
    for index, child in enumerate(children):
        if child.tag == "Tuplet":
            stack.append({"start": index, "has_real": False, "has_any": False})
        elif child.tag == "endTuplet":
            if stack:
                context = stack.pop()
                context["end"] = index
                ranges.append(context)
        elif child.tag in ("Chord", "Rest"):
            for context in stack:
                context["has_any"] = True
                if not padding_rest.get(id(child), False):
                    context["has_real"] = True

    removed = 0
    for context in ranges:
        if context.get("has_real"):
            continue
        # Padding-only (or empty) tuplet: remove its whole range.
        for index in range(context["start"], context["end"] + 1):
            if not remove[index]:
                remove[index] = True
                removed += 1
    for index, child in enumerate(children):
        if child.tag == "Rest" and padding_rest.get(id(child), False) and not remove[index]:
            # A padding rest inside a real tuplet is kept: normalize_tuplets
            # needs its written duration, and it may be part of a valid fill.
            if _inside_real_tuplet(children, index):
                continue
            remove[index] = True
            removed += 1

    if removed:
        voice[:] = [child for index, child in enumerate(children) if not remove[index]]
    return removed


def _inside_real_tuplet(children: list[ElementTree.Element], index: int) -> bool:
    """True if ``children[index]`` sits inside a tuplet that has real content."""
    stack: list[bool] = []
    for position, child in enumerate(children):
        if position == index:
            return any(stack)
        if child.tag == "Tuplet":
            stack.append(False)
        elif child.tag == "endTuplet":
            if stack:
                stack.pop()
        elif child.tag in ("Chord", "Rest") and not _is_padding_rest(child):
            for depth in range(len(stack)):
                stack[depth] = True
    return False


def _is_padding_rest(element: ElementTree.Element) -> bool:
    return element.tag == "Rest" and element.find("padding") is not None


def normalize_tuplets(voice: ElementTree.Element, measure: Fraction) -> tuple[int, str | None]:
    """Fill or trim every tuplet so ``sum(written) == baseNote * actualNotes``.

    A tuplet's *sounding* span is preserved.  Overfull tuplets lose tail notes
    (forced repair); underfull tuplets gain hidden filler rests.  If an overfull
    tuplet cannot be trimmed without cutting through a nested tuplet the voice
    is left unchanged and the caller reports it as unresolved.
    """
    edits = 0
    for _ in range(256):
        timeline = voice_timeline(voice, measure)
        invalid = [span for span in timeline.spans if not span.valid]
        if not invalid:
            return edits, None
        invalid.sort(key=lambda span: (span.depth, span.start), reverse=True)
        span = invalid[0]
        delta = span.delta
        if _retime_tuplet(voice, span):
            edits += 1
            continue
        if delta > 0:
            changed, remaining = _trim_tuplet(voice, span, delta)
            edits += changed
            if remaining > 0:
                return 0, f"tuplet at {float(span.start):g} still {float(remaining):g} too long"
        elif delta < 0:
            added = _fill_tuplet(voice, span, -delta)
            if added == 0:
                return 0, f"tuplet at {float(span.start):g} cannot be filled exactly"
            edits += added
        else:  # pragma: no cover - defensive
            return 0, "tuplet changed while normalizing"
    return 0, "tuplet normalization did not converge"


def _voice_children(voice: ElementTree.Element) -> list[ElementTree.Element]:
    return list(voice)


def _tuplet_bounds(voice: ElementTree.Element, node: ElementTree.Element) -> tuple[int, int] | None:
    children = list(voice)
    start = None
    depth = 0
    for index, child in enumerate(children):
        if child is node:
            start = index
            depth = 1
            continue
        if start is None:
            continue
        if child.tag == "Tuplet":
            depth += 1
        elif child.tag == "endTuplet":
            depth -= 1
            if depth == 0:
                return start, index
    return None


def _retime_tuplet(voice: ElementTree.Element, span: TupletSpan) -> bool:
    """Rewrite a tuplet's ratio/base so its existing content is exactly full.

    ``W`` is the written content and ``S`` the tuplet's intended sounding span.
    Choosing ``actual / normal == W / S`` and a legal ``base == W / actual``
    preserves both the notes and ``S`` while making
    ``sum(written) == base * actual`` true.  A 1:1 result is simply the removal
    of the (then meaningless) tuplet markers.
    """
    written = span.written
    span_length = span.nominal
    if written <= 0 or span_length <= 0:
        return False
    ratio = written / span_length
    p, q = ratio.numerator, ratio.denominator
    for multiplier in range(1, 65):
        base = written / (p * multiplier)
        name = _base_name(base)
        if name is None:
            continue
        actual = p * multiplier
        normal = q * multiplier
        if actual == normal:
            _remove_tuplet_markers(voice, span.node)
            return True
        _write_tuplet(span.node, normal, actual, name)
        return True
    return False


def _base_name(value: Fraction) -> str | None:
    for name, base in BASE_WHOLE.items():
        if base == value:
            return name
    return None


def _write_tuplet(node: ElementTree.Element, normal: int, actual: int, base: str) -> None:
    for tag in ("normalNotes", "actualNotes", "baseNote"):
        for child in node.findall(tag):
            node.remove(child)
    ElementTree.SubElement(node, "normalNotes").text = str(normal)
    ElementTree.SubElement(node, "actualNotes").text = str(actual)
    ElementTree.SubElement(node, "baseNote").text = base
    number = node.find("Number/text")
    if number is not None:
        number.text = str(actual)


def _remove_tuplet_markers(voice: ElementTree.Element, node: ElementTree.Element) -> None:
    bounds = _tuplet_bounds(voice, node)
    if bounds is None:
        return
    start, end = bounds
    children = list(voice)
    voice.remove(children[end])
    voice.remove(children[start])


def _trim_tuplet(voice: ElementTree.Element, span: TupletSpan, excess: Fraction) -> tuple[int, Fraction]:
    """Remove/shorten direct tail elements of a tuplet; return (edits, remaining)."""
    bounds = _tuplet_bounds(voice, span.node)
    if bounds is None:
        return 0, excess
    start, end = bounds
    children = list(voice)

    # Walk direct children (and whole child tuplets) from the end.
    index = end - 1
    edited = 0
    while index > start and excess > 0:
        child = children[index]
        if child.tag == "endTuplet":
            index -= 1
            continue
        if child.tag == "Tuplet":
            # A nested tuplet can only be removed whole.
            child_span = _span_for_node(span, child)
            if child_span is None:
                break
            if child_span.written <= excess:
                child_bounds = _tuplet_bounds(voice, child)
                if child_bounds is None:
                    break
                for position in range(child_bounds[0], child_bounds[1] + 1):
                    voice.remove(children[position])
                excess -= child_span.written
                edited += 1
                children = list(voice)
                index = min(index, len(children) - 1)
                continue
            break
        if child.tag in ("Chord", "Rest") and _is_direct_child(span, child):
            written = element_written(child) or Fraction(0)
            if written <= excess:
                voice.remove(child)
                excess -= written
                edited += 1
                children = list(voice)
                index = min(index, len(children) - 1)
                continue
            new_written = written - excess
            _set_written_duration(child, new_written)
            excess = Fraction(0)
            edited += 1
            break
        index -= 1
    return edited, excess


def _span_for_node(parent: TupletSpan, node: ElementTree.Element) -> TupletSpan | None:
    for child in parent.children:
        if child.node is node:
            return child
    return None


def _is_direct_child(span: TupletSpan, element: ElementTree.Element) -> bool:
    return any(child is element for child in span.direct)


def _fill_tuplet(voice: ElementTree.Element, span: TupletSpan, gap: Fraction) -> int:
    """Insert hidden rests with written duration ``gap`` before ``endTuplet``."""
    bounds = _tuplet_bounds(voice, span.node)
    if bounds is None:
        return 0
    end = bounds[1]
    rests = _padding_rests(gap)
    if not rests:
        return 0
    for offset, rest in enumerate(rests):
        voice.insert(end + offset, rest)
    return len(rests)


def _padding_rests(gap: Fraction) -> list[ElementTree.Element]:
    """Hidden rests whose *written* duration sums exactly to ``gap``.

    Legal dotted values are used first; an irreducible remainder becomes one
    explicit ``<duration>`` rest.  That rest is still tick-exact because the
    mscx reader treats ``<duration>`` as authoritative.
    """
    if gap <= 0:
        return []
    gap_ticks = gap * TICKS_PER_WHOLE
    rests: list[ElementTree.Element] = []
    remaining_ticks = int(gap_ticks) if gap_ticks.denominator == 1 else 0
    if gap_ticks.denominator == 1:
        for name, dots, ticks in legal_ticks_parts(remaining_ticks):
            rests.append(_rest(name, dots, ticks))
            remaining_ticks -= ticks
        if remaining_ticks:
            rests.append(_explicit_rest(Fraction(remaining_ticks, TICKS_PER_WHOLE)))
    else:
        rests.append(_explicit_rest(gap))
    return rests


def _rest(name: str, dots: int, ticks: int) -> ElementTree.Element:
    rest = ElementTree.Element("Rest")
    ElementTree.SubElement(rest, "padding").text = "1"
    if dots:
        ElementTree.SubElement(rest, "dots").text = str(dots)
    ElementTree.SubElement(rest, "durationType").text = name
    ElementTree.SubElement(rest, "visible").text = "0"
    return rest


def _explicit_rest(written: Fraction) -> ElementTree.Element:
    rest = ElementTree.Element("Rest")
    ElementTree.SubElement(rest, "padding").text = "1"
    name, dots = _approximate_type(written)
    if dots:
        ElementTree.SubElement(rest, "dots").text = str(dots)
    ElementTree.SubElement(rest, "durationType").text = name
    ElementTree.SubElement(rest, "duration").text = f"{written.numerator}/{written.denominator}"
    ElementTree.SubElement(rest, "visible").text = "0"
    return rest


def _approximate_type(written: Fraction) -> tuple[str, int]:
    best = ("128th", 0)
    for name, dots, value in _LEGAL_REST_PARTS:
        if Fraction(value, TICKS_PER_WHOLE) <= written:
            best = (name, dots)
            break
    return best


def make_voice_exact(
    voice: ElementTree.Element,
    expected: Fraction,
    *,
    allow_pad: bool,
    log: list[tuple[str, ElementTree.Element, Fraction, Fraction | None]] | None = None,
) -> tuple[int, str | None]:
    """Trim or pad one voice to ``expected``; rollback on any doubt."""
    timeline = voice_timeline(voice, expected)
    if timeline.overlaps:
        return 0, "overlapping Chord/Rest"
    if any(not span.valid for span in timeline.spans):
        return 0, "invalid tuplet"
    if timeline.end == expected:
        return 0, None

    working = copy.deepcopy(voice)
    if timeline.end > expected:
        changed, remaining = _trim_tail(working, timeline.end - expected, log)
        if remaining > 0:
            return 0, f"cannot remove {float(remaining):g} whole notes from the tail"
    else:
        if not allow_pad:
            return 0, None
        changed = _pad_voice(working, expected - timeline.end, timeline)

    checked = voice_timeline(working, expected)
    if checked.end != expected:
        return 0, (
            f"edit would end at {float(checked.end):g}, expected {float(expected):g}"
        )
    if checked.overlaps:
        return 0, "edit would create an overlap"
    if any(not span.valid for span in checked.spans):
        return 0, "edit would leave an invalid tuplet"
    voice[:] = list(working)
    return changed, None


def _depths(voice: ElementTree.Element) -> list[int]:
    depths = []
    depth = 0
    for child in voice:
        if child.tag == "endTuplet":
            depth = max(0, depth - 1)
        depths.append(depth)
        if child.tag == "Tuplet":
            depth += 1
    return depths


def _trim_tail(
    voice: ElementTree.Element,
    excess: Fraction,
    log: list[tuple[str, ElementTree.Element, Fraction, Fraction | None]] | None = None,
) -> tuple[int, Fraction]:
    """Trim depth-0 Chord/Rest tails; never cut through a tuplet."""
    children = list(voice)
    depths = _depths(voice)
    item_indices = [
        index for index, child in enumerate(children) if child.tag in ("Chord", "Rest")
    ]
    if not item_indices:
        return 0, excess
    last = item_indices[-1]
    if depths[last] > 0:
        return 0, excess

    edited = 0
    # Trailing depth-0 rests after the last depth-0 *sounding* chord.  A grace chord
    # consumes no time, so it can neither absorb the excess nor block the walk.
    chord_indices = [
        index
        for index in item_indices
        if children[index].tag == "Chord"
        and depths[index] == 0
        and not is_grace(children[index])
    ]
    last_chord = chord_indices[-1] if chord_indices else -1
    index = last
    while index > last_chord and excess > 0:
        child = children[index]
        if child.tag == "Rest" and depths[index] == 0:
            written = element_written(child) or Fraction(0)
            if written <= excess:
                voice.remove(child)
                if log is not None:
                    log.append(("remove", child, written, None))
                excess -= written
                edited += 1
                children = list(voice)
                depths = _depths(voice)
                index = min(index, len(children) - 1)
                continue
            new_written = written - excess
            _set_written_duration(child, new_written)
            if log is not None:
                log.append(("shorten", child, written, new_written))
            excess = Fraction(0)
            edited += 1
            break
        index -= 1

    # Then the last chord, then earlier chords until a rest blocks the walk.
    index = last_chord
    while index >= 0 and excess > 0:
        child = children[index]
        if depths[index] != 0:
            index -= 1
            continue
        if child.tag == "Rest":
            break
        if child.tag != "Chord":
            index -= 1
            continue
        if is_grace(child):
            # Removing a grace note would not shorten the bar.
            index -= 1
            continue
        written = element_written(child) or Fraction(0)
        if written <= excess:
            voice.remove(child)
            if log is not None:
                log.append(("remove", child, written, None))
            excess -= written
            edited += 1
            children = list(voice)
            depths = _depths(voice)
            index = min(index, len(children) - 1)
            continue
        new_written = written - excess
        _set_written_duration(child, new_written)
        if log is not None:
            log.append(("shorten", child, written, new_written))
        excess = Fraction(0)
        edited += 1
        break
    return edited, excess


def _pad_voice(voice: ElementTree.Element, gap: Fraction, timeline) -> int:
    changed = 0
    if timeline.final != timeline.end:
        # A trailing location may have left the reader before/after the last
        # sounding event.  Move it back to the sounding end before padding.
        location = ElementTree.Element("location")
        delta = timeline.end - timeline.final
        ElementTree.SubElement(location, "fractions").text = f"{delta.numerator}/{delta.denominator}"
        voice.append(location)
        changed += 1
    rests = _padding_rests(gap)
    for rest in rests:
        voice.append(rest)
    return changed + len(rests)


def _set_written_duration(element: ElementTree.Element, written: Fraction) -> None:
    """Rewrite a Chord/Rest to exactly ``written`` whole notes.

    ``<dots>`` must precede ``<durationType>``: MuseScore's reader sets ticks
    when it sees ``<durationType>`` and only then records later ``<dots>``.
    """
    for tag in ("duration", "durationType", "dots"):
        for node in element.findall(tag):
            element.remove(node)
    for node in element.findall("NoteDot"):
        element.remove(node)
    values = duration_parts(written)
    if values is not None:
        name, dots = values
        if dots:
            ElementTree.SubElement(element, "dots").text = str(dots)
        ElementTree.SubElement(element, "durationType").text = name
        return
    name, dots = _approximate_type(written)
    if dots:
        ElementTree.SubElement(element, "dots").text = str(dots)
    ElementTree.SubElement(element, "durationType").text = name
    ElementTree.SubElement(element, "duration").text = f"{written.numerator}/{written.denominator}"
