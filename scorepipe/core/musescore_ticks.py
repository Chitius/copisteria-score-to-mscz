"""MuseScore's mscx tick model, mirrored from the open-source reader.

Sources (MuseScore Studio, GPL-3.0):

* ``src/engraving/types/constants.h`` - ``Constants::DIVISION == 480``.
* ``src/engraving/types/fraction.h`` - ``Fraction::ticks()`` rounds
  ``numerator * DIVISION * 4 / denominator`` half away from zero; the
  ``Fraction(-1, 1)`` sentinel means "invalid / measure" and yields ``-1``.
* ``src/engraving/rw/read500/measureread.cpp`` - a voice starts at
  ``measure->tick()``.  A ``<location>`` is relative: ``ReadContext::setLocation``
  adds its fraction to the *current* reading position (``rtick``), then moves the
  reader to ``current measure tick + that fraction``.  Several locations in one
  voice therefore accumulate, and a negative fraction moves backwards.
* ``src/engraving/rw/read500/tread.cpp`` - a ``Chord``/``Rest`` is placed at
  ``ctx.tick()`` and advances it by ``actualTicks()``.  ``<duration>`` is the
  written duration as a fraction of a whole note; it overrides
  ``durationType``/``dots``.  The reader is order sensitive: ``<durationType>``
  fixes ticks using the dots seen *so far*, so a later ``<dots>`` only changes
  layout.  The writer therefore emits ``<dots>`` before ``<durationType>``.
  ``<durationType>measure</durationType>`` means the measure's nominal time
  signature.
* ``src/engraving/dom/durationelement.cpp`` - ``globalTicks()`` divides the
  written duration by *every* enclosing tuplet ratio
  (``ratio == actualNotes / normalNotes``); ``endTick()`` is
  ``tick() + actualTicks()``.
* Grace chords (``<grace16/>`` and friends) are placed at the current tick and
  never advance it; their ``durationType`` is glyph information only.
* ``src/engraving/dom/tuplet.h`` - for a tuplet, ``baseLen * actualNotes`` is the
  total *written* duration of its elements and ``baseLen * normalNotes`` is the
  total *sounding* duration.  A well-formed tuplet has
  ``sum(written) == baseLen * actualNotes``.
* ``src/engraving/rw/write/twrite.cpp`` - the writer emits ``<location>`` only
  when the current position differs from an element's tick, which confirms that
  ``<fractions>`` is a relative delta.

The model is deliberately read-only: it reports exact :class:`fractions.Fraction`
positions so callers can decide whether an edit is provably tick-exact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from xml.etree import ElementTree

TICKS_PER_QUARTER = 480
TICKS_PER_WHOLE = TICKS_PER_QUARTER * 4

# MuseScore's DurationType values, in whole notes.
BASE_WHOLE = {
    "breve": Fraction(2),
    "whole": Fraction(1),
    "half": Fraction(1, 2),
    "quarter": Fraction(1, 4),
    "eighth": Fraction(1, 8),
    "16th": Fraction(1, 16),
    "32nd": Fraction(1, 32),
    "64th": Fraction(1, 64),
    "128th": Fraction(1, 128),
    "256th": Fraction(1, 256),
}

# MuseScore marks a grace chord with one of these children instead of a duration.
# ``grace4``/``grace8``/``grace16``/... carry the *appoggiatura* note value; a plain
# ``<grace>`` is the legacy accent.  None of them advances the voice tick.
GRACE_TAGS = (
    "grace",
    "grace4",
    "grace8",
    "grace16",
    "grace32",
    "grace64",
    "grace128",
    "grace256",
)

# Legal note values with zero, one or two dots, smallest first.
LEGAL_VALUES: tuple[tuple[str, int, Fraction], ...] = tuple(
    sorted(
        (
            (name, dots, value * sum((Fraction(1, 2) ** d for d in range(dots + 1)), Fraction(0)))
            for name, value in BASE_WHOLE.items()
            if name != "256th"
            for dots in (0, 1, 2)
        ),
        key=lambda item: item[2],
    )
)


def fraction_ticks(value: Fraction) -> int:
    """Mirror ``Fraction::ticks()`` exactly (round half away from zero).

    C++ computes ``sign * (abs(n) * 1920 + d // 2) // d``; Python's ``round``
    uses banker's rounding, so it must not be used here.
    """
    value = Fraction(value)
    numerator, denominator = value.numerator, value.denominator
    if numerator == -1 and denominator == 1:  # MuseScore's -1 / invalid sentinel
        return -1
    sign = -1 if numerator < 0 else 1
    return sign * ((abs(numerator) * TICKS_PER_WHOLE + denominator // 2) // denominator)


def ticks_fraction(ticks: int) -> Fraction:
    """Whole-note fraction for an integer tick count (``Fraction::fromTicks``)."""
    return Fraction(int(ticks), TICKS_PER_WHOLE)


def _dot_multiplier(dots: int) -> Fraction:
    return sum((Fraction(1, 2) ** index for index in range(dots + 1)), Fraction(0))


def note_value(name: str, dots: int = 0) -> Fraction | None:
    """Whole-note fraction of a duration type plus dots, or ``None``."""
    if name == "measure":
        return None
    base = BASE_WHOLE.get(name)
    if base is None:
        return None
    return base * _dot_multiplier(int(dots))


def duration_parts(written: Fraction) -> tuple[str, int] | None:
    """Return ``(durationType, dots)`` for an exact legal written duration."""
    for name, dots, value in LEGAL_VALUES:
        if value == written:
            return name, dots
    return None


def legal_ticks_parts(ticks: int) -> list[tuple[str, int, int]]:
    """Decompose integer ticks into legal dotted note values, largest first.

    Returns ``(name, dots, ticks)`` entries.  Any remainder below a 128th is the
    caller's responsibility (MuseScore cannot express it as a plain value).
    """
    remaining = int(ticks)
    parts: list[tuple[str, int, int]] = []
    for name, dots, value in reversed(LEGAL_VALUES):
        part_ticks = fraction_ticks(value)
        if part_ticks <= 0:
            continue
        while remaining >= part_ticks:
            parts.append((name, dots, part_ticks))
            remaining -= part_ticks
    return parts


def tuplet_numbers(tuplet: ElementTree.Element) -> tuple[int, int]:
    """``(normalNotes, actualNotes)`` with harmless defaults for corrupt input."""
    try:
        normal = int(tuplet.findtext("normalNotes") or 1)
        actual = int(tuplet.findtext("actualNotes") or 1)
    except (TypeError, ValueError):
        return 1, 1
    if normal <= 0 or actual <= 0:
        return 1, 1
    return normal, actual


def tuplet_ratio(tuplet: ElementTree.Element) -> Fraction:
    """Sounding multiplier for one tuplet: ``normalNotes / actualNotes``."""
    normal, actual = tuplet_numbers(tuplet)
    return Fraction(normal, actual)


def tuplet_base(tuplet: ElementTree.Element) -> Fraction:
    return BASE_WHOLE.get(tuplet.findtext("baseNote") or "", Fraction(1, 4))


def tuplet_target_written(tuplet: ElementTree.Element) -> Fraction:
    """Total *written* duration a full tuplet should contain."""
    _normal, actual = tuplet_numbers(tuplet)
    return tuplet_base(tuplet) * actual


def tuplet_nominal(tuplet: ElementTree.Element) -> Fraction:
    """Total *sounding* duration of the tuplet."""
    normal, _actual = tuplet_numbers(tuplet)
    return tuplet_base(tuplet) * normal


def element_ticks(element: ElementTree.Element) -> int:
    """Written ticks for one Chord/Rest (``durationType``+dots or ``duration``)."""
    written = element_written(element)
    if written is None:
        return -1
    return fraction_ticks(written)


def is_grace(element: ElementTree.Element) -> bool:
    """True for a MuseScore grace ``Chord``/``Rest``.

    MuseScore writes ``<grace16/>`` (or ``grace4``..``grace256``) as a child of the chord and
    still emits a ``<durationType>``.  The chord is engraved at zero time: it is placed at the
    current tick and never advances it.
    """
    if element.tag not in ("Chord", "Rest"):
        return False
    return any(element.find(tag) is not None for tag in GRACE_TAGS)


def element_written(element: ElementTree.Element, measure: Fraction | None = None) -> Fraction | None:
    """Written duration of a Chord/Rest in whole notes.

    MuseScore's reader is **order sensitive**: ``<duration>`` sets ticks
    directly, ``<durationType>`` sets ticks from the type plus the dots seen *so
    far*, and a later ``<dots>`` only changes the layout/dot count.  The mscx
    writer therefore emits ``<dots>`` before ``<durationType>``.  Reading in
    order here is what makes a malformed ``durationType``/``dots`` pair visible
    instead of silently over-crediting the note.

    A grace chord is always zero: its ``durationType`` describes the slash/appoggiatura
    glyph, not time in the bar.
    """
    if is_grace(element):
        return Fraction(0)
    if element.tag not in ("Chord", "Rest"):
        return measure
    ticks: Fraction | None = None
    dots = 0
    saw_type = False
    for child in element:
        if child.tag == "duration":
            try:
                ticks = Fraction(child.text or "")
            except (ValueError, ZeroDivisionError):
                pass
        elif child.tag == "durationType":
            saw_type = True
            name = (child.text or "").strip()
            if name == "measure" and measure is not None:
                ticks = measure
            else:
                base = BASE_WHOLE.get(name, Fraction(1, 4))
                ticks = base * _dot_multiplier(dots)
        elif child.tag == "dots":
            try:
                dots = int(child.text or 0)
            except (TypeError, ValueError):
                dots = 0
    if ticks is not None:
        return ticks
    if not saw_type:
        # A Rest created by the reader starts as a measure rest; a Chord starts
        # as a quarter note.
        if element.tag == "Rest" and measure is not None:
            return measure
        if element.tag == "Chord":
            return Fraction(1, 4)
    return measure


@dataclass(frozen=True)
class TimelineItem:
    element: ElementTree.Element
    kind: str
    start: Fraction
    end: Fraction
    written: Fraction
    actual: Fraction
    tuplet_depth: int


@dataclass
class TupletSpan:
    node: ElementTree.Element
    start: Fraction
    depth: int
    base: Fraction
    normal: int
    actual: int
    ratio: Fraction
    target_written: Fraction
    nominal: Fraction
    written: Fraction = Fraction(0)
    end: Fraction = Fraction(0)
    direct: list[ElementTree.Element] = field(default_factory=list)
    children: list["TupletSpan"] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return self.written == self.target_written

    @property
    def delta(self) -> Fraction:
        return self.written - self.target_written


@dataclass
class VoiceTimeline:
    items: list[TimelineItem]
    spans: list[TupletSpan]
    locations: list[Fraction]
    start: Fraction
    end: Fraction
    final: Fraction
    gaps: list[tuple[Fraction, Fraction]] = field(default_factory=list)
    overlaps: list[tuple[Fraction, Fraction]] = field(default_factory=list)

    @property
    def invalid_tuplets(self) -> list[TupletSpan]:
        return [span for span in self.spans if not span.valid]


def voice_timeline(voice: ElementTree.Element, measure: Fraction | None = None) -> VoiceTimeline:
    """Exact start/end ticks of every Chord/Rest in one ``<voice>``.

    ``<location>`` values are applied as deltas from the current reading
    position (MuseScore's ``ReadContext::setLocation``), not as absolute
    measure offsets.  Tuplet ratios nest multiplicatively and are applied to
    the written duration; each element is rounded to integer ticks only when it
    is reported, never before the ratio is applied.
    """
    if measure is None:
        measure = Fraction(4, 4)
    position = Fraction(0)
    items: list[TimelineItem] = []
    spans: list[TupletSpan] = []
    locations: list[Fraction] = []
    stack: list[TupletSpan] = []
    max_end = Fraction(0)
    gaps: list[tuple[Fraction, Fraction]] = []
    overlaps: list[tuple[Fraction, Fraction]] = []

    ratios: list[Fraction] = []

    for child in voice:
        if child.tag == "Tuplet":
            normal, actual = tuplet_numbers(child)
            base = tuplet_base(child)
            span = TupletSpan(
                node=child,
                start=position,
                depth=len(stack),
                base=base,
                normal=normal,
                actual=actual,
                ratio=Fraction(actual, normal),
                target_written=base * actual,
                nominal=base * normal,
            )
            if stack:
                stack[-1].children.append(span)
                # A child tuplet contributes its *sounding span* to the parent:
                # its chords are already scaled by the child ratio.
                stack[-1].written += span.nominal
            stack.append(span)
            spans.append(span)
            ratios.append(span.ratio)
        elif child.tag == "endTuplet":
            if stack:
                span = stack.pop()
                span.end = position
                if ratios:
                    ratios.pop()
        elif child.tag == "location":
            fraction = child.findtext("fractions")
            try:
                delta = Fraction(fraction) if fraction else Fraction(0)
            except (ValueError, ZeroDivisionError):
                delta = Fraction(0)
            locations.append(delta)
            position += delta
        elif child.tag in ("Chord", "Rest"):
            written = element_written(child, measure)
            if written is None:
                continue
            if written == 0:
                # Grace notes (and any zero-length chord the importer emits) sit on the
                # current tick without consuming time, so they never create a gap or an
                # overlap and never contribute written length to an enclosing tuplet.
                items.append(
                    TimelineItem(
                        element=child,
                        kind=child.tag.lower(),
                        start=position,
                        end=position,
                        written=Fraction(0),
                        actual=Fraction(0),
                        tuplet_depth=len(stack),
                    )
                )
                if stack:
                    stack[-1].direct.append(child)
                continue
            ratio = Fraction(1)
            for value in ratios:
                ratio *= value
            actual = written / ratio
            start = position
            end = position + actual
            if start < max_end:
                overlaps.append((start, max_end))
            elif start > max_end:
                gaps.append((max_end, start))
            item = TimelineItem(
                element=child,
                kind=child.tag.lower(),
                start=start,
                end=end,
                written=written,
                actual=actual,
                tuplet_depth=len(stack),
            )
            items.append(item)
            if stack:
                stack[-1].written += written
                stack[-1].direct.append(child)
            position = end
            max_end = max(max_end, end)

    # Any tuplet left open (missing <endTuplet/>) is still reported.
    while stack:
        span = stack.pop()
        span.end = position
        if ratios:
            ratios.pop()

    start = items[0].start if items else (locations[0] if locations else Fraction(0))
    return VoiceTimeline(
        items=items,
        spans=spans,
        locations=locations,
        start=start,
        end=max_end,
        final=position,
        gaps=gaps,
        overlaps=overlaps,
    )


def voice_ticks(voice: ElementTree.Element) -> int:
    """Sounding ticks of a voice's elements, ignoring ``<location>`` deltas."""
    timeline = voice_timeline(voice)
    return sum(fraction_ticks(item.actual) for item in timeline.items)


def location_ticks(voice: ElementTree.Element) -> int:
    """Total displacement caused by all ``<location>`` deltas, in ticks."""
    total = Fraction(0)
    for child in voice:
        if child.tag != "location":
            continue
        fraction = child.findtext("fractions")
        try:
            total += Fraction(fraction) if fraction else Fraction(0)
        except (ValueError, ZeroDivisionError):
            pass
    return fraction_ticks(total)


def measure_expected_fraction(
    measure: ElementTree.Element, inherited: Fraction | int | None = None
) -> Fraction:
    """MuseScore's ``measure->ticks()`` as a whole-note fraction.

    ``len`` is the irregular/pickup length and wins over the nominal time
    signature (the reader keeps ``m_len`` when the measure is irregular).
    """
    length = measure.get("len")
    if length:
        try:
            return Fraction(length)
        except (ValueError, ZeroDivisionError):
            pass
    signature = measure.find(".//TimeSig")
    if signature is not None:
        try:
            return Fraction(int(signature.findtext("sigN") or 4), int(signature.findtext("sigD") or 4))
        except (ValueError, ZeroDivisionError):
            pass
    if inherited is not None:
        if isinstance(inherited, Fraction):
            return inherited
        return Fraction(int(inherited), TICKS_PER_WHOLE)
    return Fraction(4, 4)


def measure_expected_ticks(measure: ElementTree.Element, inherited: Fraction | int | None = None) -> int:
    return fraction_ticks(measure_expected_fraction(measure, inherited))


def measure_report(measure: ElementTree.Element, inherited: Fraction | int | None = None) -> list[dict]:
    """Per-voice exact tick report for one measure (int fields for display)."""
    expected = measure_expected_fraction(measure, inherited)
    rows = []
    for index, voice in enumerate(measure.findall("voice"), start=1):
        timeline = voice_timeline(voice, expected)
        rows.append(
            {
                "voice": index,
                "start": fraction_ticks(timeline.start),
                "actual": fraction_ticks(timeline.end),
                "expected": fraction_ticks(expected),
                "delta": fraction_ticks(timeline.end) - fraction_ticks(expected),
                "start_fraction": timeline.start,
                "end_fraction": timeline.end,
                "expected_fraction": expected,
                "delta_fraction": timeline.end - expected,
                "final_fraction": timeline.final,
                "overlaps": list(timeline.overlaps),
                "gaps": list(timeline.gaps),
                "invalid_tuplets": [span for span in timeline.spans if not span.valid],
            }
        )
    return rows
