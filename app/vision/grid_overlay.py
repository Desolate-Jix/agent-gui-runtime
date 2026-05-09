from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def create_grid_overlay_image(
    source_path: str | Path,
    output_path: str | Path,
    *,
    spacing: int = 100,
) -> dict[str, int | str]:
    source = Path(source_path)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(source) as image:
        base = image.convert("RGBA")
        overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        font = ImageFont.load_default()
        width, height = base.size

        major_spacing = max(20, int(spacing))
        minor_spacing = max(8, major_spacing // 4)

        _draw_grid(draw, width=width, height=height, spacing=minor_spacing, alpha=20)
        _draw_grid(draw, width=width, height=height, spacing=major_spacing, alpha=52)
        _draw_ticks(draw, width=width, height=height, spacing=major_spacing, font=font)

        result = Image.alpha_composite(base, overlay).convert("RGB")
        result.save(target)

    return {
        "width": width,
        "height": height,
        "spacing": major_spacing,
        "minor_spacing": minor_spacing,
        "output_path": str(target.resolve()),
    }


def _draw_grid(draw: ImageDraw.ImageDraw, *, width: int, height: int, spacing: int, alpha: int) -> None:
    color = (120, 170, 255, alpha)
    for x in range(0, width, spacing):
        draw.line((x, 0, x, height), fill=color, width=1)
    for y in range(0, height, spacing):
        draw.line((0, y, width, y), fill=color, width=1)


def _draw_ticks(draw: ImageDraw.ImageDraw, *, width: int, height: int, spacing: int, font: ImageFont.ImageFont) -> None:
    marker_fill = (245, 248, 255, 176)
    text_fill = (48, 92, 176, 255)
    line_fill = (48, 92, 176, 180)

    for x in range(0, width, spacing):
        draw.line((x, 0, x, min(12, height)), fill=line_fill, width=2)
        label = str(x)
        _draw_label(draw, x + 2, 2, label, font=font, marker_fill=marker_fill, text_fill=text_fill)

    for y in range(0, height, spacing):
        draw.line((0, y, min(12, width), y), fill=line_fill, width=2)
        label = str(y)
        _draw_label(draw, 2, y + 2, label, font=font, marker_fill=marker_fill, text_fill=text_fill)


def _draw_label(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    label: str,
    *,
    font: ImageFont.ImageFont,
    marker_fill: tuple[int, int, int, int],
    text_fill: tuple[int, int, int, int],
) -> None:
    try:
        left, top, right, bottom = draw.textbbox((x, y), label, font=font)
        text_w = right - left
        text_h = bottom - top
    except Exception:
        text_w = max(16, len(label) * 7)
        text_h = 12
    draw.rectangle((x, y, x + text_w + 4, y + text_h + 4), fill=marker_fill)
    draw.text((x + 2, y + 2), label, fill=text_fill, font=font)
