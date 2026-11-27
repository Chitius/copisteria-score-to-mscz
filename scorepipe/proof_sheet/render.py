"""MusicXML/MSCZ header & pagination preparation and MuseScore rendering (PNG & SVG)."""

from __future__ import annotations

import copy as copy_module
import shutil
import subprocess
from pathlib import Path
from typing import Sequence
from xml.etree import ElementTree

from .models import A4_HEIGHT, A4_WIDTH, RENDER_DPI, TALL_PAGE_HEIGHT
from .svg import parse_svg_measures


def _position_credit(credit) -> None:
    """Give a credit-words element the page-1 position MuseScore needs to draw it at the top.

    MuseScore stacks a credit without ``default-y`` at the bottom of the page (measured: a garbled
    strip under the last system), so the copied credits are placed like the previous skill's
    ``write_credits``: title centred near the top, composer right-aligned under it.
    """
    words = credit.find("credit-words")
    if words is None or words.get("default-y"):
        return
    kind = (credit.findtext("credit-type") or "title").strip()
    if kind == "title":
        x, y, justify, size = A4_WIDTH // 2, A4_HEIGHT - 170, "center", "28"
    elif kind == "subtitle":
        x, y, justify, size = A4_WIDTH // 2, A4_HEIGHT - 260, "center", "16"
    elif kind == "lyricist":
        x, y, justify, size = A4_WIDTH - 150, A4_HEIGHT - 250, "right", "12"
    elif kind == "arranger":
        x, y, justify, size = A4_WIDTH - 150, A4_HEIGHT - 330, "right", "12"
    else:
        x, y, justify, size = A4_WIDTH - 150, A4_HEIGHT - 250, "right", "12"
    words.set("default-x", str(x))
    words.set("default-y", str(y))
    words.set("justify", justify)
    words.set("valign", "top")
    words.set("font-size", size)


def _join_role_credits(root, credits: list) -> None:
    """Merge composer/arranger/transcriber credits into the first one, newline-separated."""
    roles = [
        credit
        for credit in credits
        if (credit.findtext("credit-type") or "").strip() in ("composer", "arranger", "transcriber")
        and credit.find("credit-words") is not None
    ]
    if len(roles) < 2:
        return
    first = roles[0]
    words = first.find("credit-words")
    lines = []
    for credit in roles:
        text = (credit.find("credit-words").text or "").strip()
        if text:
            lines.append(text)
    if not lines:
        return
    words.text = "\n".join(lines)
    for credit in roles[1:]:
        root.remove(credit)


def copy_header(source: Path, page: Path, target: Path) -> list[tuple[str, str]]:
    """Copy ``work``/``identification``/``credit`` from the merged score into a page copy.

    A page MusicXML is what the reader wrote for that page; the title block lives in the merged
    score (``apply_credits_facts``) or was copied into the first page by the conversion step.  The
    sheet renders each page on its own, so without this the first page's render has no title while
    the scan does.  Only header elements are copied -- notes are never touched.

    Returns the ``(credit-type, credit-words)`` pairs that were added.
    """
    source_root = ElementTree.parse(str(source)).getroot()
    page_root = ElementTree.parse(str(page)).getroot()
    added: list[tuple[str, str]] = []

    for index, tag in enumerate(("work", "identification")):
        element = source_root.find(tag)
        if element is None:
            continue
        existing = page_root.find(tag)
        if existing is not None:
            page_root.remove(existing)
        # MusicXML order: work, movement-number, movement-title, identification, ..., credit,
        # part-list.  Insert by position so `identification` never lands before `work`.
        page_root.insert(index, copy_module.deepcopy(element))

    credits = source_root.findall("credit")
    if credits:
        for credit in page_root.findall("credit"):
            page_root.remove(credit)
        part_list = page_root.find("part-list")
        index = list(page_root).index(part_list) if part_list is not None else len(page_root)
        copied = []
        for credit in credits:
            element = copy_module.deepcopy(credit)
            element.set("page", element.get("page") or "1")
            _position_credit(element)
            page_root.insert(index, element)
            index += 1
            copied.append(element)
        # MuseScore puts every right-justified credit on the same baseline, so a separate composer
        # and arranger line print on top of each other ("Hans Zimmer" over "PianiCast").  Join them
        # into one credit with a newline, which is how its own title frame spells the pair.
        _join_role_credits(page_root, copied)
        added = [
            (
                (element.findtext("credit-type") or "").strip(),
                (element.findtext("credit-words") or "").strip(),
            )
            for element in copied
            if element in list(page_root)
        ]

    ElementTree.ElementTree(page_root).write(target, encoding="utf-8", xml_declaration=True)
    return added


def _page_sort_key(path: Path) -> tuple[int, str]:
    """Sort MuseScore/pdftoppm page outputs numerically (``-1``, ``-2``, ..., ``-10``)."""
    stem = path.stem
    if "-" in stem:
        suffix = stem.rsplit("-", 1)[1]
        if suffix.isdigit():
            return int(suffix), path.name
    return 0, path.name


def _write_tall_style(out_dir: Path) -> Path:
    style = out_dir / "onepage.mss"
    style.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<museScore version="4.00">\n  <Style>\n'
        "    <pageWidth>8.27</pageWidth>\n"
        f"    <pageHeight>{TALL_PAGE_HEIGHT:.2f}</pageHeight>\n"
        "    <spatium>1.35</spatium>\n"
        "  </Style>\n</museScore>\n",
        encoding="utf-8",
    )
    return style


def _run_musescore(
    source: Path, musescore: str, out_dir: Path, target: Path, *, tall: bool
) -> subprocess.CompletedProcess[str]:
    extra: list[str] = []
    if tall:
        style = _write_tall_style(out_dir)
        extra = ["-S", str(style)]
    return subprocess.run(
        [musescore, "-f", *extra, "-o", str(target), str(source)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def prepare_paginated_mscz(
    mscz_path: Path, page_counts: Sequence[int], out_path: Path
) -> Path:
    """Copy a delivered ``.mscz`` and force page breaks to match ``page_counts``."""
    from ..core.mscz import MsczArchive

    archive = MsczArchive.open(mscz_path)
    staves = archive.document.staves()
    if not staves:
        raise ValueError(f"{mscz_path}: mscz has no staves with measures")
    for staff in staves:
        for measure in staff.findall("Measure"):
            for layout_break in list(measure.findall("LayoutBreak")):
                if (layout_break.findtext("subtype") or "").strip() == "page":
                    measure.remove(layout_break)
    measures = staves[0].findall("Measure")
    expected = sum(page_counts)
    if len(measures) != expected:
        raise ValueError(
            f"{mscz_path}: expected {expected} measures for pagination, found {len(measures)}"
        )
    running = 0
    for count in page_counts[:-1]:
        running += count
        if 0 < running <= len(measures):
            target = measures[running - 1]
            layout_break = ElementTree.Element("LayoutBreak")
            ElementTree.SubElement(layout_break, "subtype").text = "page"
            target.insert(0, layout_break)
    out_path = Path(out_path)
    archive.save(out_path)
    return out_path


def prepare_paginated_musicxml(
    musicxml_path: Path, page_counts: Sequence[int], out_path: Path
) -> Path:
    """Copy a repaired MusicXML and insert ``<print new-page="yes"/>`` at scan page boundaries."""
    root = ElementTree.parse(str(musicxml_path)).getroot()
    parts = root.findall("part")
    if not parts:
        raise ValueError(f"{musicxml_path}: MusicXML has no <part>")
    expected = sum(page_counts)
    for part in parts:
        measures = part.findall("measure")
        if len(measures) != expected:
            part_id = part.get("id") or "P1"
            raise ValueError(
                f"{musicxml_path}: part {part_id} expected {expected} measures for pagination, "
                f"found {len(measures)}"
            )
        for measure in measures:
            for print_node in measure.findall("print"):
                print_node.attrib.pop("new-page", None)
        running = 0
        for count in page_counts[:-1]:
            running += count
            if 0 < running < len(measures):
                target = measures[running]
                print_node = target.find("print")
                if print_node is None:
                    print_node = ElementTree.Element("print")
                    target.insert(0, print_node)
                print_node.set("new-page", "yes")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ElementTree.ElementTree(root).write(out_path, encoding="utf-8", xml_declaration=True)
    return out_path


def _group_overflow_pages(
    png_pages: Sequence[Path],
    svg_pages: Sequence[Path],
    page_counts: Sequence[int],
) -> list[tuple[list[Path], list[Path]]] | None:
    """Group rendered pages back onto the original scan pages when a dense page split in two."""
    expected_pages = len(page_counts)
    if len(png_pages) == expected_pages:
        return [
            ([png_pages[index]], [svg_pages[index]] if len(svg_pages) == len(png_pages) else [])
            for index in range(expected_pages)
        ]
    if len(png_pages) < expected_pages or len(svg_pages) != len(png_pages):
        return None
    svg_counts = []
    for svg in svg_pages:
        try:
            geometry = parse_svg_measures(svg)
            svg_counts.append(sum(len(system["cells"]) for system in geometry["systems"]))
        except Exception:  # noqa: BLE001 - cannot group reliably without SVG geometry
            return None
    groups: list[tuple[list[Path], list[Path]]] = []
    cursor = 0
    total_rendered = len(png_pages)
    for page_index, target in enumerate(page_counts):
        remaining_scan = expected_pages - page_index - 1
        max_end = total_rendered - remaining_scan
        if cursor >= max_end:
            return None
        if page_index == expected_pages - 1:
            groups.append((list(png_pages[cursor:]), list(svg_pages[cursor:])))
            cursor = total_rendered
            break
        acc = 0
        start = cursor
        while cursor < max_end:
            acc += svg_counts[cursor]
            cursor += 1
            if acc >= target:
                break
        groups.append((list(png_pages[start:cursor]), list(svg_pages[start:cursor])))
    return groups if len(groups) == expected_pages and cursor == total_rendered else None


def render_paginated_score(
    score_path: Path,
    page_counts: Sequence[int],
    musescore: str,
    out_dir: Path,
) -> tuple[list[dict], list[str]]:
    """Render the delivered ``.mscz`` or ``.musicxml`` once, paginated to match the scan pages."""
    score_path = Path(score_path)
    render_dir = Path(out_dir) / "_render" / "_score"
    if render_dir.exists():
        shutil.rmtree(render_dir, ignore_errors=True)
    render_dir.mkdir(parents=True, exist_ok=True)

    is_mscz = score_path.suffix.lower() == ".mscz"
    if is_mscz:
        paginated = prepare_paginated_mscz(score_path, page_counts, render_dir / "paginated.mscz")
        mode = "score-mscz"
    else:
        paginated = prepare_paginated_musicxml(
            score_path, page_counts, render_dir / "paginated.musicxml"
        )
        mode = "score-musicxml"

    warnings: list[str] = []
    used_tall = False
    png_pages = _render(paginated, musescore, render_dir, tall=False)
    if len(png_pages) != len(page_counts):
        used_tall = True
        png_pages = _render(paginated, musescore, render_dir, tall=True)

    svg_pages: list[Path] = []
    try:
        svg_pages = _render_svg(paginated, musescore, render_dir, tall=used_tall)
    except Exception as error:  # noqa: BLE001 - the ink fallback still works
        warnings.append(f"SVG export unavailable ({error}); using ink barline detection")
    if svg_pages and len(svg_pages) != len(png_pages):
        warnings.append(
            f"SVG export produced {len(svg_pages)} page(s) for {len(png_pages)} render page(s); "
            "using ink barline detection"
        )
        svg_pages = []

    groups = _group_overflow_pages(png_pages, svg_pages, page_counts)
    if groups is None:
        raise RuntimeError(
            f"delivered score rendered as {len(png_pages)} page(s) for {len(page_counts)} scan page(s)"
        )

    entries: list[dict] = []
    for (page_pngs, page_svgs), delivered_measures in zip(groups, page_counts):
        entries.append(
            {
                "png_pages": page_pngs,
                "svg_pages": page_svgs,
                "render_mode": mode,
                "source_path": str(score_path),
                "source_label": score_path.name,
                "delivered_measures": delivered_measures,
                "warnings": list(warnings),
            }
        )
    return entries, warnings


def render_page_svg(musicxml: Path, musescore: str, out_dir: Path) -> list[Path]:
    """Export the page's MusicXML to SVG; MuseScore writes the exact barline geometry into it."""
    pages = _render_svg(musicxml, musescore, out_dir, tall=False)
    if len(pages) > 1:
        pages = _render_svg(musicxml, musescore, out_dir, tall=True)
    return pages


def _render_svg(musicxml: Path, musescore: str, out_dir: Path, *, tall: bool) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{musicxml.stem}_svg.svg"
    for stale in list(out_dir.glob(f"{musicxml.stem}_svg-*.svg")) + [target]:
        stale.unlink(missing_ok=True)
    completed = _run_musescore(musicxml, musescore, out_dir, target, tall=tall)
    pages = sorted(out_dir.glob(f"{musicxml.stem}_svg-*.svg"), key=_page_sort_key)
    if not pages and target.is_file():
        pages = [target]
    if not pages:
        raise RuntimeError(
            f"MuseScore wrote no SVG for {musicxml.name}: {(completed.stderr or '').strip()[:300]}"
        )
    return pages


def render_page_musicxml(musicxml: Path, musescore: str, out_dir: Path) -> list[Path]:
    """Render one page's MusicXML; retry on a tall page when MuseScore splits it in two."""
    pages = _render(musicxml, musescore, out_dir, tall=False)
    if len(pages) > 1:
        pages = _render(musicxml, musescore, out_dir, tall=True)
    return pages


def _render(musicxml: Path, musescore: str, out_dir: Path, *, tall: bool) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf = out_dir / f"{musicxml.stem}.pdf"
    for stale in list(out_dir.glob(f"{musicxml.stem}_render-*.png")) + [pdf]:
        stale.unlink(missing_ok=True)
    completed = _run_musescore(musicxml, musescore, out_dir, pdf, tall=tall)
    if not pdf.is_file():
        raise RuntimeError(
            f"MuseScore wrote no PDF for {musicxml.name}: {(completed.stderr or '').strip()[:300]}"
        )
    prefix = out_dir / f"{musicxml.stem}_render"
    rasterize = shutil.which("pdftoppm")
    if not rasterize:
        raise RuntimeError("pdftoppm is required to rasterise the render")
    raster = subprocess.run(
        [rasterize, "-r", str(RENDER_DPI), "-png", str(pdf), str(prefix)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    pages = sorted(out_dir.glob(f"{prefix.name}-*.png"), key=_page_sort_key)
    if raster.returncode != 0 or not pages:
        raise RuntimeError(f"pdftoppm failed for {pdf.name}: {(raster.stderr or '').strip()[:300]}")
    return pages
