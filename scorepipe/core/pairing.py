"""Pair slur/tie endpoints by key without letting a reused number swallow a later phrase.

Endpoint pairs (slurs, ties) are written as separate start/stop marks.  When an OMR file reuses a
number for several marks, a single-slot stack either pairs the oldest start with the wrong stop or
drops the whole cluster.  This pairer keeps **all** open starts per key and, when a stop arrives,
picks the best *valid* one:

- the start must be earlier than the stop;
- the pair must not exceed ``max_span``;
- an optional scorer can prefer the same pitch/voice, otherwise the shortest span wins
  (ties are broken towards the latest start).

Endpoints that cannot be paired are returned as orphans; no cluster is deleted wholesale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Endpoint:
    key: tuple
    position: tuple
    kind: str  # "start" | "stop"
    payload: object = None


@dataclass
class Pairing:
    pairs: list[tuple[Endpoint, Endpoint]] = field(default_factory=list)
    orphans: list[Endpoint] = field(default_factory=list)
    ambiguous_keys: set[tuple] = field(default_factory=set)


Score = Callable[[Endpoint, Endpoint], float]


def pair_endpoints(
    endpoints: list[Endpoint], *, max_span: int | None = None, score: Score | None = None
) -> Pairing:
    open_starts: dict[tuple, list[Endpoint]] = {}
    result = Pairing()

    for endpoint in endpoints:
        key = endpoint.key
        if endpoint.kind == "start":
            open_starts.setdefault(key, []).append(endpoint)
            if len(open_starts[key]) > 1:
                result.ambiguous_keys.add(key)
            continue

        candidates = [
            start
            for start in open_starts.get(key, [])
            if start.position < endpoint.position
            and (max_span is None or endpoint.position[0] - start.position[0] <= max_span)
        ]
        if not candidates:
            result.orphans.append(endpoint)
            continue
        if score is not None:
            best = max(
                candidates,
                key=lambda start: (
                    score(start, endpoint),
                    -(endpoint.position[0] - start.position[0]),
                    start.position,
                ),
            )
        else:
            best = max(
                candidates,
                key=lambda start: (
                    -(endpoint.position[0] - start.position[0]),
                    start.position,
                ),
            )
        open_starts[key].remove(best)
        result.pairs.append((best, endpoint))

    for starts in open_starts.values():
        result.orphans.extend(starts)
    return result
