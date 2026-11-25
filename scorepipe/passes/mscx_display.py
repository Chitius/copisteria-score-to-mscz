"""Mechanical passes on the MuseScore display form (.mscx)."""

from __future__ import annotations

from fractions import Fraction
from xml.etree import ElementTree

from ..core.mscx import MsxcDocument, has_text, note_count
from ..core.musescore_ticks import (
    element_written,
    measure_expected_fraction,
    voice_timeline,
)
from ..core.pass_base import Context, Kind, PassResult, PassSpec, Phase


class DropTextVoiceRests:
    spec = PassSpec(
        name="drop_text_voice_rests",
        phase=Phase.DISPLAY,
        kind=Kind.MECHANICAL,
        owns=("text-voice-rests",),
        description="a text-only voice carries an imported whole-measure rest; remove it",
        measure="rests inside text-only voices",
    )

    def run(self, doc: MsxcDocument, ctx: Context) -> PassResult:
        changed = 0
        for _staff, _index, measure in doc.iter_measures():
            for voice in doc.voices(measure):
                if voice.findall("Chord") or not has_text(voice):
                    continue
                if not any(other.findall("Chord") for other in doc.voices(measure) if other is not voice):
                    # The text voice is the staff's only content: its whole-measure rest *is* the
                    # measure (Suzume m1: Tempo + Dynamic + Rest). Removing it left a 0-length
                    # measure, which MuseScore shows as an incomplete bar.
                    continue
                for rest in list(voice.findall("Rest")):
                    voice.remove(rest)
                    changed += 1
        return PassResult(changed=changed)


class UnhideRealRests:
    spec = PassSpec(
        name="unhide_real_rests",
        phase=Phase.DISPLAY,
        kind=Kind.MECHANICAL,
        owns=("rest-visibility",),
        description="mscx visibility is a child element; remove it from non-measure rests",
        measure="hidden non-measure rests",
    )

    def run(self, doc: MsxcDocument, ctx: Context) -> PassResult:
        changed = 0
        for _staff, _index, measure in doc.iter_measures():
            for voice in doc.voices(measure):
                for rest in voice.findall("Rest"):
                    if rest.findtext("durationType") == "measure":
                        continue
                    if rest.find("pickupPadding") is not None:
                        continue
                    visible = rest.find("visible")
                    if visible is not None:
                        rest.remove(visible)
                        changed += 1
        return PassResult(changed=changed)


class DropPaddingVoices:
    spec = PassSpec(
        name="drop_padding_voices",
        phase=Phase.DISPLAY,
        kind=Kind.MECHANICAL,
        owns=("padding-voices",),
        description="a rest-only voice next to a chord voice is padding, not notation",
        measure="rest-only voices next to a chord voice",
    )

    def run(self, doc: MsxcDocument, ctx: Context) -> PassResult:
        changed = 0
        for _staff, _index, measure in doc.iter_measures():
            if not any(voice.findall("Chord") for voice in doc.voices(measure)):
                continue
            for voice in list(doc.voices(measure)):
                if voice.findall("Chord") or has_text(voice):
                    continue
                # a spanner or dynamic is real content. Clef/KeySig/TimeSig are measure metadata
                # that MuseScore sometimes parks in the padding voice (laputa m26 voice 2 was a
                # measure rest + Clef, so the whole voice looked non-empty and survived).
                metadata_tags = ("Clef", "KeySig", "TimeSig")
                if any(
                    child.tag not in ("Rest", "BarLine", "location", *metadata_tags)
                    for child in voice
                ):
                    continue
                owner = next(
                    (candidate for candidate in doc.voices(measure) if candidate.findall("Chord")),
                    None,
                )
                if owner is None:
                    continue
                for tag in reversed(metadata_tags):
                    item = voice.find(tag)
                    if item is None:
                        continue
                    if owner.find(tag) is None:
                        owner.insert(0, item)
                    else:
                        voice.remove(item)
                barline = voice.find("BarLine")
                if barline is not None:
                    owner.append(barline)
                measure.remove(voice)
                changed += 1
        return PassResult(changed=changed)


class DropSecondaryVoiceRests:
    spec = PassSpec(
        name="drop_secondary_voice_rests",
        phase=Phase.DISPLAY,
        kind=Kind.MECHANICAL,
        owns=("secondary-voice-rests",),
        description="drop rests on secondary voices; voice 1 already defines the measure's beats",
        measure="rests on voices other than the primary voice",
    )

    def run(self, doc: MsxcDocument, ctx: Context) -> PassResult:
        changed = 0
        for _staff, _index, measure in doc.iter_measures():
            voices = doc.voices(measure)
            if len(voices) < 2:
                continue
            primary = next((voice for voice in voices if voice.findall("Chord")), None)
            if primary is None:
                continue
            for voice in voices:
                if voice is primary or has_text(voice):
                    continue
                if not voice.findall("Chord"):
                    continue
                changed += _hide_secondary_rests(voice, measure_expected_fraction(measure))
        return PassResult(changed=changed)


def _hide_secondary_rests(voice, measure: Fraction) -> int:
    """Rests before a later chord become <location> gaps; rests after the last chord disappear."""
    children = list(voice)
    last_chord = max((index for index, child in enumerate(children) if child.tag == "Chord"), default=-1)
    changed = 0
    for index, child in enumerate(children):
        if child.tag != "Rest":
            continue
        if index > last_chord:
            voice.remove(child)
            changed += 1
            continue
        if child.findtext("durationType") == "measure" and child.find("duration") is None:
            continue
        length = element_written(child, measure)
        if length is None or length <= 0:
            continue
        location = ElementTree.Element("location")
        ElementTree.SubElement(location, "fractions").text = (
            f"{length.numerator}/{length.denominator}"
        )
        position = list(voice).index(child)
        voice.remove(child)
        voice.insert(position, location)
        changed += 1
    return changed


def _rest_beats(rest, measure: Fraction) -> float:
    if rest.findtext("durationType") == "measure" and rest.find("duration") is None:
        return 0.0
    length = element_written(rest, measure)
    return float(length) * 4.0 if length is not None else 0.0


RANGE_SPANNER_TYPES = {
    "HairPin",
    "Pedal",
    "GradualTempoChange",
    "Ottava",
    "TextLine",
    "Volta",
}


class NormalizeRangeSpanners:
    spec = PassSpec(
        name="normalize_range_spanners",
        phase=Phase.DISPLAY,
        kind=Kind.MECHANICAL,
        owns=("range-spanner-anchors",),
        description="anchor time-range spanners on the primary voice instead of a rest carrier",
        measure="range-spanner endpoints on secondary voices",
    )

    def run(self, doc: MsxcDocument, ctx: Context) -> PassResult:
        changed = 0
        for _staff, _index, measure in doc.iter_measures():
            voices = doc.voices(measure)
            if len(voices) < 2:
                continue
            primary = next((voice for voice in voices if voice.findall("Chord")), None)
            if primary is None:
                continue
            targets = _anchor_map(primary, measure_expected_fraction(measure))
            for voice in voices:
                if voice is primary or has_text(voice):
                    continue
                moved = 0
                for spanner in list(voice.findall("Spanner")):
                    if spanner.get("type") not in RANGE_SPANNER_TYPES:
                        continue
                    anchor = _next_anchor(voice, spanner)
                    if anchor is None:
                        continue
                    target = targets.get(
                        round(_anchor_tick(voice, anchor, measure_expected_fraction(measure)), 4)
                    )
                    if target is None:
                        continue
                    voice.remove(spanner)
                    primary.insert(list(primary).index(target), spanner)
                    moved += 1
                if moved:
                    changed += moved
                    _drop_rest_carrier(voice, measure)
        return PassResult(changed=changed)


def _anchor_map(voice, measure: Fraction) -> dict[float, object]:
    anchors = {}
    for item in voice_timeline(voice, measure).items:
        anchors.setdefault(round(float(item.start) * 4.0, 4), item.element)
    return anchors


def _anchor_tick(voice, anchor, measure: Fraction) -> float:
    for item in voice_timeline(voice, measure).items:
        if item.element is anchor:
            return float(item.start) * 4.0
    return 0.0


def _next_anchor(voice, spanner):
    children = list(voice)
    start = children.index(spanner) + 1
    for child in children[start:]:
        if child.tag in ("Chord", "Rest"):
            return child
    return None


def _drop_rest_carrier(voice, measure) -> None:
    if voice.findall("Chord") or has_text(voice):
        return
    remaining = [
        child
        for child in voice
        if child.tag not in ("Rest", "location", "Clef", "KeySig", "TimeSig")
    ]
    if remaining:
        return
    measure.remove(voice)


class CanonicalVoiceOrder:
    spec = PassSpec(
        name="canonical_voice_order",
        phase=Phase.DISPLAY,
        kind=Kind.MECHANICAL,
        owns=("voice-order",),
        description="densest chord voice first, text voices after; stable and idempotent",
        measure="voice slots out of canonical order",
    )

    def run(self, doc: MsxcDocument, ctx: Context) -> PassResult:
        changed = 0
        for _staff, _index, measure in doc.iter_measures():
            voices = doc.voices(measure)
            if not voices:
                continue
            ordered = sorted(
                voices,
                key=lambda voice: (
                    0 if voice.findall("Chord") else (1 if has_text(voice) else 2),
                    -note_count(voice),
                ),
            )
            if ordered == voices:
                continue
            for voice in list(voices):
                measure.remove(voice)
            for voice in ordered:
                measure.append(voice)
            changed += 1
        return PassResult(changed=changed)


class HidePickupLeadingRest:
    spec = PassSpec(
        name="hide_pickup_leading_rest",
        phase=Phase.DISPLAY,
        kind=Kind.MECHANICAL,
        owns=("pickup-leading-rest",),
        description="hide the padding rest that MuseScore creates before a bar-end pickup",
        measure="rest at the start of the first measure before a late first chord",
    )

    def run(self, doc: MsxcDocument, ctx: Context) -> PassResult:
        staff = next((s for s in doc.root.iter("Staff") if s.get("id") == "1"), None)
        if staff is None:
            return PassResult()
        measure = staff.find("Measure")
        if measure is None:
            return PassResult()
        changed = 0
        for voice in measure.findall("voice"):
            children = list(voice)
            rest = next((child for child in children if child.tag == "Rest"), None)
            if rest is None:
                continue
            first_chord = next((child for child in children if child.tag == "Chord"), None)
            if first_chord is None or children.index(rest) > children.index(first_chord):
                continue
            if _rest_beats(rest, measure_expected_fraction(measure)) < 2.0:
                continue
            if rest.find("pickupPadding") is None:
                marker = ElementTree.Element("pickupPadding")
                marker.text = "1"
                rest.insert(0, marker)
            visible = rest.find("visible")
            if visible is None:
                visible = ElementTree.Element("visible")
                rest.insert(0, visible)
            if (visible.text or "") != "0":
                visible.text = "0"
                changed += 1
        return PassResult(changed=changed)


class DropFirstTimeSignature:
    spec = PassSpec(
        name="drop_first_time_signature",
        phase=Phase.DISPLAY,
        kind=Kind.MECHANICAL,
        owns=("initial-time-signature",),
        description="delete an initial courtesy 4/4 instead of leaving it invisible",
        measure="initial 4/4 time signature when the score never changes metre",
    )

    DEFAULT_METER = (4, 4)

    def run(self, doc: MsxcDocument, ctx: Context) -> PassResult:
        staves = list(doc.root.iter("Staff"))
        first_measures = [(staff, staff.find("Measure")) for staff in staves]
        total = len(list(doc.root.iter("TimeSig")))
        if total > len(staves):
            return PassResult()  # keep an initial signature when the metre changes later
        changed = 0
        for _staff, measure in first_measures:
            if measure is None:
                continue
            for voice in measure.findall("voice"):
                for time_sig in list(voice.findall("TimeSig")):
                    # Only 4/4 is MuseScore's default, so only 4/4 can be a courtesy that is safe
                    # to delete.  Removing any other metre makes MuseScore fall back to 4/4 and
                    # every 3/4 bar becomes an irregular 3-beat bar (measured on the Schubert
                    # page: 33 mscx-measure-length violations from this pass alone).
                    meter = (
                        int(time_sig.findtext("sigN") or 4),
                        int(time_sig.findtext("sigD") or 4),
                    )
                    if meter != self.DEFAULT_METER:
                        continue
                    voice.remove(time_sig)
                    changed += 1
        return PassResult(changed=changed)


DISPLAY_PASSES = [
    DropTextVoiceRests(),
    UnhideRealRests(),
    DropPaddingVoices(),
    CanonicalVoiceOrder(),
    DropSecondaryVoiceRests(),
    NormalizeRangeSpanners(),
    HidePickupLeadingRest(),
    DropFirstTimeSignature(),
]

def compact_secondary_padding(doc) -> int:
    """Replace secondary padding rests with equal location deltas, in place.

    A padding rest already occupies the correct time between its neighbours. Replacing
    it at the same position preserves every chord onset, including existing location
    gaps and tuplet-scaled padding. Realigning the whole voice from its final tick
    would instead move every note in that voice.
    """
    from ..core.musescore_ticks import voice_timeline

    changed = 0
    meters = {}
    for staff, index, measure in doc.iter_measures():
        meter = meters.get(id(staff), Fraction(1))
        for time in measure.iter("TimeSig"):
            try:
                meter = Fraction(int(time.findtext("sigN") or 4), int(time.findtext("sigD") or 4))
            except (ValueError, ZeroDivisionError):
                pass
        meters[id(staff)] = meter
        voices = measure.findall("voice")
        primary = next((voice for voice in voices if voice.findall("Chord")), None)
        if primary is not None:
            for rest in primary.findall("Rest"):
                if rest.find("padding") is None:
                    continue
                visible = rest.find("visible")
                if visible is not None and (visible.text or "").strip().lower() in ("0", "false"):
                    rest.remove(visible)
                    changed += 1
        for voice in voices:
            if voice is primary:
                continue
            pads = [rest for rest in voice.findall("Rest") if rest.find("padding") is not None]
            if not pads:
                continue
            timeline = voice_timeline(voice, meter)
            sounding = {id(item.element): item.actual for item in timeline.items}
            for pad in pads:
                duration = sounding.get(id(pad))
                if duration is None or duration <= 0:
                    continue
                location = ElementTree.Element("location")
                ElementTree.SubElement(location, "fractions").text = (
                    f"{duration.numerator}/{duration.denominator}"
                )
                position = list(voice).index(pad)
                voice.remove(pad)
                voice.insert(position, location)
                changed += 1
    return changed

