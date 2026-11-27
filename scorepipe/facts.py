"""External facts: the text layer and the agent are producers, never passes.

A facts file is plain JSON:

    {"marks": [{"measure": 9, "beat": 0, "placement": "above",
                "rehearsal": "A", "text": "Allegro", "tempo": 110, "beat_unit": "quarter"}]}

The inject pass below is mechanical and idempotent; it never invents a fact.
"""

from __future__ import annotations

import json
from pathlib import Path

from .instruments import INSTRUMENT_KEYS, resolve_instrument


def load_facts(path: str | Path | None) -> dict:
    if not path:
        return {}
    # BOM tolerant: the file may come from PowerShell or an agent writer
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if (data.get("producer") or {}).get("name") == "agent-visual":
        from .agent_facts import normalize_agent_facts

        data = normalize_agent_facts(data)
    return data


def validate_facts(facts: dict) -> list[str]:
    problems: list[str] = []
    for index, mark in enumerate(facts.get("marks") or []):
        if not isinstance(mark.get("measure"), int) or mark["measure"] < 1:
            problems.append(f"marks[{index}]: measure must be a positive integer")
        if not any(mark.get(key) for key in ("text", "rehearsal", "tempo", "metronome")):
            problems.append(f"marks[{index}]: empty mark")
        if mark.get("placement") not in (None, "above", "below"):
            problems.append(f"marks[{index}]: placement must be above/below")
    for index, entry in enumerate(facts.get("parts") or []):
        if not isinstance(entry, dict):
            problems.append(f"parts[{index}]: must be an object")
            continue
        if not isinstance(entry.get("part"), str) or not entry["part"].strip():
            problems.append(f"parts[{index}]: part must be a non-empty string")
        if not any(
            entry.get(key) is not None and entry.get(key) != ""
            for key in ("name", "abbreviation", "instrument", "sound", "midi_program", "midi_channel")
        ):
            problems.append(f"parts[{index}]: empty part instrument fact")
        inst = entry.get("instrument")
        if inst is not None and (not isinstance(inst, str) or resolve_instrument(inst) is None):
            problems.append(
                f"parts[{index}]: unknown instrument {inst!r} (known: {len(INSTRUMENT_KEYS)} presets)"
            )
        prog = entry.get("midi_program")
        if prog is not None and (isinstance(prog, bool) or not isinstance(prog, int) or not 1 <= prog <= 128):
            problems.append(f"parts[{index}]: midi_program must be an integer 1..128")
        ch = entry.get("midi_channel")
        if ch is not None and (isinstance(ch, bool) or not isinstance(ch, int) or not 1 <= ch <= 16):
            problems.append(f"parts[{index}]: midi_channel must be an integer 1..16")
    return problems
