from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree

from scorepipe.agent_facts import merge_agent_facts, validate_agent_facts
from scorepipe.core.document import Document
from scorepipe.core.invariants import VERIFIERS
from scorepipe.core.mscx import MsxcDocument
from scorepipe.core.mscx_invariants import MSCX_VERIFIERS
from scorepipe.core.pass_base import Context
from scorepipe.core.pipeline import run_pipeline
from scorepipe.facts import validate_facts
from scorepipe.loader import merge_pages
from scorepipe.mscz_export import extract_chord_fragments, extract_ties
from scorepipe.notation_patches import (
    apply_patches,
    score_map,
    validate_patches,
    verify_patches,
)
from scorepipe.passes import (
    INJECT_PARTS,
    INJECT_PASSES,
    NORMALIZE_PERCUSSION,
    STRUCTURAL_PASSES,
    TRUNCATE_OVERFULL_MSCX,
)
from scorepipe.passes.xml_empty_staves import PAD_EMPTY_STAVES
from scorepipe.passes.xml_pickup import MARK_PICKUP
from scorepipe.passes.xml_redundant_voices import DROP_REDUNDANT_VOICES
from scorepipe.passes.xml_tail import DROP_DUPLICATE_TAIL
from scorepipe.passes.xml_voice_merge import MERGE_STAFF_VOICES
from scorepipe.proof_sheet import prepare_paginated_musicxml
from scorepipe.sanity import check_sounding_notes_preserved, snapshot


def _doc(parts_xml: str, part_ids: tuple[str, ...] = ("P1", "P2")) -> Document:
    part_list = "".join(
        f'<score-part id="{pid}"><part-name>{pid}</part-name></score-part>' for pid in part_ids
    )
    return Document(
        ElementTree.fromstring(
            f'<score-partwise version="4.0"><part-list>{part_list}</part-list>{parts_xml}</score-partwise>'
        )
    )


class MultiPartPassesTest(unittest.TestCase):
    def test_pad_empty_staves_stays_scoped_per_part(self):
        # P1 has 1 staff; P2 has 2 staves (staff 2 missing in m2).
        # P1 must NOT receive a staff 2 rest from P2's staff set.
        doc = _doc(
            '<part id="P1">'
            '<measure number="1"><attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>'
            '<note><pitch><step>C</step><octave>5</octave></pitch><duration>16</duration><voice>1</voice></note></measure>'
            '<measure number="2">'
            '<note><pitch><step>D</step><octave>5</octave></pitch><duration>16</duration><voice>1</voice></note></measure>'
            "</part>"
            '<part id="P2">'
            '<measure number="1"><attributes><divisions>4</divisions><staves>2</staves><time><beats>4</beats><beat-type>4</beat-type></time></attributes>'
            '<note><pitch><step>E</step><octave>4</octave></pitch><duration>16</duration><voice>1</voice><staff>1</staff></note>'
            '<backup><duration>16</duration></backup>'
            '<note><pitch><step>C</step><octave>3</octave></pitch><duration>16</duration><voice>5</voice><staff>2</staff></note></measure>'
            '<measure number="2">'
            '<note><pitch><step>F</step><octave>4</octave></pitch><duration>16</duration><voice>1</voice><staff>1</staff></note></measure>'
            "</part>"
        )
        result = PAD_EMPTY_STAVES.run(doc, Context())
        self.assertEqual(result.changed, 1)
        p1_staves = {n.findtext("staff") or "1" for m in doc.measures("P1") for n in m.findall("note")}
        p2_m2_staves = {n.findtext("staff") or "1" for n in doc.measures("P2")[1].findall("note")}
        self.assertEqual(p1_staves, {"1"})
        self.assertEqual(p2_m2_staves, {"1", "2"})

    def test_pad_empty_staves_replaces_bare_forward_without_oscillating(self):
        # Empty bar emitted by copisteria with only <forward>; must become a beat-0 measure rest
        # and converge cleanly with drop_overflow_rests.
        doc = _doc(
            '<part id="P1">'
            '<measure number="1"><attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>'
            '<note><pitch><step>C</step><octave>5</octave></pitch><duration>16</duration><voice>1</voice></note></measure>'
            '<measure number="2"><forward><duration>16</duration></forward></measure>'
            "</part>",
            part_ids=("P1",),
        )
        report = run_pipeline(
            doc, Context(), structural=STRUCTURAL_PASSES, inject=INJECT_PASSES, verifiers=VERIFIERS
        )
        self.assertTrue(all(phase.stable for phase in report.phases))
        self.assertEqual(report.verifier, [])
        m2_events = doc.events(doc.measures("P1")[1])
        self.assertEqual([(e.onset, e.duration, e.rest) for e in m2_events], [(0.0, 4.0, True)])

    def test_drop_trailing_duplicate_requires_all_parts_to_agree(self):
        # P1 repeats C5 shorter, but P2 has a different pitch in m2 -> MUST NOT drop.
        doc = _doc(
            '<part id="P1">'
            '<measure number="1"><attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>'
            '<note><pitch><step>C</step><octave>5</octave></pitch><duration>16</duration><voice>1</voice></note></measure>'
            '<measure number="2">'
            '<note><pitch><step>C</step><octave>5</octave></pitch><duration>8</duration><voice>1</voice></note></measure>'
            "</part>"
            '<part id="P2">'
            '<measure number="1"><attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>'
            '<note><pitch><step>G</step><octave>3</octave></pitch><duration>16</duration><voice>1</voice></note></measure>'
            '<measure number="2">'
            '<note><pitch><step>A</step><octave>3</octave></pitch><duration>16</duration><voice>1</voice></note></measure>'
            "</part>"
        )
        self.assertEqual(DROP_DUPLICATE_TAIL.run(doc, Context()).changed, 0)
        self.assertEqual(len(doc.measures("P1")), 2)
        self.assertEqual(len(doc.measures("P2")), 2)

        # When both parts repeat shorter (or P1 is resting), both parts drop m2 in lockstep.
        doc2 = _doc(
            '<part id="P1">'
            '<measure number="1"><attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>'
            '<note><rest measure="yes"/><duration>16</duration><voice>1</voice></note></measure>'
            '<measure number="2">'
            '<note><rest measure="yes"/><duration>16</duration><voice>1</voice></note></measure>'
            "</part>"
            '<part id="P2">'
            '<measure number="1"><attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>'
            '<note><pitch><step>G</step><octave>3</octave></pitch><duration>16</duration><voice>1</voice></note></measure>'
            '<measure number="2">'
            '<note><pitch><step>G</step><octave>3</octave></pitch><duration>8</duration><voice>1</voice></note></measure>'
            "</part>"
        )
        self.assertEqual(DROP_DUPLICATE_TAIL.run(doc2, Context()).changed, 1)
        self.assertEqual(len(doc2.measures("P1")), 1)
        self.assertEqual(len(doc2.measures("P2")), 1)

    def test_pickup_coordinates_all_parts_and_keeps_unpitched_notes(self):
        # P1 has a 1-beat vocal pickup + 3-beat padding rest; P2 has a 1-beat drum hit + 3-beat rest.
        doc = _doc(
            '<part id="P1">'
            '<measure number="1"><attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>'
            '<note><pitch><step>C</step><octave>5</octave></pitch><duration>4</duration><voice>1</voice></note>'
            '<note><rest/><duration>12</duration><voice>1</voice></note></measure>'
            "</part>"
            '<part id="P2">'
            '<measure number="1"><attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>'
            '<note><unpitched><display-step>F</display-step><display-octave>4</display-octave></unpitched><duration>4</duration><voice>1</voice></note>'
            '<note><rest/><duration>12</duration><voice>1</voice></note></measure>'
            "</part>"
        )
        result = MARK_PICKUP.run(doc, Context())
        self.assertEqual(result.changed, 2)
        p1_events = doc.events(doc.measures("P1")[0])
        p2_events = doc.events(doc.measures("P2")[0])
        self.assertEqual([(e.onset, e.duration) for e in p1_events], [(3.0, 1.0)])
        self.assertEqual([(e.onset, e.duration) for e in p2_events], [(3.0, 1.0)])
        self.assertIsNotNone(p2_events[0].element.find("unpitched"))

    def test_unpitched_percussion_voices_are_not_dropped_or_merged(self):
        doc = _doc(
            '<part id="P1">'
            '<measure number="1"><attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>'
            '<note><unpitched><display-step>G</display-step><display-octave>5</display-octave></unpitched><duration>8</duration><voice>1</voice><type>half</type></note>'
            '<note><unpitched><display-step>G</display-step><display-octave>5</display-octave></unpitched><duration>8</duration><voice>1</voice><type>half</type></note>'
            '<backup><duration>16</duration></backup>'
            '<note><unpitched><display-step>F</display-step><display-octave>4</display-octave></unpitched><duration>16</duration><voice>2</voice><type>whole</type></note>'
            "</measure></part>",
            part_ids=("P1",),
        )
        self.assertEqual(DROP_REDUNDANT_VOICES.run(doc, Context()).changed, 0)
        self.assertEqual(MERGE_STAFF_VOICES.run(doc, Context()).changed, 0)
        self.assertEqual(len(doc.events(doc.measures("P1")[0])), 3)

    def test_mscz_export_maps_part_staves_to_global_staff_ids(self):
        # P1 has 1 staff (global 1); P2 has 2 staves (global 2 and 3).
        doc = _doc(
            '<part id="P1">'
            '<measure number="1"><attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>'
            '<note><pitch><step>C</step><octave>5</octave></pitch><duration>16</duration><tie type="start"/><voice>1</voice></note></measure>'
            '<measure number="2">'
            '<note><pitch><step>C</step><octave>5</octave></pitch><duration>16</duration><tie type="stop"/><voice>1</voice></note></measure>'
            "</part>"
            '<part id="P2">'
            '<measure number="1"><attributes><divisions>4</divisions><staves>2</staves><time><beats>4</beats><beat-type>4</beat-type></time></attributes>'
            '<note><pitch><step>E</step><octave>4</octave></pitch><duration>16</duration><voice>1</voice><staff>1</staff></note>'
            '<note><chord/><pitch><step>G</step><octave>4</octave></pitch><duration>8</duration><voice>1</voice><staff>1</staff></note>'
            '<backup><duration>16</duration></backup>'
            '<note><pitch><step>C</step><octave>3</octave></pitch><duration>16</duration><tie type="start"/><voice>5</voice><staff>2</staff></note></measure>'
            '<measure number="2">'
            '<note><pitch><step>E</step><octave>4</octave></pitch><duration>16</duration><voice>1</voice><staff>1</staff></note>'
            '<backup><duration>16</duration></backup>'
            '<note><pitch><step>C</step><octave>3</octave></pitch><duration>16</duration><tie type="stop"/><voice>5</voice><staff>2</staff></note></measure>'
            "</part>"
        )
        ties = extract_ties(doc)
        self.assertEqual({(t["staff"], t["pitch"]) for t in ties}, {("1", 72), ("3", 48)})
        fragments = extract_chord_fragments(doc)
        self.assertEqual(len(fragments), 1)
        self.assertEqual(fragments[0]["staff"], "2")

    def test_notation_patches_and_score_map_support_target_part(self):
        doc = _doc(
            '<part id="P1">'
            '<measure number="1"><attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>'
            '<note><pitch><step>C</step><octave>5</octave></pitch><duration>16</duration><voice>1</voice></note></measure>'
            "</part>"
            '<part id="P2">'
            '<measure number="1"><attributes><divisions>4</divisions><staves>2</staves><time><beats>4</beats><beat-type>4</beat-type></time></attributes>'
            '<note><pitch><step>E</step><octave>5</octave></pitch><duration>8</duration><voice>1</voice><staff>1</staff></note>'
            '<note><pitch><step>G</step><octave>5</octave></pitch><duration>8</duration><voice>1</voice><staff>1</staff></note>'
            '<backup><duration>16</duration></backup>'
            '<note><pitch><step>C</step><octave>3</octave></pitch><duration>16</duration><voice>5</voice><staff>2</staff></note></measure>'
            "</part>"
        )
        mapping = score_map(doc)
        self.assertEqual(set(mapping["parts"]), {"P1", "P2"})
        payload = {
            "patches": [
                {
                    "op": "ottava",
                    "part": "P2",
                    "subtype": "8va",
                    "staff": 1,
                    "start": {"measure": 1, "beat": 0},
                    "end": {"measure": 1, "beat": 2},
                    "status": "accepted",
                    "page": 1,
                    "bbox": [0, 0, 10, 10],
                    "evidence": "8va on P2 staff 1",
                }
            ]
        }
        self.assertEqual(validate_patches(payload, doc, require_acceptance=True), [])
        self.assertEqual(apply_patches(doc, payload), 2)
        self.assertEqual(verify_patches(doc, payload), [])
        self.assertEqual(len(list(doc.part_by_id("P1").iter("octave-shift"))), 0)
        self.assertEqual(len(list(doc.part_by_id("P2").iter("octave-shift"))), 2)

        bad_payload = {"patches": [{**payload["patches"][0], "part": "P9"}]}
        self.assertTrue(validate_patches(bad_payload, doc, require_acceptance=True))

    def test_page_restore_isolates_parts_on_merged_multi_part_pages(self):
        page1 = (
            '<?xml version="1.0" encoding="UTF-8"?><score-partwise version="4.0">'
            '<part-list><score-part id="P1"><part-name>Voice</part-name></score-part>'
            '<score-part id="P2"><part-name>Piano</part-name></score-part></part-list>'
            '<part id="P1"><measure number="1"><attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>'
            '<note><pitch><step>C</step><octave>5</octave></pitch><duration>8</duration><voice>1</voice><notations><slur type="start" number="1"/></notations></note>'
            '<note><pitch><step>D</step><octave>5</octave></pitch><duration>8</duration><voice>1</voice><notations><slur type="stop" number="1"/></notations></note>'
            "</measure></part>"
            '<part id="P2"><measure number="1"><attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>'
            '<direction placement="below"><direction-type><pedal type="start" number="1"/></direction-type><staff>1</staff></direction>'
            '<note><pitch><step>C</step><octave>5</octave></pitch><duration>8</duration><tie type="start"/><voice>1</voice><staff>1</staff></note>'
            '<note><pitch><step>C</step><octave>5</octave></pitch><duration>8</duration><tie type="stop"/><voice>1</voice><staff>1</staff></note>'
            "</measure></part></score-partwise>"
        )
        with tempfile.TemporaryDirectory() as tmp:
            p1 = Path(tmp) / "p01.musicxml"
            p1.write_text(page1, encoding="utf-8")
            merged = merge_pages([p1])
            report = run_pipeline(
                merged.document,
                Context(pages=merged),
                structural=STRUCTURAL_PASSES,
                inject=INJECT_PASSES,
                verifiers=VERIFIERS,
            )
            self.assertEqual(report.verifier, [])
            self.assertTrue(any(p.get("type") == "start" for p in merged.document.part_by_id("P2").iter("pedal")))
            self.assertFalse(any(True for _ in merged.document.part_by_id("P1").iter("pedal")))
            self.assertEqual(len(list(merged.document.part_by_id("P1").iter("slur"))), 2)
            self.assertEqual(len(list(merged.document.part_by_id("P2").iter("tie"))), 2)

    def test_prepare_paginated_musicxml_marks_all_parts(self):
        doc = _doc(
            '<part id="P1"><measure number="1"/><measure number="2"/></part>'
            '<part id="P2"><measure number="1"/><measure number="2"/></part>'
        )
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "score.musicxml"
            out = Path(tmp) / "paged.musicxml"
            doc.save(src)
            prepare_paginated_musicxml(src, [1, 1], out)
            root = ElementTree.parse(out).getroot()
            for part in root.findall("part"):
                m2 = part.findall("measure")[1]
                self.assertEqual(m2.find("print").get("new-page"), "yes")

    def test_sanity_detects_lost_note_in_second_part(self):
        before_doc = _doc(
            '<part id="P1"><measure number="1"><attributes><divisions>4</divisions></attributes>'
            '<note><pitch><step>C</step><octave>4</octave></pitch><duration>16</duration><voice>1</voice></note></measure></part>'
            '<part id="P2"><measure number="1"><attributes><divisions>4</divisions></attributes>'
            '<note><pitch><step>C</step><octave>4</octave></pitch><duration>16</duration><voice>1</voice></note></measure></part>'
        )
        after_doc = _doc(
            '<part id="P1"><measure number="1"><attributes><divisions>4</divisions></attributes>'
            '<note><pitch><step>C</step><octave>4</octave></pitch><duration>16</duration><voice>1</voice></note></measure></part>'
            '<part id="P2"><measure number="1"><attributes><divisions>4</divisions></attributes>'
            '<note><rest/><duration>16</duration><voice>1</voice></note></measure></part>'
        )
        problems = check_sounding_notes_preserved(snapshot(before_doc), snapshot(after_doc))
        self.assertEqual(len(problems), 1)
        self.assertIn("P2", problems[0])

    def test_truncate_overfull_trims_trailing_rest_on_silent_staves(self):
        # When one part in a multi-part score is overfull (len="17/16"), MuseScore stretches
        # silent staves by appending a trailing <Rest> after <Rest measure/>. Truncation must
        # trim those silent staves too once len="17/16" is removed.
        mscx = MsxcDocument(
            ElementTree.fromstring(
                "<museScore version='4.40'><Score>"
                "<Staff id='1'><Measure len='17/16'><voice>"
                "<TimeSig><sigN>4</sigN><sigD>4</sigD></TimeSig>"
                "<Chord><durationType>whole</durationType><Note><pitch>60</pitch><tpc>14</tpc></Note></Chord>"
                "<Rest><durationType>16th</durationType></Rest>"
                "</voice></Measure></Staff>"
                "<Staff id='2'><Measure len='17/16'><voice>"
                "<Rest><durationType>measure</durationType><duration>4/4</duration></Rest>"
                "<Rest><durationType>16th</durationType></Rest>"
                "</voice></Measure></Staff>"
                "</Score></museScore>"
            )
        )
        result = TRUNCATE_OVERFULL_MSCX.run(mscx, Context())
        self.assertGreaterEqual(result.changed, 2)
        violations = [v for verifier in MSCX_VERIFIERS for v in verifier(mscx, Context())]
        self.assertEqual(violations, [])

    def test_normalize_percussion_binds_gm_drumset_and_cymbal_noteheads(self):
        doc = _doc(
            '<part id="P1"><measure number="1">'
            "<attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time>"
            "<clef><sign>G</sign><line>2</line></clef></attributes>"
            "<note><pitch><step>C</step><octave>5</octave></pitch><duration>16</duration><voice>1</voice><type>whole</type></note>"
            "</measure></part>"
            '<part id="P2"><measure number="1">'
            "<attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time>"
            "<clef><sign>percussion</sign></clef></attributes>"
            "<note><unpitched><display-step>F</display-step><display-octave>4</display-octave></unpitched>"
            "<duration>4</duration><voice>1</voice><type>quarter</type></note>"
            "<note><unpitched><display-step>C</display-step><display-octave>5</display-octave></unpitched>"
            "<duration>4</duration><voice>1</voice><type>quarter</type></note>"
            "<note><unpitched><display-step>F</display-step><display-octave>5</display-octave></unpitched>"
            "<duration>4</duration><voice>1</voice><type>quarter</type></note>"
            "<note><unpitched><display-step>G</display-step><display-octave>5</display-octave></unpitched>"
            "<duration>4</duration><voice>1</voice><type>quarter</type></note>"
            "</measure></part>",
            part_ids=("P1", "P2"),
        )
        first = NORMALIZE_PERCUSSION.run(doc, Context())
        self.assertGreater(first.changed, 0)
        # Idempotent on second run.
        second = NORMALIZE_PERCUSSION.run(doc, Context())
        self.assertEqual(second.changed, 0)

        p1_score = doc.root.find("part-list/score-part[@id='P1']")
        p2_score = doc.root.find("part-list/score-part[@id='P2']")
        self.assertEqual(p1_score.findall("midi-instrument"), [])
        midi_unpitched = {
            m.get("id"): (m.findtext("midi-channel"), int(m.findtext("midi-unpitched")))
            for m in p2_score.findall("midi-instrument")
        }
        # 1-based MusicXML midi-unpitched = GM MIDI note + 1:
        # F4 Bass Drum (36->37), C5 Snare (38->39), G5 Hi-Hat (42->43), F5 Ride (51->52)
        self.assertEqual(
            midi_unpitched,
            {
                "P2-I37": ("10", 37),
                "P2-I39": ("10", 39),
                "P2-I43": ("10", 43),
                "P2-I52": ("10", 52),
            },
        )
        notes = list(doc.part_by_id("P2").iter("note"))
        self.assertEqual([n.find("instrument").get("id") for n in notes], ["P2-I37", "P2-I39", "P2-I52", "P2-I43"])
        self.assertEqual([n.findtext("notehead") for n in notes], [None, None, "x", "x"])

    def test_normalize_percussion_ignores_pitched_grand_staff_with_spurious_percussion_clef(self):
        # OMR occasionally misreads a piano bass clef on one page as a percussion clef.
        # A 2-staff / predominantly pitched part must never be reclassified as a drumset.
        doc = _doc(
            '<part id="P1"><measure number="1">'
            "<attributes><divisions>4</divisions><staves>2</staves>"
            "<time><beats>4</beats><beat-type>4</beat-type></time>"
            '<clef number="1"><sign>G</sign><line>2</line></clef>'
            '<clef number="2"><sign>F</sign><line>4</line></clef></attributes>'
            "<note><pitch><step>C</step><octave>5</octave></pitch><duration>16</duration><voice>1</voice><staff>1</staff></note>"
            "<backup><duration>16</duration></backup>"
            "<note><pitch><step>C</step><octave>3</octave></pitch><duration>16</duration><voice>5</voice><staff>2</staff></note>"
            '</measure><measure number="2">'
            '<attributes><clef number="2"><sign>percussion</sign></clef></attributes>'
            "<note><pitch><step>D</step><octave>5</octave></pitch><duration>16</duration><voice>1</voice><staff>1</staff></note>"
            "<backup><duration>16</duration></backup>"
            "<note><unpitched><display-step>F</display-step><display-octave>4</display-octave></unpitched>"
            "<duration>16</duration><voice>5</voice><staff>2</staff></note>"
            "</measure></part>",
            part_ids=("P1",),
        )
        res = NORMALIZE_PERCUSSION.run(doc, Context())
        self.assertEqual(res.changed, 0)
        p1_score = doc.root.find("part-list/score-part[@id='P1']")
        self.assertEqual(p1_score.findall("midi-instrument"), [])

    def test_apply_parts_facts_sets_instruments_and_preserves_drumset_bindings(self):
        doc = _doc(
            '<part id="P1"><measure number="1">'
            "<attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time>"
            "<clef><sign>G</sign><line>2</line></clef></attributes>"
            "<note><pitch><step>E</step><octave>4</octave></pitch><duration>16</duration><voice>1</voice><type>whole</type></note>"
            "</measure></part>"
            '<part id="P2"><measure number="1">'
            "<attributes><divisions>4</divisions><time><beats>4</beats><beat-type>4</beat-type></time>"
            "<clef><sign>percussion</sign></clef></attributes>"
            "<note><unpitched><display-step>C</display-step><display-octave>5</display-octave></unpitched>"
            "<duration>16</duration><voice>1</voice><type>whole</type></note>"
            "</measure></part>",
            part_ids=("P1", "P2"),
        )
        facts = {
            "parts": [
                {"part": "P1", "name": "原音吉他", "abbreviation": "Guit.", "instrument": "acoustic-guitar"},
                {"part": "P2", "name": "架子鼓", "abbreviation": "D. Set", "instrument": "drumset"},
            ]
        }
        report = run_pipeline(
            doc,
            Context(facts=facts),
            structural=STRUCTURAL_PASSES,
            inject=INJECT_PASSES,
            verifiers=VERIFIERS,
        )
        self.assertEqual(report.verifier, [])
        self.assertTrue(all(phase.stable for phase in report.phases))

        p1 = doc.root.find("part-list/score-part[@id='P1']")
        self.assertEqual(p1.findtext("part-name"), "原音吉他")
        self.assertEqual(p1.findtext("part-abbreviation"), "Guit.")
        self.assertEqual(p1.findtext("score-instrument/instrument-sound"), "pluck.guitar.acoustic")
        self.assertEqual(p1.findtext("midi-instrument/midi-program"), "26")
        self.assertEqual(p1.findtext("midi-instrument/midi-channel"), "1")

        p2 = doc.root.find("part-list/score-part[@id='P2']")
        self.assertEqual(p2.findtext("part-name"), "架子鼓")
        self.assertEqual(p2.findtext("part-abbreviation"), "D. Set")
        self.assertEqual(p2.findtext("midi-instrument/midi-channel"), "10")
        self.assertEqual(p2.findtext("midi-instrument/midi-unpitched"), "39")

        # Validate generated MusicXML against the W3C MusicXML 4.0 XSD when lxml is available.
        try:
            from lxml import etree
        except ImportError:
            etree = None
        if etree is not None:
            xsd = Path(__file__).parent / "fixtures" / "musicxml" / "sanity_schema.xsd"
            schema = etree.XMLSchema(etree.parse(str(xsd)))
            xml_doc = etree.fromstring(ElementTree.tostring(doc.root))
            self.assertTrue(schema.validate(xml_doc), schema.error_log)

    def test_parts_facts_validation_and_merge(self):
        good = {
            "producer": {"name": "agent-visual", "pages": [1]},
            "parts": [
                {
                    "part": "P1",
                    "name": "原音吉他",
                    "abbreviation": "Guit.",
                    "instrument": "acoustic-guitar",
                    "page": 1,
                    "bbox": [10, 20, 80, 50],
                    "evidence": "staff 1 label",
                }
            ],
        }
        self.assertEqual(validate_agent_facts(good, page_count=1), [])
        self.assertEqual(validate_facts(good), [])

        bad = {
            "parts": [
                {
                    "part": "P1",
                    "instrument": "nonexistent-kazoo",
                    "midi_program": 200,
                    "midi_channel": 99,
                    "page": 1,
                    "bbox": [10, 20, 80, 50],
                    "evidence": "staff 1",
                }
            ]
        }
        problems = validate_agent_facts(bad, page_count=1)
        self.assertTrue(any("unknown instrument" in p for p in problems))
        self.assertTrue(any("midi_program" in p for p in problems))
        self.assertTrue(any("midi_channel" in p for p in problems))

        merged = merge_agent_facts(
            [
                good,
                {
                    "producer": {"name": "agent-visual", "pages": [2]},
                    "parts": [
                        {
                            "part": "P1",
                            "name": "duplicate ignored",
                            "instrument": "piano",
                            "page": 2,
                            "bbox": [10, 20, 80, 50],
                            "evidence": "page 2",
                        },
                        {
                            "part": "P2",
                            "name": "架子鼓",
                            "instrument": "drumset",
                            "page": 2,
                            "bbox": [10, 60, 80, 90],
                            "evidence": "staff 2",
                        },
                    ],
                },
            ]
        )
        self.assertEqual([p["part"] for p in merged["parts"]], ["P1", "P2"])
        self.assertEqual(merged["parts"][0]["name"], "原音吉他")

    def test_lieder_ground_truth_corpus_converges_preserving_sounding_notes(self):
        corpus = Path(__file__).parent / "corpus" / "lieder"
        for name in ("aus_meinen_traenen", "die_wetterfahne", "der_lindenbaum", "gute_nacht"):
            doc = Document.load(corpus / name / "ground_truth.musicxml")
            before = snapshot(doc)
            report = run_pipeline(
                doc,
                Context(),
                structural=STRUCTURAL_PASSES,
                inject=INJECT_PASSES,
                verifiers=VERIFIERS,
            )
            self.assertTrue(all(phase.stable for phase in report.phases), name)
            self.assertEqual(check_sounding_notes_preserved(before, snapshot(doc)), [], name)
            if name in ("die_wetterfahne", "gute_nacht"):
                self.assertEqual(report.verifier, [], f"{name}: {report.verifier[:5]}")
            elif name == "aus_meinen_traenen":
                # Final bar m18 (1.5 beats) complements the 0.5-beat pickup bar m0 in 2/4.
                non_final = [v for v in report.verifier if v.measure != 18]
                self.assertEqual(non_final, [], f"{name}: {non_final[:5]}")


if __name__ == "__main__":
    unittest.main()
