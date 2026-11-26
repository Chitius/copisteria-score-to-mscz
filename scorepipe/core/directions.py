"""Helpers for preserving MusicXML ``<direction>`` timing across measure rewrites."""

from __future__ import annotations

from xml.etree import ElementTree

_PRE_NOTE_TAGS = frozenset({"attributes", "print", "sound", "direction"})


def direction_onsets(measure: ElementTree.Element) -> dict[int, int]:
    """Return ``{id(direction): onset_ticks}`` for every direct ``<direction>`` in ``measure``.

    Onset is measured in ticks from the start of the measure, combining the stream cursor at the
    element's position with its optional ``<offset>`` child (clamped at 0).
    """
    onsets: dict[int, int] = {}
    cursor = 0
    for child in measure:
        if child.tag in ("backup", "forward"):
            text = child.findtext("duration")
            if text is None:
                continue
            value = int(text)
            cursor += -value if child.tag == "backup" else value
        elif child.tag == "note":
            if child.find("chord") is not None:
                continue
            text = child.findtext("duration")
            if text is not None:
                cursor += int(text)
        elif child.tag == "direction":
            offset_text = (child.findtext("offset") or "").strip()
            try:
                offset = int(offset_text) if offset_text else 0
            except ValueError:
                offset = 0
            onsets[id(child)] = max(0, cursor + offset)
    return onsets


def set_direction_offset(direction: ElementTree.Element, onset_ticks: int) -> None:
    """Stamp ``onset_ticks`` onto ``direction`` for placement at cursor 0.

    Removes ``<offset>`` when ``onset_ticks <= 0``; otherwise updates the existing ``<offset>`` or
    inserts one immediately after the last ``<direction-type>`` (per MusicXML schema order).
    """
    existing = direction.find("offset")
    if onset_ticks <= 0:
        if existing is not None:
            direction.remove(existing)
        return
    if existing is not None:
        existing.text = str(onset_ticks)
        return
    insert_at = 0
    for index, child in enumerate(direction):
        if child.tag == "direction-type":
            insert_at = index + 1
    offset = ElementTree.Element("offset")
    offset.text = str(onset_ticks)
    direction.insert(insert_at, offset)


def direction_insertion_index(measure: ElementTree.Element) -> int:
    """Return an index at cursor 0 where relocated ``<direction>`` elements can be inserted."""
    index = 0
    for position, child in enumerate(measure):
        if child.tag in _PRE_NOTE_TAGS:
            index = position + 1
        elif child.tag in ("note", "forward", "backup"):
            break
    return index
