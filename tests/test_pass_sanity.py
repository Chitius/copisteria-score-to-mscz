from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

import pytest

from scorepipe.core.document import Document
from scorepipe.core.pass_base import Context
from scorepipe.loader import load_pages
from scorepipe.passes import INJECT_PASSES, STRUCTURAL_PASSES
from scorepipe.sanity import PassContract, run_contract

PART = """
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>t</part-name></score-part></part-list>
  <part id="P1">{measures}</part>
</score-partwise>
"""


def note(step="C", octave=4, duration=16, *, voice="1", staff=None, chord=False, tie=None, rest=False, extra=""):
    chord_tag = "<chord/>" if chord else ""
    if rest:
        body = f"<rest/>{extra}"
    else:
        body = f"<pitch><step>{step}</step><octave>{octave}</octave></pitch>{extra}"
    staff_tag = f"<staff>{staff}</staff>" if staff else ""
    tie_tag = f'<tie type="{tie}"/>' if tie else ""
    return (
        f"<note>{chord_tag}{body}<duration>{duration}</duration>{tie_tag}"
        f"<voice>{voice}</voice>{staff_tag}</note>"
    )


def measure(number, body, *, time=True, clef=False, key=False):
    head = ""
    if time:
        head += "<time><beats>4</beats><beat-type>4</beat-type></time>"
    if clef:
        head += "<clef><sign>G</sign><line>2</line></clef>"
    if key:
        head += "<key><fifths>0</fifths></key>"
    attrs = f"<attributes><divisions>4</divisions>{head}</attributes>" if head else ""
    return f'<measure number="{number}">{attrs}{body}</measure>'


def build(measures):
    return Document(ElementTree.fromstring(PART.format(measures=measures)))


FIXTURES = Path(__file__).parent / "fixtures"


def simple():
    return build(measure(1, note("C")) + measure(2, note("D")))


def duplicate_ties():
    return build(measure(1, note("C", tie="start", extra='<tie type="start"/>')) + measure(2, note("D")))


def tie_slur_pair():
    return build(
        measure(
            1,
            note("C", duration=8, tie="start", extra='<notations><slur type="start" number="1"/></notations>')
            + note("C", duration=8, tie="stop", extra='<notations><slur type="stop" number="1"/></notations>'),
        )
        + measure(2, note("D"))
    )


def beam_run():
    notes = "".join(note(step, duration=2) for step in ("C", "D", "E", "F", "G", "A", "B", "C"))
    return build(measure(1, notes))


def adjacent_slurs():
    return build(
        measure(1, note("G", extra='<notations><slur type="start" number="1"/></notations>'))
        + measure(
            2,
            note(
                "A",
                extra='<notations><slur type="stop" number="1"/><slur type="start" number="2"/></notations>',
            ),
        )
        + measure(3, note("E", extra='<notations><slur type="stop" number="2"/></notations>'))
    )


def redundant_time():
    return build(measure(1, note("C")) + measure(2, note("D")))


def hidden_rest():
    return build(
        measure(1, note("C", duration=8) + note(duration=8, rest=True, extra='<display-step>C</display-step>'))
    )


def redundant_clef_key():
    return build(measure(1, note("C"), clef=True, key=True) + measure(2, note("D"), clef=True, key=True))


def duplicate_notes():
    return build(measure(1, note("C") + note("C", chord=True) + note("E", chord=True)))


def trailing_duplicate():
    return build(measure(1, note("C") + note("D", chord=True)) + measure(2, note("C")))


def overflow_duplicate():
    return build(
        measure(1, note("C") + note("D", chord=True) + note("E", duration=8, voice="2"))
        + measure(2, note("E", duration=8) + note("G", duration=8))
    )


def pickup():
    return build(measure(1, note("C", duration=8)) + measure(2, note("D")))


def empty_staff():
    return build(measure(1, note("C")) + measure(2, note("C", staff=2)))


def fragmented():
    return build(
        measure(1, note("C") + note("E", chord=True) + "<backup><duration>16</duration></backup>" + note("G", duration=8) + note("A", duration=8))
    )


def two_voices():
    return build(
        measure(1, note("C") + "<backup><duration>16</duration></backup>" + note("E", duration=16, voice="2"))
        + measure(2, note("D"))
    )


def redundant_voices():
    return build(
        measure(1, note("C") + "<backup><duration>16</duration></backup>" + note("C", duration=16, voice="2"))
        + measure(2, note("D"))
    )


def overflow():
    return build(
        measure(1, note("C", duration=20))
        + measure(2, note("D") + "<backup><duration>16</duration></backup>" + note("E", duration=16, voice="2"))
    )


def aligned():
    return build(
        measure(1, note("C") + note("E", chord=True) + "<backup><duration>16</duration></backup>" + note("G", duration=16, voice="2"))
    )


def odd_voices():
    return build(measure(1, note("C", voice="5") + note("D", chord=True, voice="5")))


def orphan_slur():
    return build(measure(1, note("C", extra='<notations><slur type="start" number="1"/></notations>')))


def short_voice():
    return build(
        measure(1, note("C", duration=8))
        + measure(2, note("D", duration=8))
        + measure(3, note("E"))
    )


def page_context(name):
    model = load_pages(FIXTURES / name)
    return model.document, Context(pages=model)


def pages_restore():
    doc, ctx = page_context("pages_restore")
    return ctx, doc


def pages_notation():
    doc, ctx = page_context("pages_notation")
    return ctx, doc


def facts_marks():
    return Context(facts={"marks": [{"measure": 1, "text": "Allegro", "tempo": 110}]}), simple()


def facts_credits():
    return Context(facts={"credits": [{"type": "title", "text": "Innocent"}]}), simple()


STRUCTURAL = {pass_obj.spec.name: pass_obj for pass_obj in STRUCTURAL_PASSES}
INJECT = {pass_obj.spec.name: pass_obj for pass_obj in INJECT_PASSES}

FACTORIES = {
    "dedupe_ties": duplicate_ties,
    "reconcile_tie_slurs": tie_slur_pair,
    "restore_beams": beam_run,
    "merge_adjacent_slurs": adjacent_slurs,
    "drop_redundant_time_signatures": redundant_time,
    "unhide_rests": hidden_rest,
    "drop_redundant_clefs": redundant_clef_key,
    "drop_redundant_key_signatures": redundant_clef_key,
    "drop_duplicate_notes": duplicate_notes,
    "drop_trailing_duplicate_measure": trailing_duplicate,
    "drop_overflow_duplicates": overflow_duplicate,
    "mark_pickup": pickup,
    "pad_empty_staves": empty_staff,
    "rebuild_voice_layers": fragmented,
    "merge_staff_voices": two_voices,
    "drop_redundant_voices": redundant_voices,
    "rebase_measures": overflow,
    "merge_aligned_voices": aligned,
    "normalize_voice_numbers": odd_voices,
    "sanitize_slurs": orphan_slur,
    "fill_short_measures": short_voice,
    "restore_page_ties": pages_restore,
    "restore_page_slurs": pages_restore,
    "restore_page_pedals": pages_restore,
    "restore_page_arpeggios": pages_notation,
    "restore_page_articulations": pages_notation,
    "restore_page_wedges": pages_notation,
    "apply_marks_facts": facts_marks,
    "apply_credits_facts": facts_credits,
}

# What each pass may change.  Everything not listed must be preserved; every pass must also be
# idempotent, keep chord/cursor structure valid, not turn healthy measures unhealthy and not add
# verifier violations.
CONTRACTS = {
    "dedupe_ties": PassContract("dedupe_ties"),
    "reconcile_tie_slurs": PassContract("reconcile_tie_slurs"),
    "restore_beams": PassContract("restore_beams"),
    "merge_adjacent_slurs": PassContract("merge_adjacent_slurs"),
    "drop_redundant_time_signatures": PassContract("drop_redundant_time_signatures"),
    "unhide_rests": PassContract("unhide_rests"),
    "drop_redundant_clefs": PassContract("drop_redundant_clefs"),
    "drop_redundant_key_signatures": PassContract("drop_redundant_key_signatures"),
    "drop_duplicate_notes": PassContract("drop_duplicate_notes", allows_remove_notes=True),
    "drop_trailing_duplicate_measure": PassContract("drop_trailing_duplicate_measure", allows_add_or_remove_measures=True),
    "drop_overflow_duplicates": PassContract("drop_overflow_duplicates", allows_remove_notes=True),
    "mark_pickup": PassContract("mark_pickup"),
    "pad_empty_staves": PassContract("pad_empty_staves", allows_add_notes=True, allows_voice_changes=True),
    "rebuild_voice_layers": PassContract(
        "rebuild_voice_layers",
        allows_add_notes=True,
        allows_remove_notes=True,
        allows_move_onsets=True,
        allows_retime=True,
        allows_voice_changes=True,
    ),
    "merge_staff_voices": PassContract(
        "merge_staff_voices",
        allows_add_notes=True,
        allows_remove_notes=True,
        allows_move_onsets=True,
        allows_retime=True,
        allows_voice_changes=True,
    ),
    "drop_redundant_voices": PassContract(
        "drop_redundant_voices", allows_remove_notes=True, allows_voice_changes=True
    ),
    "rebase_measures": PassContract(
        "rebase_measures",
        allows_add_notes=True,
        allows_remove_notes=True,
        allows_move_onsets=True,
        allows_retime=True,
        allows_voice_changes=True,
    ),
    "merge_aligned_voices": PassContract("merge_aligned_voices", allows_remove_notes=True, allows_voice_changes=True),
    "normalize_voice_numbers": PassContract("normalize_voice_numbers", allows_voice_changes=True),
    "sanitize_slurs": PassContract("sanitize_slurs"),
    "fill_short_measures": PassContract("fill_short_measures", allows_add_notes=True),
    "restore_page_ties": PassContract("restore_page_ties"),
    "restore_page_slurs": PassContract("restore_page_slurs"),
    "restore_page_pedals": PassContract("restore_page_pedals"),
    "restore_page_arpeggios": PassContract("restore_page_arpeggios"),
    "restore_page_articulations": PassContract("restore_page_articulations"),
    "restore_page_wedges": PassContract("restore_page_wedges"),
    "apply_marks_facts": PassContract("apply_marks_facts"),
    "apply_credits_facts": PassContract("apply_credits_facts"),
}

ALL_PASSES = {**STRUCTURAL, **INJECT}
MECHANICAL = {
    name: pass_obj
    for name, pass_obj in ALL_PASSES.items()
    if pass_obj.spec.kind == "mechanical"
}


def test_every_mechanical_pass_has_a_contract():
    assert set(MECHANICAL) == set(FACTORIES), "a registered mechanical pass has no sanity fixture"
    assert set(MECHANICAL) == set(CONTRACTS), "a registered mechanical pass has no declared contract"


@pytest.mark.parametrize("name", sorted(MECHANICAL))
def test_pass_obeys_contract(name):
    factory = FACTORIES[name]
    result = factory()
    if isinstance(result, tuple):
        ctx, doc = result
        factory = lambda: _rebuild(doc)
    else:
        doc = result
        ctx = Context()
    contract = CONTRACTS[name]
    report = run_contract(MECHANICAL[name], factory, contract, ctx)
    assert report.idempotent, f"{name} is not idempotent"
    assert not report.contract_violations, f"{name} broke its contract: {report.contract_violations}"
    assert not report.checker_violations, f"{name} failed sanity checks: {report.checker_violations}"


def _rebuild(doc):
    return Document(ElementTree.fromstring(ElementTree.tostring(doc.root)))
