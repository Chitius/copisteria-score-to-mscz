from __future__ import annotations

import unittest
from pathlib import Path
from xml.etree import ElementTree

from scorepipe.core.document import Document
from scorepipe.core.invariants import VERIFIERS
from scorepipe.core.pass_base import Context
from scorepipe.notation_patches import apply_patches, score_map, validate_patches, verify_patches

TINY = Path(__file__).parent / "fixtures" / "tiny.musicxml"


def patch(**overrides):
    value = {
        "op": "ottava",
        "subtype": "8va",
        "staff": 1,
        "start": {"measure": 1, "beat": 0},
        "end": {"measure": 2, "beat": 0},
        "page": 1,
        "bbox": [10, 20, 30, 40],
        "evidence": "8va bracket",
    }
    value.update(overrides)
    return {"patches": [value]}


def make_doc(body: str, divisions: int = 20) -> Document:
    root = ElementTree.fromstring(
        f"""<score-partwise version="4.0">
        <part-list><score-part id="P1"><part-name>Test</part-name></score-part></part-list>
        <part id="P1"><measure number="1">
          <attributes><divisions>{divisions}</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
          {body}
        </measure></part>
        </score-partwise>"""
    )
    return Document(root)


def note_xml(
    pitch: str = "C4",
    *,
    duration: int = 20,
    note_type: str = "quarter",
    dots: int = 0,
    voice: int = 1,
    staff: int = 1,
    chord: bool = False,
    extra: str = "",
    include_duration: bool = True,
    include_type: bool = True,
) -> str:
    step = pitch[0]
    octave = pitch[-1]
    accidental = pitch[1:-1]
    alter = accidental.count("#") - accidental.count("b")
    alter_xml = f"<alter>{alter}</alter>" if alter else ""
    accidental_xml = f"<accidental>{'sharp' if alter > 0 else 'flat'}</accidental>" if alter else ""
    duration_xml = f"<duration>{duration}</duration>" if include_duration else ""
    type_xml = f"<type>{note_type}</type>" if include_type else ""
    return (
        f"<note>{'<chord/>' if chord else ''}<pitch><step>{step}</step>{alter_xml}<octave>{octave}</octave></pitch>"
        f"{duration_xml}<voice>{voice}</voice>{type_xml}{'<dot/>' * dots}{accidental_xml}<staff>{staff}</staff>{extra}</note>"
    )


def five_note_doc(divisions: int = 20) -> Document:
    return make_doc("".join(note_xml(pitch, duration=divisions) for pitch in ("C4", "D4", "E4", "F4", "G4")), divisions)


def tuplet_patch(**overrides):
    value = {
        "op": "tuplet",
        "measure": 1,
        "staff": 1,
        "voice": "1",
        "start": {"measure": 1, "beat": 0, "pitch": "C4"},
        "end": {"measure": 1, "beat": 4, "pitch": "G4"},
        "actual_notes": 5,
        "normal_notes": 4,
        "note_count": 5,
        "span_beats": 4,
        "page": 1,
        "bbox": [10, 20, 30, 40],
        "evidence": "five notes under one bracket",
        "status": "accepted",
    }
    value.update(overrides)
    return {"patches": [value]}


class NotationPatchesTest(unittest.TestCase):
    def test_ottava_becomes_musicxml_octave_shift(self):
        doc = Document.load(TINY)
        self.assertEqual(validate_patches(patch(), doc), [])
        changed = apply_patches(doc, patch())
        self.assertEqual(changed, 2)
        shifts = list(doc.root.iter("octave-shift"))
        self.assertEqual([shift.get("type") for shift in shifts], ["up", "stop"])
        self.assertEqual(shifts[0].get("size"), "8")
        self.assertEqual(shifts[0].get("number"), "1")

    def test_8vb_is_placed_below_the_staff(self):
        doc = Document.load(TINY)
        apply_patches(doc, patch(subtype="8vb"))
        placements = [
            direction.get("placement")
            for direction in doc.root.iter("direction")
            if direction.find(".//octave-shift") is not None
        ]
        self.assertEqual(placements, ["below", "below"])

    def test_end_must_be_after_start(self):
        bad = patch(start={"measure": 2, "beat": 0}, end={"measure": 2, "beat": 0})
        self.assertTrue(any("end must be after start" in problem for problem in validate_patches(bad)))

    def test_evidence_is_required(self):
        bad = patch(page=None, bbox=None)
        self.assertTrue(any("evidence is required" in problem for problem in validate_patches(bad)))

    def test_replace_removes_existing_ottava_before_adding(self):
        doc = Document.load(TINY)
        apply_patches(doc, patch())
        replacement = patch(mode="replace", start={"measure": 1, "beat": 2}, end={"measure": 2, "beat": 0})
        apply_patches(doc, replacement)
        shifts = list(doc.root.iter("octave-shift"))
        self.assertEqual([shift.get("type") for shift in shifts], ["up", "stop"])
        self.assertEqual(len(shifts), 2)

    def test_remove_mode_clears_staff_ottava(self):
        doc = Document.load(TINY)
        apply_patches(doc, patch())
        removed = apply_patches(doc, patch(mode="remove"))
        self.assertEqual(removed, 2)
        self.assertEqual(list(doc.root.iter("octave-shift")), [])
        self.assertEqual(verify_patches(doc, patch(mode="remove")), [])

    def test_clef_patch_places_and_retires_a_staff_clef(self):
        # Suzume m56/m58: copisteria put the bass clef three bars late; the patch moves it.
        root = ElementTree.fromstring(
            """<score-partwise version="4.0">
            <part-list><score-part id="P1"><part-name>t</part-name></score-part></part-list>
            <part id="P1">
              <measure number="1">
                <attributes><divisions>4</divisions>
                  <time><beats>4</beats><beat-type>4</beat-type></time>
                  <clef number="1"><sign>G</sign><line>2</line></clef>
                  <clef number="2"><sign>G</sign><line>2</line></clef>
                </attributes>
                """ + note_xml("C4", duration=16, staff=1) + """
              </measure>
              <measure number="2">
                <attributes><clef number="2"><sign>F</sign><line>4</line></clef></attributes>
                """ + note_xml("C3", duration=16, staff=2) + """
              </measure>
            </part></score-partwise>"""
        )
        doc = Document(root)
        payload = {
            "patches": [
                {
                    "op": "clef",
                    "measure": 1,
                    "staff": 2,
                    "clef": "F",
                    "line": 4,
                    "from_measure": 2,
                    "status": "accepted",
                    "page": 4,
                    "bbox": [70, 320, 90, 340],
                    "evidence": "bass clef at the end of the previous bar",
                }
            ]
        }
        self.assertEqual(validate_patches(payload, doc, require_acceptance=True), [])
        self.assertEqual(apply_patches(doc, payload), 2)
        clefs = [
            (measure.get("number"), clef.get("number"), clef.findtext("sign"))
            for measure in doc.measures()
            for clef in measure.iter("clef")
        ]
        self.assertIn(("1", "2", "F"), clefs)
        self.assertEqual([entry for entry in clefs if entry[0] == "2"], [])
        self.assertEqual(verify_patches(doc, payload), [])

    def test_clef_patch_requires_acceptance_and_evidence(self):
        proposed = {
            "patches": [
                {
                    "op": "clef",
                    "measure": 1,
                    "staff": 2,
                    "clef": "F",
                    "line": 4,
                    "status": "proposed",
                }
            ]
        }
        problems = validate_patches(proposed, Document.load(TINY))
        self.assertTrue(any("status must be accepted" in problem for problem in problems))
        self.assertTrue(any("evidence" in problem for problem in problems))

    def test_tuplet_patch_survives_post_pipeline_check(self):
        doc = make_doc(
            "".join(note_xml(pitch, duration=16) for pitch in ("C4", "D4", "E4", "F4", "G4"))
        )
        payload = tuplet_patch(end={"measure": 1, "beat": 3.2, "pitch": "G4"}, span_beats=4)
        self.assertEqual(validate_patches(payload, doc), [])
        apply_patches(doc, payload)
        self.assertEqual(verify_patches(doc, payload), [])
        for note in doc.root.iter("note"):
            for modification in list(note.findall("time-modification")):
                note.remove(modification)
        self.assertTrue(verify_patches(doc, payload))

    def test_verify_rejects_ottava_size_drift(self):
        doc = Document.load(TINY)
        payload = patch()
        apply_patches(doc, payload)
        first = next(doc.root.iter("octave-shift"))
        first.set("size", "15")
        self.assertTrue(any("ottava" in problem for problem in verify_patches(doc, payload)))

    def test_verify_rejects_tuplet_duration_drift(self):
        doc = make_doc(
            "".join(note_xml(pitch, duration=16) for pitch in ("C4", "D4", "E4", "F4", "G4"))
        )
        payload = tuplet_patch(end={"measure": 1, "beat": 3.2, "pitch": "G4"}, span_beats=4)
        apply_patches(doc, payload)
        doc.root.find(".//note/duration").text = "20"
        self.assertTrue(any("tuplet" in problem for problem in verify_patches(doc, payload)))

    def test_proposed_ottava_is_rejected_when_acceptance_is_required(self):
        doc = Document.load(TINY)
        payload = patch(status="proposed")
        self.assertTrue(validate_patches(payload, doc, require_acceptance=True))

    def assert_tuplet_rejected(self, doc: Document, payload: dict):
        before = doc.state_hash()
        problems = validate_patches(payload, doc)
        self.assertTrue(problems)
        self.assertEqual(doc.state_hash(), before)

    def test_five_four_rewrites_complete_segment_and_removes_forward(self):
        body = (
            note_xml("C4", extra='<notations><tuplet type="start"/></notations>')
            + note_xml("D4", extra='<notations><tuplet type="stop"/></notations>')
            + "<forward><duration>20</duration></forward>"
            + note_xml("E4", extra='<notations><tuplet type="start"/></notations>')
            + note_xml("F4")
            + note_xml("G4", extra='<notations><tuplet type="stop"/></notations>')
        )
        doc = make_doc(body)
        payload = tuplet_patch(end={"measure": 1, "beat": 5, "pitch": "G4"})
        self.assertEqual(validate_patches(payload, doc), [])
        self.assertEqual(apply_patches(doc, payload), 1)
        notes = list(doc.root.iter("note"))
        self.assertEqual([note.findtext("duration") for note in notes], ["16"] * 5)
        self.assertEqual(list(doc.root.iter("forward")), [])
        self.assertEqual(
            [(mod.findtext("actual-notes"), mod.findtext("normal-notes")) for mod in doc.root.iter("time-modification")],
            [("5", "4")] * 5,
        )
        self.assertEqual([tuplet.get("type") for tuplet in doc.root.iter("tuplet")], ["start", "stop"])
        self.assertEqual([note.findtext("pitch/step") for note in notes], ["C", "D", "E", "F", "G"])
        for verifier in VERIFIERS:
            self.assertEqual(verifier(doc, Context()), [], verifier.__name__)

    def test_twelve_eight_ratio_with_six_independent_onsets(self):
        pitches = ("C4", "D4", "E4", "F4", "G4", "A4")
        doc = make_doc("".join(note_xml(pitch, duration=24) for pitch in pitches), 24)
        payload = tuplet_patch(
            end={"measure": 1, "beat": 5, "pitch": "A4"},
            actual_notes=12,
            normal_notes=8,
            note_count=6,
        )
        self.assertEqual(validate_patches(payload, doc), [])
        self.assertEqual(apply_patches(doc, payload), 1)
        self.assertEqual([note.findtext("duration") for note in doc.root.iter("note")], ["16"] * 6)

    def test_chord_durations_and_existing_notations_are_preserved(self):
        body = (
            note_xml(
                "C4",
                duration=18,
                dots=1,
                extra='<notations><tied type="start"/><tuplet type="start"/></notations>',
            )
            + note_xml("E4", duration=18, dots=1, chord=True)
            + note_xml("D4", duration=18, dots=1)
            + note_xml(
                "F#4",
                duration=18,
                dots=1,
                extra='<notations><slur type="start"/><tuplet type="stop"/></notations>',
            )
        )
        doc = make_doc(body, 12)
        payload = tuplet_patch(
            end={"measure": 1, "beat": 3, "pitch": "F#4"},
            actual_notes=3,
            normal_notes=2,
            note_count=3,
            span_beats=3,
        )
        before_pitches = [ElementTree.tostring(note.find("pitch")) for note in doc.root.iter("note")]
        self.assertEqual(validate_patches(payload, doc), [])
        self.assertEqual(apply_patches(doc, payload), 1)
        notes = list(doc.root.iter("note"))
        self.assertEqual(len(notes), 4)
        self.assertEqual([note.findtext("duration") for note in notes], ["12"] * 4)
        self.assertEqual([ElementTree.tostring(note.find("pitch")) for note in notes], before_pitches)
        self.assertEqual([child.tag for child in notes[0].find("notations")], ["tied", "tuplet"])
        self.assertEqual([child.tag for child in notes[-1].find("notations")], ["slur", "tuplet"])
        self.assertIsNone(notes[1].find("notations"))
        self.assertEqual(notes[0].find("notations/tuplet").get("type"), "start")
        self.assertEqual(notes[-1].find("notations/tuplet").get("type"), "stop")
        last_tags = [child.tag for child in notes[-1]]
        self.assertLess(last_tags.index("type"), last_tags.index("dot"))
        self.assertLess(last_tags.index("dot"), last_tags.index("accidental"))
        self.assertLess(last_tags.index("accidental"), last_tags.index("time-modification"))
        self.assertLess(last_tags.index("time-modification"), last_tags.index("notations"))
        self.assertEqual(len(list(doc.root.iter("time-modification"))), 4)

    def test_score_map_exposes_tuplet_note_details(self):
        base = note_xml("C#4", duration=18, dots=1).replace(
            "<staff>1</staff>",
            "<time-modification><actual-notes>3</actual-notes><normal-notes>2</normal-notes></time-modification><staff>1</staff>",
        )
        doc = make_doc(base + note_xml("Eb4", duration=18, dots=1, chord=True), 12)
        notes = score_map(doc)["measures"][0]["staves"]["1"]
        self.assertEqual([note["pitch"] for note in notes], ["C#4", "Eb4"])
        self.assertEqual([note["alter"] for note in notes], [1, -1])
        self.assertEqual([note["chord"] for note in notes], [False, True])
        self.assertEqual([note["type"] for note in notes], ["quarter", "quarter"])
        self.assertEqual([note["dots"] for note in notes], [1, 1])
        self.assertEqual([(note["actual"], note["normal"]) for note in notes], [(3, 2), (None, None)])

    def test_tuplet_status_numbers_and_evidence_are_validated(self):
        bad_payloads = [
            tuplet_patch(status="proposed"),
            tuplet_patch(actual_notes=0),
            tuplet_patch(normal_notes=0),
            tuplet_patch(note_count=0),
            tuplet_patch(span_beats=0),
            tuplet_patch(page=None),
            tuplet_patch(bbox=None, crop=None),
            tuplet_patch(evidence=""),
        ]
        for payload in bad_payloads:
            with self.subTest(payload=payload):
                self.assert_tuplet_rejected(five_note_doc(), payload)

    def test_tuplet_rejects_bad_anchors_pitch_voice_and_order(self):
        bad_payloads = [
            tuplet_patch(start={"measure": 1, "beat": 0.25, "pitch": "C4"}),
            tuplet_patch(start={"measure": 1, "beat": 0, "pitch": "C#4"}),
            tuplet_patch(voice="2"),
            tuplet_patch(start={"measure": 2, "beat": 0, "pitch": "C4"}),
            tuplet_patch(end={"measure": 1, "beat": 0, "pitch": "C4"}),
            tuplet_patch(note_count=4),
        ]
        for payload in bad_payloads:
            with self.subTest(payload=payload):
                self.assert_tuplet_rejected(five_note_doc(), payload)
        ambiguous = make_doc(note_xml("C4") + note_xml("C4", chord=True) + note_xml("D4") + note_xml("E4") + note_xml("F4") + note_xml("G4"))
        self.assert_tuplet_rejected(ambiguous, tuplet_patch())

    def test_tuplet_rejects_rests_unpitched_and_missing_note_data(self):
        rest = '<note><rest/><duration>20</duration><voice>1</voice><type>quarter</type><staff>1</staff></note>'
        unpitched = '<note><duration>20</duration><voice>1</voice><type>quarter</type><staff>1</staff></note>'
        cases = [
            (note_xml("C4") + rest + note_xml("E4") + note_xml("F4") + note_xml("G4"), tuplet_patch()),
            (note_xml("C4") + unpitched + note_xml("E4") + note_xml("F4") + note_xml("G4"), tuplet_patch()),
            (
                note_xml("C4") + note_xml("D4", include_duration=False) + note_xml("E4") + note_xml("F4") + note_xml("G4"),
                tuplet_patch(end={"measure": 1, "beat": 3, "pitch": "G4"}),
            ),
            (
                note_xml("C4") + note_xml("D4", include_type=False) + note_xml("E4") + note_xml("F4") + note_xml("G4"),
                tuplet_patch(),
            ),
        ]
        for body, payload in cases:
            with self.subTest(body=body):
                self.assert_tuplet_rejected(make_doc(body), payload)

    def test_tuplet_rejects_backup_and_interleaved_voice(self):
        backup_doc = make_doc(
            note_xml("C4")
            + note_xml("D4")
            + "<backup><duration>20</duration></backup>"
            + note_xml("E4")
            + note_xml("F4")
            + note_xml("G4")
        )
        self.assert_tuplet_rejected(
            backup_doc, tuplet_patch(end={"measure": 1, "beat": 3, "pitch": "G4"})
        )
        voice_doc = make_doc(
            note_xml("C4")
            + note_xml("D4")
            + note_xml("B3", voice=2)
            + note_xml("E4")
            + note_xml("F4")
            + note_xml("G4")
        )
        self.assert_tuplet_rejected(
            voice_doc, tuplet_patch(end={"measure": 1, "beat": 5, "pitch": "G4"})
        )

    def test_tuplet_rejects_nested_and_crossing_old_tuplets(self):
        nested_doc = make_doc(
            note_xml("C4", extra='<notations><tuplet type="start"/></notations>')
            + note_xml("D4", extra='<notations><tuplet type="start"/></notations>')
            + note_xml("E4")
            + note_xml("F4", extra='<notations><tuplet type="stop"/></notations>')
            + note_xml("G4", extra='<notations><tuplet type="stop"/></notations>')
        )
        self.assert_tuplet_rejected(nested_doc, tuplet_patch())
        crossing_doc = make_doc(
            note_xml("C4", extra='<notations><tuplet type="start"/></notations>')
            + note_xml("D4")
            + note_xml("E4")
            + note_xml("F4", extra='<notations><tuplet type="stop"/></notations>')
            + note_xml("G4")
        )
        crossing = tuplet_patch(
            start={"measure": 1, "beat": 1, "pitch": "D4"},
            end={"measure": 1, "beat": 3, "pitch": "F4"},
            actual_notes=3,
            normal_notes=2,
            note_count=3,
            span_beats=2,
        )
        self.assert_tuplet_rejected(crossing_doc, crossing)

    def test_tuplet_rejects_overlapping_patches(self):
        first = tuplet_patch(
            end={"measure": 1, "beat": 2, "pitch": "E4"},
            actual_notes=3,
            normal_notes=2,
            note_count=3,
            span_beats=2,
        )["patches"][0]
        second = tuplet_patch(
            start={"measure": 1, "beat": 1, "pitch": "D4"},
            end={"measure": 1, "beat": 3, "pitch": "F4"},
            actual_notes=3,
            normal_notes=2,
            note_count=3,
            span_beats=2,
        )["patches"][0]
        self.assert_tuplet_rejected(five_note_doc(24), {"patches": [first, second]})

    def test_tuplet_rejects_fractional_ticks_and_wrong_span(self):
        self.assert_tuplet_rejected(five_note_doc(12), tuplet_patch())
        self.assert_tuplet_rejected(five_note_doc(), tuplet_patch(span_beats=3))


if __name__ == "__main__":
    unittest.main()
