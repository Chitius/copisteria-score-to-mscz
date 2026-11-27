"""Measure cell alignment: scan reconciliation, sliver folding, and common-prefix matching."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence

from .models import TRAILING_SLIVER_FRACTION


def reconcile_scan_rows(
    rows: Sequence[Sequence[tuple[int, int, int, int]]],
    systems: Sequence[tuple[int, int]],
    expected: int,
    reading: Path,
    *,
    origin: tuple[int, int] = (0, 0),
    right_edges: Sequence[int] | None = None,
) -> tuple[list[list[tuple[int, int, int, int]]], list[int], list[str]]:
    """Give a row the bars the reader knows it has, even when a barline was missed.

    The render side is exact (SVG geometry); the scan side depends on copisteria's barline
    detections and can miss one.  Two measured shapes:

    * the **final** barline of a system is missing (First Step page 1, system 1): the reader's
      change records still place a symbol past the last detected barline, so the row gets one more
      cell from that barline to the staff's right edge -- that edge *is* where the final barline
      stands, so this cell is not a guess;
    * an **internal** barline is missing: there is no evidence for the boundary, so the widest cell
      is split and both halves are returned as inferred; the sheet does not tint them.

    Everything after the repair keeps its measured boundaries, so one missed barline no longer
    throws away the whole page.
    """
    data = json.loads(Path(reading).read_text(encoding="utf-8"))
    origin_x, origin_y = origin
    system_bars: dict[int, set[int]] = {}
    bar_x: dict[int, dict[int, float]] = {}
    for entry in data.get("changes") or []:
        if entry.get("bar") is None or not entry.get("box"):
            continue
        y = (entry["box"][1] + entry["box"][3]) / 2 - origin_y
        system = next(
            (index for index, (top, bottom) in enumerate(systems) if top - 6 <= y <= bottom + 6),
            None,
        )
        if system is None:
            continue
        bar = int(entry["bar"])
        system_bars.setdefault(system, set()).add(bar)
        x = min(entry["box"][0], entry["box"][2]) - origin_x
        slot = bar_x.setdefault(system, {})
        slot[bar] = min(slot.get(bar, float("inf")), x)

    result = [list(row) for row in rows]
    inferred_by_row: list[set[int]] = [set() for _ in result]
    notes: list[str] = []
    targets = []
    for index, row in enumerate(result):
        bars = system_bars.get(index) or set()
        targets.append(max(len(row), (max(bars) + 1) if bars else 0))
    total = sum(targets)
    while total > expected:
        candidates = [index for index in range(len(result)) if targets[index] > len(result[index])]
        if not candidates:
            break
        index = max(candidates, key=lambda item: targets[item] - len(result[item]))
        targets[index] -= 1
        total -= 1
    while total < expected:
        index = _widest_splittable_row(result)
        if index is None:
            break
        targets[index] += 1
        total += 1

    for index, row in enumerate(result):
        while len(row) < targets[index]:
            appended = _append_tail(row, index, right_edges, bar_x.get(index) or {})
            if appended:
                notes.append(
                    f"system {index + 1}: closed the missed final barline at "
                    f"x={round(row[-1][2])}"
                )
                continue
            position = _split_widest(row)
            if position is None:
                break
            inferred_by_row[index].update({position - 1, position})
            notes.append(f"system {index + 1}: split a wide cell at x={round(row[position][0])}")

    offsets: list[int] = []
    running = 0
    for row in result:
        offsets.append(running)
        running += len(row)
    flat_inferred = sorted(
        offsets[index] + position
        for index, positions in enumerate(inferred_by_row)
        for position in positions
    )
    return result, flat_inferred, notes


def _append_tail(
    row: list[tuple[int, int, int, int]],
    index: int,
    right_edges: Sequence[int] | None,
    bar_x: dict[int, float],
) -> bool:
    """Append a final cell when a bar's symbols start past the last detected barline."""
    if not row or right_edges is None or index >= len(right_edges):
        return False
    edge = int(right_edges[index])
    last = row[-1]
    if edge <= last[2] + 8:
        return False
    # A bar whose first symbol lies past the last barline proves the system continues.
    if not any(x > last[2] - 6 for x in bar_x.values()):
        return False
    row.append((last[2], last[1], edge, last[3]))
    return True


def _widest_splittable_row(rows: Sequence[list[tuple[int, int, int, int]]]) -> int | None:
    best: tuple[float, int] | None = None
    for index, row in enumerate(rows):
        if len(row) < 2:
            continue
        widths = sorted(cell[2] - cell[0] for cell in row)
        median = widths[len(widths) // 2] or 1
        widest = max(cell[2] - cell[0] for cell in row)
        if widest > median * 1.5 and (best is None or widest > best[0]):
            best = (float(widest), index)
    return best[1] if best else None


def _split_widest(row: list[tuple[int, int, int, int]]) -> int | None:
    """Split the widest cell one typical measure from its left edge; return the new index."""
    if len(row) < 2:
        return None
    widths = sorted(cell[2] - cell[0] for cell in row)
    median = widths[len(widths) // 2] or 1
    index = max(range(len(row)), key=lambda item: row[item][2] - row[item][0])
    cell = row[index]
    if cell[2] - cell[0] < median * 1.5:
        return None
    cut = min(max(cell[0] + median, cell[0] + 1), cell[2] - 1)
    row.insert(index + 1, (cut, cell[1], cell[2], cell[3]))
    row[index] = (cell[0], cell[1], cut, cell[3])
    return index + 1


def fit_cells_to_count(
    rows: Sequence[Sequence[tuple[int, int, int, int]]],
    expected: int,
    fraction: float = 0.70,
) -> tuple[list[list[tuple[int, int, int, int]]], int]:
    """Fold the narrowest interior cells until the count reaches ``expected``.

    Used only when the detector found *more* cells than the page declares: the extra ones are
    stems read as barlines, and the narrowest cells are the suspects.  It never invents a cell, so
    a page that genuinely has fewer bars than its MusicXML still fails the count check.  Every fold
    is counted and reported, and a fold needs the cell to be under ``fraction`` of its system's
    median width -- if nothing qualifies, the mismatch stands.
    """
    merged = [list(row) for row in rows]
    folded = 0
    while sum(len(row) for row in merged) > expected:
        best: tuple[float, int, int] | None = None
        for row_index, row in enumerate(merged):
            if len(row) < 3:
                continue
            widths = sorted(cell[2] - cell[0] for cell in row)
            median = widths[len(widths) // 2] or 1
            for cell_index in range(1, len(row) - 1):
                width = row[cell_index][2] - row[cell_index][0]
                if width < median * fraction and (best is None or width < best[0]):
                    best = (float(width), row_index, cell_index)
        if best is None:
            break
        _, row_index, cell_index = best
        row = merged[row_index]
        row[cell_index - 1] = (
            row[cell_index - 1][0],
            row[cell_index - 1][1],
            row[cell_index][2],
            row[cell_index - 1][3],
        )
        del row[cell_index]
        folded += 1
    return merged, folded


def _system_groups(cells: Sequence[Sequence[float]]) -> list[list[tuple[float, float, float, float]]]:
    """Split cells into systems; consecutive cells sharing a y band belong to one system."""
    groups: list[list[tuple[float, float, float, float]]] = []
    previous: tuple[int, int] | None = None
    for cell in cells:
        key = (round(cell[1]), round(cell[3]))
        if key != previous:
            groups.append([])
            previous = key
        groups[-1].append(tuple(float(value) for value in cell[:4]))
    return groups


def system_counts(cells: Sequence[Sequence[float]]) -> list[int]:
    """Cells per system, using the y band each cell occupies as the system identity."""
    return [len(group) for group in _system_groups(cells)]


def _trailing_extra(
    cells: Sequence[Sequence[float]], kept: int, fraction: float = 0.15
) -> bool:
    """True when everything after ``kept`` is a narrow stroke appended at the right edge.

    That is the shape of a final-barline stroke or a duplicate closing cell: it is appended after
    the real bar, not inserted inside it, so the first ``kept`` cells still line up.  The width
    guard keeps a sliver that *splits* a bar from being read as an appended cell.
    """
    if kept <= 0 or len(cells) <= kept:
        return False
    edge = cells[kept - 1][2]
    widths = sorted(cell[2] - cell[0] for cell in cells)
    median = widths[len(widths) // 2] or 1.0
    return all(
        cell[0] >= edge - 2 and (cell[2] - cell[0]) < median * fraction
        for cell in cells[kept:]
    )


def fold_trailing_slivers(
    cells: Sequence[Sequence[float]],
    expected: int,
    fraction: float = TRAILING_SLIVER_FRACTION,
) -> tuple[list[tuple[float, float, float, float]], int]:
    """Fold barline-stroke cells at the *end* of a system into the cell on their left.

    Only runs while the total exceeds ``expected``, so a page whose count already matches is never
    touched.  The suspect has to be the last cell of its system and narrower than ``fraction`` of
    that system's median width; it is merged, never dropped, so the bar it belonged to keeps its
    right edge.  This is the tail counterpart of :func:`fit_cells_to_count`, which only folds
    interior cells.
    """
    folded = [tuple(float(value) for value in cell[:4]) for cell in cells]
    operations = 0
    while len(folded) > expected:
        counts = system_counts(folded)
        if not counts:
            break
        # Rebuild system groups with their index ranges.
        groups: list[tuple[int, int]] = []
        start = 0
        for count in counts:
            groups.append((start, start + count))
            start += count
        best: tuple[float, int] | None = None
        for first, last in groups:
            if last - first < 2:
                continue
            widths = sorted(folded[index][2] - folded[index][0] for index in range(first, last))
            median = widths[len(widths) // 2] or 1.0
            candidate = last - 1
            width = folded[candidate][2] - folded[candidate][0]
            if width < median * fraction and (best is None or width < best[0]):
                best = (float(width), last)
        if best is None:
            break
        _, last = best
        tail = last - 1
        left = folded[tail - 1]
        folded[tail - 1] = (left[0], left[1], folded[tail][2], left[3])
        del folded[tail]
        operations += 1
    return folded, operations


def common_prefix_measures(
    render_cells: Sequence[Sequence[float]],
    scan_cells: Sequence[Sequence[float]],
    expected: int,
) -> int:
    """How many measures can be tinted on both sides before the bar counts disagree.

    Systems are compared in order; a system whose two counts differ ends the trustworthy prefix,
    because from there on the measure numbers may be shifted.  The one tolerated exception is the
    *last* system with extra cells appended at its right edge (the final-barline case): those sit
    after the real bars, so the shorter side still lines up and is tinted.
    """
    render_groups = _system_groups(render_cells)
    scan_groups = _system_groups(scan_cells)
    last = min(len(render_groups), len(scan_groups)) - 1
    total = 0
    for index, (render, scan) in enumerate(zip(render_groups, scan_groups)):
        if len(render) == len(scan):
            total += len(render)
        elif len(render) > len(scan) and index == last and _trailing_extra(render, len(scan)):
            total += len(scan)
        elif len(scan) > len(render) and index == last and _trailing_extra(scan, len(render)):
            total += len(render)
        else:
            break
        if total >= expected:
            break
    return min(total, expected)
