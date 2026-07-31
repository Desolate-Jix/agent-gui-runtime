from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from pathlib import Path
from typing import Any


OBSERVATION_RECORD_CONTRACT = "navigation_runtime_observation_record_v1"


def build_navigation_runtime_observation(
    *,
    capture: dict[str, Any],
    screen_reading: dict[str, Any],
    interface_specs: list[dict[str, Any]],
) -> dict[str, Any]:
    """只使用当前截图证据生成连续阅读控制器所需的观察记录。"""

    image_path = Path(_required_text(capture.get("image_path"), "image_path"))
    if not image_path.is_file():
        raise ValueError(f"current screenshot does not exist: {image_path}")
    width = _positive_int(capture.get("image_width"), "image_width")
    height = _positive_int(capture.get("image_height"), "image_height")
    if screen_reading.get("contract_version") != "screen_reading_v1":
        raise ValueError("screen_reading_v1 is required")

    texts = _normalized_texts(screen_reading.get("texts"))
    current_text = _canonical_identity_text(
        "\n".join(item["text"] for item in texts)
    )
    matched = [
        deepcopy(spec)
        for spec in interface_specs
        if _spec_matches_current_text(spec, current_text)
    ]
    if len(matched) != 1:
        reason = "missing" if not matched else "ambiguous"
        raise ValueError(f"{reason} current interface identity")
    spec = matched[0]

    screenshot_sha256 = hashlib.sha256(image_path.read_bytes()).hexdigest()
    trace_path = _required_text(screen_reading.get("trace_path"), "trace_path")
    resolved_read_targets: dict[str, dict[str, Any]] = {}
    reached_bottom = False
    read_target = spec.get("read_target")
    if isinstance(read_target, dict):
        content_id = _required_text(read_target.get("content_id"), "content_id")
        document_bbox = _current_document_bbox(
            screen_reading=screen_reading,
            width=width,
            height=height,
        )
        resolved_read_targets[content_id] = {
            "target_container_id": content_id,
            "bbox": document_bbox,
            "scroll_scope": str(read_target.get("scroll_scope") or "page"),
            "target_pane": str(read_target.get("target_pane") or "page"),
            "wheel_clicks": _positive_int(
                read_target.get("wheel_clicks") or 5,
                "wheel_clicks",
            ),
        }
        reached_bottom = any(
            _marker_matches_current_text(marker, current_text)
            for marker in read_target.get("bottom_markers") or []
        )

    return {
        "contract_version": OBSERVATION_RECORD_CONTRACT,
        "observation": {
            "contract_version": "current_interface_observation_v1",
            "interface_id": _required_text(
                spec.get("interface_id"),
                "interface_id",
            ),
            "surface_type": _required_text(
                spec.get("surface_type"),
                "surface_type",
            ),
            "capture_id": f"capture-{screenshot_sha256[:16]}",
            "screenshot_sha256": screenshot_sha256,
            "trace_path": trace_path,
        },
        "image_path": str(image_path.resolve()),
        "window_size": {"width": width, "height": height},
        "ocr_result": {
            "contract_version": "navigation_runtime_ocr_projection_v1",
            "items": texts,
        },
        "resolved_read_targets": resolved_read_targets,
        "reached_bottom": reached_bottom,
    }


def _spec_matches_current_text(spec: dict[str, Any], current_text: str) -> bool:
    raw_marker_sets = spec.get("identity_marker_sets")
    if isinstance(raw_marker_sets, list):
        marker_sets = [
            [
                _canonical_identity_text(
                    _required_text(marker, "identity marker")
                )
                for marker in raw_markers
            ]
            for raw_markers in raw_marker_sets
            if isinstance(raw_markers, list) and raw_markers
        ]
    else:
        markers = [
            _canonical_identity_text(_required_text(marker, "identity marker"))
            for marker in spec.get("identity_markers") or []
        ]
        marker_sets = [markers] if markers else []
    return any(
        all(marker in current_text for marker in markers)
        for markers in marker_sets
    )


def _canonical_identity_text(value: str) -> str:
    text = value.casefold()
    # 只在界面身份短语匹配时修正常见的 Interface 首字母 OCR 混淆。
    return re.sub(r"\blnterface\b", "interface", text)


def _marker_matches_current_text(marker: Any, current_text: str) -> bool:
    expected = _required_text(marker, "bottom marker").casefold()
    if expected in current_text:
        return True
    compact_expected = re.sub(r"\s+", "", expected)
    compact_current = re.sub(r"\s+", "", current_text)
    return bool(compact_expected and compact_expected in compact_current)


def _normalized_texts(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        result.append(
            {
                "text": text,
                "bbox": _bbox(item.get("bbox")),
                "confidence": float(item.get("confidence") or 0.0),
                "source": str(item.get("source") or "screen_reading.texts"),
            }
        )
    if not result:
        raise ValueError("current screen reading contains no text evidence")
    return result


def _current_document_bbox(
    *,
    screen_reading: dict[str, Any],
    width: int,
    height: int,
) -> dict[str, int]:
    inventories = screen_reading.get("screen_inventory")
    if isinstance(inventories, dict):
        inventories = [inventories]
    candidates: list[dict[str, int]] = []
    for inventory in inventories if isinstance(inventories, list) else []:
        if not isinstance(inventory, dict):
            continue
        for card in inventory.get("cards") or []:
            if not isinstance(card, dict):
                continue
            role = str(card.get("role") or "").strip().casefold()
            if role != "document":
                continue
            bbox = _bbox(card.get("bbox"))
            if _bbox_inside_window(bbox, width=width, height=height):
                candidates.append(bbox)
    if not candidates:
        raise ValueError("current screen reading did not provide a document bbox")
    return max(candidates, key=lambda item: item["w"] * item["h"])


def _bbox_inside_window(bbox: dict[str, int], *, width: int, height: int) -> bool:
    return (
        bbox["x"] >= 0
        and bbox["y"] >= 0
        and bbox["x"] + bbox["w"] <= width
        and bbox["y"] + bbox["h"] <= height
    )


def _bbox(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError("bbox is required")
    try:
        x = int(value.get("x") or 0)
        y = int(value.get("y") or 0)
        w = int(
            value.get("w")
            if value.get("w") is not None
            else value.get("width")
        )
        h = int(
            value.get("h")
            if value.get("h") is not None
            else value.get("height")
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("bbox is invalid") from exc
    if w <= 0 or h <= 0:
        raise ValueError("bbox must be positive")
    return {"x": x, "y": y, "w": w, "h": h}


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required")
    return text


def _positive_int(value: Any, field_name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    if number <= 0:
        raise ValueError(f"{field_name} must be positive")
    return number
