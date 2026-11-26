from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

from PIL import Image, ImageDraw

from scorepipe import proof_sheet
from scorepipe.core.mscz import MsczArchive


CONTAINER = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<container><rootfiles><rootfile full-path="score.mscx"/></rootfiles></container>'
)


def _write_mscz(path: Path, measure_count: int, *, title: str | None = None, existing_break_at: int | None = None) -> Path:
    vbox = (
        f"<VBox><Text><style>title</style><text>{title}</text></Text></VBox>"
        if title
        else ""
    )
    measures_s1 = []
    measures_s2 = []
    for index in range(1, measure_count + 1):
        extra = ""
        if existing_break_at == index:
            extra = (
                "<LayoutBreak><subtype>page</subtype></LayoutBreak>"
                "<LayoutBreak><subtype>line</subtype></LayoutBreak>"
            )
        measures_s1.append(
            f"<Measure>{extra}<voice><Chord><durationType>whole</durationType>"
            "<Note><pitch>60</pitch></Note></Chord></voice></Measure>"
        )
        measures_s2.append(
            "<Measure><voice><Chord><durationType>whole</durationType>"
            "<Note><pitch>48</pitch></Note></Chord></voice></Measure>"
        )
    mscx = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<museScore version="4.4"><Score>'
        f'<Staff id="1">{vbox}{"".join(measures_s1)}</Staff>'
        f'<Staff id="2">{"".join(measures_s2)}</Staff>'
        "</Score></museScore>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/container.xml", CONTAINER)
        archive.writestr("score.mscx", mscx)
    return path


def _write_musicxml(path: Path, measure_count: int, *, existing_new_page_at: int | None = None) -> Path:
    measures = []
    for index in range(1, measure_count + 1):
        pr = '<print new-page="yes"/>' if existing_new_page_at == index else ""
        measures.append(
            f'<measure number="{index}">{pr}'
            "<note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration></note>"
            "</measure>"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?><score-partwise version="4.0">'
        '<part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>'
        f'<part id="P1">{"".join(measures)}</part></score-partwise>'
    )
    path.write_text(xml, encoding="utf-8")
    return path


def _synthetic_scan(path: Path, bars: int = 2) -> Path:
    image = Image.new("RGB", (800, 300), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    top, bottom = 80, 160
    for row in range(top, bottom + 1, 20):
        draw.line((40, row, 760, row), fill=(0, 0, 0), width=2)
    step = (760 - 40) // bars
    for i in range(bars + 1):
        x = 40 + i * step
        draw.line((x, top, x, bottom), fill=(0, 0, 0), width=3)
    image.save(path)
    return path


def _synthetic_svg(path: Path, bars: int = 2) -> Path:
    step = 720.0 / bars
    polylines = "\n".join(
        f'<polyline class="BarLine" points="{40 + i * step},80 {40 + i * step},160"/>'
        for i in range(bars + 1)
    )
    path.write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 300">{polylines}</svg>',
        encoding="utf-8",
    )
    return path


class PaginatedScoreProofSheetTest(unittest.TestCase):
    def test_page_sort_key_orders_numerically_past_nine(self):
        names = [Path(f"paginated_svg-{n}.svg") for n in (1, 10, 2, 11, 3)]
        ordered = [p.name for p in sorted(names, key=proof_sheet._page_sort_key)]
        self.assertEqual(
            ordered,
            [
                "paginated_svg-1.svg",
                "paginated_svg-2.svg",
                "paginated_svg-3.svg",
                "paginated_svg-10.svg",
                "paginated_svg-11.svg",
            ],
        )

    def test_prepare_paginated_mscz_replaces_page_breaks_and_keeps_line_breaks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = _write_mscz(root / "score.mscz", 6, title="My Piece", existing_break_at=2)
            out = proof_sheet.prepare_paginated_mscz(src, [3, 3], root / "paginated.mscz")
            self.assertEqual(proof_sheet.read_score_title(src), "My Piece")
            self.assertEqual(proof_sheet.score_measure_count(src), 6)

            archive = MsczArchive.open(out)
            measures = archive.document.staves()[0].findall("Measure")
            page_breaks = [
                i + 1
                for i, m in enumerate(measures)
                if any((lb.findtext("subtype") or "").strip() == "page" for lb in m.findall("LayoutBreak"))
            ]
            line_breaks = [
                i + 1
                for i, m in enumerate(measures)
                if any((lb.findtext("subtype") or "").strip() == "line" for lb in m.findall("LayoutBreak"))
            ]
            self.assertEqual(page_breaks, [3])
            self.assertEqual(line_breaks, [2])

    def test_prepare_paginated_musicxml_sets_new_page_at_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = _write_musicxml(root / "score.musicxml", 7, existing_new_page_at=2)
            out = proof_sheet.prepare_paginated_musicxml(src, [3, 2, 2], root / "paginated.musicxml")
            measures = ElementTree.parse(str(out)).getroot().findall(".//measure")
            new_pages = [
                i + 1
                for i, m in enumerate(measures)
                if any(pr.get("new-page") == "yes" for pr in m.findall("print"))
            ]
            self.assertEqual(new_pages, [4, 6])

    def test_reconcile_page_measure_counts_handles_exact_dropped_tail_and_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            counts, notes = proof_sheet.reconcile_page_measure_counts([10, 12], 22)
            self.assertEqual(counts, [10, 12])
            self.assertEqual(notes, [])

            report = root / "report.json"
            report.write_text(
                json.dumps(
                    {
                        "trace": [
                            {"pass": "drop_trailing_duplicate_measure", "changed": 1},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            counts, notes = proof_sheet.reconcile_page_measure_counts([10, 12], 21, report)
            self.assertEqual(counts, [10, 11])
            self.assertTrue(any("trailing duplicate" in note for note in notes))

            counts, notes = proof_sheet.reconcile_page_measure_counts([10, 12], 19, report)
            self.assertIsNone(counts)
            self.assertTrue(any("cannot map" in note for note in notes))

    def test_group_overflow_pages_merges_split_scan_page_using_svg_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pngs = [root / f"p-{i}.png" for i in range(1, 4)]
            svgs = [
                _synthetic_svg(root / "p-1.svg", bars=2),
                _synthetic_svg(root / "p-2.svg", bars=2),
                _synthetic_svg(root / "p-3.svg", bars=3),
            ]
            groups = proof_sheet._group_overflow_pages(pngs, svgs, [4, 3])
            self.assertIsNotNone(groups)
            self.assertEqual([len(g[0]) for g in groups], [2, 1])

    def test_review_sheets_renders_delivered_mscz_without_calling_raw_page_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p1_xml = _write_musicxml(root / "p1.musicxml", 2)
            p2_xml = _write_musicxml(root / "p2.musicxml", 2)
            p1_scan = _synthetic_scan(root / "p1.png", bars=2)
            p2_scan = _synthetic_scan(root / "p2.png", bars=2)
            for stem in ("p1", "p2"):
                (root / f"{stem}.reading.json").write_text(
                    json.dumps({"tokens": {}, "changes": []}), encoding="utf-8"
                )
            mscz = _write_mscz(root / "score.mscz", 4, title="Delivered Piece")
            r1_png = _synthetic_scan(root / "render-1.png", bars=2)
            r2_png = _synthetic_scan(root / "render-2.png", bars=2)
            r1_svg = _synthetic_svg(root / "render-1.svg", bars=2)
            r2_svg = _synthetic_svg(root / "render-2.svg", bars=2)

            pages = [
                proof_sheet.SheetPage("p1", p1_scan, p1_xml, root / "p1.reading.json", offset=0),
                proof_sheet.SheetPage("p2", p2_scan, p2_xml, root / "p2.reading.json", offset=2),
            ]
            fake_rendered = [
                {
                    "png_pages": [r1_png],
                    "svg_pages": [r1_svg],
                    "render_mode": "score-mscz",
                    "source_path": str(mscz),
                    "source_label": "score.mscz",
                    "delivered_measures": 2,
                    "warnings": [],
                },
                {
                    "png_pages": [r2_png],
                    "svg_pages": [r2_svg],
                    "render_mode": "score-mscz",
                    "source_path": str(mscz),
                    "source_label": "score.mscz",
                    "delivered_measures": 2,
                    "warnings": [],
                },
            ]
            with (
                patch.object(
                    proof_sheet, "render_paginated_score", return_value=(fake_rendered, [])
                ) as whole_render,
                patch.object(
                    proof_sheet, "render_page_musicxml", side_effect=AssertionError("must not render raw pages")
                ),
            ):
                summary = proof_sheet.review_sheets(
                    pages,
                    root / "sheets",
                    musescore="musescore",
                    score_path=mscz,
                )

            whole_render.assert_called_once()
            self.assertEqual(summary["render_mode"], "score-mscz")
            self.assertEqual(summary["status"], "complete_no_issues")
            self.assertEqual(summary["pdf_cover"]["title"], "Delivered Piece")
            self.assertEqual(summary["pdf_cover"]["render_mode"], "score-mscz")
            for page_out in summary["outputs"]["pages"]:
                page_report = json.loads(Path(page_out["json"]).read_text(encoding="utf-8"))
                self.assertEqual(page_report["render_mode"], "score-mscz")
                self.assertTrue(page_report["aligned"])


if __name__ == "__main__":
    unittest.main()
