"""即时测试通道只记录识别风险；保留当前图、候选和几何绑定。"""
from copy import deepcopy
from pathlib import Path


def local_recognition_selection(plan, *, image_path, viewport_size):
    if not isinstance(plan, dict) or not isinstance(plan.get("image_path"), str):
        raise ValueError("local recognition plan invalid")
    if Path(plan.get("image_path", "")).resolve() != Path(image_path).resolve():
        raise ValueError("local recognition requires the current capture")
    parsed = plan.get("parse_result") or {}
    if not isinstance(parsed, dict) or not isinstance(parsed.get("vision_regions"), dict):
        raise ValueError("local recognition parse result invalid")
    size = (parsed.get("vision_regions") or {}).get("image_size")
    if size != viewport_size or not isinstance(size, dict):
        raise ValueError("local recognition viewport mismatch")
    if any(type(size.get(k)) is not int or size[k] <= 0 for k in ("width", "height")):
        raise ValueError("local recognition viewport invalid")
    ranking = plan.get("candidate_result") or {}
    if not isinstance(ranking, dict):
        raise ValueError("local recognition ranking invalid")
    candidate_id = ranking.get("recommended_candidate_id")
    candidates = ranking.get("candidates") or []
    if not isinstance(candidates, list) or any(not isinstance(c, dict) for c in candidates):
        raise ValueError("local recognition candidates invalid")
    chosen = [c for c in candidates if c.get("candidate_id") == candidate_id]
    if not candidate_id or len(chosen) != 1:
        raise ValueError("local recognition has no unique recommended candidate")
    candidate = chosen[0]
    element = candidate.get("element") or {}
    narrow = plan.get("narrow_search_result") or {}
    if not isinstance(element, dict) or not isinstance(narrow, dict):
        raise ValueError("local recognition element or grounding invalid")
    results = narrow.get("results", [])
    if not isinstance(results, list) or any(not isinstance(c, dict) for c in results):
        raise ValueError("local recognition grounding results invalid")
    local = [c for c in results
             if c.get("candidate_id") == candidate_id]
    if (len(local) != 1 or not candidate.get("element_id")
            or local[0].get("element_id") != candidate["element_id"]
            or element.get("element_id") != candidate["element_id"]):
        raise ValueError("local recognition candidate identity mismatch")
    point = local[0].get("refined_click_point")
    if not isinstance(point, dict) or set(point) != {"x", "y"} or any(type(v) is not int for v in point.values()):
        raise ValueError("local recognition point missing or invalid")
    if not (0 <= point["x"] < size["width"] and 0 <= point["y"] < size["height"]):
        raise ValueError("local recognition point outside capture")
    box = candidate.get("refined_bbox") or element.get("bbox")
    if (not isinstance(box, dict) or any(type(box.get(k)) is not int for k in ("x", "y", "w", "h"))
            or min(box["x"], box["y"]) < 0 or min(box["w"], box["h"]) <= 0
            or not (box["x"] <= point["x"] < box["x"] + box["w"]
                    and box["y"] <= point["y"] < box["y"] + box["h"])):
        raise ValueError("local recognition point outside candidate")
    # 模式状态不等于本次覆盖了拒绝，未知原判也不能宣称已覆盖。
    original_policy = plan.get("pre_click_decision")
    original_allowed = original_policy.get("allowed") if isinstance(original_policy, dict) else None
    bypass_applied = original_allowed is False
    reasons = ["operator_mode_active"]
    reasons.append("automatic_rejection_bypassed" if bypass_applied else (
        "automatic_policy_already_allowed" if original_allowed is True else "automatic_policy_unavailable"))
    return {"contract_version": "local_operator_recognition_selection_v1", "allowed": True,
            "automatic_safety_interception": False, "selected_candidate_id": candidate_id,
            "selected_element_id": candidate["element_id"], "selected_click_point": deepcopy(point),
            "coordinate_space": "capture_image_pixels", "image_path": str(image_path),
            "viewport_size": deepcopy(size), "reasons": reasons, "bypass_applied": bypass_applied,
            "original_policy_allowed": original_allowed,
            "candidate_decisions": [{"candidate_id": candidate_id,
                "element_id": candidate["element_id"], "allowed": True,
                "click_point": deepcopy(point), "coordinate_space": "capture_image_pixels",
                "coordinate_source": local[0].get("coordinate_source"),
                "original_grounding_status": local[0].get("status"),
                "reasons": list(reasons), "bypass_applied": bypass_applied,
                "original_grounding_reasons": deepcopy(local[0].get("reasons", [])),
                "bbox_source": candidate.get("bbox_refine_reason"),
                "independent_target_bbox_verified": False,
                "geometry_check_scope": "capture_and_candidate_bounds_only"}],
            "original_policy": deepcopy(plan.get("pre_click_decision"))}
