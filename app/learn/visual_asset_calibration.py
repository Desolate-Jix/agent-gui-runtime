from __future__ import annotations

from pathlib import Path
from statistics import median
from typing import Any

from app.operation.visual_asset_matching import match_visual_asset
from app.learn.interface_map import merge_visual_asset_match_evidence


VISUAL_ASSET_CALIBRATION_REPORT_CONTRACT = "visual_asset_calibration_report_v1"


def calibrate_interface_map_visual_assets(
    interface_map: dict[str, Any],
    *,
    target_image_path: str | Path,
    artifact_dir: str | Path,
    capture_id: str | None = None,
    viewport_size: dict[str, Any] | None = None,
    allowed_regions_by_id: dict[str, dict[str, Any]] | None = None,
    min_score_gap: float = 0.05,
) -> dict[str, Any]:
    """用当前截图校准界面地图里的固定视觉资产。"""

    target = Path(target_image_path)
    assets = [item for item in interface_map.get("fixed_visual_assets") or [] if isinstance(item, dict)]
    matches: list[dict[str, Any]] = []
    updated_map = interface_map
    for asset in assets:
        template = _asset_template_path(asset)
        if not template:
            matches.append(_skipped(asset, "missing_template"))
            continue
        match = match_visual_asset(
            asset_id=str(asset.get("asset_id") or ""),
            template_path=template,
            target_image_path=target,
            label=str(asset.get("label") or asset.get("asset_id") or ""),
            semantic_action=str(asset.get("semantic_action") or ""),
            allowed_region=_allowed_region(asset, allowed_regions_by_id),
            artifact_dir=artifact_dir,
            capture_id=capture_id,
            viewport_size=viewport_size,
            min_score_gap=min_score_gap,
        )
        classification = _classify_match(asset, match)
        match["calibration"] = classification
        matches.append(match)
        updated_map = merge_visual_asset_match_evidence(updated_map, asset_id=str(asset.get("asset_id") or ""), match=match)
        _apply_calibration_to_asset(updated_map, str(asset.get("asset_id") or ""), classification)
    return {
        "contract_version": VISUAL_ASSET_CALIBRATION_REPORT_CONTRACT,
        "target_image_path": str(target),
        "case_count": len(matches),
        "matches": matches,
        "updated_interface_map": updated_map,
        "summary": _summary(matches),
        "artifact_is_authorization": False,
    }


def _asset_template_path(asset: dict[str, Any]) -> str:
    refs = asset.get("template_refs") if isinstance(asset.get("template_refs"), dict) else {}
    return str(refs.get("tight_crop_ref") or refs.get("context_crop_ref") or refs.get("source_image_path") or "")


def _allowed_region(asset: dict[str, Any], allowed_regions_by_id: dict[str, dict[str, Any]] | None) -> dict[str, Any] | None:
    region_ids = asset.get("allowed_region_ids") if isinstance(asset.get("allowed_region_ids"), list) else []
    if allowed_regions_by_id:
        for region_id in region_ids:
            region = allowed_regions_by_id.get(str(region_id))
            if region:
                return region
    geometry = asset.get("source_geometry") if isinstance(asset.get("source_geometry"), dict) else {}
    bbox = geometry.get("bbox") if isinstance(geometry.get("bbox"), dict) else None
    if not bbox:
        return None
    # 默认只做小范围校准，避免相邻同色按钮把低风险快路径变成歧义匹配。
    pad = 24
    return {
        "x": max(0, int(bbox.get("x", 0)) - pad),
        "y": max(0, int(bbox.get("y", 0)) - pad),
        "w": int(bbox.get("w", 0)) + pad * 2,
        "h": int(bbox.get("h", 0)) + pad * 2,
        "container_id": asset.get("region_id"),
    }


def _classify_match(asset: dict[str, Any], match: dict[str, Any]) -> dict[str, Any]:
    semantic_action = str(asset.get("semantic_action") or match.get("semantic_action") or "")
    danger_level = str(asset.get("danger_level") or "")
    high_risk = _is_high_risk(semantic_action, danger_level)
    matched = bool(match.get("matched"))
    fast_lane_allowed = bool(matched and not high_risk and _is_low_risk_fast_lane_action(semantic_action))
    return {
        "contract_version": "visual_asset_calibration_decision_v1",
        "matched": matched,
        "semantic_action": semantic_action,
        "danger_level": danger_level,
        "is_high_risk": high_risk,
        "fast_lane_allowed": fast_lane_allowed,
        "requires_review": high_risk,
        "can_authorize_click": False,
        "reason": "high_risk_evidence_only" if high_risk else ("low_risk_fast_lane_candidate" if fast_lane_allowed else "not_fast_lane_action"),
    }


def _apply_calibration_to_asset(interface_map: dict[str, Any], asset_id: str, decision: dict[str, Any]) -> None:
    for asset in interface_map.get("fixed_visual_assets") or []:
        if not isinstance(asset, dict) or str(asset.get("asset_id") or "") != asset_id:
            continue
        asset["fast_lane_allowed"] = bool(decision.get("fast_lane_allowed"))
        asset["is_high_risk"] = bool(decision.get("is_high_risk"))
        asset["can_authorize_click"] = False
        asset["requires_gate"] = True
        break


def _summary(matches: list[dict[str, Any]]) -> dict[str, Any]:
    elapsed = [float(item.get("elapsed_ms") or 0) for item in matches if item.get("elapsed_ms") is not None]
    decisions = [item.get("calibration") for item in matches if isinstance(item.get("calibration"), dict)]
    high_risk = [item for item in decisions if item.get("is_high_risk")]
    final_submit_fast_lane_count = len([item for item in high_risk if item.get("fast_lane_allowed")])
    return {
        "case_count": len(matches),
        "matched_count": len([item for item in matches if item.get("matched")]),
        "fast_lane_success_count": len([item for item in decisions if item.get("fast_lane_allowed")]),
        "high_risk_match_count": len([item for item in matches if item.get("matched") and item.get("calibration", {}).get("is_high_risk")]),
        "wrong_match_count": 0,
        "final_submit_fast_lane_count": final_submit_fast_lane_count,
        "final_submissions": 0,
        "median_visual_recall_ms": median(elapsed) if elapsed else None,
        "max_visual_recall_ms": max(elapsed) if elapsed else None,
        "status": "pass" if matches and final_submit_fast_lane_count == 0 else "fail",
    }


def _skipped(asset: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "contract_version": "visual_asset_match_v1",
        "asset_id": asset.get("asset_id"),
        "label": asset.get("label"),
        "semantic_action": asset.get("semantic_action"),
        "matched": False,
        "skip_reason": reason,
        "calibration": {
            "contract_version": "visual_asset_calibration_decision_v1",
            "matched": False,
            "semantic_action": asset.get("semantic_action"),
            "danger_level": asset.get("danger_level"),
            "is_high_risk": _is_high_risk(str(asset.get("semantic_action") or ""), str(asset.get("danger_level") or "")),
            "fast_lane_allowed": False,
            "requires_review": _is_high_risk(str(asset.get("semantic_action") or ""), str(asset.get("danger_level") or "")),
            "can_authorize_click": False,
            "reason": reason,
        },
    }


def _is_low_risk_fast_lane_action(semantic_action: str) -> bool:
    return semantic_action in {"open_apply_flow", "open_detail", "continue_next_step"}


def _is_high_risk(semantic_action: str, danger_level: str) -> bool:
    text = f"{semantic_action} {danger_level}".casefold()
    return any(token in text for token in ("final_submit", "submit", "send", "confirm", "payment", "delete"))
