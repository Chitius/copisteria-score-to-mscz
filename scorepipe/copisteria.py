"""Built-in adapter for running upstream ``copisteria`` per page on a PDF.

Replaces the legacy external ``copisteria-to-musicxml/scripts/convert.py`` wrapper so this
repository only depends on upstream ``kobimusic/copisteria``, poppler, and Pillow:

1. Extract each PDF page into ``<work>/pages/<stem>_pNN.png`` (using ``pdfimages`` when a page
   holds a single embedded scan, otherwise ``pdftoppm`` at 300 dpi, applying PDF ``/Rotate``).
   A page whose physical size would rasterise past :data:`MAX_LONG_SIDE` /
   :data:`MAX_PAGE_PIXELS` is rendered at a capped dpi instead: some exports are a 5x-A4 page
   (2976x4209 pt) whose embedded scan is 217 MP, which Pillow refuses to open and which the
   OMR reader does not need.
2. Run ``python -m copisteria.pipeline`` over those PNGs with ``cwd=<copisteria_repo>`` so
   per-page ``.musicxml``, ``.reading.json`` and ``.html`` land in ``<work>/copisteria/`` and
   cached ``.dets_*.json`` detections stay beside the page images in ``<work>/pages/``.
"""

from __future__ import annotations

import hashlib
import math
import re
import shutil
import subprocess
from pathlib import Path

RENDER_DPI = 300
#: Long-side ceiling for an extracted page: 4200 px is A4 at ~360 dpi, so an A4 page keeps the
#: requested dpi and an oversized page is rendered smaller instead of exploding into pixels.
MAX_LONG_SIDE = 4200
#: Hard pixel ceiling for the raster handed to Pillow/OpenCV (A4 at 300 dpi is 8.7 MP).
MAX_PAGE_PIXELS = 40_000_000


def pdf_page_count(pdf: Path) -> int:
    binary = shutil.which("pdfinfo")
    if not binary:
        raise RuntimeError("pdfinfo not found; install poppler to extract pages from a PDF")
    completed = subprocess.run(
        [binary, str(pdf)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"pdfinfo failed ({completed.returncode}): {(completed.stderr or '').strip()[:300]}")
    match = re.search(r"^Pages:\s+(\d+)", completed.stdout, re.MULTILINE)
    if not match:
        raise RuntimeError(f"could not read page count from pdfinfo output for {pdf}")
    return int(match.group(1))


def pdf_page_rotations(pdf: Path, first: int, last: int) -> dict[int, int]:
    binary = shutil.which("pdfinfo")
    if not binary:
        return {}
    completed = subprocess.run(
        [binary, "-f", str(first), "-l", str(last), str(pdf)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        return {}
    return {
        int(number): int(angle) % 360
        for number, angle in re.findall(r"^Page\s+(\d+)\s+rot:\s+(-?\d+)", completed.stdout, re.MULTILINE)
    }


def pdf_page_sizes(pdf: Path, first: int, last: int) -> dict[int, tuple[float, float]]:
    """Page width/height in PDF points; empty when ``pdfinfo`` is missing or fails."""
    binary = shutil.which("pdfinfo")
    if not binary:
        return {}
    completed = subprocess.run(
        [binary, "-f", str(first), "-l", str(last), str(pdf)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        return {}
    return {
        int(number): (float(width), float(height))
        for number, width, height in re.findall(
            r"^Page\s+(\d+)\s+size:\s+([\d.]+)\s+x\s+([\d.]+)\s+pts",
            completed.stdout,
            re.MULTILINE,
        )
    }


def page_render_dpi(width: float, height: float, requested: int = RENDER_DPI) -> int:
    """Raster dpi for one page, capped so an oversized page stays a sane raster.

    ``width``/``height`` are PDF points.  A 5x-A4 page (2976x4209 pt) would need ~217 MP at
    300 dpi: Pillow refuses to open that (``DecompressionBombError``) and the OMR reader gains
    nothing from it.  The same page at 72 dpi is 12.5 MP and reads like A4 at 360 dpi, which is
    the density the detector expects.  A normal A4 page keeps the requested 300 dpi.
    """
    if width <= 0 or height <= 0:
        return requested
    by_side = math.ceil(72 * MAX_LONG_SIDE / max(width, height))
    by_pixels = math.floor(72 * math.sqrt(MAX_PAGE_PIXELS / (width * height)))
    return max(1, min(requested, by_side, by_pixels))


def parse_page_range(page_range: str | None, total_pages: int) -> tuple[int, int]:
    """Parse ``None``, ``"3"``, or ``"2-5"`` into an inclusive 1-based ``(first, last)`` pair."""
    if total_pages < 1:
        raise ValueError(f"PDF has no pages ({total_pages})")
    if not page_range:
        return 1, total_pages
    text = page_range.strip()
    if "-" in text:
        low_text, _, high_text = text.partition("-")
        try:
            first = int(low_text.strip()) if low_text.strip() else 1
            last = int(high_text.strip()) if high_text.strip() else total_pages
        except ValueError as error:
            raise ValueError(f"invalid page range: {page_range!r}") from error
    else:
        try:
            first = last = int(text)
        except ValueError as error:
            raise ValueError(f"invalid page range: {page_range!r}") from error
    if first < 1 or last < first or last > total_pages:
        raise ValueError(f"page range {first}-{last} is outside 1-{total_pages}")
    return first, last


def safe_page_stem(pdf: Path) -> str:
    """ASCII-safe prefix for extracted page PNGs.

    OpenCV and ``pdfimages`` on Windows can fail on non-ASCII paths, and two different CJK PDFs
    would otherwise collapse to the same ``score`` stem.  Keep plain ASCII stems readable and add
    a short deterministic hash whenever characters were stripped or replaced.
    """
    raw = pdf.stem
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", raw).strip("_")
    if cleaned and cleaned == raw:
        return cleaned
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    base = cleaned[:32].strip("_") if cleaned else "score"
    return f"{base}_{digest}"


def _run_pdfimages(pdf: Path, number: int, prefix: Path) -> list[Path]:
    binary = shutil.which("pdfimages")
    if not binary:
        return []
    completed = subprocess.run(
        [binary, "-png", "-f", str(number), "-l", str(number), str(pdf), str(prefix)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    parts = sorted(prefix.parent.glob(f"{prefix.name}-*.png"))
    if completed.returncode == 0 and len(parts) == 1:
        return parts
    for part in parts:
        part.unlink(missing_ok=True)
    return []


def _run_pdftoppm(pdf: Path, number: int, prefix: Path, dpi: int) -> list[Path]:
    binary = shutil.which("pdftoppm")
    if not binary:
        raise RuntimeError("pdftoppm not found; install poppler to render PDF pages")
    completed = subprocess.run(
        [
            binary,
            "-r",
            str(dpi),
            "-gray",
            "-png",
            "-f",
            str(number),
            "-l",
            str(number),
            str(pdf),
            str(prefix),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    parts = sorted(prefix.parent.glob(f"{prefix.name}-*.png"))
    if completed.returncode != 0 or not parts:
        raise RuntimeError(
            f"pdftoppm failed on page {number} of {pdf.name}: {(completed.stderr or '').strip()[:300]}"
        )
    return parts


def _extract_page_parts(
    pdf: Path, number: int, prefix: Path, dpi: int, page_dpi: int
) -> list[Path]:
    """Raw raster pieces for one page: the embedded scan, or ``pdftoppm`` when that is unusable.

    ``page_dpi < dpi`` means the page is physically oversized, so its embedded scan would be
    enormous too; render it directly at the capped dpi.  A page the size of A4 still goes through
    ``pdfimages`` (native scan, no resampling), but a scan that still trips Pillow's decompression
    guard falls back to ``pdftoppm`` at ``page_dpi`` instead of crashing the run.
    """
    from PIL import Image

    if page_dpi < dpi:
        return _run_pdftoppm(pdf, number, prefix, page_dpi)
    parts = _run_pdfimages(pdf, number, prefix)
    if not parts:
        return _run_pdftoppm(pdf, number, prefix, page_dpi)
    try:
        with Image.open(parts[0]) as probe:
            pixels = probe.width * probe.height
            probe.verify()
    except (Image.DecompressionBombError, OSError):
        pixels = None
    if pixels is None or pixels > MAX_PAGE_PIXELS:
        for part in parts:
            part.unlink(missing_ok=True)
        return _run_pdftoppm(pdf, number, prefix, page_dpi)
    return parts


def extract_pdf_pages(
    pdf: str | Path,
    out_dir: str | Path,
    *,
    page_range: str | None = None,
    dpi: int = RENDER_DPI,
) -> list[Path]:
    """Write requested PDF pages as greyscale PNGs inside ``out_dir``."""
    from PIL import Image

    pdf_path = Path(pdf).resolve()
    target_dir = Path(out_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    total = pdf_page_count(pdf_path)
    first, last = parse_page_range(page_range, total)
    rotations = pdf_page_rotations(pdf_path, first, last)
    sizes = pdf_page_sizes(pdf_path, first, last)
    prefix_stem = safe_page_stem(pdf_path)
    width = max(2, len(str(last)))

    extracted: list[Path] = []
    for number in range(first, last + 1):
        turn = rotations.get(number, 0)
        stem = f"{prefix_stem}_p{number:0{width}d}" + (f"_r{turn}" if turn else "")
        target = target_dir / f"{stem}.png"
        if not target.is_file():
            page_width, page_height = sizes.get(number, (0.0, 0.0))
            page_dpi = page_render_dpi(page_width, page_height, dpi)
            temp_prefix = target_dir / f".{stem}"
            parts = _extract_page_parts(pdf_path, number, temp_prefix, dpi, page_dpi)
            try:
                with Image.open(parts[0]) as image:
                    grey = image.convert("L")
                    if turn:
                        grey = grey.rotate(-turn, expand=True)
                    grey.save(target)
            finally:
                for part in parts:
                    part.unlink(missing_ok=True)
        extracted.append(target)
    return extracted


def check_copisteria_import(interpreter: str) -> None:
    completed = subprocess.run(
        [interpreter, "-c", "import copisteria"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(
            f"OMR interpreter cannot import copisteria ({interpreter}): {detail[:400]}"
        )


def build_copisteria_command(
    omr_python: str,
    page_paths: list[Path],
    raw_dir: Path,
    *,
    detector: str = "28m",
    device: str | None = None,
) -> list[str]:
    command = [
        omr_python,
        "-m",
        "copisteria.pipeline",
        *[str(path) for path in page_paths],
        "--detector",
        detector,
        "--out",
        str(raw_dir),
    ]
    if device:
        command.extend(["--device", device])
    return command


def run_copisteria(
    pdf: str | Path,
    work_dir: str | Path,
    *,
    omr_python: str,
    repo: str | Path,
    detector: str = "28m",
    device: str | None = None,
    page_range: str | None = None,
    dpi: int = RENDER_DPI,
) -> tuple[Path, list[str]]:
    """Extract PDF pages and run upstream ``copisteria.pipeline`` into ``<work_dir>/copisteria``."""
    repo_path = Path(repo).resolve()
    if not repo_path.is_dir():
        raise RuntimeError(f"copisteria repository not found: {repo_path}")
    check_copisteria_import(omr_python)

    work = Path(work_dir).resolve()
    pages_dir = work / "pages"
    raw_dir = work / "copisteria"
    raw_dir.mkdir(parents=True, exist_ok=True)

    page_paths = extract_pdf_pages(pdf, pages_dir, page_range=page_range, dpi=dpi)
    command = build_copisteria_command(
        omr_python, page_paths, raw_dir, detector=detector, device=device
    )
    print("+ " + " ".join(command))
    completed = subprocess.run(
        command,
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    if output.strip():
        print(output.rstrip())
    if completed.returncode != 0:
        raise RuntimeError(
            f"copisteria.pipeline failed ({completed.returncode}); "
            f"verify --repo ({repo_path}) and --omr-python ({omr_python})"
        )
    xmls = sorted(raw_dir.glob("*.musicxml"))
    if not xmls:
        raise RuntimeError(f"copisteria.pipeline produced no page MusicXML in {raw_dir}")
    return raw_dir, command
