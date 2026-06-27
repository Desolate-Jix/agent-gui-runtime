from __future__ import annotations

import copy
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image


VISUAL_ASSET_CROP_EXPORT_CONTRACT = "visual_asset_crop_export_v1"
VISUAL_ASSET_LEARNING_CONTRACT = "visual_asset_learning_v1"


def build_visual_assets_from_screen_map(
    screen_map: dict[str, Any] | None,
    *,
    source_image_path: str | Path,
    output_dir: str | Path,
    app_id: str | None = None,
    page_type: str | None = None,
    capture_id: str | None = None,
    learn_depth: str | None = None,
    max_assets: int = 24,
) -> dict[str, Any]:
    """从 Learn Mode 的 screen_map 候选里自动裁出稳定控件视觉资产。"""

    source_path = Path(source_image_path)
    asset_dir = Path(output_dir)
    asset_dir.mkdir(parents=True, exist_ok=True)
    graph = screen_map if isinstance(screen_map, dict) else {}
    candidates = [item for item in graph.get("candidates") or [] if isinstance(item, dict)]
    assets: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    with Image.open(source_path) as image:
        screenshot_size = {"width": int(image.width), "height": int(image.height)}
        for candidate in candidates:
            if len(assets) >= max_assets:
                break
            decision = _learnable_candidate_decision(candidate, app_id=app_id)
            if not decision["learnable"]:
                if decision["reason"] != "not_stable_visual_control":
                    skipped.append(
                        {
                            "candidate_id": candidate.get("candidate_id"),
                            "label": candidate.get("label"),
                            "reason": decision["reason"],
                        }
                    )
                continue
            bbox = _clip_bbox(_candidate_bbox(candidate) or {}, image.width, image.height)
            if bbox is None:
                skipped.append(
                    {
                        "candidate_id": candidate.get("candidate_id"),
                        "label": candidate.get("label"),
                        "reason": "invalid_bbox",
                    }
                )
                continue
            tight_bbox = _expand_clipped_bbox(bbox, image.width, image.height, padding=6)
            context_bbox = _expand_clipped_bbox(bbox, image.width, image.height, padding=16)
            asset_id = _visual_asset_id(
                app_id=app_id,
                page_type=page_type,
                candidate=candidate,
                label=str(candidate.get("label") or decision["label"]),
            )
            tight_path = asset_dir / f"{asset_id}.tight.png"
            context_path = asset_dir / f"{asset_id}.context.png"
            tight_crop = image.crop(tight_bbox)
            context_crop = image.crop(context_bbox)
            tight_crop.save(tight_path)
            context_crop.save(context_path)
            template_refs = {
                "tight_crop_ref": str(tight_path),
                "context_crop_ref": str(context_path),
                "source_image_path": str(source_path),
            }
            asset = {
                "contract_version": "visual_asset_v1",
                "asset_id": asset_id,
                "asset_type": "button_crop",
                "asset_status": "verified_stable" if learn_depth == "deep" else "draft_observed",
                "artifact_is_authorization": False,
                "usable_for_recall": True,
                "requires_gate": True,
                "can_authorize_click": False,
                "label": decision["label"],
                "role": str(candidate.get("role") or "control"),
                "semantic_action": decision["semantic_action"],
                "danger_level": decision["danger_level"],
                "review_policy": _visual_asset_review_policy(decision),
                "source": {
                    "capture_id": capture_id or str(source_path),
                    "source_image_path": str(source_path),
                    "coordinate_space": "source_capture_px",
                    "screenshot_size": screenshot_size,
                    "app_id": app_id,
                    "page_type": page_type,
                    "candidate_id": candidate.get("candidate_id"),
                    "candidate_source": candidate.get("source"),
                },
                "source_geometry": {
                    "bbox": _bbox_to_payload(bbox),
                    "click_point": _candidate_click_point(candidate, bbox),
                    "click_point_policy": "learned_relative_point",
                    "click_point_relative": _relative_click_point(candidate, bbox),
                    "source_is_authorization": False,
                },
                "template_refs": template_refs,
                "crop": {
                    **template_refs,
                    "padding_px": 6,
                    "context_padding_px": 16,
                    "tight_bbox": _bbox_to_payload(tight_bbox),
                    "context_bbox": _bbox_to_payload(context_bbox),
                    "hash": _average_hash(tight_crop),
                    "context_hash": _average_hash(context_crop),
                    "size_px": [tight_crop.width, tight_crop.height],
                },
                "match_policy": {
                    "methods": ["gray_template", "edge_template", "ocr_confirm"],
                    "scale_variants": [0.9, 1.0, 1.1],
                    "min_score": 0.88,
                    "min_score_gap": 0.06,
                    "nms_iou": 0.4,
                    "roi_policy": "last_known_then_container_then_page_region",
                },
                "scope": {
                    "allowed_page_types": [page_type] if page_type else [],
                    "allowed_container_ids": [candidate.get("section_id")] if candidate.get("section_id") else [],
                    "expected_text": [decision["label"]],
                    "negative_text": ["Submit", "Send application", "Complete application"]
                    if decision["semantic_action"] != "final_submit"
                    else [],
                },
                "candidate_snapshot": {
                    "candidate_id": candidate.get("candidate_id"),
                    "risk_class": candidate.get("risk_class"),
                    "section_id": candidate.get("section_id"),
                    "confidence": candidate.get("confidence"),
                },
            }
            assets.append(asset)

    return {
        "contract_version": VISUAL_ASSET_LEARNING_CONTRACT,
        "source_image_path": str(source_path),
        "output_dir": str(asset_dir),
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "app_id": app_id,
        "page_type": page_type,
        "learn_depth": learn_depth,
        "visual_assets": {
            "contract_version": "visual_asset_store_v1",
            "asset_status_default": "verified_stable" if learn_depth == "deep" else "draft_observed",
            "asset_match_is_evidence_only": True,
            "asset_can_authorize_click": False,
            "assets": assets,
        },
        "summary": {
            "candidate_count": len(candidates),
            "asset_count": len(assets),
            "skipped_count": len(skipped),
            "artifact_is_authorization": False,
        },
        "skipped": skipped[:40],
    }


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

    sample_sources = _representative_visual_samples(graph)
    crop_count = 0
    with Image.open(source_path) as image:
        for asset in assets_payload.get("assets") or []:
            if not isinstance(asset, dict):
                continue
            asset["can_authorize_click"] = False
            source = asset.setdefault("source", {})
            asset_id = str(asset.get("asset_id") or "")
            sample = sample_sources.get(asset_id) or {}
            bbox = sample.get("bbox")
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
            if isinstance(sample.get("click_point"), dict):
                source["click_point"] = sample["click_point"]
            if sample.get("sample_source"):
                source["sample_source"] = sample["sample_source"]
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


def _representative_visual_samples(runtime_path_graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    samples: dict[str, dict[str, Any]] = {}
    for sample in runtime_path_graph.get("visual_asset_samples") or []:
        if not isinstance(sample, dict):
            continue
        asset_id = str(sample.get("asset_id") or "")
        bbox = sample.get("bbox")
        if asset_id and isinstance(bbox, dict):
            samples.setdefault(
                asset_id,
                {
                    "bbox": bbox,
                    "click_point": sample.get("click_point"),
                    "sample_source": sample.get("source"),
                },
            )
    for entity in runtime_path_graph.get("entities") or []:
        if not isinstance(entity, dict):
            continue
        if entity.get("entity_type") == "job_card" and isinstance(entity.get("bbox"), dict):
            samples.setdefault(
                "seek:visual:job_card_shape",
                {
                    "bbox": entity["bbox"],
                    "click_point": entity.get("click_point"),
                    "sample_source": "runtime_path_graph_entity",
                },
            )
    return samples


def _learnable_candidate_decision(candidate: dict[str, Any], *, app_id: str | None = None) -> dict[str, Any]:
    label = str(candidate.get("label") or "").strip()
    role = str(candidate.get("role") or "").strip().casefold()
    if not label:
        return {"learnable": False, "reason": "missing_label"}
    if _candidate_bbox(candidate) is None:
        return {"learnable": False, "reason": "missing_bbox"}
    if _looks_like_dynamic_content(role=role, label=label, candidate=candidate):
        return {"learnable": False, "reason": "not_stable_visual_control"}
    if _label_is_final_submit_like(label) and not _role_can_be_dangerous_action(role):
        return {"learnable": False, "reason": "danger_label_not_actionable_control"}
    if not _looks_like_button_or_fixed_control(role=role, label=label):
        return {"learnable": False, "reason": "not_stable_visual_control"}
    semantic_action, danger_level = _classify_visual_asset_action(label, app_id=app_id)
    return {
        "learnable": True,
        "reason": "stable_visual_control",
        "label": label,
        "semantic_action": semantic_action,
        "danger_level": danger_level,
    }


def _looks_like_button_or_fixed_control(*, role: str, label: str) -> bool:
    if role in {
        "button",
        "icon_button",
        "menu_item",
        "menuitem",
        "tab",
        "checkbox",
        "radio",
        "switch",
        "toggle",
        "dropdown",
        "select",
        "combobox",
        "text_input",
        "input",
        "link",
    }:
        return True
    label_key = label.casefold()
    action_words = (
        "apply",
        "quick apply",
        "continue",
        "next",
        "save",
        "submit",
        "send",
        "confirm",
        "search",
        "login",
        "sign in",
        "open",
        "more",
    )
    return any(word in label_key for word in action_words)


def _label_is_final_submit_like(label: str) -> bool:
    key = label.casefold()
    return any(word in key for word in ("submit", "send application", "confirm", "payment", "complete application"))


def _role_can_be_dangerous_action(role: str) -> bool:
    return role in {"button", "icon_button", "menu_item", "menuitem", "link"}


def _looks_like_dynamic_content(*, role: str, label: str, candidate: dict[str, Any]) -> bool:
    if role in {"card", "news_card", "job_card", "result", "row", "article", "detail"}:
        return True
    if candidate.get("screen_map_rule") in {"ocr_card_group", "news_card_group", "result_card_group"}:
        return True
    bbox = _candidate_bbox(candidate)
    if bbox is not None and (bbox["w"] > 420 or bbox["h"] > 180):
        return True
    return len(label) > 80


def _classify_visual_asset_action(label: str, *, app_id: str | None = None) -> tuple[str, str]:
    key = label.casefold()
    if any(word in key for word in ("submit", "send", "confirm", "payment", "complete application")):
        return "final_submit", "final_submit"
    if "quick apply" in key:
        return "open_apply_flow", "flow_entry"
    if app_id and app_id.casefold() == "seek" and key.strip() == "apply":
        return "external_apply_flow", "external_flow_entry"
    if "apply" in key:
        return "open_apply_flow", "flow_entry"
    if any(word in key for word in ("continue", "next")):
        return "continue_next_step", "continue_step"
    if "save" in key:
        return "save_or_bookmark", "safe_navigation"
    if any(word in key for word in ("search", "open", "more", "login", "sign in")):
        return "open_or_navigation", "safe_navigation"
    return "activate_control", "safe_navigation"


def _visual_asset_review_policy(decision: dict[str, Any]) -> dict[str, Any]:
    semantic_action = str(decision.get("semantic_action") or "")
    danger_level = str(decision.get("danger_level") or "")
    if semantic_action == "final_submit" or danger_level == "final_submit":
        return {
            "contract_version": "visual_asset_review_policy_v1",
            "risk_tier": "high",
            "click_permission": "manual_review_required",
            "requires_manual_review_before_click": True,
            "requires_structured_authorization": True,
            "fast_lane_eligible": False,
            "reason": "final_submit_like_visual_asset",
        }
    if danger_level in {"flow_entry", "continue_step"}:
        return {
            "contract_version": "visual_asset_review_policy_v1",
            "risk_tier": "medium",
            "click_permission": "gate_required",
            "requires_manual_review_before_click": False,
            "requires_structured_authorization": False,
            "fast_lane_eligible": False,
            "reason": f"{danger_level}_requires_scope_and_gate",
        }
    return {
        "contract_version": "visual_asset_review_policy_v1",
        "risk_tier": "low",
        "click_permission": "low_risk_fast_lane_eligible",
        "requires_manual_review_before_click": False,
        "requires_structured_authorization": False,
        "fast_lane_eligible": True,
        "reason": "safe_fixed_control",
    }


def _candidate_bbox(candidate: dict[str, Any]) -> dict[str, int] | None:
    bbox = candidate.get("bbox") if isinstance(candidate.get("bbox"), dict) else None
    if not bbox:
        return None
    x = _int_or_none(bbox.get("x"))
    y = _int_or_none(bbox.get("y"))
    width = _int_or_none(bbox.get("w", bbox.get("width")))
    height = _int_or_none(bbox.get("h", bbox.get("height")))
    if x is None or y is None or width is None or height is None or width <= 0 or height <= 0:
        return None
    return {"x": x, "y": y, "w": width, "h": height}


def _candidate_click_point(candidate: dict[str, Any], crop_bbox: tuple[int, int, int, int]) -> dict[str, int]:
    point = candidate.get("click_point") if isinstance(candidate.get("click_point"), dict) else None
    if point:
        x = _int_or_none(point.get("x"))
        y = _int_or_none(point.get("y"))
        if x is not None and y is not None:
            return {"x": x, "y": y}
    left, top, right, bottom = crop_bbox
    return {"x": left + ((right - left) // 2), "y": top + ((bottom - top) // 2)}


def _relative_click_point(candidate: dict[str, Any], crop_bbox: tuple[int, int, int, int]) -> list[float]:
    point = _candidate_click_point(candidate, crop_bbox)
    left, top, right, bottom = crop_bbox
    width = max(1, right - left)
    height = max(1, bottom - top)
    return [
        round((point["x"] - left) / width, 4),
        round((point["y"] - top) / height, 4),
    ]


def _expand_clipped_bbox(
    crop_bbox: tuple[int, int, int, int],
    image_width: int,
    image_height: int,
    *,
    padding: int,
) -> tuple[int, int, int, int]:
    left, top, right, bottom = crop_bbox
    return (
        max(0, left - padding),
        max(0, top - padding),
        min(image_width, right + padding),
        min(image_height, bottom + padding),
    )


def _visual_asset_id(*, app_id: str | None, page_type: str | None, candidate: dict[str, Any], label: str) -> str:
    parts = [
        app_id or "app",
        page_type or "page",
        candidate.get("section_id") or "section",
        candidate.get("candidate_id") or label,
    ]
    return _safe_asset_name(".".join(str(part) for part in parts))[:120]


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
