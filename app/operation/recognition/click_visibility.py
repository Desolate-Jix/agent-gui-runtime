from __future__ import annotations

import math
from typing import Any

from app.operation.mousetester import target_bbox_from_recommended
from app.operation.recognition.control_target import generic_field_target


def _box(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, dict):
        return None
    parts = (value.get("x"), value.get("y"), value.get("width", value.get("w")),
             value.get("height", value.get("h")))
    if any(type(part) not in (int, float) or not math.isfinite(part) for part in parts):
        return None
    x, y, width, height = parts
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        return None
    return parts


def recognition_click_visibility(
    plan: dict[str, Any], selected_point: dict[str, Any], *,
    goal: str, click_kind: str, local_operator: bool,
) -> dict[str, Any]:
    """区分候选范围与显式编辑区右键的输入足迹，不授予输入权限。"""
    recommended = plan.get("recommended_target") or {}
    target_bbox = target_bbox_from_recommended(recommended)
    result = {"target_bbox": target_bbox, "candidate_bbox": target_bbox,
              "scope": "candidate_bbox", "reason": "full_candidate_visibility_required"}
    if (local_operator is not True or click_kind != "right" or not isinstance(goal, str)
            or not generic_field_target(goal, control_target=plan.get("control_target"),
                                        target_text=plan.get("target_text"))):
        return result
    reading = (plan.get("parse_result") or {}).get("screen_reading") or {}
    image_path = plan.get("image_path")
    if not isinstance(image_path, str) or not image_path.strip() or reading.get("image_path") != image_path:
        return {**result, "reason": "current_image_evidence_missing_or_mismatched"}
    layer = (reading.get("source_layers") or {}).get("windows_uia") or {}
    if (layer.get("provider") != "windows_uia" or layer.get("status") != "ok"
            or layer.get("scan_complete") is not True or layer.get("truncated") is not False
            or layer.get("scan_scope") != "bound_window" or not isinstance(layer.get("controls"), list)):
        return {**result, "reason": "complete_bound_window_uia_required"}
    if not isinstance(selected_point, dict) or any(type(selected_point.get(key)) is not int for key in ("x", "y")):
        return {**result, "reason": "integer_input_point_required"}
    px, py = selected_point["x"], selected_point["y"]
    size = reading.get("image_size") or {}
    if (any(type(size.get(key)) is not int or size[key] <= 0 for key in ("width", "height"))
            or not (0 <= px < size["width"] and 0 <= py < size["height"])):
        return {**result, "reason": "current_image_bounds_required"}
    element = recommended.get("element") or {}
    action = (element.get("evidence") or {}).get("screen_inventory_action") or {}
    candidate_box = _box(element.get("bbox"))
    if (action.get("source") != "windows_uia.controls" or not isinstance(action.get("source_id"), str)
            or not action["source_id"] or candidate_box is None
            or _box(action.get("bbox")) != candidate_box or _box(target_bbox) != candidate_box):
        return {**result, "reason": "candidate_uia_binding_required"}
    matches = []
    controls = layer["controls"]
    for control in controls:
        if not isinstance(control, dict):
            continue
        box = _box(control.get("bbox"))
        patterns = control.get("patterns")
        if (control.get("provider") != "windows_uia"
                or str(control.get("control_type") or "").casefold() not in {"edit", "textbox", "text box"}
                or control.get("enabled") is not True or control.get("visible") is not True
                or not isinstance(patterns, list)
                or not any(isinstance(item, str) and item.casefold() in {"value", "text"} for item in patterns)
                or box is None):
            continue
        x, y, width, height = box
        if x <= px and px + 1 <= x + width and y <= py and py + 1 <= y + height:
            matches.append(control)
    if len(matches) != 1:
        return {**result, "reason": "unique_current_editable_control_required"}
    control = matches[0]
    control_id = control.get("control_id")
    if (control_id != action["source_id"] or _box(control.get("bbox")) != candidate_box
            or candidate_box[0] + candidate_box[2] > size["width"]
            or candidate_box[1] + candidate_box[3] > size["height"]
            or sum(isinstance(item, dict) and item.get("control_id") == control_id for item in controls) != 1):
        return {**result, "reason": "candidate_control_identity_or_bounds_mismatch"}
    # 实时点归属、绑定漂移、权限及鼠标落点检查仍由原输入层执行。
    return {**result, "target_bbox": {"x": px, "y": py, "width": 1, "height": 1},
            "scope": "editable_container_point", "reason": "same_frame_unique_editable_container_right_click",
            "control_id": control_id}
