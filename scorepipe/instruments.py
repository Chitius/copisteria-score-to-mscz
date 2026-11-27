"""Standard GM instrument presets and drumset staff-position mappings.

MusicXML uses 1-based MIDI program numbers (1..128) and 1-based ``<midi-unpitched>``
values (GM MIDI note + 1, 1..128).  MuseScore 4 maps standard drumset notes onto its
16-drum ``drum.group.set`` table using those GM MIDI note numbers.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DrumSpec:
    """One GM drumkit voice mapped from a standard 5-line percussion staff position."""

    midi_pitch: int  # 0-based GM MIDI note number (35..57)
    name: str
    sound: str
    notehead: str | None = None  # "x" for cymbals / hi-hat, None for normal drumhead

    @property
    def midi_unpitched(self) -> int:
        """1-based MusicXML ``<midi-unpitched>`` value."""
        return self.midi_pitch + 1


# Standard 5-line drumset notation positions (matching MuseScore 4's default Drumset).
STANDARD_DRUMSET: dict[tuple[str, str], DrumSpec] = {
    ("D", "4"): DrumSpec(44, "Pedal Hi-Hat", "metal.hi-hat", "x"),
    ("E", "4"): DrumSpec(35, "Acoustic Bass Drum", "drum.bass-drum", None),
    ("F", "4"): DrumSpec(36, "Bass Drum 1", "drum.bass-drum", None),
    ("G", "4"): DrumSpec(43, "High Floor Tom", "drum.tom-tom", None),
    ("A", "4"): DrumSpec(41, "Low Floor Tom", "drum.tom-tom", None),
    ("B", "4"): DrumSpec(45, "Low Tom", "drum.tom-tom", None),
    ("C", "5"): DrumSpec(38, "Acoustic Snare", "drum.snare-drum", None),
    ("D", "5"): DrumSpec(47, "Low-Mid Tom", "drum.tom-tom", None),
    ("E", "5"): DrumSpec(50, "High Tom", "drum.tom-tom", None),
    ("F", "5"): DrumSpec(51, "Ride Cymbal 1", "metal.cymbal.ride", "x"),
    ("G", "5"): DrumSpec(42, "Closed Hi-Hat", "metal.hi-hat", "x"),
    ("A", "5"): DrumSpec(49, "Crash Cymbal 1", "metal.cymbal.crash", "x"),
    ("B", "5"): DrumSpec(57, "Crash Cymbal 2", "metal.cymbal.crash", "x"),
}


@dataclass(frozen=True)
class InstrumentPreset:
    """Metadata needed to populate MusicXML ``<score-part>`` playback and labels."""

    key: str
    name: str
    abbreviation: str
    sound: str
    midi_program: int  # 1-based GM program (1..128)
    percussion: bool = False


_PRESET_LIST: tuple[InstrumentPreset, ...] = (
    # Keyboards
    InstrumentPreset("piano", "Piano", "Pno.", "keyboard.piano", 1),
    InstrumentPreset("electric-piano", "Electric Piano", "El. Pno.", "keyboard.piano.electric", 5),
    InstrumentPreset("harpsichord", "Harpsichord", "Hpd.", "keyboard.harpsichord", 7),
    InstrumentPreset("organ", "Organ", "Org.", "keyboard.organ", 20),
    InstrumentPreset("accordion", "Accordion", "Acc.", "keyboard.accordion", 22),
    # Guitars & Plucked
    InstrumentPreset("nylon-guitar", "Classical Guitar", "Guit.", "pluck.guitar.nylon-string", 25),
    InstrumentPreset("acoustic-guitar", "Acoustic Guitar", "Guit.", "pluck.guitar.acoustic", 26),
    InstrumentPreset("electric-guitar", "Electric Guitar", "El. Guit.", "pluck.guitar.electric", 28),
    InstrumentPreset(
        "electric-guitar-overdrive", "Overdriven Guitar", "El. Guit.", "pluck.guitar.electric", 30
    ),
    InstrumentPreset(
        "electric-guitar-distortion", "Distortion Guitar", "El. Guit.", "pluck.guitar.electric", 31
    ),
    InstrumentPreset("acoustic-bass", "Acoustic Bass", "Bass", "pluck.bass.acoustic", 33),
    InstrumentPreset("electric-bass", "Electric Bass", "El. B.", "pluck.bass.electric", 34),
    InstrumentPreset("harp", "Harp", "Hrp.", "pluck.harp", 47),
    # Strings
    InstrumentPreset("violin", "Violin", "Vln.", "strings.violin", 41),
    InstrumentPreset("viola", "Viola", "Vla.", "strings.viola", 42),
    InstrumentPreset("cello", "Violoncello", "Vc.", "strings.cello", 43),
    InstrumentPreset("contrabass", "Contrabass", "Cb.", "strings.contrabass", 44),
    InstrumentPreset("strings", "Strings", "Str.", "strings.group", 49),
    # Woodwinds
    InstrumentPreset("piccolo", "Piccolo", "Picc.", "wind.flutes.flute.piccolo", 73),
    InstrumentPreset("flute", "Flute", "Fl.", "wind.flutes.flute", 74),
    InstrumentPreset("oboe", "Oboe", "Ob.", "wind.reed.oboe", 69),
    InstrumentPreset("clarinet", "Clarinet", "Cl.", "wind.reed.clarinet.bflat", 72),
    InstrumentPreset("bassoon", "Bassoon", "Bsn.", "wind.reed.bassoon", 71),
    InstrumentPreset("soprano-sax", "Soprano Saxophone", "S. Sax.", "wind.reed.saxophone.soprano", 65),
    InstrumentPreset("alto-sax", "Alto Saxophone", "A. Sax.", "wind.reed.saxophone.alto", 66),
    InstrumentPreset("tenor-sax", "Tenor Saxophone", "T. Sax.", "wind.reed.saxophone.tenor", 67),
    InstrumentPreset(
        "baritone-sax", "Baritone Saxophone", "B. Sax.", "wind.reed.saxophone.baritone", 68
    ),
    # Brass
    InstrumentPreset("trumpet", "Trumpet", "Tpt.", "brass.trumpet.bflat", 57),
    InstrumentPreset("horn", "Horn", "Hn.", "brass.french-horn", 61),
    InstrumentPreset("trombone", "Trombone", "Tbn.", "brass.trombone", 58),
    InstrumentPreset("tuba", "Tuba", "Tba.", "brass.tuba", 59),
    # Voice
    InstrumentPreset("voice", "Voice", "Vo.", "voice.vocals", 53),
    InstrumentPreset("soprano", "Soprano", "S.", "voice.soprano", 53),
    InstrumentPreset("mezzo-soprano", "Mezzo-soprano", "Ms.", "voice.mezzo-soprano", 53),
    InstrumentPreset("alto", "Alto", "A.", "voice.alto", 53),
    InstrumentPreset("tenor", "Tenor", "T.", "voice.tenor", 53),
    InstrumentPreset("baritone", "Baritone", "Bar.", "voice.baritone", 53),
    InstrumentPreset("bass-voice", "Bass", "B.", "voice.bass", 53),
    InstrumentPreset("choir", "Choir", "Ch.", "voice.choir", 53),
    # Synth
    InstrumentPreset("synth-lead", "Synth Lead", "Syn.", "synth.tone.lead", 81),
    InstrumentPreset("synth-pad", "Synth Pad", "Pad", "synth.pad.warm", 90),
    # Percussion
    InstrumentPreset("drumset", "Drumset", "D. Set", "drum.group.set", 1, percussion=True),
    InstrumentPreset("percussion", "Percussion", "Perc.", "drum.group.set", 1, percussion=True),
)

INSTRUMENT_PRESETS: dict[str, InstrumentPreset] = {item.key: item for item in _PRESET_LIST}
INSTRUMENT_KEYS: frozenset[str] = frozenset(INSTRUMENT_PRESETS)


def resolve_instrument(key: str | None) -> InstrumentPreset | None:
    """Resolve a canonical instrument preset key (tolerant of case/space/underscore)."""
    if not key:
        return None
    normalized = key.strip().lower().replace("_", "-").replace(" ", "-")
    return INSTRUMENT_PRESETS.get(normalized)
