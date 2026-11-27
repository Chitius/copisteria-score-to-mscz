"""Sheet image drawing: measure tinting, badges, panel stacking, legend, and composition."""

from __future__ import annotations

from typing import Sequence

from .models import (
    BACKGROUND,
    CAPTION_BAND,
    CJK_RANGES,
    COLUMN_GAP,
    COLUMN_WIDTH,
    DESIGN_WIDTH,
    FOOTNOTE,
    LEGEND_MARGIN,
    LEGEND_PAD,
    RED,
    ROW_LABELS,
    TINT_ALPHA,
    YELLOW,
    _numpy,
)


def _needs_cjk(text: str) -> bool:
    return any(
        any(low <= ord(character) <= high for low, high in CJK_RANGES) for character in text
    )


def _font(size: int, text: str | None = None):
    """A font that can actually render ``text`` (CJK/Hangul files otherwise print as boxes)."""
    from PIL import ImageFont

    names = ["DejaVuSans.ttf", "arial.ttf", "segoeui.ttf"]
    if text and _needs_cjk(text):
        names = [
            "malgun.ttf",  # Windows Korean
            "malgunbd.ttf",
            "msyh.ttc",  # Windows Chinese
            "simsun.ttc",
            "YuGothR.ttc",  # Windows Japanese
            "msgothic.ttc",
        ] + names
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _badge(draw, text: str, box, colour, font, ink=None, image_size=None) -> None:
    """A filled badge above the measure, nudged until it covers no ink.

    A filled badge with white text is what the previous skill drew, and it stays readable over
    staff lines.  The nudge order matters: shift right first, then up, and stop at the bar's own
    right edge -- a label that drifts onto the neighbouring bar is worse than one that overlaps.
    """
    left, upper, right, lower = draw.textbbox((0, 0), text, font=font)
    text_width, text_height = right - left, lower - upper
    width_px = text_width + int(font.size * 0.7)
    height_px = text_height + int(font.size * 0.45)
    x0, y0, x1, _ = (int(value) for value in box)
    x = x0 + 2
    y = max(0, y0 - height_px - max(6, int(font.size * 0.55)))
    max_x = x1 - width_px + 6

    def ink_share(candidate: tuple[int, int]) -> float:
        if ink is None or image_size is None:
            return 0.0
        cx, cy = candidate
        x0c, y0c = max(0, cx), max(0, cy)
        x1c, y1c = min(image_size[0], cx + width_px), min(image_size[1], cy + height_px)
        if x1c <= x0c or y1c <= y0c:
            return 1.0
        patch = ink[y0c:y1c, x0c:x1c]
        return float(patch.mean()) if patch.size else 1.0

    for dx, dy in [(0, 0)] + [(int(width_px * step), 0) for step in (0.8, 1.6, 2.4)] + [(0, -int(height_px * 1.5))]:
        bx, by = x + dx, y + dy
        if bx < 0 or by < 0 or image_size is None:
            continue
        if bx + width_px > image_size[0] or by + height_px > image_size[1]:
            continue
        if max_x is not None and bx > max_x:
            continue
        if ink_share((bx, by)) < 0.04:
            x, y = bx, by
            break
    draw.rounded_rectangle(
        (x, y, x + width_px, y + height_px),
        radius=max(3, font.size // 5),
        fill=colour + (240,),
        outline=(255, 255, 255, 210),
        width=max(1, font.size // 12),
    )
    draw.text(
        (x + (width_px - text_width) / 2 - left, y + (height_px - text_height) / 2 - upper),
        text,
        font=font,
        fill=(255, 255, 255, 255),
    )


def annotate(
    image,
    cells: Sequence[tuple[int, int, int, int]],
    colours: dict[int, tuple],
    labels: dict[int, str],
):
    """Tint the given cells (0-based index) and label them with the global measure number."""
    numpy = _numpy()
    from PIL import Image, ImageDraw

    rgba = image.convert("RGBA")
    ink = numpy.asarray(image.convert("L")) < 190
    overlay = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = _font(max(13, round(22 * image.height / 1700)))
    thickness = max(2, font.size // 8)
    for index, colour in sorted(colours.items()):
        if index >= len(cells):
            continue
        box = cells[index]
        draw.rectangle(box, fill=colour + (TINT_ALPHA,), outline=colour + (210,), width=thickness)
        _badge(draw, labels.get(index, str(index + 1)), box, colour, font, ink=ink, image_size=image.size)
    return Image.alpha_composite(rgba, overlay).convert("RGB")


def stack(panels: Sequence):
    """Stack render pages into one column, keeping each panel's y offset."""
    from PIL import Image

    if len(panels) == 1:
        return panels[0], [0]
    width = max(panel.width for panel in panels)
    height = sum(panel.height for panel in panels) + 24 * (len(panels) - 1)
    canvas = Image.new("RGB", (width, height), BACKGROUND)
    offsets = []
    top = 0
    for panel in panels:
        canvas.paste(panel, (0, top))
        offsets.append(top)
        top += panel.height + 24
    return canvas, offsets


def legend_size(canvas, red: int, yellow: int, length_count: int, font, small, *, scale: float = 1.0) -> tuple[int, int]:
    """Wide enough for its longest line, so the text never spills out of the box."""
    from PIL import ImageDraw

    pad = round(LEGEND_PAD * scale)
    gap = round(28 * scale)
    probe = ImageDraw.Draw(canvas)
    rows = list(ROW_LABELS)
    if length_count:
        rows.append("also: bars whose voices do not add up to the metre (badge has ≠)")
    width = max(
        max(probe.textlength(text, font=font) for text in rows) + 2 * gap + round(16 * scale),
        probe.textlength(FOOTNOTE, font=small),
    )
    big = probe.textbbox((0, 0), rows[0], font=font)
    small_box = probe.textbbox((0, 0), FOOTNOTE, font=small)
    height = (
        2 * pad
        + len(rows) * (big[3] - big[1] + round(6 * scale))
        + round(8 * scale)
        + (small_box[3] - small_box[1])
    )
    return int(width) + 2 * pad + round(8 * scale), int(height)


def draw_legend(canvas, box, red: int, yellow: int, length_count: int, font, small, *, scale: float = 1.0) -> None:
    from PIL import ImageDraw

    pad = round(LEGEND_PAD * scale)
    gap = round(8 * scale)
    swatch_min = round(12 * scale)
    radius = max(4, round(8 * scale))
    outline = max(1, round(2 * scale))
    draw = ImageDraw.Draw(canvas, "RGBA")
    x0, y0, _, _ = box
    draw.rounded_rectangle(box, radius=radius, fill=(255, 255, 255, 236), outline=(150, 150, 150, 255), width=1)

    def row(text: str, colour: tuple[int, int, int], top: int) -> int:
        _, upper, _, lower = draw.textbbox((0, 0), text, font=font)
        text_height = lower - upper
        swatch = max(swatch_min, text_height)
        centre = top + text_height / 2
        draw.rectangle(
            (x0 + pad, centre - swatch / 2, x0 + pad + swatch, centre + swatch / 2),
            fill=colour + (80,),
            outline=colour + (220,),
            width=outline,
        )
        draw.text((x0 + pad + swatch + gap, top - upper), text, font=font, fill=(30, 30, 30, 255))
        return int(text_height) + round(6 * scale)

    line_height = row(ROW_LABELS[0], RED, y0 + pad)
    line_height = row(ROW_LABELS[1], YELLOW, y0 + pad + line_height)
    top = y0 + pad + 2 * line_height
    if length_count:
        top += row("also: bars whose voices do not add up to the metre (badge has ≠)", (28, 32, 40), top)
    draw.text((x0 + pad, top + gap), FOOTNOTE, font=small, fill=(90, 90, 90, 255))


def compose(
    left,
    right,
    left_caption: str,
    right_caption: str,
    *,
    red: int,
    yellow: int,
    length_count: int,
    width: int = COLUMN_WIDTH,
):
    """Two columns at one width, captions under each, legend in the caption band.

    Type sizes and paddings were tuned at ``DESIGN_WIDTH``; everything scales with the requested
    column width so a 300-dpi sheet does not end up with 15 px captions.
    """
    from PIL import Image, ImageDraw

    scale = width / DESIGN_WIDTH
    gap = round(COLUMN_GAP * scale)
    caption_band = round(CAPTION_BAND * scale)
    legend_margin = round(LEGEND_MARGIN * scale)

    def fit(panel):
        return panel.resize((width, max(1, round(panel.height * width / panel.width))), Image.LANCZOS)

    left, right = fit(left), fit(right)
    body = max(left.height, right.height)
    right_x = width + gap
    canvas = Image.new("RGB", (right_x + width, body + caption_band), BACKGROUND)
    canvas.paste(left, (0, 0))
    canvas.paste(right, (right_x, 0))

    draw = ImageDraw.Draw(canvas)
    rule_y = body + round(20 * scale)
    caption_font = _font(round(24 * scale))
    caption_ink = (72, 72, 68)
    for x, text in ((0, left_caption), (right_x, right_caption)):
        inset = round(44 * scale)
        draw.line((x + inset, rule_y, x + width - inset, rule_y), fill=(206, 204, 197), width=1)
        left_box = draw.textbbox((0, 0), text, font=caption_font)
        text_width = left_box[2] - left_box[0]
        draw.text(
            (x + (width - text_width) / 2 - left_box[0], rule_y + round(16 * scale) - left_box[1]),
            text,
            font=caption_font,
            fill=caption_ink,
        )
    draw.line(
        (right_x - gap // 2, 0, right_x - gap // 2, body + caption_band - round(24 * scale)),
        fill=(232, 230, 223),
    )

    font = _font(round(20 * scale))
    small = _font(round(15 * scale))
    legend_w, legend_h = legend_size(canvas, red, yellow, length_count, font, small, scale=scale)
    band_height = caption_band + legend_h + round(24 * scale)
    extended = Image.new("RGB", (canvas.width, body + band_height), BACKGROUND)
    extended.paste(canvas, (0, 0))
    canvas = extended
    draw = ImageDraw.Draw(canvas)
    draw.line(
        (right_x - gap // 2, 0, right_x - gap // 2, body + band_height - round(24 * scale)),
        fill=(232, 230, 223),
    )
    draw_legend(
        canvas,
        (legend_margin, body + caption_band + round(6 * scale), legend_margin + legend_w, body + caption_band + round(6 * scale) + legend_h),
        red,
        yellow,
        length_count,
        font,
        small,
        scale=scale,
    )
    return canvas
