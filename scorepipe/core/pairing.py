"""Pair slur/tie endpoints by key without guessing across ambiguous numbering.

Endpoint pairs (slurs, ties) are written as separate start/stop marks.  When an OMR file reuses a
number for several simultaneous marks, a plain stack pairs the *oldest* open start with a much later
stop, which is how a 3-bar slur appears.  Rather than guess, this pairer works on one open start per
key and marks a key **ambiguous** as soon as a second start arrives before the previous one closed:
the colliding cluster is dropped until a stop clears it.  A clean start/stop after that pairs again.

Positions are ``(measure, onset)`` tuples; ``max_span`` rejects pairs longer than N measures.
"""

from __future__ import annotations

from dataclasses import dataclass, field


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


def pair_endpoints(endpoints: list[Endpoint], *, max_span: int | None = None) -> Pairing:
    open_starts: dict[tuple, Endpoint] = {}
    blocked: set[tuple] = set()
    result = Pairing()

    for endpoint in endpoints:
        key = endpoint.key
        if endpoint.kind == "start":
            if key in blocked:
                result.orphans.append(endpoint)
                continue
            if key in open_starts:
                # two starts before a stop: the numbers collide and we cannot know which stop
                # belongs to which start. Drop the earlier one and block the key until a stop.
                result.orphans.append(open_starts.pop(key))
                blocked.add(key)
                result.ambiguous_keys.add(key)
                result.orphans.append(endpoint)
                continue
            open_starts[key] = endpoint
        else:  # stop
            if key in blocked:
                result.orphans.append(endpoint)
                blocked.discard(key)
                continue
            start = open_starts.pop(key, None)
            if start is None:
                result.orphans.append(endpoint)
                continue
            if endpoint.position <= start.position:
                result.orphans.extend((start, endpoint))
                continue
            if max_span is not None and endpoint.position[0] - start.position[0] > max_span:
                result.orphans.extend((start, endpoint))
                continue
            result.pairs.append((start, endpoint))

    result.orphans.extend(open_starts.values())
    return result
