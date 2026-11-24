"""Tests for :mod:`scorepipe.proof_sheet`, the measure-level page comparison."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scorepipe import proof_sheet

pytest.importorskip("PIL")
pytest.importorskip("numpy")

RUNS = Path(__file__).parent / ".runs" / "proof_sheet"


def workspace(name: str) -> Path:
    directory = RUNS / name
    shutil.rmtree(directory, ignore_errors=True)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def staff_page(path: Path, barlines: list[int], *, staves: int = 1, width: int = 700, height: int = 260) -> Path:
    """A synthetic page: black staff lines and barlines on white, big enough for the detector."""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    top = 40
    for staff in range(staves):
        base = top + staff * 90
        for line in range(5):
            y = base + line * 9
            draw.line((30, y, width - 30, y), fill=(0, 0, 0), width=2)
    # Barlines span the whole system, the way a bracketed score draws them; that is also what
    # tells systems_from_ink that the staves belong together.
    span = 36 + (staves - 1) * 90
    for x in barlines:
        draw.line((x, top, x, top + span), fill=(0, 0, 0), width=3)
    image.save(path)
    return path


def reading(path: Path, changes: list[dict], tokens: dict | None = None) -> Path:
    path.write_text(
        json.dumps({"tokens": tokens or {}, "changes": changes}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def musicxml(path: Path, measures: int) -> Path:
    body = "".join(f'<measure number="{index}"><note/></measure>' for index in range(1, measures + 1))
    path.write_text(
        f'<score-partwise><part-list><score-part id="P1"><part-name>t</part-name></score-part>'
        f'</part-list><part id="P1">{body}</part></score-partwise>',
        encoding="utf-8",
    )
    return path


# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------


def test_a_staff_with_three_barlines_has_two_measures():
    root = workspace("cells")
    image = staff_page(root / "page.png", [40, 300, 620])
    from PIL import Image

    cells, systems, _ = proof_sheet.detect_measures(Image.open(image).convert("RGB"))
    assert len(systems) == 1, systems
    assert len(cells) == 2, cells


def test_three_staves_of_one_system_stay_one_system():
    root = workspace("three_staves")
    image = staff_page(root / "page.png", [40, 300, 620], staves=3, height=340)
    from PIL import Image

    cells, systems, _ = proof_sheet.detect_measures(Image.open(image).convert("RGB"))
    assert len(systems) == 1, systems
    assert len(cells) == 2, cells


def test_detection_barlines_are_merged_with_the_ink_ones():
    root = workspace("dets_merge")
    image = staff_page(root / "page.png", [40, 300, 620])
    from PIL import Image

    dets = [
        {"cls": "barLine_single", "xyxy": [38, 40, 42, 76]},
        {"cls": "barLine_double", "xyxy": [297, 40, 303, 76]},
        {"cls": "barLine_final", "xyxy": [617, 40, 623, 76]},
        {"cls": "note_quarter", "xyxy": [100, 50, 120, 70]},
    ]
    cells, _, _ = proof_sheet.detect_measures(Image.open(image).convert("RGB"), dets)
    assert len(cells) == 2, cells


# ---------------------------------------------------------------------------
# placing a symbol in a measure
# ---------------------------------------------------------------------------


def test_a_symbol_is_placed_by_its_system_and_its_system_local_bar():
    root = workspace("scores")
    read = reading(
        root / "a.reading.json",
        [
            {"sym": 1, "bar": 0, "staff": 0, "box": [10, 20, 30, 40]},
            {"sym": 2, "bar": 1, "staff": 0, "box": [100, 20, 120, 40]},
        ],
        {
            "1": {"cls": {"det": "note", "v": "rest", "p": 0.99}},
            "2": {"real": {"p": 0.5}},
        },
    )
    systems = [(0, 100), (200, 300)]
    offsets = [0, 4]
    scores, unplaced = proof_sheet.measure_scores(
        read, systems, offsets, origin=(0, 0), system_counts=[4, 3]
    )
    assert unplaced == 0, unplaced
    assert sorted(scores) == [1, 2], scores


def test_a_bar_past_the_end_of_its_system_is_unplaced():
    root = workspace("past_end")
    read = reading(
        root / "a.reading.json",
        [{"sym": 1, "bar": 9, "staff": 0, "box": [10, 20, 30, 40]}],
        {"1": {"real": {"p": 0.5}}},
    )
    scores, unplaced = proof_sheet.measure_scores(
        read, [(0, 100)], [0], origin=(0, 0), system_counts=[4]
    )
    assert scores == {}, scores
    assert unplaced == 1


def test_a_symbol_outside_every_system_is_unplaced():
    root = workspace("outside")
    read = reading(
        root / "a.reading.json",
        [{"sym": 1, "bar": 0, "staff": 0, "box": [10, 900, 30, 940]}],
        {"1": {"real": {"p": 0.5}}},
    )
    scores, unplaced = proof_sheet.measure_scores(
        read, [(0, 100)], [0], origin=(0, 0), system_counts=[4]
    )
    assert scores == {}
    assert unplaced == 1


def test_the_origin_of_the_crop_is_taken_into_account():
    root = workspace("origin")
    read = reading(
        root / "a.reading.json",
        [{"sym": 1, "bar": 0, "staff": 0, "box": [110, 320, 130, 340]}],
        {"1": {"real": {"p": 0.5}}},
    )
    scores, unplaced = proof_sheet.measure_scores(
        read, [(0, 100)], [0], origin=(100, 300), system_counts=[4]
    )
    assert unplaced == 0 and sorted(scores) == [1], (scores, unplaced)


# ---------------------------------------------------------------------------
# composition
# ---------------------------------------------------------------------------


def test_compose_puts_both_columns_side_by_side():
    from PIL import Image

    root = workspace("compose")
    left = Image.new("RGB", (400, 600), (250, 250, 250))
    right = Image.new("RGB", (400, 500), (240, 240, 240))
    canvas = proof_sheet.compose(left, right, "render", "scan", width=300)
    assert canvas.width == 300 * 2 + 24, canvas.width
    # Both columns are scaled to 300 px wide: the taller (600 px) becomes 450, plus the caption band.
    assert canvas.height == 450 + 54, canvas.height


def test_page_measure_count_reads_the_first_part():
    root = workspace("count")
    path = musicxml(root / "a.musicxml", 7)
    assert proof_sheet.page_measure_count(path) == 7


# ---------------------------------------------------------------------------
# one sheet without a renderer
# ---------------------------------------------------------------------------


def test_without_musescore_the_sheet_still_aligns_the_scan():
    from PIL import Image

    root = workspace("no_render")
    scan = staff_page(root / "p1.png", [40, 300, 620])
    read = reading(
        root / "p1.reading.json",
        [{"sym": 1, "bar": 0, "staff": 0, "box": [60, 40, 90, 76]}],
        {"1": {"real": {"p": 0.5}}},
    )
    xml = musicxml(root / "p1.musicxml", 2)
    page = proof_sheet.SheetPage(stem="p1", scan=scan, musicxml=xml, reading=read)
    report = proof_sheet.build_sheet(page, root / "out", musescore=None, width=420)

    assert report["scan_measures"] == 2, report
    assert report["aligned"] is True
    assert report["red"] == [1], report["red"]
    assert Path(report["outputs"]["image"]).is_file()
    with Image.open(report["outputs"]["image"]) as image:
        assert image.width > 800


def test_a_measure_count_mismatch_is_reported_and_not_painted():
    root = workspace("mismatch")
    scan = staff_page(root / "p1.png", [40, 300, 620])
    read = reading(root / "p1.reading.json", [], {"1": {"real": {"p": 0.5}}})
    xml = musicxml(root / "p1.musicxml", 5)
    page = proof_sheet.SheetPage(stem="p1", scan=scan, musicxml=xml, reading=read)
    report = proof_sheet.build_sheet(page, root / "out", musescore=None, width=420)

    assert report["scan_measures"] == 2
    assert report["aligned"] is False
    assert any(failure["code"] == "scan_layout_mismatch" for failure in report["failures"])


def test_a_broken_detection_cache_falls_back_to_ink():
    root = workspace("broken_dets")
    scan = staff_page(root / "p1.png", [40, 300, 620])
    dets = root / "p1.dets_x.json"
    dets.write_text("{not json", encoding="utf-8")
    read = reading(root / "p1.reading.json", [], {})
    xml = musicxml(root / "p1.musicxml", 2)
    page = proof_sheet.SheetPage(stem="p1", scan=scan, musicxml=xml, reading=read, dets=dets)
    report = proof_sheet.build_sheet(page, root / "out", musescore=None, width=420)

    assert report["scan_measures"] == 2, report
    assert any("detection cache" in warning for warning in report["warnings"])


# ---------------------------------------------------------------------------
# page-layout gaps and sliver cells
# ---------------------------------------------------------------------------


def test_a_tall_blank_band_is_collapsed():
    from PIL import Image, ImageDraw

    root = workspace("collapse")
    image = Image.new("RGB", (400, 1200), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    for y in (100, 104, 108, 112, 116):
        draw.line((40, y, 360, y), fill=(0, 0, 0), width=2)
    for y in (1000, 1004, 1008, 1012, 1016):
        draw.line((40, y, 360, y), fill=(0, 0, 0), width=2)
    path = root / "tall.png"
    image.save(path)

    collapsed, removed = proof_sheet.collapse_blank_bands(Image.open(path).convert("RGB"))
    assert removed, "the gap between the two staffs must be found"
    assert collapsed.height < 200, collapsed.height
    assert collapsed.width == 400


def test_normal_spacing_is_left_alone():
    from PIL import Image, ImageDraw

    root = workspace("collapse_noop")
    image = Image.new("RGB", (400, 320), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    for top in (20, 70):
        for line in range(5):
            draw.line((40, top + line * 8, 360, top + line * 8), fill=(0, 0, 0), width=2)
    path = root / "p.png"
    image.save(path)

    original = Image.open(path).convert("RGB")
    collapsed, removed = proof_sheet.collapse_blank_bands(original)
    # The empty margins are candidates; the 14 px gap between the two staves is music spacing.
    assert removed, "the empty margins should be found"
    assert not any(start >= 56 and end <= 104 for start, end in removed), (
        f"the gap between the staves is music spacing and must stay: {removed}"
    )
    assert collapsed.height < original.height
    assert collapsed.height >= 100, collapsed.height


def test_an_interior_sliver_is_merged_but_the_edges_are_not():
    cells = [
        (0, 0, 200, 30),
        (200, 0, 450, 30),
        (450, 0, 462, 30),
        (462, 0, 700, 30),
        (700, 0, 900, 30),
    ]
    merged = proof_sheet._merge_narrow_cells(cells)
    assert len(merged) == 4, merged
    assert merged[0] == cells[0], "the first bar of a system may be short for real"
    assert merged[-1] == cells[-1], "the final bar of a system may be short for real"
    assert (450, 0, 462, 30) not in merged, "the sliver is gone"


def test_the_narrow_filter_can_be_switched_off():
    from PIL import Image

    root = workspace("narrow_off")
    image = staff_page(root / "p.png", [40, 300, 620])
    plain, _, _ = proof_sheet.detect_measures(Image.open(image).convert("RGB"))
    filtered, _, _ = proof_sheet.detect_measures(
        Image.open(image).convert("RGB"), narrow_filter=True
    )
    assert len(filtered) <= len(plain)
