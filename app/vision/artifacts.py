from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from app.vision.schemas import VisionAnalyzeResponse, VisionRegion


ARTIFACTS_DIR = Path("logs/vision-regions")
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


def _safe_name(value: str, *, fallback: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value.strip())
    cleaned = cleaned.strip("_")
    return cleaned or fallback


def _label_text(region: VisionRegion) -> str:
    short_match = region.match_key[:12] if region.match_key else "no_match_key"
    return f"{region.region_id} | {region.role} | {short_match}"


def _draw_region_box(draw: ImageDraw.ImageDraw, region: VisionRegion, *, color: tuple[int, int, int], font: ImageFont.ImageFont) -> None:
    x1 = int(region.diagonal.x1)
    y1 = int(region.diagonal.y1)
    x2 = int(region.diagonal.x2)
    y2 = int(region.diagonal.y2)
    draw.rectangle((x1, y1, x2, y2), outline=color, width=3)

    label = _label_text(region)
    try:
        left, top, right, bottom = draw.textbbox((x1, y1), label, font=font)
        text_w = right - left
        text_h = bottom - top
    except Exception:
        text_w = max(40, len(label) * 7)
        text_h = 14
    text_y = max(0, y1 - text_h - 6)
    draw.rectangle((x1, text_y, x1 + text_w + 6, text_y + text_h + 4), fill=color)
    draw.text((x1 + 3, text_y + 2), label, fill=(255, 255, 255), font=font)


def _save_region_crop(image: Image.Image, region: VisionRegion, output_dir: Path) -> dict[str, Any]:
    x1 = int(region.diagonal.x1)
    y1 = int(region.diagonal.y1)
    x2 = int(region.diagonal.x2)
    y2 = int(region.diagonal.y2)
    crop = image.crop((x1, y1, x2, y2))

    region_name = _safe_name(region.region_id, fallback="region")
    crop_path = output_dir / f"{region_name}.png"
    crop.save(crop_path)

    annotated_crop = crop.copy()
    draw = ImageDraw.Draw(annotated_crop)
    font = ImageFont.load_default()
    draw.rectangle((0, 0, max(1, crop.width - 1), max(1, crop.height - 1)), outline=(255, 64, 64), width=2)
    label = _label_text(region)
    draw.rectangle((0, 0, min(crop.width, max(80, len(label) * 7)), 18), fill=(255, 64, 64))
    draw.text((3, 2), label, fill=(255, 255, 255), font=font)
    annotated_crop_path = output_dir / f"{region_name}.annotated.png"
    annotated_crop.save(annotated_crop_path)

    return {
        "region_id": region.region_id,
        "role": region.role,
        "label": region.label,
        "match_key": region.match_key,
        "bbox": region.bbox.to_dict(),
        "crop_path": str(crop_path.resolve()),
        "annotated_crop_path": str(annotated_crop_path.resolve()),
    }


def save_region_artifacts(image_path: str | Path, response: VisionAnalyzeResponse) -> dict[str, Any]:
    source_path = Path(image_path)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    stem = _safe_name(source_path.stem, fallback="capture")
    bundle_dir = ARTIFACTS_DIR / f"{timestamp}-{stem}"
    bundle_dir.mkdir(parents=True, exist_ok=True)

    with Image.open(source_path) as image:
        base = image.convert("RGB")
        annotated = base.copy()
        draw = ImageDraw.Draw(annotated)
        font = ImageFont.load_default()
        region_outputs: list[dict[str, Any]] = []

        for index, region in enumerate(response.regions):
            color = (
                (64 + (index * 53)) % 256,
                (96 + (index * 71)) % 256,
                (160 + (index * 37)) % 256,
            )
            _draw_region_box(draw, region, color=color, font=font)
            region_outputs.append(_save_region_crop(base, region, bundle_dir))

        annotated_path = bundle_dir / f"{stem}.annotated.png"
        annotated.save(annotated_path)

    manifest = {
        "source_image_path": str(source_path.resolve()),
        "annotated_image_path": str(annotated_path.resolve()),
        "region_count": len(response.regions),
        "regions": region_outputs,
    }
    manifest_path = bundle_dir / "regions.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "bundle_dir": str(bundle_dir.resolve()),
        "annotated_image_path": str(annotated_path.resolve()),
        "manifest_path": str(manifest_path.resolve()),
        "region_count": len(response.regions),
        "regions": region_outputs,
    }
