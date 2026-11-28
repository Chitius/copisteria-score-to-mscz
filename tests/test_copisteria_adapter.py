from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from scorepipe import copisteria
from scripts import convert as convert_script
from scripts import preflight as preflight_script


class CopisteriaAdapterTest(unittest.TestCase):
    def test_parse_page_range_variants_and_bounds(self):
        self.assertEqual(copisteria.parse_page_range(None, 5), (1, 5))
        self.assertEqual(copisteria.parse_page_range("3", 5), (3, 3))
        self.assertEqual(copisteria.parse_page_range("2-4", 5), (2, 4))
        self.assertEqual(copisteria.parse_page_range("-3", 5), (1, 3))
        self.assertEqual(copisteria.parse_page_range("3-", 5), (3, 5))
        with self.assertRaises(ValueError):
            copisteria.parse_page_range("4-2", 5)
        with self.assertRaises(ValueError):
            copisteria.parse_page_range("1-6", 5)

    def test_safe_page_stem_keeps_ascii_and_disambiguates_non_ascii(self):
        self.assertEqual(copisteria.safe_page_stem(Path("FirstStep.pdf")), "FirstStep")
        a = copisteria.safe_page_stem(Path("夜に駆ける.pdf"))
        b = copisteria.safe_page_stem(Path("千本桜.pdf"))
        self.assertTrue(a.isascii())
        self.assertTrue(b.isascii())
        self.assertNotEqual(a, b)
        self.assertEqual(a, copisteria.safe_page_stem(Path("夜に駆ける.pdf")))

    def test_extract_pdf_pages_applies_rotation_and_falls_back_to_pdftoppm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "Sample.pdf"
            pdf.write_bytes(b"%PDF-1.4")
            out = root / "pages"

            def fake_pdftoppm(_pdf, number, prefix, dpi):
                target = prefix.parent / f"{prefix.name}-{number}.png"
                Image.new("RGB", (40, 20), (255, 255, 255)).save(target)
                return [target]

            with (
                patch.object(copisteria, "pdf_page_count", return_value=2),
                patch.object(copisteria, "pdf_page_rotations", return_value={1: 0, 2: 90}),
                patch.object(copisteria, "pdf_page_sizes", return_value={}),
                patch.object(copisteria, "_run_pdfimages", return_value=[]),
                patch.object(copisteria, "_run_pdftoppm", side_effect=fake_pdftoppm),
            ):
                paths = copisteria.extract_pdf_pages(pdf, out)

            self.assertEqual([p.name for p in paths], ["Sample_p01.png", "Sample_p02_r90.png"])
            with Image.open(paths[0]) as first, Image.open(paths[1]) as second:
                self.assertEqual(first.mode, "L")
                self.assertEqual(first.size, (40, 20))
                self.assertEqual(second.mode, "L")
                self.assertEqual(second.size, (20, 40))

    def test_page_render_dpi_keeps_a4_and_caps_oversized_pages(self):
        # A4 at 300 dpi is the target; a 5x-A4 page (2976x4209 pt) must not rasterise to 217 MP.
        self.assertEqual(copisteria.page_render_dpi(595.28, 841.89), 300)
        self.assertEqual(copisteria.page_render_dpi(2976, 4209), 72)
        self.assertLessEqual(copisteria.page_render_dpi(11904, 16836), 18)
        self.assertEqual(copisteria.page_render_dpi(0, 0), 300)
        for width, height in ((2976, 4209), (11904, 16836), (595.28, 841.89)):
            dpi = copisteria.page_render_dpi(width, height)
            self.assertLessEqual(
                (width / 72 * dpi) * (height / 72 * dpi), copisteria.MAX_PAGE_PIXELS
            )

    def test_extract_pdf_pages_renders_oversized_page_with_pdftoppm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "Big.pdf"
            pdf.write_bytes(b"%PDF-1.4")
            out = root / "pages"
            seen = {}

            def forbidden_pdfimages(*_args, **_kwargs):
                raise AssertionError("an oversized page must not go through pdfimages")

            def fake_pdftoppm(_pdf, number, prefix, dpi):
                seen["dpi"] = dpi
                target = prefix.parent / f"{prefix.name}-{number}.png"
                Image.new("RGB", (30, 40), (255, 255, 255)).save(target)
                return [target]

            with (
                patch.object(copisteria, "pdf_page_count", return_value=1),
                patch.object(copisteria, "pdf_page_rotations", return_value={1: 0}),
                patch.object(copisteria, "pdf_page_sizes", return_value={1: (2976.0, 4209.0)}),
                patch.object(copisteria, "_run_pdfimages", side_effect=forbidden_pdfimages),
                patch.object(copisteria, "_run_pdftoppm", side_effect=fake_pdftoppm),
            ):
                paths = copisteria.extract_pdf_pages(pdf, out)

            self.assertEqual(seen["dpi"], 72)
            self.assertEqual([p.name for p in paths], ["Big_p01.png"])

    def test_extract_pdf_pages_falls_back_when_embedded_scan_is_a_decompression_bomb(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf = root / "Bomb.pdf"
            pdf.write_bytes(b"%PDF-1.4")
            out = root / "pages"
            real_open = Image.open
            calls = {"pdftoppm": 0}

            def fake_pdfimages(_pdf, _number, prefix):
                target = prefix.parent / f"{prefix.name}-000.png"
                Image.new("RGB", (8, 8), (255, 255, 255)).save(target)
                return [target]

            def fake_open(path, *args, **kwargs):
                if Path(path).name.endswith("-000.png"):
                    raise Image.DecompressionBombError("too many pixels")
                return real_open(path, *args, **kwargs)

            def fake_pdftoppm(_pdf, number, prefix, dpi):
                calls["pdftoppm"] += 1
                target = prefix.parent / f"{prefix.name}-{number}.png"
                Image.new("RGB", (30, 40), (255, 255, 255)).save(target)
                return [target]

            with (
                patch.object(copisteria, "pdf_page_count", return_value=1),
                patch.object(copisteria, "pdf_page_rotations", return_value={1: 0}),
                patch.object(copisteria, "pdf_page_sizes", return_value={1: (595.28, 841.89)}),
                patch.object(copisteria, "_run_pdfimages", side_effect=fake_pdfimages),
                patch.object(copisteria, "_run_pdftoppm", side_effect=fake_pdftoppm),
                patch("PIL.Image.open", side_effect=fake_open),
            ):
                paths = copisteria.extract_pdf_pages(pdf, out)

            self.assertEqual(calls["pdftoppm"], 1)
            self.assertEqual([p.name for p in paths], ["Bomb_p01.png"])
            with Image.open(paths[0]) as saved:
                self.assertEqual(saved.mode, "L")
                self.assertEqual(saved.size, (30, 40))

    def test_run_copisteria_invokes_upstream_pipeline_in_repo_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "copisteria"
            repo.mkdir()
            pdf = root / "score.pdf"
            pdf.write_bytes(b"%PDF-1.4")
            work = root / "work"
            recorded = {}

            def fake_extract(_pdf, out_dir, **_kwargs):
                out_dir.mkdir(parents=True, exist_ok=True)
                p1 = out_dir / "score_p01.png"
                p1.write_bytes(b"png")
                return [p1]

            def fake_subproc(cmd, cwd=None, **_kwargs):
                recorded["cmd"] = cmd
                recorded["cwd"] = cwd
                out_idx = cmd.index("--out") + 1
                raw_dir = Path(cmd[out_idx])
                raw_dir.mkdir(parents=True, exist_ok=True)
                (raw_dir / "score_p01.musicxml").write_text("<score-partwise/>", encoding="utf-8")
                return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

            with (
                patch.object(copisteria, "check_copisteria_import"),
                patch.object(copisteria, "extract_pdf_pages", side_effect=fake_extract),
                patch.object(copisteria.subprocess, "run", side_effect=fake_subproc),
            ):
                raw_dir, cmd = copisteria.run_copisteria(
                    pdf,
                    work,
                    omr_python="omr-py",
                    repo=repo,
                    detector="2m",
                    device="cuda",
                )

            self.assertEqual(raw_dir, (work / "copisteria").resolve())
            self.assertEqual(recorded["cwd"], str(repo.resolve()))
            self.assertEqual(cmd[:3], ["omr-py", "-m", "copisteria.pipeline"])
            self.assertIn("--detector", cmd)
            self.assertEqual(cmd[cmd.index("--detector") + 1], "2m")
            self.assertIn("--device", cmd)
            self.assertEqual(cmd[cmd.index("--device") + 1], "cuda")

    def test_convert_uses_builtin_adapter_without_external_converter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "copisteria"
            repo.mkdir()
            pdf = root / "source.pdf"
            pdf.write_bytes(b"%PDF-1.4")
            outdir = root / "out"
            raw_dir = outdir / "work" / "copisteria"
            raw_dir.mkdir(parents=True)
            (raw_dir / "source_p01.musicxml").write_text("<score-partwise/>", encoding="utf-8")

            def fake_run(command, cwd, tolerate=False):
                Path(command[command.index("-o") + 1]).write_text("musicxml", encoding="utf-8")
                Path(command[command.index("--report") + 1]).write_text("{}", encoding="utf-8")
                return 0, ""

            with (
                patch.object(
                    convert_script,
                    "_run_copisteria",
                    return_value=(raw_dir, ["omr-py", "-m", "copisteria.pipeline"]),
                ) as adapter,
                patch.object(convert_script, "_pdf_pages", return_value=1),
                patch.object(convert_script, "_run", side_effect=fake_run),
            ):
                code = convert_script.main(
                    [
                        str(pdf),
                        "--repo",
                        str(repo),
                        "--omr-python",
                        "omr-py",
                        "--detector",
                        "2m",
                        "--outdir",
                        str(outdir),
                        "--no-mscz",
                    ]
                )

            self.assertEqual(code, 0)
            adapter.assert_called_once()
            manifest = json.loads((outdir / "delivery.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["omr_command"], ["omr-py", "-m", "copisteria.pipeline"])

    def test_preflight_no_longer_requires_external_converter_or_music21(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "copisteria"
            (repo / "src").mkdir(parents=True)
            (repo / "models" / "small").mkdir(parents=True)
            (repo / "models" / "evidence-2m.pt").write_bytes(b"pt")
            (repo / "models" / "small" / "v7_obj-recall-30m_best.pt").write_bytes(b"pt")

            args = preflight_script.argparse.Namespace(
                repo=str(repo),
                converter=None,
                python="py",
                omr_python="omr-py",
                musescore=None,
            )
            probes = []

            def fake_run(interpreter, code):
                probes.append((interpreter, code))
                return True, "ok"

            with (
                patch.object(preflight_script, "_run", side_effect=fake_run),
                patch.object(preflight_script, "_find_musescore", return_value=None),
            ):
                checks = preflight_script.probe(args, {})

            names = {check.name: check for check in checks}
            self.assertNotIn("copisteria converter", names)
            self.assertNotIn("copisteria + music21", names)
            self.assertIn("copisteria import", names)
            self.assertTrue(names["copisteria weights"].ok)
            self.assertIn("2 .pt file(s)", names["copisteria weights"].detail)
            self.assertFalse(any("music21" in code for _, code in probes))


if __name__ == "__main__":
    unittest.main()
