"""Tests for :mod:`scorepipe.sanity`, the reusable per-pass sanity framework."""

from __future__ import annotations

from xml.etree import ElementTree
from xml.etree.ElementTree import Element, SubElement

import pytest

from scorepipe.core.document import Document
from scorepipe.core.pass_base import Context, Kind, PassResult, PassSpec, Phase
from scorepipe.sanity import (
    ADDED,
    CHANGED_IDENTITY,
    CHANGED_PITCH,
    MOVED,
    REMOVED,
    RETIMED,
    PassContract,
    check_idempotent,
    check_measure_health_preserved,
    check_no_new_verifier_violations,
    check_note_inventory_preserved,
    check_onsets_preserved,
    check_structure,
    diff_snapshots,
    run_contract,
    snapshot,
)

PART = """
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>t</part-name></score-part></part-list>
  <part id="P1">{measures}</part>
</score-partwise>
"""


# ---------------------------------------------------------------------------
# fixtures as plain strings
# ---------------------------------------------------------------------------


def note(
    step: str = "C",
    duration: int = 4,
    *,
    octave: int = 4,
    alter: int | float | None = None,
    voice: str = "1",
    staff: str | None = None,
    chord: bool = False,
    rest: bool = False,
    note_type: str | None = None,
    tie_start: bool = False,
    tie_stop: bool = False,
    hidden: bool = False,
) -> str:
    """A MusicXML note body.  ``duration`` is in divisions (4 per quarter)."""
    attribute = ' print-object="no"' if hidden else ""
    head = f"<note{attribute}>"
    if chord:
        head += "<chord/>"
    if rest:
        pitch = "<rest/>"
    else:
        pitch = f"<pitch><step>{step}</step>"
        if alter is not None:
            pitch += f"<alter>{alter}</alter>"
        pitch += f"<octave>{octave}</octave></pitch>"
    body = f"<duration>{duration}</duration>"
    if tie_start:
        body += '<tie type="start"/>'
    if tie_stop:
        body += '<tie type="stop"/>'
    if staff is not None:
        body += f"<staff>{staff}</staff>"
    body += f"<voice>{voice}</voice>"
    if note_type is not None:
        body += f"<type>{note_type}</type>"
    return f"{head}{pitch}{body}</note>"


def measure(
    number: int = 1,
    body: str = "",
    *,
    time: bool = True,
    implicit: bool = False,
) -> str:
    attributes = "<attributes><divisions>4</divisions>"
    if time:
        attributes += "<time><beats>4</beats><beat-type>4</beat-type></time>"
    attributes += "</attributes>"
    implicit_attribute = ' implicit="yes"' if implicit else ""
    return f'<measure number="{number}"{implicit_attribute}>{attributes}{body}</measure>'


def document(measures: str) -> Document:
    return Document(ElementTree.fromstring(PART.format(measures=measures)))


def fresh(measures: str):
    return lambda: Document(ElementTree.fromstring(PART.format(measures=measures)))


# ---------------------------------------------------------------------------
# fake passes
# ---------------------------------------------------------------------------


class NoOpPass:
    spec = PassSpec(name="noop", phase=Phase.STRUCTURAL, kind=Kind.MECHANICAL)

    def run(self, doc: Document, ctx: Context) -> PassResult:
        return PassResult(changed=0)


def _append_chord_d(doc: Document) -> None:
    first = doc.measures()[0]
    element = Element("note")
    SubElement(element, "chord")
    pitch = SubElement(element, "pitch")
    SubElement(pitch, "step").text = "D"
    SubElement(pitch, "octave").text = "4"
    SubElement(element, "duration").text = "16"
    SubElement(element, "staff").text = "1"
    SubElement(element, "voice").text = "1"
    first.append(element)


class AddChordNoteOncePass:
    """A pass that adds a chord tone exactly once: contract violation, idempotent."""

    spec = PassSpec(name="add_chord_note_once", phase=Phase.STRUCTURAL, kind=Kind.MECHANICAL)

    def run(self, doc: Document, ctx: Context) -> PassResult:
        first = doc.measures()[0]
        if any(note.findtext("pitch/step") == "D" for note in first.iter("note")):
            return PassResult(changed=0)
        _append_chord_d(doc)
        return PassResult(changed=1)


class AddChordNoteEachRunPass:
    """A deliberately non-idempotent pass: every run appends another note."""

    spec = PassSpec(name="add_chord_note_each_run", phase=Phase.STRUCTURAL, kind=Kind.MECHANICAL)

    def run(self, doc: Document, ctx: Context) -> PassResult:
        _append_chord_d(doc)
        return PassResult(changed=1)


class AddRestEachRunPass:
    """A deliberately non-idempotent pass that also grows the measure."""

    spec = PassSpec(name="add_rest_each_run", phase=Phase.STRUCTURAL, kind=Kind.MECHANICAL)

    def run(self, doc: Document, ctx: Context) -> PassResult:
        first = doc.measures()[0]
        element = Element("note")
        SubElement(element, "rest")
        SubElement(element, "duration").text = "4"
        SubElement(element, "staff").text = "1"
        SubElement(element, "voice").text = "1"
        first.append(element)
        return PassResult(changed=1)


class SilentMutationPass(NoOpPass):
    """Mutates the tree but reports changed=0; idempotence must still catch it."""

    spec = PassSpec(name="silent_mutation", phase=Phase.STRUCTURAL, kind=Kind.MECHANICAL)

    def run(self, doc: Document, ctx: Context) -> PassResult:
        _append_chord_d(doc)
        return PassResult(changed=0)


# ---------------------------------------------------------------------------
# snapshot / diff
# ---------------------------------------------------------------------------


def test_snapshot_captures_measure_and_note_fields():
    body = (
        note("C", 4, alter=1, note_type="quarter", tie_start=True, tie_stop=True)
        + note("E", 4, chord=True)
        + note(rest=True, duration=8, voice="2")
    )
    doc = document(measure(1, body) + measure(2, note("D", 16), time=False))
    snap = snapshot(doc)

    assert snap.measure_numbers == (1, 2), f"measure order lost: {snap.measure_numbers}"
    assert snap.measures[0].time_signature == (4.0, 4.0), "declared 4/4 was not captured"
    assert snap.measures[1].time_signature is None, "undeclared time signature should stay None"

    notes = snap.measures[0].notes
    assert len(notes) == 3, f"expected three note occurrences, got {len(notes)}"
    first = notes[0]
    assert (first.staff, first.voice, first.rest) == ("1", "1", False), (
        f"staff/voice/rest wrong: {first}"
    )
    assert (first.step, first.alter, first.octave) == ("C", 1.0, 4), (
        f"pitch fields wrong: {first}"
    )
    assert first.pitch == "C#4", f"pitch name wrong: {first.pitch}"
    assert (first.onset, first.duration) == (0.0, 1.0), (
        f"beats wrong: onset={first.onset}, duration={first.duration}"
    )
    assert first.chord is False, "base note marked as chord"
    assert first.type == "quarter", f"type not captured: {first.type}"
    assert first.tie_start and first.tie_stop, "tie start/stop not captured"

    chord_note = notes[1]
    assert chord_note.chord is True, "chord flag not captured"
    assert chord_note.onset == 0.0, "chord tone should share the base onset"

    rest_note = notes[2]
    assert rest_note.rest is True, "rest flag not captured"
    assert rest_note.pitch is None, f"rest should have no pitch, got {rest_note.pitch}"


def test_snapshot_measure_lookup():
    snap = snapshot(document(measure(1, note("C", 16)) + measure(5, note("D", 16))))
    assert snap.measure(5).number == 5, "measure lookup returned the wrong measure"
    with pytest.raises(KeyError):
        snap.measure(2)


def test_diff_noop_is_empty():
    before = snapshot(document(measure(1, note("C", 16))))
    after = snapshot(document(measure(1, note("C", 16))))
    diff = diff_snapshots(before, after)
    assert diff.is_empty, f"identical scores produced changes: {diff}"
    assert diff.same_note_identity, "identical scores should preserve note identity"


def test_diff_reports_added_note():
    before = snapshot(document(measure(1, note("C", 16))))
    after = snapshot(document(measure(1, note("C", 16) + note("D", 16))))
    diff = diff_snapshots(before, after)
    assert len(diff.added_notes) == 1, f"expected one added note: {diff.added_notes}"
    change = diff.added_notes[0]
    assert change.kind == ADDED, f"wrong kind: {change.kind}"
    assert change.pitch == "D4", f"wrong added pitch: {change.pitch}"
    assert diff.removed_notes == [], f"unexpected removals: {diff.removed_notes}"


def test_diff_reports_removed_note():
    before = snapshot(document(measure(1, note("C", 16) + note("D", 16))))
    after = snapshot(document(measure(1, note("C", 16))))
    diff = diff_snapshots(before, after)
    assert len(diff.removed_notes) == 1, f"expected one removed note: {diff.removed_notes}"
    change = diff.removed_notes[0]
    assert change.kind == REMOVED, f"wrong kind: {change.kind}"
    assert change.pitch == "D4", f"wrong removed pitch: {change.pitch}"
    assert diff.added_notes == [], f"unexpected additions: {diff.added_notes}"


def test_diff_reports_moved_onset():
    before = snapshot(document(measure(1, note("C", 4))))
    after = snapshot(
        document(measure(1, '<forward><duration>4</duration></forward>' + note("C", 4)))
    )
    diff = diff_snapshots(before, after)
    assert len(diff.moved_onsets) == 1, f"expected one moved onset: {diff.moved_onsets}"
    change = diff.moved_onsets[0]
    assert change.kind == MOVED, f"wrong kind: {change.kind}"
    assert change.before.onset == 0.0 and change.after.onset == 1.0, (
        f"wrong onsets: {change.before.onset} -> {change.after.onset}"
    )
    assert not diff.same_note_identity, "moving a note must break identity"
    assert diff.retimed_notes == [], f"unexpected retime: {diff.retimed_notes}"
    assert diff.changed_pitches == [], f"unexpected pitch change: {diff.changed_pitches}"


def test_diff_reports_retimed_note():
    before = snapshot(document(measure(1, note("C", 4))))
    after = snapshot(document(measure(1, note("C", 8))))
    diff = diff_snapshots(before, after)
    assert len(diff.retimed_notes) == 1, f"expected one retime: {diff.retimed_notes}"
    change = diff.retimed_notes[0]
    assert change.kind == RETIMED, f"wrong kind: {change.kind}"
    assert change.before.duration == 1.0 and change.after.duration == 2.0, (
        f"wrong durations: {change.before.duration} -> {change.after.duration}"
    )
    assert diff.same_note_identity, "retiming must not move the note"
    assert diff.added_notes == [] and diff.removed_notes == [], "retime should not add/remove"


def test_diff_reports_changed_pitch():
    before = snapshot(document(measure(1, note("C", 4))))
    after = snapshot(document(measure(1, note("D", 4))))
    diff = diff_snapshots(before, after)
    assert len(diff.changed_pitches) == 1, f"expected one pitch change: {diff.changed_pitches}"
    change = diff.changed_pitches[0]
    assert change.kind == CHANGED_PITCH, f"wrong kind: {change.kind}"
    assert change.before.pitch == "C4" and change.after.pitch == "D4", (
        f"wrong pitches: {change.before.pitch} -> {change.after.pitch}"
    )
    assert diff.same_note_identity, "a same-slot pitch change keeps staff/voice/onset"
    assert diff.added_notes == [] and diff.removed_notes == [], "pitch change must not add/remove"


def test_diff_reports_added_and_removed_measures():
    before = snapshot(document(measure(1, note("C", 16))))
    after = snapshot(document(measure(1, note("C", 16)) + measure(2, note("D", 16))))
    added = diff_snapshots(before, after)
    assert added.added_measures == [2], f"wrong added measures: {added.added_measures}"
    assert added.removed_measures == [], f"wrong removed measures: {added.removed_measures}"

    removed = diff_snapshots(after, before)
    assert removed.removed_measures == [2], f"wrong removed measures: {removed.removed_measures}"
    assert removed.added_measures == [], f"wrong added measures: {removed.added_measures}"


def test_diff_reports_voice_count_change():
    before = snapshot(document(measure(1, note("C", 16))))
    after = snapshot(
        document(
            measure(
                1,
                note("C", 16)
                + "<backup><duration>16</duration></backup>"
                + note("E", 16, voice="2"),
            )
        )
    )
    diff = diff_snapshots(before, after)
    assert len(diff.voice_count_changes) == 1, (
        f"expected one voice-count change: {diff.voice_count_changes}"
    )
    change = diff.voice_count_changes[0]
    assert (change.measure, change.staff, change.old, change.new) == (1, "1", 1, 2), (
        f"wrong voice-count change: {change}"
    )


def test_diff_reports_identity_change_without_voice_count_change():
    before = snapshot(document(measure(1, note("C", 16, voice="1"))))
    after = snapshot(document(measure(1, note("C", 16, voice="2"))))
    diff = diff_snapshots(before, after)
    assert len(diff.identity_changes) == 1, (
        f"expected one identity change: {diff.identity_changes}"
    )
    change = diff.identity_changes[0]
    assert change.kind == CHANGED_IDENTITY, f"wrong kind: {change.kind}"
    assert not diff.same_note_identity, "a voice reassignment must break identity"
    assert diff.voice_count_changes == [], "voice count is still one; it must not be reported"
    assert diff.added_notes == [] and diff.removed_notes == [], "identity change is not add/remove"


# ---------------------------------------------------------------------------
# PassContract
# ---------------------------------------------------------------------------


def test_contract_strict_rejects_added_note():
    before = snapshot(document(measure(1, note("C", 16))))
    after = snapshot(document(measure(1, note("C", 16) + note("D", 16))))
    violations = PassContract("strict").violations(before, after)
    assert violations, "strict contract accepted an added note"
    assert "m1" in violations[0] and "D4" in violations[0], (
        f"violation lacks measure/pitch detail: {violations[0]}"
    )
    assert "added" in violations[0], f"violation does not say added: {violations[0]}"


def test_contract_strict_rejects_removed_note():
    before = snapshot(document(measure(1, note("C", 16) + note("D", 16))))
    after = snapshot(document(measure(1, note("C", 16))))
    violations = PassContract("strict").violations(before, after)
    assert violations, "strict contract accepted a removed note"
    assert "removed" in violations[0] and "D4" in violations[0], (
        f"violation lacks removed pitch detail: {violations[0]}"
    )


def test_contract_strict_rejects_moved_onset():
    before = snapshot(document(measure(1, note("C", 4))))
    after = snapshot(
        document(measure(1, '<forward><duration>4</duration></forward>' + note("C", 4)))
    )
    violations = PassContract("strict").violations(before, after)
    assert violations, "strict contract accepted a moved onset"
    assert "onset 0 -> 1" in violations[0], f"violation lacks onset transition: {violations[0]}"


def test_contract_strict_rejects_retime():
    before = snapshot(document(measure(1, note("C", 4))))
    after = snapshot(document(measure(1, note("C", 8))))
    violations = PassContract("strict").violations(before, after)
    assert violations, "strict contract accepted a duration change"
    assert "duration 1 -> 2" in violations[0], (
        f"violation lacks duration transition: {violations[0]}"
    )


def test_contract_strict_rejects_pitch_change():
    before = snapshot(document(measure(1, note("C", 4))))
    after = snapshot(document(measure(1, note("D", 4))))
    violations = PassContract("strict").violations(before, after)
    assert violations, "strict contract accepted a pitch change"
    assert "pitch C4 -> D4" in violations[0], f"violation lacks pitches: {violations[0]}"


def test_contract_strict_rejects_added_measure():
    before = snapshot(document(measure(1, note("C", 16))))
    after = snapshot(document(measure(1, note("C", 16)) + measure(2, note("D", 16))))
    violations = PassContract("strict").violations(before, after)
    assert any("m2 added" in violation for violation in violations), (
        f"strict contract accepted an added measure: {violations}"
    )


def test_contract_strict_rejects_voice_change():
    before = snapshot(document(measure(1, note("C", 16, voice="1"))))
    after = snapshot(document(measure(1, note("C", 16, voice="2"))))
    violations = PassContract("strict").violations(before, after)
    assert violations, "strict contract accepted a voice reassignment"
    assert "staff/voice 1/1 -> 1/2" in violations[0], (
        f"violation lacks staff/voice detail: {violations[0]}"
    )


@pytest.mark.parametrize(
    ("flag", "before_body", "after_body"),
    [
        ("allows_add_notes", note("C", 16), note("C", 16) + note("D", 16)),
        ("allows_remove_notes", note("C", 16) + note("D", 16), note("C", 16)),
        (
            "allows_move_onsets",
            note("C", 4),
            '<forward><duration>4</duration></forward>' + note("C", 4),
        ),
        ("allows_retime", note("C", 4), note("C", 8)),
        ("allows_change_pitch", note("C", 4), note("D", 4)),
        ("allows_voice_changes", note("C", 16, voice="1"), note("C", 16, voice="2")),
    ],
)
def test_contract_flag_suppresses_matching_violation(flag, before_body, after_body):
    before = snapshot(document(measure(1, before_body)))
    after = snapshot(document(measure(1, after_body)))
    contract = PassContract("relaxed", **{flag: True})
    violations = contract.violations(before, after)
    assert violations == [], f"{flag} should allow the change, got {violations}"


def test_contract_allows_add_or_remove_measures():
    before = snapshot(document(measure(1, note("C", 16))))
    after = snapshot(document(measure(1, note("C", 16)) + measure(2, note("D", 16))))
    contract = PassContract("measure-relaxed", allows_add_or_remove_measures=True)
    assert contract.violations(before, after) == [], "measure flag did not allow an added measure"


# ---------------------------------------------------------------------------
# checkers
# ---------------------------------------------------------------------------


def test_check_structure_clean():
    doc = document(measure(1, note("C", 16)))
    messages = check_structure(doc, Context())
    assert messages == [], f"clean score reported structural problems: {messages}"


def test_check_structure_reports_orphan_chord():
    doc = document(measure(1, note("C", 16, chord=True)))
    messages = check_structure(doc, Context())
    assert messages, "an orphan <chord/> was not reported"
    assert "orphan-chord" in messages[0], f"missing orphan-chord code: {messages[0]}"
    assert "m1" in messages[0], f"missing measure number: {messages[0]}"


def test_check_structure_reports_negative_cursor():
    doc = document(measure(1, "<backup><duration>8</duration></backup>"))
    messages = check_structure(doc, Context())
    assert any("negative-cursor" in message for message in messages), (
        f"negative cursor was not reported: {messages}"
    )


def test_check_measure_health_preserved_flags_new_short_measure():
    before = document(measure(1, note("C", 16)))
    after = document(measure(1, note("C", 8)))
    messages = check_measure_health_preserved(before, after, Context())
    assert messages, "a newly short measure was accepted"
    assert "measure-length" in messages[0] and "m1" in messages[0], (
        f"measure-length detail missing: {messages[0]}"
    )


def test_check_measure_health_preserved_tolerates_existing_violation():
    before = document(measure(1, note("C", 8)))
    after = document(measure(1, note("C", 8)))
    messages = check_measure_health_preserved(before, after, Context())
    assert messages == [], f"an existing short measure should be tolerated, got {messages}"


def test_check_measure_health_preserved_allows_fixing_an_existing_violation():
    before = document(measure(1, note("C", 8)))  # 2 beats: already bad
    after = document(measure(1, note("C", 16)))  # 4 beats: fixed
    messages = check_measure_health_preserved(before, after, Context())
    assert messages == [], f"fixing a measure must not be reported as new damage, got {messages}"


def test_check_measure_health_preserved_flags_changed_violation_detail():
    before = document(measure(1, note("C", 8)))  # 2 beats
    after = document(measure(1, note("C", 4)))  # 1 beat
    messages = check_measure_health_preserved(before, after, Context())
    assert messages, "a worse measure-length violation was not reported as new"
    assert "1 beats" in messages[0], f"detail lacks the new length: {messages[0]}"


def test_check_no_new_verifier_violations_flags_hidden_rest():
    before = document(measure(1, note("C", 16)))
    after = document(measure(1, note(rest=True, duration=16, hidden=True)))
    messages = check_no_new_verifier_violations(before, after, Context())
    assert messages, "a new hidden rest was not reported"
    assert "hidden-rest" in messages[0] and "m1" in messages[0], (
        f"hidden-rest detail missing: {messages[0]}"
    )


def test_check_no_new_verifier_violations_tolerates_existing():
    before = document(measure(1, note(rest=True, duration=16, hidden=True)))
    after = document(measure(1, note(rest=True, duration=16, hidden=True)))
    messages = check_no_new_verifier_violations(before, after, Context())
    assert messages == [], f"an existing violation should be tolerated, got {messages}"


def test_check_no_new_verifier_violations_allows_fixing_an_existing_violation():
    before = document(measure(1, note(rest=True, duration=16, hidden=True)))
    after = document(measure(1, note("C", 16)))
    messages = check_no_new_verifier_violations(before, after, Context())
    assert messages == [], f"fixing an existing hidden rest must be allowed, got {messages}"


def test_check_no_new_verifier_violations_accepts_explicit_empty_list():
    before = document(measure(1, note("C", 16)))
    after = document(measure(1, note("C", 8)))
    messages = check_no_new_verifier_violations(before, after, Context(), verifiers=[])
    assert messages == [], f"no verifiers should mean no messages, got {messages}"


def test_check_note_inventory_preserved_reports_added_pitch():
    before = snapshot(document(measure(1, note("C", 16))))
    after = snapshot(document(measure(1, note("C", 16) + note("D", 16))))
    messages = check_note_inventory_preserved(before, after)
    assert len(messages) == 1, f"expected one inventory change: {messages}"
    assert "D4" in messages[0] and "added" in messages[0], (
        f"added pitch detail missing: {messages[0]}"
    )


def test_check_note_inventory_preserved_reports_removed_pitch():
    before = snapshot(document(measure(1, note("C", 16) + note("D", 16))))
    after = snapshot(document(measure(1, note("C", 16))))
    messages = check_note_inventory_preserved(before, after)
    assert len(messages) == 1, f"expected one inventory change: {messages}"
    assert "D4" in messages[0] and "removed" in messages[0], (
        f"removed pitch detail missing: {messages[0]}"
    )


def test_check_note_inventory_preserved_ignores_rests():
    before = snapshot(document(measure(1, note("C", 16))))
    after = snapshot(document(measure(1, note("C", 16) + note(rest=True, duration=4))))
    messages = check_note_inventory_preserved(before, after)
    assert messages == [], f"rests must not count as pitch inventory, got {messages}"


def test_check_onsets_preserved_reports_moved_pitch():
    before = snapshot(document(measure(1, note("C", 4))))
    after = snapshot(
        document(measure(1, '<forward><duration>4</duration></forward>' + note("C", 4)))
    )
    messages = check_onsets_preserved(before, after)
    assert len(messages) == 1, f"expected one moved onset: {messages}"
    assert "onset" in messages[0] and "C4" in messages[0], (
        f"onset detail missing: {messages[0]}"
    )


def test_check_onsets_preserved_ignores_retime():
    before = snapshot(document(measure(1, note("C", 4))))
    after = snapshot(document(measure(1, note("C", 8))))
    messages = check_onsets_preserved(before, after)
    assert messages == [], f"retiming must not look like an onset move, got {messages}"


# ---------------------------------------------------------------------------
# idempotence and the contract runner
# ---------------------------------------------------------------------------


def test_check_idempotent_accepts_noop():
    messages = check_idempotent(NoOpPass(), document(measure(1, note("C", 16))), Context())
    assert messages == [], f"a no-op pass should be idempotent, got {messages}"


def test_check_idempotent_flags_non_idempotent_pass():
    messages = check_idempotent(
        AddRestEachRunPass(), document(measure(1, note("C", 16))), Context()
    )
    assert messages, "a pass that changes the score on every run was accepted"
    assert "add_rest_each_run" in messages[0], f"pass name missing: {messages[0]}"
    assert "not idempotent" in messages[0], f"idempotence detail missing: {messages[0]}"


def test_run_contract_clean_pass_is_ok():
    report = run_contract(NoOpPass(), fresh(measure(1, note("C", 16))), PassContract("strict"))
    assert report.pass_name == "noop", f"wrong pass name: {report.pass_name}"
    assert report.changed == 0, f"no-op reported changes: {report.changed}"
    assert report.contract_violations == [], (
        f"no-op broke its contract: {report.contract_violations}"
    )
    assert report.checker_violations == [], (
        f"no-op failed the checkers: {report.checker_violations}"
    )
    assert report.idempotent is True, "no-op should be idempotent"
    assert report.ok, "a clean no-op report should be ok"


def test_run_contract_strict_contract_flags_note_addition():
    report = run_contract(
        AddChordNoteOncePass(),
        fresh(measure(1, note("C", 16))),
        PassContract("strict"),
    )
    assert report.changed == 1, f"fake pass should report one change, got {report.changed}"
    assert report.contract_violations, "strict contract missed the added note"
    assert "added" in report.contract_violations[0] and "D4" in report.contract_violations[0], (
        f"contract message lacks the addition: {report.contract_violations[0]}"
    )
    assert report.idempotent, "the once-only fake pass should be idempotent"
    assert not report.ok, "a contract violation must make the report not ok"


def test_run_contract_permissive_contract_accepts_note_addition():
    report = run_contract(
        AddChordNoteOncePass(),
        fresh(measure(1, note("C", 16))),
        PassContract("permissive", allows_add_notes=True),
    )
    assert report.contract_violations == [], (
        f"permissive contract rejected an allowed add: {report.contract_violations}"
    )
    assert report.checker_violations == [], (
        f"adding a chord tone should keep the score healthy: {report.checker_violations}"
    )
    assert report.ok, "an allowed, healthy, idempotent pass should be ok"


def test_run_contract_marks_non_idempotent_pass():
    report = run_contract(
        AddChordNoteEachRunPass(),
        fresh(measure(1, note("C", 16))),
        PassContract("permissive", allows_add_notes=True),
    )
    assert report.idempotent is False, "a pass that appends on every run was called idempotent"
    assert any("not idempotent" in message for message in report.checker_violations), (
        f"idempotence message missing from checker violations: {report.checker_violations}"
    )
    assert not report.ok, "a non-idempotent pass must make the report not ok"


def test_run_contract_uses_three_fresh_documents():
    calls: list[Document] = []

    def factory() -> Document:
        built = document(measure(1, note("C", 16)))
        calls.append(built)
        return built

    report = run_contract(NoOpPass(), factory, PassContract("strict"))
    assert len(calls) == 3, (
        f"expected three fresh documents (before/after/idempotence), got {len(calls)}"
    )
    assert len({id(document_) for document_ in calls}) == 3, (
        "doc_factory must return a distinct Document object on every call"
    )
    assert report.ok, "clean run with a three-call factory should be ok"


def test_check_idempotent_detects_silent_state_mutation():
    messages = check_idempotent(
        SilentMutationPass(), document(measure(1, note("C", 16))), Context()
    )
    assert messages, "a pass that mutates while reporting changed=0 was called idempotent"
    assert "silent_mutation" in messages[0]


def test_check_no_new_verifier_violations_catches_a_second_identical_violation():
    before = document(measure(1, note(rest=True, duration=16, hidden=True)))
    after = document(
        measure(
            1,
            note(rest=True, duration=16, hidden=True)
            + note(rest=True, duration=16, hidden=True),
        )
    )
    messages = check_no_new_verifier_violations(before, after, Context())
    assert messages, "a second identical hidden-rest violation in the same measure was ignored"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))

def test_pitch_set_preserved_flags_a_lost_chord_member():
    from scorepipe.sanity import check_pitch_set_preserved

    before = document(measure(1, note("C") + note("E", chord=True)))
    after = document(measure(1, note("C")))
    messages = check_pitch_set_preserved(before, after)
    assert messages and "E" in messages[0]
