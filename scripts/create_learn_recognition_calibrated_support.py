from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def create_calibrated_support(
    *,
    screenshot_path: str | Path,
    targets_path: str | Path,
    out_dir: str | Path,
    app_name: str = "",
    state_hint: str = "",
    source_tracking: str = "human_curated",
    json_stdout: bool = False,
) -> dict[str, Any]:
    screenshot_path = Path(screenshot_path)
    targets_path = Path(targets_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if not screenshot_path.exists():
        raise FileNotFoundError(str(screenshot_path))
    if not targets_path.exists():
        raise FileNotFoundError(str(targets_path))

    image_size = _image_size(screenshot_path)
    screenshot_sha256 = _sha256_file(screenshot_path)
    raw_targets = _read_targets(targets_path)
    targets = [_normalize_target(item, image_size=image_size, index=index) for index, item in enumerate(raw_targets)]
    invalid = [item for item in targets if item["coordinate_validation"]["status"] != "valid"]
    if invalid:
        raise ValueError(f"invalid calibrated target bbox/click point: {invalid[0]['candidate_id']}")

    payload = {
        "contract_version": "learn_recognition_same_screenshot_support_v1",
        "support_type": "calibrated_targets",
        "support_scope": "same_screenshot_interactable_support_only",
        "source_tracking": source_tracking,
        "counts_as_model_ability": False,
        "created_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "app_name": app_name,
        "state_hint": state_hint,
        "screenshot_path": str(screenshot_path),
        "screenshot_sha256": screenshot_sha256,
        "screenshot": {
            "path": str(screenshot_path),
            "sha256": screenshot_sha256,
            "image_width": image_size["width"],
            "image_height": image_size["height"],
        },
        "review_source": {
            "targets_path": str(targets_path),
            "source_tracking": source_tracking,
            "interpretation": "reviewed target boxes are explicit calibration support, not model-generated ability evidence",
        },
        "sources": {
            "calibrated_targets": {
                "source": "reviewed_target_selection",
                "source_tracking": source_tracking,
                "counts_as_model_ability": False,
                "targets": targets,
            }
        },
        "safety": _safety(),
        "interpretation": (
            "Same-screenshot calibrated support may help review-only parser candidates become eligible for grounding "
            "after bbox alignment; it is not Execute authorization, not model accuracy, and not PathGraph promotion."
        ),
    }
    support_path = out_dir / "same_screenshot_calibrated_support.json"
    support_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {
        "status": "created",
        "support_path": str(support_path),
        "screenshot_path": str(screenshot_path),
        "screenshot_sha256": screenshot_sha256,
        "target_count": len(targets),
        "source_tracking": source_tracking,
        "counts_as_model_ability": False,
        "safety": payload["safety"],
    }
    if json_stdout:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def _read_targets(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    targets = payload.get("targets") if isinstance(payload, dict) else None
    if isinstance(targets, list):
        return [item for item in targets if isinstance(item, dict)]
    raise ValueError("targets file must be a list or contain a targets list")


def _normalize_target(item: dict[str, Any], *, image_size: dict[str, int], index: int) -> dict[str, Any]:
    bbox = item.get("bbox") if isinstance(item.get("bbox"), dict) else {}
    x = _float_or_zero(bbox.get("x"))
    y = _float_or_zero(bbox.get("y"))
    w = _float_or_zero(bbox.get("w"))
    h = _float_or_zero(bbox.get("h"))
    click_point = item.get("click_point") if isinstance(item.get("click_point"), dict) else {}
    cx = _float_or_zero(click_point.get("x")) if click_point else x + w / 2
    cy = _float_or_zero(click_point.get("y")) if click_point else y + h / 2
    candidate_id = str(item.get("candidate_id") or f"reviewed_target_{index + 1}")
    validation = _coordinate_validation(x=x, y=y, w=w, h=h, cx=cx, cy=cy, image_size=image_size)
    return {
        "candidate_id": candidate_id,
        "label": str(item.get("label") or candidate_id),
        "role": str(item.get("role") or "actionable"),
        "bbox": {"x": x, "y": y, "w": w, "h": h},
        "click_point": {"x": cx, "y": cy},
        "confidence": float(item.get("confidence") or 1.0),
        "source": str(item.get("source") or "reviewed_target_selection"),
        "coordinate_source": str(item.get("coordinate_source") or "human_reviewed_bbox"),
        "location_status": "coordinate_verified" if validation["status"] == "valid" else "invalid",
        "source_tracking": str(item.get("source_tracking") or "human_curated"),
        "counts_as_model_ability": False,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "coordinate_validation": validation,
    }


def _coordinate_validation(
    *,
    x: float,
    y: float,
    w: float,
    h: float,
    cx: float,
    cy: float,
    image_size: dict[str, int],
) -> dict[str, Any]:
    width = int(image_size["width"])
    height = int(image_size["height"])
    bbox_present = w > 0 and h > 0
    click_point_present = cx >= 0 and cy >= 0
    bbox_inside_image = bbox_present and x >= 0 and y >= 0 and x + w <= width and y + h <= height
    click_point_inside_image = click_point_present and 0 <= cx <= width and 0 <= cy <= height
    click_point_inside_bbox = bbox_present and x <= cx <= x + w and y <= cy <= y + h
    reasons = []
    if not bbox_present:
        reasons.append("bbox_missing_or_empty")
    if not bbox_inside_image:
        reasons.append("bbox_outside_image")
    if not click_point_inside_image:
        reasons.append("click_point_outside_image")
    if not click_point_inside_bbox:
        reasons.append("click_point_outside_bbox")
    return {
        "contract_version": "learn_target_coordinate_validation_v1",
        "status": "valid" if not reasons else "invalid",
        "bbox_present": bbox_present,
        "click_point_present": click_point_present,
        "bbox_inside_image": bbox_inside_image,
        "click_point_inside_image": click_point_inside_image,
        "click_point_inside_bbox": click_point_inside_bbox,
        "image_size": image_size,
        "reasons": reasons,
    }


def _safety() -> dict[str, Any]:
    return {
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "no_dispatch": True,
        "real_clicks_performed": 0,
        "final_submit_forbidden": True,
    }


def _image_size(path: Path) -> dict[str, int]:
    with Image.open(path) as image:
        return {"width": int(image.width), "height": int(image.height)}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshot", required=True)
    parser.add_argument("--targets", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--app-name", default="")
    parser.add_argument("--state-hint", default="")
    parser.add_argument("--source-tracking", default="human_curated", choices=["human_curated", "assisted_generation", "mixed"])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    create_calibrated_support(
        screenshot_path=args.screenshot,
        targets_path=args.targets,
        out_dir=args.out,
        app_name=args.app_name,
        state_hint=args.state_hint,
        source_tracking=args.source_tracking,
        json_stdout=args.json,
    )


if __name__ == "__main__":
    main()
