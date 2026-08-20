from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import cv2


VISUAL_ASSET_MATCH_CONTRACT = "visual_asset_match_v1"


def match_visual_asset(
    *,
    asset_id: str,
    template_path: str | Path,
    target_image_path: str | Path,
    label: str,
    semantic_action: str,
    allowed_region: dict[str, Any] | None = None,
    scales: list[float] | tuple[float, ...] = (0.9, 1.0, 1.1),
    min_score: float = 0.88,
    min_score_gap: float = 0.0,
    methods: list[str] | tuple[str, ...] = ("gray_template", "edge_template"),
    artifact_dir: str | Path | None = None,
    capture_id: str | None = None,
    viewport_size: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    template_file = Path(template_path)
    target_file = Path(target_image_path)
    target = cv2.imread(str(target_file), cv2.IMREAD_COLOR)
    template = cv2.imread(str(template_file), cv2.IMREAD_COLOR)
    if target is None:
        return _failed_result(
            asset_id=asset_id,
            label=label,
            semantic_action=semantic_action,
            reason="target_image_unreadable",
            started=started,
            template_path=template_file,
            target_image_path=target_file,
            allowed_region=allowed_region,
            min_score=min_score,
            capture_id=capture_id,
            viewport_size=viewport_size,
        )
    if template is None:
        return _failed_result(
            asset_id=asset_id,
            label=label,
            semantic_action=semantic_action,
            reason="template_image_unreadable",
            started=started,
            template_path=template_file,
            target_image_path=target_file,
            allowed_region=allowed_region,
            min_score=min_score,
            capture_id=capture_id,
            viewport_size=viewport_size,
        )

    search, offset, normalized_region = _search_region(target, allowed_region)
    current_roi_ref = _write_match_artifact(
        artifact_dir,
        f"{asset_id}.current_roi.png",
        search,
    )
    best: dict[str, Any] | None = None
    ranked: list[dict[str, Any]] = []
    for scale in scales:
        resized_color = _resize_template(template, float(scale))
        if resized_color.shape[0] > search.shape[0] or resized_color.shape[1] > search.shape[1]:
            continue
        for method in methods:
            prepared_search, prepared_template = _prepare_match_images(search, resized_color, method)
            response = cv2.matchTemplate(prepared_search, prepared_template, cv2.TM_CCOEFF_NORMED)
            for scored in _top_template_locations(response, limit=2):
                location = scored["location"]
                candidate = {
                    "score": float(scored["score"]),
                    "bbox": {
                        "x": int(location[0] + offset[0]),
                        "y": int(location[1] + offset[1]),
                        "w": int(resized_color.shape[1]),
                        "h": int(resized_color.shape[0]),
                    },
                    "scale": float(scale),
                    "method": method,
                }
                ranked.append(candidate)
                if best is None or candidate["score"] > best["score"]:
                    best = candidate

    if best is None:
        return _failed_result(
            asset_id=asset_id,
            label=label,
            semantic_action=semantic_action,
            reason="no_template_scale_fit",
            started=started,
            template_path=template_file,
            target_image_path=target_file,
            allowed_region=normalized_region,
            min_score=min_score,
            capture_id=capture_id,
            viewport_size=viewport_size,
        )

    bbox = best["bbox"]
    click_point = {"x": bbox["x"] + bbox["w"] // 2, "y": bbox["y"] + bbox["h"] // 2}
    score = float(best["score"])
    second = _second_distinct_candidate(best, ranked)
    score_gap = round(score - float(second["score"]), 6) if second else None
    threshold_ok = score >= float(min_score)
    score_gap_ok = score_gap is None or score_gap >= float(min_score_gap)
    scope_ok = _bbox_inside_region(bbox, normalized_region) if normalized_region else True
    current_match_ref = _write_bbox_artifact(
        artifact_dir,
        f"{asset_id}.current_match.png",
        target,
        bbox,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
    return {
        "contract_version": VISUAL_ASSET_MATCH_CONTRACT,
        "asset_id": str(asset_id),
        "label": str(label),
        "semantic_action": str(semantic_action),
        "template_path": str(template_file),
        "target_image_path": str(target_file),
        "allowed_region": normalized_region,
        "current_roi_ref": current_roi_ref,
        "current_match_ref": current_match_ref,
        "match_score": round(score, 6),
        "min_score": float(min_score),
        "score_gap_to_second": score_gap,
        "min_score_gap": float(min_score_gap),
        "threshold_ok": threshold_ok,
        "score_gap_ok": score_gap_ok,
        "scope_ok": scope_ok,
        "matched": bool(threshold_ok and score_gap_ok and scope_ok),
        "ambiguous": bool(threshold_ok and scope_ok and not score_gap_ok),
        "bbox": bbox,
        "click_point": click_point,
        "scale": best["scale"],
        "match_method": best["method"],
        "top_candidates": [
            {
                "score": round(float(item["score"]), 6),
                "bbox": item["bbox"],
                "scale": item["scale"],
                "method": item["method"],
            }
            for item in _distinct_ranked_candidates(ranked)[:5]
        ],
        "elapsed_ms": elapsed_ms,
        "can_authorize_click": False,
        "candidate_freshness": {
            "contract_version": "action_candidate_freshness_v1",
            "capture_id": capture_id or str(target_file),
            "viewport_size": viewport_size or {"width": int(target.shape[1]), "height": int(target.shape[0])},
            "source": "visual_asset_match_v1",
            "freshness": "current_capture" if capture_id else "image_file",
        },
        "candidate": {
            "contract_version": "seeded_candidate_v1",
            "source": "visual_asset_match_v1",
            "candidate_id": f"visual_asset_{asset_id}",
            "role": "button",
            "label": str(label),
            "container_id": normalized_region.get("container_id") if isinstance(normalized_region, dict) else None,
            "bbox": bbox,
            "click_point": click_point,
            "risk_class": _risk_class_for_semantic_action(semantic_action),
            "expected_effect": str(semantic_action),
            "candidate_freshness": {
                "contract_version": "action_candidate_freshness_v1",
                "capture_id": capture_id or str(target_file),
                "viewport_size": viewport_size or {"width": int(target.shape[1]), "height": int(target.shape[0])},
                "source": "visual_asset_match_v1",
                "freshness": "current_capture" if capture_id else "image_file",
            },
        },
    }


def _failed_result(
    *,
    asset_id: str,
    label: str,
    semantic_action: str,
    reason: str,
    started: float,
    template_path: Path,
    target_image_path: Path,
    allowed_region: dict[str, Any] | None,
    min_score: float,
    capture_id: str | None,
    viewport_size: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "contract_version": VISUAL_ASSET_MATCH_CONTRACT,
        "asset_id": str(asset_id),
        "label": str(label),
        "semantic_action": str(semantic_action),
        "template_path": str(template_path),
        "target_image_path": str(target_image_path),
        "allowed_region": _normalize_region(allowed_region),
        "matched": False,
        "match_score": 0.0,
        "min_score": float(min_score),
        "threshold_ok": False,
        "scope_ok": False,
        "failure_reason": reason,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        "can_authorize_click": False,
        "candidate_freshness": {
            "contract_version": "action_candidate_freshness_v1",
            "capture_id": capture_id or str(target_image_path),
            "viewport_size": viewport_size,
            "source": "visual_asset_match_v1",
            "freshness": "unmatched",
        },
    }


def _resize_template(template: Any, scale: float) -> Any:
    if scale == 1.0:
        return template
    width = max(1, round(template.shape[1] * scale))
    height = max(1, round(template.shape[0] * scale))
    interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
    return cv2.resize(template, (width, height), interpolation=interpolation)


def _prepare_match_images(search: Any, template: Any, method: str) -> tuple[Any, Any]:
    normalized = str(method or "gray_template").casefold()
    search_gray = cv2.cvtColor(search, cv2.COLOR_BGR2GRAY)
    template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    if normalized == "edge_template":
        return cv2.Canny(search_gray, 50, 150), cv2.Canny(template_gray, 50, 150)
    return search_gray, template_gray


def _top_template_locations(response: Any, *, limit: int) -> list[dict[str, Any]]:
    work = response.copy()
    results: list[dict[str, Any]] = []
    for _ in range(max(1, limit)):
        _, max_score, _, max_location = cv2.minMaxLoc(work)
        results.append({"score": float(max_score), "location": (int(max_location[0]), int(max_location[1]))})
        x, y = max_location
        pad = 12
        left = max(0, int(x) - pad)
        top = max(0, int(y) - pad)
        right = min(work.shape[1], int(x) + pad + 1)
        bottom = min(work.shape[0], int(y) + pad + 1)
        work[top:bottom, left:right] = -1.0
    return results


def _distinct_ranked_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted(candidates, key=lambda item: float(item.get("score") or 0.0), reverse=True)
    distinct: list[dict[str, Any]] = []
    for item in ranked:
        if any(_bbox_iou(item["bbox"], kept["bbox"]) >= 0.4 for kept in distinct):
            continue
        distinct.append(item)
    return distinct


def _second_distinct_candidate(best: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in _distinct_ranked_candidates(candidates):
        if item is best:
            continue
        if _bbox_iou(item["bbox"], best["bbox"]) < 0.4:
            return item
    return None


def _bbox_iou(a: dict[str, int], b: dict[str, int]) -> float:
    left = max(int(a["x"]), int(b["x"]))
    top = max(int(a["y"]), int(b["y"]))
    right = min(int(a["x"]) + int(a["w"]), int(b["x"]) + int(b["w"]))
    bottom = min(int(a["y"]) + int(a["h"]), int(b["y"]) + int(b["h"]))
    if right <= left or bottom <= top:
        return 0.0
    inter = (right - left) * (bottom - top)
    area_a = max(1, int(a["w"]) * int(a["h"]))
    area_b = max(1, int(b["w"]) * int(b["h"]))
    return inter / max(1, area_a + area_b - inter)


def _write_match_artifact(artifact_dir: str | Path | None, filename: str, image: Any) -> str | None:
    if artifact_dir is None:
        return None
    output_dir = Path(artifact_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / _safe_artifact_name(filename)
    cv2.imwrite(str(output_path), image)
    return str(output_path)


def _write_bbox_artifact(
    artifact_dir: str | Path | None,
    filename: str,
    image: Any,
    bbox: dict[str, int],
) -> str | None:
    if artifact_dir is None:
        return None
    x = max(0, int(bbox["x"]))
    y = max(0, int(bbox["y"]))
    right = min(image.shape[1], x + int(bbox["w"]))
    bottom = min(image.shape[0], y + int(bbox["h"]))
    if right <= x or bottom <= y:
        return None
    return _write_match_artifact(artifact_dir, filename, image[y:bottom, x:right])


def _safe_artifact_name(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in str(value))
    return safe.strip("._") or "visual_asset_match.png"


def _search_region(target: Any, allowed_region: dict[str, Any] | None) -> tuple[Any, tuple[int, int], dict[str, Any] | None]:
    region = _normalize_region(allowed_region)
    if not region:
        return target, (0, 0), None
    x = max(0, min(int(region["x"]), target.shape[1] - 1))
    y = max(0, min(int(region["y"]), target.shape[0] - 1))
    width = max(1, min(int(region["w"]), target.shape[1] - x))
    height = max(1, min(int(region["h"]), target.shape[0] - y))
    clipped = dict(region)
    clipped.update({"x": x, "y": y, "w": width, "h": height})
    return target[y : y + height, x : x + width], (x, y), clipped


def _normalize_region(region: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(region, dict):
        return None
    try:
        x = int(region.get("x"))
        y = int(region.get("y"))
        width = int(region.get("w", region.get("width")))
        height = int(region.get("h", region.get("height")))
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    normalized = {"x": x, "y": y, "w": width, "h": height}
    if region.get("container_id"):
        normalized["container_id"] = str(region["container_id"])
    return normalized


def _bbox_inside_region(bbox: dict[str, int], region: dict[str, Any] | None) -> bool:
    if not region:
        return True
    return (
        bbox["x"] >= region["x"]
        and bbox["y"] >= region["y"]
        and bbox["x"] + bbox["w"] <= region["x"] + region["w"]
        and bbox["y"] + bbox["h"] <= region["y"] + region["h"]
    )


def _risk_class_for_semantic_action(semantic_action: str) -> str:
    action = str(semantic_action or "").casefold()
    if action == "open_apply_flow":
        return "safe_open_apply_flow"
    if action == "continue_next_step":
        return "safe_continue_next_step"
    if "submit" in action or "send" in action or "payment" in action:
        return "potential_side_effect_action"
    return "safe_click_allowed"
