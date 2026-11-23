"""Export the repaired MusicXML to MuseScore, then run the display passes on the result.

This is the missing link between the two IRs: the structural pipeline owns the MusicXML, MuseScore
converts it, and the display pipeline then fixes what the importer re-created (hidden rests, padding
voices, tempo text). The conversion is a boundary, not a pass, so it runs once between the phases.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .core.document import Document
from .core.mscz import MsczArchive
from .core.mscx_invariants import MSCX_VERIFIERS
from .core.pass_base import Context
from .core.pipeline import PhaseReport, RunReport, TraceEntry, run_display
from .passes import DISPLAY_PASSES, TRUNCATE_OVERFULL_MSCX
from .passes.mscx_display import compact_secondary_padding
from .passes.mscx_truncate import normalize_explicit_durations

COMMON_PATHS = (
    r"S:\Program Files\MuseScore 4\bin\MuseScore4.exe",
    r"C:\Program Files\MuseScore 4\bin\MuseScore4.exe",
    r"C:\Program Files\MuseScore 4\bin\MuseScore4.exe",
)


def find_musescore(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    from_env = os.environ.get("MSCORE") or os.environ.get("MUSESCORE")
    if from_env:
        return from_env
    found = shutil.which("MuseScore4") or shutil.which("mscore")
    if found:
        return found
    for candidate in COMMON_PATHS:
        if Path(candidate).is_file():
            return candidate
    raise RuntimeError("MuseScore not found: pass --musescore or set MSCORE")


def convert(musicxml: str | Path, mscz: str | Path, musescore: str | None = None) -> None:
    binary = find_musescore(musescore)
    destination = Path(mscz)
    destination.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [binary, "-f", "-o", str(destination), str(musicxml)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0 or not destination.is_file():
        raise RuntimeError(f"MuseScore conversion failed: {(completed.stderr or '').strip()[:500]}")


def export_and_display(
    document: Document,
    mscz_path: str | Path,
    ctx: Context,
    musescore: str | None = None,
    work_musicxml: str | Path | None = None,
) -> RunReport:
    """Write the MusicXML, convert it, run the display fixpoint and re-save the archive."""
    destination = Path(mscz_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    created_temp = False
    if work_musicxml:
        intermediate = Path(work_musicxml)
    else:
        fd, temp_name = tempfile.mkstemp(prefix=".scorepipe-", suffix=".musicxml", dir=destination.parent)
        os.close(fd)
        intermediate = Path(temp_name)
        created_temp = True
    document.save(intermediate)
    try:
        convert(intermediate, destination, musescore)
        archive = MsczArchive.open(destination)
        options = dict(ctx.options)
        options.setdefault("ties", extract_ties(document))
        options.setdefault("chord_fragments", extract_chord_fragments(document))
        display_ctx = Context(facts=dict(ctx.facts), options=options)
        display_passes = list(DISPLAY_PASSES)
        report = run_display(archive.document, display_ctx, display_passes, MSCX_VERIFIERS)
        if options.get("truncate_overfull"):
            before = archive.document.state_hash()
            notes: list[str] = []
            total_changed = 0
            rounds = 0
            unresolved = False
            last_changed = 0
            for round_number in range(1, 4):
                rounds = round_number
                result = TRUNCATE_OVERFULL_MSCX.run(archive.document, display_ctx)
                total_changed += result.changed
                last_changed = result.changed
                notes.extend(result.notes)
                unresolved = any(note.startswith("UNRESOLVED") for note in result.notes)
                if unresolved or not result.changed:
                    break
            normalized, canonical_notes = normalize_explicit_durations(archive.document)
            notes.extend(canonical_notes)
            unresolved = unresolved or any(
                note.startswith("UNRESOLVED") for note in canonical_notes
            )
            if normalized:
                notes.append(f"normalized {normalized} explicit duration(s)")
            compacted = compact_secondary_padding(archive.document)
            if compacted:
                notes.append(f"converted {compacted} secondary padding rest(s) to location offsets")
            if total_changed or notes:
                report.trace.append(
                    TraceEntry(
                        phase="display-final",
                        round=rounds,
                        pass_name=TRUNCATE_OVERFULL_MSCX.spec.name,
                        changed=total_changed,
                        hash_before=before[:12],
                        hash_after=archive.document.state_hash()[:12],
                        notes=notes,
                    )
                )
                report.phases.append(
                    PhaseReport(
                        phase="display-final",
                        rounds=rounds,
                        changes=total_changed,
                        stable=not unresolved and last_changed == 0,
                    )
                )
                report.verifier = [
                    violation for verifier in MSCX_VERIFIERS for violation in verifier(archive.document, display_ctx)
                ]
        archive.save(destination)
        return report
    finally:
        if created_temp:
            intermediate.unlink(missing_ok=True)


def extract_ties(document: Document) -> list[dict]:
    """Tie pairs as (measure, staff, pitch, onset); the importer can lose these on chords."""
    from .core.pairing import Endpoint, pair_endpoints

    endpoints: list[Endpoint] = []
    for number, measure in document.iter_measures():
        for event in document.events(measure):
            if event.rest:
                continue
            pitch = _midi(event.element)
            if pitch is None:
                continue
            for tie in event.element.findall("tie"):
                kind = tie.get("type")
                if kind not in ("start", "stop"):
                    continue
                endpoints.append(
                    Endpoint(
                        key=(event.staff, event.voice, pitch),
                        position=(number, round(event.onset, 4)),
                        kind=kind,
                        payload=(number, event.onset, pitch, event.staff),
                    )
                )
    pairs: list[dict] = []
    for start, stop in pair_endpoints(endpoints).pairs:
        start_measure, start_onset, _start_pitch, staff = start.payload
        stop_measure, stop_onset, pitch, _staff = stop.payload
        pairs.append(
            {
                "start_measure": start_measure,
                "start_onset": start_onset,
                "stop_measure": stop_measure,
                "stop_onset": stop_onset,
                "staff": staff,
                "pitch": pitch,
            }
        )
    return pairs


def _midi(note) -> int | None:
    step = note.findtext("pitch/step")
    octave = note.findtext("pitch/octave")
    if step is None or octave is None:
        return None
    semitones = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    alter = note.findtext("pitch/alter") or "0"
    return (int(octave) + 1) * 12 + semitones[step] + int(float(alter))


def extract_chord_fragments(document: Document) -> list[dict]:
    """Chord members whose duration differs from the chord base (MuseScore would coerce them)."""
    fragments: list[dict] = []
    for number, measure in document.iter_measures():
        groups: dict[tuple, list] = {}
        for event in document.events(measure):
            if event.rest:
                continue
            groups.setdefault((event.staff, event.voice, round(event.onset, 4)), []).append(event)
        for (staff, _voice, onset), events in groups.items():
            base_duration = max(event.duration for event in events)
            for event in events:
                if abs(event.duration - base_duration) < 1e-6:
                    continue
                pitch = _midi(event.element)
                if pitch is None:
                    continue
                fragments.append(
                    {
                        "measure": number,
                        "staff": staff,
                        "pitch": pitch,
                        "onset": onset,
                        "duration": event.duration,
                    }
                )
    return fragments
