"""Tests for :mod:`scorepipe.confidence`, the OMR doubt heat map."""

from __future__ import annotations

import atexit
import json
import shutil
import tempfile
from pathlib import Path

import pytest

from scorepipe import confidence

pytest.importorskip("PIL")


def workspace(name: str) -> Path:
    """An isolated temporary directory, cleaned up at process exit."""
    directory = Path(tempfile.mkdtemp(prefix=f"scorepipe_conf_{name}_"))
    atexit.register(shutil.rmtree, directory, ignore_errors=True)
    return directory


def reading(path: Path, tokens: dict, changes: list[dict] | None = None) -> Path:
    path.write_text(
        json.dumps({"tokens": tokens, "changes": changes or []}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def page(path: Path, size: tuple[int, int] = (600, 400)) -> Path:
    from PIL import Image

    Image.new("RGB", size, (255, 255, 255)).save(path)
    return path


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------


def test_a_context_change_is_the_red_class():
    token = {"cls": {"det": "note", "v": "rest", "p": 0.999, "ev": 2.0}}
    result = confidence.summarise(token)
    assert result["score"] >= confidence.CHANGE_WEIGHT["cls"], result
    assert confidence.classify(result["score"], result["reasons"]) == "changed"


def test_an_ambiguous_existence_is_the_orange_class():
    result = confidence.summarise({"real": {"p": 0.5, "det": 0.5, "ev": 0.0}})
    assert result["score"] == 2.0, result
    assert confidence.classify(result["score"], result["reasons"]) == "existence"


def test_a_low_attribute_probability_is_the_amber_class():
    result = confidence.summarise({"cls": {"det": "note", "v": "note", "p": 0.4}})
    assert result["score"] > 0, result
    assert confidence.classify(result["score"], result["reasons"]) == "attribute"


def test_a_confident_symbol_scores_zero_and_stays_blue():
    result = confidence.summarise({"cls": {"det": "note", "v": "note", "p": 0.999}})
    assert result["score"] == 0, result
    assert result["reasons"] == []
    assert confidence.classify(result["score"], result["reasons"]) == "low"


def test_partial_chord_or_tie_probability_adds_a_reason():
    result = confidence.summarise({"chord": 0.5})
    assert result["score"] == 1.0, result
    assert result["reasons"][0]["head"] == "chord"


# ---------------------------------------------------------------------------
# one page
# ---------------------------------------------------------------------------


def test_build_page_writes_image_json_and_respects_top():
    root = workspace("build_page")
    read = reading(
        root / "sheet-1.reading.json",
        {
            "1": {"cls": {"det": "note", "v": "rest", "p": 0.99}},
            "2": {"real": {"p": 0.5}},
            "3": {"cls": {"det": "note", "v": "note", "p": 0.999}},
        },
        changes=[
            {"sym": 1, "box": [10, 10, 40, 40], "staff": 0, "bar": 2},
            {"sym": 2, "box": [60, 10, 90, 40], "staff": 0, "bar": 2},
        ],
    )
    job = confidence.PageJob(stem="sheet-1", reading=read, page=page(root / "sheet-1.png"))
    report = confidence.build_page(job, root / "out", top=1, crops=2)

    assert Path(report["outputs"]["image"]).is_file()
    assert Path(report["outputs"]["json"]).is_file()
    assert report["symbols"] == 3
    assert report["context_changes"] == 2, "both change records are counted"
    assert len(report["all_suspects"]) == 2, report["all_suspects"]
    assert len(report["suspects"]) == 1, "top must only limit the numbered boxes"
    assert report["suspect_counts"]["without_box"] == 0
    assert len(report["outputs"]["crops"]) == 1
    assert report["all_suspects"][0]["staff"] == 0 and report["all_suspects"][0]["bar"] == 2


def test_a_symbol_without_a_box_is_kept_but_not_numbered():
    root = workspace("no_box")
    read = reading(root / "sheet-1.reading.json", {"7": {"real": {"p": 0.4}}}, changes=[])
    job = confidence.PageJob(stem="sheet-1", reading=read, page=page(root / "sheet-1.png"))
    report = confidence.build_page(job, root / "out", top=40, crops=0)

    assert report["suspect_counts"]["total"] == 1
    assert report["suspect_counts"]["with_box"] == 0
    assert report["suspect_counts"]["without_box"] == 1
    assert report["suspects"] == [], "no box means nothing to point at"


def test_a_rendered_page_is_composed_beside_the_scan():
    from PIL import Image

    root = workspace("compose")
    read = reading(
        root / "sheet-1.reading.json",
        {"1": {"real": {"p": 0.5}}},
        changes=[{"sym": 1, "box": [5, 5, 25, 25]}],
    )
    rendered = page(root / "render-1.png", (300, 400))
    job = confidence.PageJob(
        stem="sheet-1", reading=read, page=page(root / "sheet-1.png"), rendered=rendered
    )
    report = confidence.build_page(job, root / "out", top=10, crops=0)

    image = Path(report["outputs"]["image"])
    assert image.name == "sheet-1.compare.png"
    with Image.open(image) as composed, Image.open(root / "sheet-1.png") as scan:
        assert composed.width > scan.width + 100, "the comparison should hold both pages"
        assert composed.height >= scan.height


def test_a_missing_page_raises_so_the_caller_can_skip():
    root = workspace("missing_page")
    read = reading(root / "sheet-1.reading.json", {"1": {"real": {"p": 0.5}}})
    job = confidence.PageJob(stem="sheet-1", reading=read, page=None)
    with pytest.raises(FileNotFoundError):
        confidence.build_page(job, root / "out")


# ---------------------------------------------------------------------------
# planning and the whole run
# ---------------------------------------------------------------------------


def test_plan_reads_the_work_dir_layout():
    root = workspace("plan_work")
    directory = root / "work" / "copisteria"
    directory.mkdir(parents=True)
    reading(directory / "page-1.reading.json", {"1": {"real": {"p": 0.5}}})
    page(directory / "page-1.png")

    jobs = confidence.plan(work_dir=root / "work")
    assert [job.stem for job in jobs] == ["page-1"]
    assert jobs[0].page is not None and jobs[0].page.name == "page-1.png"


def test_plan_finds_the_page_in_a_separate_page_dir():
    root = workspace("plan_pages")
    readings = root / "readings"
    pages = root / "pages"
    readings.mkdir()
    pages.mkdir()
    reading(readings / "a.reading.json", {"1": {"real": {"p": 0.5}}})
    page(pages / "a.png")

    jobs = confidence.plan(readings_dir=readings, page_dirs=[pages])
    assert jobs[0].page == pages / "a.png"


def test_plan_pairs_rendered_pages_positionally_only_when_counts_match():
    root = workspace("plan_rendered")
    readings = root / "work" / "copisteria"
    readings.mkdir(parents=True)
    for stem in ("a", "b"):
        reading(readings / f"{stem}.reading.json", {"1": {"real": {"p": 0.5}}})
        page(readings / f"{stem}.png")
    rendered = root / "rendered"
    rendered.mkdir()
    page(rendered / "source-1.png")
    page(rendered / "source-2.png")

    jobs = confidence.plan(work_dir=root / "work", rendered_dir=rendered, positional_rendered=True)
    assert [job.rendered.name for job in jobs] == ["source-1.png", "source-2.png"]

    page(rendered / "source-3.png")
    with pytest.raises(ValueError):
        confidence.plan(work_dir=root / "work", rendered_dir=rendered, positional_rendered=True)


def test_review_is_incomplete_when_a_page_is_skipped():
    root = workspace("review_skip")
    read = reading(root / "a.reading.json", {"1": {"real": {"p": 0.5}}})
    jobs = [confidence.PageJob(stem="a", reading=read, page=None)]
    summary = confidence.review(jobs, root / "review")

    assert summary["status"] == "incomplete"
    assert summary["skipped"] == 1
    assert summary["skipped_pages"][0]["page"] == "a"
    assert (root / "review" / "review.md").is_file()
    assert (root / "review" / "summary.json").is_file()


def test_review_is_complete_with_issues_and_keeps_every_suspect():
    root = workspace("review_full")
    read = reading(
        root / "a.reading.json",
        {"1": {"cls": {"det": "note", "v": "rest", "p": 0.99}}, "2": {"real": {"p": 0.5}}},
        changes=[{"sym": 1, "box": [5, 5, 25, 25], "staff": 0, "bar": 0}],
    )
    jobs = [confidence.PageJob(stem="a", reading=read, page=page(root / "a.png"))]
    summary = confidence.review(jobs, root / "review", top=1, crops=0)

    assert summary["status"] == "complete_with_issues"
    assert summary["issues"]["total"] == 2
    markdown = (root / "review" / "review.md").read_text(encoding="utf-8")
    assert "a" in markdown and "score" in markdown
    assert "not a probability" in markdown


# ---------------------------------------------------------------------------
# the review-loop integration
# ---------------------------------------------------------------------------


def test_review_loop_helper_paints_when_the_page_dir_has_readings():
    from scripts import review as review_script

    root = workspace("loop_helper")
    pages = root / "work" / "copisteria"
    pages.mkdir(parents=True)
    reading(
        pages / "p1.reading.json",
        {"1": {"cls": {"det": "note", "v": "rest", "p": 0.99}}},
        changes=[{"sym": 1, "box": [5, 5, 25, 25], "staff": 0, "bar": 0}],
    )
    page(pages / "p1.png")

    result = review_script._confidence_map(pages, root / "out")
    assert result["status"] == "complete_with_issues", result
    assert Path(result["dir"], "p1.review.png").is_file()


def test_review_loop_helper_skips_without_readings():
    from scripts import review as review_script

    root = workspace("loop_skip")
    pages = root / "pages"
    pages.mkdir()
    result = review_script._confidence_map(pages, root / "out")
    assert result["status"] == "skipped"
    assert "reading.json" in result["reason"]


def test_review_loop_helper_reports_a_broken_reading_without_raising():
    from scripts import review as review_script

    root = workspace("loop_broken")
    pages = root / "work" / "copisteria"
    pages.mkdir(parents=True)
    (pages / "p1.reading.json").write_text("{not json", encoding="utf-8")
    page(pages / "p1.png")

    result = review_script._confidence_map(pages, root / "out")
    assert result["status"] in {"failed", "incomplete"}, result

