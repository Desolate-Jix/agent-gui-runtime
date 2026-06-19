from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from PIL import Image


VISUAL_ASSET_CROP_EXPORT_CONTRACT = "visual_asset_crop_export_v1"


def build_visual_asset_crop_export(
    runtime_path_graph: dict[str, Any] | None,
    visual_assets: dict[str, Any] | None,
    *,
    source_image_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    graph = runtime_path_graph if isinstance(runtime_path_graph, dict) else {}
    assets_payload = copy.deepcopy(visual_assets if isinstance(visual_assets, dict) else {})
    source_path = Path(source_image_path)
    crop_dir = Path(output_dir)
    crop_dir.mkdir(parents=True, exist_ok=True)

    sample_bboxes = _representative_bboxes(graph)
    crop_count = 0
    with Image.open(source_path) as image:
        for asset in assets_payload.get("assets") or []:
            if not isinstance(asset, dict):
                continue
            asset["can_authorize_click"] = False
            source = asset.setdefault("source", {})
            asset_id = str(asset.get("asset_id") or "")
            bbox = sample_bboxes.get(asset_id)
            if bbox is None:
                source["crop_status"] = "pending_no_learned_bbox"
                continue
            crop_bbox = _clip_bbox(bbox, image.width, image.height)
            if crop_bbox is None:
                source["crop_status"] = "skipped_invalid_bbox"
                continue
            crop = image.crop(crop_bbox)
            crop_path = crop_dir / f"{_safe_asset_name(asset_id)}.png"
            crop.save(crop_path)
            source["crop_status"] = "ok"
            source["crop_path"] = str(crop_path)
            source["source_image_path"] = str(source_path)
            source["bbox"] = _bbox_to_payload(crop_bbox)
            source["perceptual_hash"] = _average_hash(crop)
            crop_count += 1

    matching_policy = assets_payload.setdefault("matching_policy", {})
    matching_policy["asset_match_is_evidence_only"] = True
    matching_policy["asset_can_authorize_click"] = False
    return {
        "contract_version": VISUAL_ASSET_CROP_EXPORT_CONTRACT,
        "source_image_path": str(source_path),
        "output_dir": str(crop_dir),
        "visual_assets": assets_payload,
        "summary": {
            "asset_count": len([item for item in assets_payload.get("assets") or [] if isinstance(item, dict)]),
            "crop_count": crop_count,
            "artifact_is_authorization": False,
        },
    }


def _representative_bboxes(runtime_path_graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    for entity in runtime_path_graph.get("entities") or []:
        if not isinstance(entity, dict):
            continue
        if entity.get("entity_type") == "job_card" and isinstance(entity.get("bbox"), dict):
            return {"seek:visual:job_card_shape": entity["bbox"]}
    return {}


def _clip_bbox(bbox: dict[str, Any], image_width: int, image_height: int) -> tuple[int, int, int, int] | None:
    x = _int_or_none(bbox.get("x"))
    y = _int_or_none(bbox.get("y"))
    width = _int_or_none(bbox.get("w", bbox.get("width")))
    height = _int_or_none(bbox.get("h", bbox.get("height")))
    if x is None or y is None or width is None or height is None or width <= 0 or height <= 0:
        return None
    left = max(0, x)
    top = max(0, y)
    right = min(image_width, x + width)
    bottom = min(image_height, y + height)
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def _bbox_to_payload(crop_bbox: tuple[int, int, int, int]) -> dict[str, int]:
    left, top, right, bottom = crop_bbox
    return {"x": left, "y": top, "w": right - left, "h": bottom - top}


def _average_hash(image: Image.Image) -> str:
    small = image.convert("L").resize((8, 8))
    values = list(small.tobytes())
    average = sum(values) / len(values)
    return "".join("1" if value >= average else "0" for value in values)


def _safe_asset_name(asset_id: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in asset_id)


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
