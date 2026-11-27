"""Image painting, legend drawing, side-by-side composition, and suspect crops."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .scoring import COLOURS, KINDS


def _paint(page, rows: Sequence[dict], suspects: Sequence[dict], *, show_low: bool = False):
    from PIL import Image, ImageDraw

    width, height = page.size
    overlay = Image.new("RGBA", page.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    line = max(1, round(max(width, height) / 900))
    for row in rows:
        if not row["box"]:
            continue
        if row["kind"] == "low" and not show_low:
            continue
        colour = COLOURS[row["kind"]]
        draw.rectangle(
            tuple(row["box"]),
            outline=colour + (110 if row["kind"] == "low" else 235,),
            width=line,
        )
    base_font = max(14, round(width / 70))
    for index, row in enumerate(suspects, start=1):
        x0, y0, x1, y1 = row["box"]
        colour = COLOURS[row["kind"]]
        # A fixed thick outline fills a small box solid; scale it to the box.
        thickness = max(2, min(line * 2 + 1, max(2, round(min(x1 - x0, y1 - y0) / 6))))
        draw.rectangle(tuple(row["box"]), outline=colour + (255,), width=thickness)
        font = _font(max(10, min(base_font, round(min(x1 - x0, y1 - y0) * 0.9))))
        _draw_index(draw, str(index), (x0, y0), colour, font, (width, height))
    result = page.convert("RGBA")
    result.alpha_composite(overlay)
    result = result.convert("RGB")
    _draw_legend(result, rows, show_low=show_low)
    return result


def _draw_index(draw, text: str, anchor: tuple[float, float], colour, font, size: tuple[int, int]) -> None:
    """A small white chip with the review number, kept inside the page."""
    width, height = size
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    text_width, text_height = right - left, bottom - top
    x = min(max(0, anchor[0]), max(0, width - text_width - 8))
    y = anchor[1] - text_height - 8
    if y < 0:
        y = min(height - text_height - 6, anchor[1] + 2)
    draw.rectangle(
        (x, y, x + text_width + 8, y + text_height + 6),
        fill=(255, 255, 255, 245),
        outline=colour + (255,),
        width=2,
    )
    draw.text((x + 4, y + 1), text, font=font, fill=(20, 20, 20, 255))


def _draw_legend(image, rows: Sequence[dict], *, show_low: bool = False) -> None:
    from PIL import ImageDraw

    draw = ImageDraw.Draw(image, "RGBA")
    width, _height = image.size
    pad = max(10, round(width / 120))
    font = _font(max(13, round(width / 85)))
    small = _font(max(11, round(width / 115)))
    labels = {
        "changed": "changed by context",
        "existence": "existence uncertain",
        "attribute": "low attribute probability",
        "low": "read normally (reference)",
    }
    entries = [(kind, f"{labels[kind]}: {sum(1 for row in rows if row['kind'] == kind)}") for kind in KINDS]
    footer = "numbered = review order, not a verdict"
    hidden = None if show_low else "blue boxes hidden; --show-low to show"
    widest = max([draw.textlength(text, font=font) for _, text in entries] + [draw.textlength(footer, font=small)])
    swatch = round(font.size * 1.05)
    box_width = int(widest) + swatch + pad * 4
    line_height = round(font.size * 1.6)
    box_height = pad * 2 + line_height * len(entries) + round(small.size * 1.8) * (2 if hidden else 1)
    x0, y0 = _legend_origin(image, box_width, box_height, pad)
    draw.rounded_rectangle(
        (x0, y0, x0 + box_width, y0 + box_height),
        radius=8,
        fill=(255, 255, 255, 238),
        outline=(150, 150, 150, 255),
        width=1,
    )
    top = y0 + pad
    for index, (_, text) in enumerate(entries):
        colour = COLOURS[KINDS[index]]
        draw.rectangle((x0 + pad, top, x0 + pad + swatch, top + swatch), fill=colour + (255,))
        draw.text((x0 + pad * 2 + swatch, top - 2), text, font=font, fill=(30, 30, 30, 255))
        top += line_height
    draw.text((x0 + pad, top + 2), footer, font=small, fill=(90, 90, 90, 255))
    if hidden:
        draw.text((x0 + pad, top + 2 + round(small.size * 1.8)), hidden, font=small, fill=(90, 90, 90, 255))


def _legend_origin(image, box_width: int, box_height: int, pad: int) -> tuple[int, int]:
    """Put the legend in the emptiest corner so it covers no music or title."""
    from PIL import ImageStat

    width, height = image.size
    candidates = [
        (pad, pad),
        (width - box_width - pad, pad),
        (pad, height - box_height - pad),
        (width - box_width - pad, height - box_height - pad),
    ]
    candidates = [(max(0, x), max(0, y)) for x, y in candidates]
    gray = image.convert("L")

    def darkness(origin: tuple[int, int]) -> float:
        x, y = origin
        box = (x, y, min(width, x + box_width), min(height, y + box_height))
        if box[2] - box[0] < 2 or box[3] - box[1] < 2:
            return 255.0
        return float(sum(ImageStat.Stat(gray.crop(box)).mean))

    return min(candidates, key=darkness)


def _compose(rendered: Path, annotated) -> object:
    """Put the render beside the painted scan, scaled to a common height."""
    from PIL import Image, ImageDraw

    left = Image.open(rendered).convert("RGB")
    right = annotated
    target = max(left.height, right.height)
    left = _fit_height(left, target)
    right = _fit_height(right, target)
    gap = max(12, target // 60)
    header = max(20, target // 40)
    canvas = Image.new("RGB", (left.width + gap + right.width, target + header), (255, 255, 255))
    canvas.paste(left, (0, header))
    canvas.paste(right, (left.width + gap, header))
    draw = ImageDraw.Draw(canvas)
    font = _font(max(12, header // 2))
    draw.text((8, 4), "render", font=font, fill=(60, 60, 60))
    draw.text((left.width + gap + 8, 4), "OMR page, coloured by doubt", font=font, fill=(60, 60, 60))
    draw.line((left.width + gap // 2, 0, left.width + gap // 2, target + header), fill=(180, 180, 180))
    return canvas


def _fit_height(image, height: int):
    if image.height == height:
        return image
    from PIL import Image

    scale = height / image.height
    return image.resize((max(1, round(image.width * scale)), height), Image.LANCZOS)


def _crops(page, suspects: Sequence[dict], out_dir: Path, stem: str, crops: int) -> list[str]:
    """Cut the context crops from the *painted* image, so a crop carries the box and its number."""
    if crops <= 0:
        return []
    crop_dir = out_dir / "crops"
    crop_dir.mkdir(exist_ok=True)
    width, height = page.size
    paths: list[str] = []
    for index, row in enumerate(suspects[:crops], start=1):
        x0, y0, x1, y1 = row["box"]
        pad = max(60, int((x1 - x0) * 1.8))
        box = (
            max(0, int(x0 - pad)),
            max(0, int(y0 - pad)),
            min(width, int(x1 + pad)),
            min(height, int(y1 + pad)),
        )
        patch = page.crop(box)
        if patch.width < 40 or patch.height < 40:
            continue
        patch = patch.resize((patch.width * 2, patch.height * 2), _resample())
        path = crop_dir / f"{stem}_s{index:02d}.png"
        patch.save(path)
        paths.append(str(path))
    return paths


def _resample():
    from PIL import Image

    return Image.LANCZOS


def _font(size: int):
    from PIL import ImageFont

    for name in ("DejaVuSans.ttf", "arial.ttf", "segoeui.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:  # Pillow < 10
        return ImageFont.load_default()
