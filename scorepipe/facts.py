"""External facts: the text layer and the agent are producers, never passes.

A facts file is plain JSON:

    {"marks": [{"measure": 9, "beat": 0, "placement": "above",
                "rehearsal": "A", "text": "Allegro", "tempo": 110, "beat_unit": "quarter"}]}

The inject pass below is mechanical and idempotent; it never invents a fact.
"""

from __future__ import annotations

import json
from pathlib import Path


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
    return problems
