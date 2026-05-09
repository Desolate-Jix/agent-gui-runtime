from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from app.core.runtime_artifacts import build_review_overlay_path


REGION_COLOR = (255, 0, 0)
OCR_COLOR = (0, 102, 255)


def render_review_overlay(
    *,
    trace_path: str | Path,
    region_layer: str = "vision_provider_raw",
    include_regions: bool = True,
    include_ocr: bool = True,
    label_regions: bool = True,
    label_ocr: bool = False,
) -> dict[str, Any]:
    trace_file = Path(trace_path)
    trace_payload = json.loads(trace_file.read_text(encoding="utf-8"))
    result = trace_payload.get("result") or {}
    image_path = Path(str(result.get("image_path") or ""))
    if not image_path.exists():
        raise FileNotFoundError(f"image referenced by trace does not exist: {image_path}")

    provider_layer = _find_layer(result, region_layer)
    ocr_layer = _find_layer(result, "ocr_result")
    regions = list((provider_layer.get("result") or {}).get("regions") or [])
    ocr_matches = list((ocr_layer.get("result") or {}).get("matches") or [])

    output_path = build_review_overlay_path(name_hint=trace_file.stem, suffix="regions-ocr-overlay")

    with Image.open(image_path) as image:
        annotated = image.convert("RGB")
        draw = ImageDraw.Draw(annotated)
        font = ImageFont.load_default()

        if include_regions:
            for region in regions:
                _draw_region(draw, region, font=font, label_enabled=label_regions)

        if include_ocr:
            for index, match in enumerate(ocr_matches, start=1):
                _draw_ocr_match(draw, match, font=font, index=index, label_enabled=label_ocr)

        annotated.save(output_path)

    return {
        "trace_path": str(trace_file.resolve()),
        "image_path": str(image_path.resolve()),
        "output_path": str(output_path.resolve()),
        "include_regions": bool(include_regions),
        "include_ocr": bool(include_ocr),
        "label_regions": bool(label_regions),
        "label_ocr": bool(label_ocr),
        "region_count": len(regions) if include_regions else 0,
        "ocr_count": len(ocr_matches) if include_ocr else 0,
        "region_layer": region_layer,
        "ocr_layer": "ocr_result",
    }


def _find_layer(result: dict[str, Any], layer_name: str) -> dict[str, Any]:
    for item in result.get("layers") or []:
        if item.get("layer") == layer_name:
            return item
    raise ValueError(f"trace does not contain required layer: {layer_name}")


def _draw_region(draw: ImageDraw.ImageDraw, region: dict[str, Any], *, font: ImageFont.ImageFont, label_enabled: bool) -> None:
    diagonal = region.get("diagonal") or {}
    if diagonal:
        x1 = int(diagonal.get("x1", 0))
        y1 = int(diagonal.get("y1", 0))
        x2 = int(diagonal.get("x2", 0))
        y2 = int(diagonal.get("y2", 0))
    else:
        bbox = region.get("bbox") or {}
        x1 = int(bbox.get("x", 0))
        y1 = int(bbox.get("y", 0))
        x2 = x1 + int(bbox.get("w", bbox.get("width", 0)))
        y2 = y1 + int(bbox.get("h", bbox.get("height", 0)))
    draw.rectangle((x1, y1, x2, y2), outline=REGION_COLOR, width=4)
    if not label_enabled:
        return
    label = f"{region.get('region_id', '?')} | {region.get('label', 'region')}"
    _draw_label(draw, x1, y1, label, font=font, color=REGION_COLOR)


def _draw_ocr_match(
    draw: ImageDraw.ImageDraw,
    match: dict[str, Any],
    *,
    font: ImageFont.ImageFont,
    index: int,
    label_enabled: bool,
) -> None:
    bbox = match.get("bbox") or {}
    x = int(bbox.get("x", 0))
    y = int(bbox.get("y", 0))
    w = int(bbox.get("w", bbox.get("width", 0)))
    h = int(bbox.get("h", bbox.get("height", 0)))
    x2 = x + w
    y2 = y + h
    draw.rectangle((x, y, x2, y2), outline=OCR_COLOR, width=2)
    if not label_enabled:
        return
    label = f"{index} | {str(match.get('text') or '').strip()[:18]}"
    _draw_label(draw, x, y, label, font=font, color=OCR_COLOR)


def _draw_label(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    label: str,
    *,
    font: ImageFont.ImageFont,
    color: tuple[int, int, int],
) -> None:
    try:
        left, top, right, bottom = draw.textbbox((x, y), label, font=font)
        text_w = right - left
        text_h = bottom - top
    except Exception:
        text_w = max(48, len(label) * 7)
        text_h = 14
    text_y = max(0, y - text_h - 6)
    draw.rectangle((x, text_y, x + text_w + 8, text_y + text_h + 6), fill=color)
    draw.text((x + 4, text_y + 3), label, fill=(255, 255, 255), font=font)
