from __future__ import annotations

import unittest
from xml.etree import ElementTree

from scorepipe.core.mscx import MsxcDocument
from scorepipe.core.mscx_invariants import MSCX_VERIFIERS
from scorepipe.core.pass_base import Context, Phase
from scorepipe.core.pipeline import run_phase
from scorepipe.passes import DISPLAY_PASSES

MSCX = """
<museScore version="4.4">
  <Score>
    <Staff id="1">
      <Measure>
        <voice>
          <Chord><durationType>quarter</durationType><Note><pitch>60</pitch></Note></Chord>
        </voice>
        <voice>
          <Rest><visible>0</visible><durationType>measure</durationType></Rest>
        </voice>
        <voice>
          <StaffText><text>rit.</text></StaffText>
          <Rest><durationType>measure</durationType></Rest>
        </voice>
      </Measure>
      <Measure>
        <voice>
          <Chord><durationType>whole</durationType><Note><pitch>60</pitch></Note></Chord>
        </voice>
      </Measure>
    </Staff>
  </Score>
</museScore>
"""


def build() -> MsxcDocument:
    return MsxcDocument(ElementTree.fromstring(MSCX))


class DisplayPassesTest(unittest.TestCase):
    def test_display_phase_never_drops_a_chord_pitch(self):
        from scorepipe.sanity import check_mscx_pitched_notes_preserved

        reference = build()
        worked = build()
        run_phase(worked, DISPLAY_PASSES, Context(), Phase.DISPLAY)
        self.assertEqual(check_mscx_pitched_notes_preserved(reference, worked), [])

    def test_mscx_pitch_checker_flags_a_lost_chord_note(self):
        from scorepipe.sanity import check_mscx_pitched_notes_preserved

        reference = build()
        worked = build()
        staff = worked.staves()[0]
        staff.findall("Measure")[1].find("voice/Chord").remove(
            staff.findall("Measure")[1].find("voice/Chord/Note")
        )
        messages = check_mscx_pitched_notes_preserved(reference, worked)
        self.assertEqual(len(messages), 1, messages)
        self.assertIn("chord note lost", messages[0])
    DISPLAY_MECHANICAL = {
        "drop_text_voice_rests",
        "unhide_real_rests",
        "drop_padding_voices",
        "canonical_voice_order",
        "drop_secondary_voice_rests",
        "normalize_range_spanners",
        "hide_pickup_leading_rest",
        "split_chord_fragments",
        "restore_mscx_ties",
        "dedupe_pedal_spanners",
        "dedupe_text_objects",
        "merge_text_voices",
        "drop_empty_voices",
        "upgrade_tempo_texts",
        "upgrade_gradual_texts",
        "apply_text_facts_style",
        "apply_credits_display",
    }

    def test_display_mechanical_pass_inventory_is_explicit(self):
        actual = {
            one_pass.spec.name
            for one_pass in DISPLAY_PASSES
            if one_pass.spec.kind.value == "mechanical"
        }
        self.assertEqual(actual, self.DISPLAY_MECHANICAL)

    def test_each_display_mechanical_pass_is_idempotent(self):
        for one_pass in DISPLAY_PASSES:
            if one_pass.spec.kind.value != "mechanical":
                continue
            with self.subTest(pass_name=one_pass.spec.name):
                doc = build()
                one_pass.run(doc, Context())
                after_first = doc.state_hash()
                result = one_pass.run(doc, Context())
                self.assertEqual(result.changed, 0)
                self.assertEqual(doc.state_hash(), after_first)

    def test_padding_voice_is_dropped(self):
        doc = build()
        run_phase(doc, DISPLAY_PASSES, Context(), Phase.DISPLAY)
        voices = doc.staves()[0].findall("Measure")[0].findall("voice")
        self.assertEqual(len(voices), 1, "padding/text voice should be merged away")
        self.assertTrue(voices[0].findall("Chord"))

    def test_text_voice_loses_its_rest(self):
        doc = build()
        run_phase(doc, DISPLAY_PASSES, Context(), Phase.DISPLAY)
        measure = doc.staves()[0].findall("Measure")[0]
        text_voices = [voice for voice in measure.findall("voice") if voice.findall("StaffText")]
        self.assertEqual(len(text_voices), 1)
        self.assertTrue(text_voices[0].findall("Chord"))
        self.assertEqual(text_voices[0].findall("Rest"), [])

    def test_lone_text_voice_keeps_its_measure_rest(self):
        # Suzume m1: one voice holds Tempo + Dynamic + a whole-measure rest; there is no chord
        # voice to carry the measure, so dropping the rest left a 0-length bar.
        doc = MsxcDocument(
            ElementTree.fromstring(
                """
                <museScore><Score><Staff id="1"><Measure>
                  <voice>
                    <Tempo><tempo>1.3</tempo><text>q = 78</text></Tempo>
                    <Dynamic><subtype>mf</subtype></Dynamic>
                    <Rest><durationType>measure</durationType><duration>1/1</duration></Rest>
                  </voice>
                </Measure></Staff></Score></museScore>
                """
            )
        )
        run_phase(doc, DISPLAY_PASSES, Context(), Phase.DISPLAY)
        rest = doc.staves()[0].findall("Measure")[0].find("voice/Rest")
        self.assertIsNotNone(rest)
        self.assertEqual(rest.findtext("durationType"), "measure")

    def test_real_rest_is_unhidden(self):
        doc = MsxcDocument(
            ElementTree.fromstring(
                """
                <museScore><Score><Staff id="1"><Measure>
                  <voice>
                    <Chord><durationType>half</durationType><Note><pitch>60</pitch></Note></Chord>
                    <Rest><visible>0</visible><durationType>half</durationType></Rest>
                  </voice>
                </Measure></Staff></Score></museScore>
                """
            )
        )
        run_phase(doc, DISPLAY_PASSES, Context(), Phase.DISPLAY)
        rest = doc.staves()[0].findall("Measure")[0].find("voice/Rest")
        self.assertIsNotNone(rest)
        self.assertIsNone(rest.find("visible"))

    def test_chord_voice_comes_first_and_loop_is_idempotent(self):
        doc = build()
        report = run_phase(doc, DISPLAY_PASSES, Context(), Phase.DISPLAY)
        self.assertTrue(report.stable)
        measure = doc.staves()[0].findall("Measure")[0]
        self.assertTrue(measure.findall("voice")[0].findall("Chord"))
        second = run_phase(doc, DISPLAY_PASSES, Context(), Phase.DISPLAY)
        self.assertEqual(second.changes, 0)
        for verifier in MSCX_VERIFIERS:
            if verifier.__name__ == "measure_lengths":
                continue
            self.assertEqual(verifier(doc, Context()), [], verifier.__name__)


if __name__ == "__main__":
    unittest.main()

class PaddingVoiceContentTest(unittest.TestCase):
    def test_spanner_only_voice_is_not_padding(self):
        doc = MsxcDocument(ElementTree.fromstring('''
          <museScore><Score><Staff id="1"><Measure>
            <voice><Chord><durationType>whole</durationType><Note><pitch>60</pitch></Note></Chord></voice>
            <voice><Spanner type="Pedal"><Pedal><beginText>Ped.</beginText></Pedal>
              <next><location><measures>1</measures></location></next></Spanner></voice>
          </Measure></Staff></Score></museScore>'''))
        run_phase(doc, DISPLAY_PASSES, Context(), Phase.DISPLAY)
        self.assertEqual(len(list(doc.root.iter('Spanner'))), 1)

    def test_barline_only_voice_keeps_its_barline(self):
        doc = MsxcDocument(ElementTree.fromstring('''
          <museScore><Score><Staff id="1"><Measure>
            <voice><Chord><durationType>whole</durationType><Note><pitch>60</pitch></Note></Chord></voice>
            <voice><BarLine><subtype>end</subtype></BarLine></voice>
          </Measure></Staff></Score></museScore>'''))
        run_phase(doc, DISPLAY_PASSES, Context(), Phase.DISPLAY)
        measure = doc.root.find('Score/Staff/Measure')
        self.assertEqual(len(measure.findall('voice')), 1)
        self.assertEqual(len(list(measure.iter('BarLine'))), 1)

    def test_measure_rest_voice_with_a_clef_is_padding(self):
        doc = MsxcDocument(ElementTree.fromstring('''
          <museScore><Score><Staff id="1"><Measure>
            <voice><Chord><durationType>whole</durationType><Note><pitch>60</pitch></Note></Chord></voice>
            <voice><Rest><durationType>measure</durationType></Rest>
              <Clef><concertClefType>G</concertClefType></Clef></voice>
          </Measure></Staff></Score></museScore>'''))
        run_phase(doc, DISPLAY_PASSES, Context(), Phase.DISPLAY)
        measure = doc.root.find('Score/Staff/Measure')
        self.assertEqual(len(measure.findall('voice')), 1)
        self.assertEqual(len(measure.findall('.//Rest')), 0)
        self.assertEqual(len(measure.findall('.//Clef')), 1)

    def test_secondary_voice_rests_become_gaps(self):
        doc = MsxcDocument(ElementTree.fromstring('''
          <museScore><Score><Staff id="1"><Measure>
            <voice><Chord><durationType>whole</durationType><Note><pitch>60</pitch></Note></Chord></voice>
            <voice>
              <Rest><durationType>quarter</durationType></Rest>
              <Chord><durationType>quarter</durationType><Note><pitch>67</pitch></Note></Chord>
              <Rest><durationType>half</durationType></Rest>
            </voice>
          </Measure></Staff></Score></museScore>'''))
        run_phase(doc, DISPLAY_PASSES, Context(), Phase.DISPLAY)
        measure = doc.root.find('Score/Staff/Measure')
        secondary = next(voice for voice in measure.findall('voice') if voice.find('.//Note[pitch="67"]') is not None)
        self.assertEqual(len(secondary.findall('Rest')), 0)
        self.assertEqual(secondary.find('location/fractions').text, '1/4')
        self.assertEqual(len(measure.findall('voice')), 2)
        again = run_phase(doc, DISPLAY_PASSES, Context(), Phase.DISPLAY)
        self.assertEqual(again.changes, 0)

    def test_secondary_voice_dotted_rest_becomes_an_exact_gap(self):
        doc = MsxcDocument(ElementTree.fromstring('''
          <museScore><Score><Staff id="1"><Measure>
            <voice><Chord><durationType>whole</durationType><Note><pitch>60</pitch></Note></Chord></voice>
            <voice>
              <Rest><dots>1</dots><durationType>quarter</durationType></Rest>
              <Chord><durationType>quarter</durationType><Note><pitch>67</pitch></Note></Chord>
            </voice>
          </Measure></Staff></Score></museScore>'''))
        run_phase(doc, DISPLAY_PASSES, Context(), Phase.DISPLAY)
        measure = doc.root.find("Score/Staff/Measure")
        secondary = next(
            voice for voice in measure.findall("voice")
            if voice.find('.//Note[pitch="67"]') is not None
        )
        self.assertEqual(secondary.find('location/fractions').text, '3/8')

    def test_padding_compaction_preserves_secondary_note_onsets(self):
        from scorepipe.core.musescore_ticks import voice_timeline
        from scorepipe.passes.mscx_display import compact_secondary_padding

        doc = MsxcDocument(ElementTree.fromstring('''
          <museScore><Score><Staff id="1"><Measure>
            <voice><Chord><durationType>whole</durationType><Note><pitch>60</pitch></Note></Chord></voice>
            <voice>
              <location><fractions>1/2</fractions></location>
              <Chord><durationType>quarter</durationType><Note><pitch>67</pitch></Note></Chord>
              <Rest><padding>1</padding><durationType>quarter</durationType><visible>0</visible></Rest>
            </voice>
          </Measure></Staff></Score></museScore>'''))
        secondary = doc.root.findall('Score/Staff/Measure/voice')[1]
        self.assertEqual(voice_timeline(secondary).items[0].start, 0.5)

        self.assertEqual(compact_secondary_padding(doc), 1)

        timeline = voice_timeline(secondary)
        self.assertEqual(timeline.items[0].start, 0.5)
        self.assertEqual(timeline.final, 1.0)
        self.assertEqual(timeline.locations, [0.5, 0.25])
        self.assertEqual(secondary.findall('Rest'), [])

    def test_range_spanner_carrier_voice_is_removed(self):
        doc = MsxcDocument(ElementTree.fromstring('''
          <museScore><Score><Staff id="1"><Measure>
            <voice><Chord><durationType>whole</durationType><Note><pitch>60</pitch></Note></Chord></voice>
            <voice>
              <Spanner type="HairPin"><prev><location><measures>-1</measures>
                <fractions>3/8</fractions></location></prev></Spanner>
              <Rest><visible>0</visible><durationType>measure</durationType><duration>4/4</duration></Rest>
            </voice>
          </Measure></Staff></Score></museScore>'''))
        run_phase(doc, DISPLAY_PASSES, Context(), Phase.DISPLAY)
        measure = doc.root.find('Score/Staff/Measure')
        self.assertEqual(len(measure.findall('voice')), 1)
        self.assertEqual(len(list(measure.iter('Spanner'))), 1)
        self.assertIsNotNone(measure.find('.//Note'))
        again = run_phase(doc, DISPLAY_PASSES, Context(), Phase.DISPLAY)
        self.assertEqual(again.changes, 0)


class InitialTimeSignatureTest(unittest.TestCase):
    """The display phase must not touch the initial time signature.

    MuseScore writes ``<visible>0</visible>`` for a MusicXML ``<time print-object="no">``, so an
    unprinted metre is already hidden.  Deleting a *printed* 4/4 is the one thing that cannot be
    recovered: Gurenge page 1 prints 4/4 and its first delivery had no time signature at all.
    """

    def _doc(self, beats: str, visible: bool = True) -> MsxcDocument:
        hidden = "" if visible else "<visible>0</visible>"
        return MsxcDocument(
            ElementTree.fromstring(
                "<museScore><Score><Staff id='1'><Measure><voice>"
                f"<TimeSig>{hidden}<sigN>{beats}</sigN><sigD>4</sigD></TimeSig>"
                "<Chord><durationType>measure</durationType><Note><pitch>60</pitch></Note></Chord>"
                "</voice></Measure></Staff></Score></museScore>"
            )
        )

    def test_a_printed_four_four_survives_the_display_phase(self):
        doc = self._doc("4")
        run_phase(doc, DISPLAY_PASSES, Context(), Phase.DISPLAY)
        self.assertEqual([ts.findtext("sigN") for ts in doc.root.iter("TimeSig")], ["4"])

    def test_a_hidden_initial_signature_stays_hidden(self):
        doc = self._doc("4", visible=False)
        run_phase(doc, DISPLAY_PASSES, Context(), Phase.DISPLAY)
        times = list(doc.root.iter("TimeSig"))
        self.assertEqual([ts.findtext("sigN") for ts in times], ["4"])
        self.assertEqual(times[0].findtext("visible"), "0")

    def test_a_three_four_signature_is_kept(self):
        doc = self._doc("3")
        run_phase(doc, DISPLAY_PASSES, Context(), Phase.DISPLAY)
        self.assertEqual([ts.findtext("sigN") for ts in doc.root.iter("TimeSig")], ["3"])
