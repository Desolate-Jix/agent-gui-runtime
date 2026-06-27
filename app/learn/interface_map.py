from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


LEARNED_INTERFACE_MAP_CONTRACT = "learned_interface_map_v1"


def build_learned_interface_map(
    runtime_path_graph: dict[str, Any] | None,
    visual_assets: dict[str, Any] | None,
) -> dict[str, Any]:
    """把路径图和视觉资产合成面板可编辑的界面地图。"""

    graph = runtime_path_graph if isinstance(runtime_path_graph, dict) else {}
    asset_store = visual_assets if isinstance(visual_assets, dict) else {}
    regions = [_interface_region(item) for item in graph.get("regions") or [] if isinstance(item, dict)]
    fixed_assets = [_interface_visual_asset(item) for item in asset_store.get("assets") or [] if isinstance(item, dict)]
    dynamic_areas = _dynamic_areas(graph, regions)
    _attach_children_to_regions(regions, fixed_assets=fixed_assets, dynamic_areas=dynamic_areas)
    danger_zones = _danger_zones(fixed_assets)
    return {
        "contract_version": LEARNED_INTERFACE_MAP_CONTRACT,
        "map_id": f"{graph.get('app_id') or 'app'}:{graph.get('page_type') or 'page'}:interface_map_v1",
        "app_id": graph.get("app_id"),
        "page_type": graph.get("page_type"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "runtime_path_graph_contract": graph.get("contract_version"),
            "visual_assets_contract": asset_store.get("contract_version"),
            "artifact_is_authorization": False,
        },
        "states": _interface_states(graph),
        "regions": regions,
        "fixed_visual_assets": fixed_assets,
        "dynamic_areas": dynamic_areas,
        "danger_zones": danger_zones,
        "transitions": _interface_transitions(graph),
        "editor_policy": {
            "manual_edits_write_trace": True,
            "editable_fields": [
                "region.label",
                "region.role",
                "region.bbox_hint",
                "visual_asset.semantic_action",
                "visual_asset.danger_level",
                "visual_asset.allowed_region_ids",
            ],
            "dangerous_actions_require_review": True,
            "artifact_authorizes_click": False,
        },
        "summary": {
            "state_count": len(_interface_state_items(graph)),
            "region_count": len(regions),
            "fixed_visual_asset_count": len(fixed_assets),
            "dynamic_area_count": len(dynamic_areas),
            "danger_zone_count": len(danger_zones),
        },
    }


def merge_visual_asset_match_evidence(
    interface_map: dict[str, Any],
    *,
    asset_id: str,
    match: dict[str, Any],
) -> dict[str, Any]:
    """把当前截图匹配证据写回界面地图，供面板 Inspector 审核。"""

    assets = interface_map.get("fixed_visual_assets")
    if not isinstance(assets, list):
        return interface_map
    for asset in assets:
        if not isinstance(asset, dict) or str(asset.get("asset_id") or "") != str(asset_id):
            continue
        refs = asset.get("template_refs")
        if not isinstance(refs, dict):
            refs = {}
            asset["template_refs"] = refs
        if match.get("current_roi_ref"):
            refs["current_roi_ref"] = match.get("current_roi_ref")
        if match.get("current_match_ref"):
            refs["current_match_ref"] = match.get("current_match_ref")
        candidate = match.get("candidate") if isinstance(match.get("candidate"), dict) else {}
        asset["last_match_evidence"] = {
            "contract_version": "visual_asset_match_evidence_v1",
            "matched": bool(match.get("matched")),
            "match_score": match.get("match_score"),
            "score_gap_to_second": match.get("score_gap_to_second"),
            "elapsed_ms": match.get("elapsed_ms"),
            "match_method": match.get("match_method"),
            "scale_used": match.get("scale_used"),
            "risk_class": candidate.get("risk_class") or match.get("risk_class"),
            "bbox": match.get("bbox"),
            "click_point": match.get("click_point"),
            "candidate_freshness": candidate.get("candidate_freshness") or match.get("candidate_freshness"),
            "current_roi_ref": match.get("current_roi_ref"),
            "current_match_ref": match.get("current_match_ref"),
            "artifact_is_authorization": False,
        }
        asset["can_authorize_click"] = False
        asset["requires_gate"] = True
        if asset.get("semantic_action") == "final_submit" or str(asset.get("danger_level") or "").lower() in {"high", "final_submit"}:
            asset["fast_lane_allowed"] = False
        break
    interface_map["summary"] = _summary(interface_map)
    return interface_map


def _interface_states(graph: dict[str, Any]) -> list[dict[str, Any]]:
    states: list[dict[str, Any]] = []
    regions = [region for region in graph.get("regions") or [] if isinstance(region, dict)]
    all_region_refs = [region.get("region_id") for region in regions if region.get("region_id")]
    for item in _interface_state_items(graph):
        if not isinstance(item, dict):
            continue
        state_id = str(item.get("state_id") or "").strip()
        if not state_id:
            continue
        region_refs = [
            str(region_id)
            for region_id in (item.get("region_refs") or item.get("required_regions") or all_region_refs)
            if region_id
        ]
        states.append(
            {
                "state_id": state_id,
                "label": item.get("label") or state_id,
                "page_type": item.get("page_type") or graph.get("page_type"),
                "state_fingerprint": item.get("state_fingerprint") or item.get("match_evidence") or {},
                "default_collapsed": False,
                "region_refs": region_refs,
                "child_state_ids": list(item.get("child_state_ids") or []),
            }
        )
    return states


def _interface_state_items(graph: dict[str, Any]) -> list[dict[str, Any]]:
    display_states = [item for item in graph.get("display_states") or [] if isinstance(item, dict)]
    if display_states:
        return display_states
    return [item for item in graph.get("states") or [] if isinstance(item, dict)]


def _interface_region(region: dict[str, Any]) -> dict[str, Any]:
    region_id = str(region.get("region_id") or "")
    role = str(region.get("role") or "")
    region_type = _region_type(region_id=region_id, role=role)
    return {
        "region_id": region_id,
        "label": region.get("label") or region_id,
        "role": role,
        "region_type": region_type,
        "parent_region_id": region.get("parent_region_id"),
        "container_id": region.get("container_id"),
        "repeatable": bool(region.get("repeatable")),
        "default_collapsed": region_type in {"dynamic_collection", "detail_content"},
        "bbox_hint": {
            "source": "learned_region_hint",
            "bbox": region.get("bbox") if isinstance(region.get("bbox"), dict) else None,
            "requires_current_reobserve": True,
            "no_overlap_except_containment": True,
        },
        "visual_policy": {
            "fixed_assets_use_template_match": region_type in {"fixed_controls", "navigation"},
            "dynamic_content_uses_roi_model": region_type in {"dynamic_collection", "detail_content", "form_flow"},
            "full_screen_model_fallback_only": True,
        },
        "children": {
            "fixed_visual_asset_refs": [],
            "dynamic_area_refs": [],
        },
    }


def _interface_visual_asset(asset: dict[str, Any]) -> dict[str, Any]:
    source = asset.get("source") if isinstance(asset.get("source"), dict) else {}
    scope = asset.get("scope") if isinstance(asset.get("scope"), dict) else {}
    crop = asset.get("crop") if isinstance(asset.get("crop"), dict) else {}
    source_geometry = asset.get("source_geometry") if isinstance(asset.get("source_geometry"), dict) else {}
    template_refs = asset.get("template_refs") if isinstance(asset.get("template_refs"), dict) else {}
    semantic_action = str(asset.get("semantic_action") or "visual_evidence")
    danger_level = str(asset.get("danger_level") or _danger_for_action(semantic_action))
    review_policy = asset.get("review_policy") if isinstance(asset.get("review_policy"), dict) else _interface_review_policy(semantic_action, danger_level)
    region_id = (
        asset.get("region_id")
        or _first_text(scope.get("allowed_region_ids"))
        or _first_text(scope.get("allowed_container_ids"))
    )
    return {
        "asset_id": asset.get("asset_id"),
        "label": asset.get("label"),
        "role": asset.get("role"),
        "region_id": region_id,
        "semantic_action": semantic_action,
        "danger_level": danger_level,
        "is_high_risk": _is_high_risk(semantic_action, danger_level),
        "review_policy": review_policy,
        "click_permission": review_policy.get("click_permission"),
        "fast_lane_eligible": bool(review_policy.get("fast_lane_eligible")),
        "can_authorize_click": False,
        "requires_gate": True,
        "allowed_region_ids": scope.get("allowed_region_ids") or ([region_id] if region_id else []),
        "expected_text": scope.get("expected_text") or asset.get("anchors") or [],
        "negative_text": scope.get("negative_text") or [],
        "template_refs": {
            "tight_crop_ref": template_refs.get("tight_crop_ref") or crop.get("tight_crop_ref") or source.get("crop_path"),
            "context_crop_ref": template_refs.get("context_crop_ref") or crop.get("context_crop_ref"),
            "source_image_path": template_refs.get("source_image_path") or crop.get("source_image_path") or source.get("source_image_path"),
            "current_roi_ref": None,
            "current_match_ref": None,
        },
        "source_geometry": {
            "bbox": source_geometry.get("bbox") or source.get("bbox"),
            "click_point": source_geometry.get("click_point") or source.get("click_point"),
            "coordinate_space": source_geometry.get("coordinate_space") or source.get("coordinate_space") or "source_capture_px",
            "source_is_authorization": False,
            "click_point_policy": source_geometry.get("click_point_policy"),
            "click_point_relative": source_geometry.get("click_point_relative"),
        },
        "match_policy": asset.get("match_policy") or {},
    }


def _attach_children_to_regions(
    regions: list[dict[str, Any]],
    *,
    fixed_assets: list[dict[str, Any]],
    dynamic_areas: list[dict[str, Any]],
) -> None:
    """把资产和动态区挂回区域，避免面板只能看到孤立节点。"""

    region_by_id = {str(item.get("region_id") or ""): item for item in regions if item.get("region_id")}
    region_bboxes = [
        (region_id, region.get("bbox_hint", {}).get("bbox"))
        for region_id, region in region_by_id.items()
        if isinstance(region.get("bbox_hint", {}).get("bbox"), dict)
    ]
    for asset in fixed_assets:
        region_id = str(asset.get("region_id") or "")
        if region_id not in region_by_id:
            inferred = _best_region_for_bbox(asset.get("source_geometry", {}).get("bbox"), region_bboxes)
            region_id = inferred or ""
            asset["region_id"] = region_id or None
        if region_id and region_id in region_by_id:
            refs = region_by_id[region_id]["children"].setdefault("fixed_visual_asset_refs", [])
            asset_id = asset.get("asset_id")
            if asset_id and asset_id not in refs:
                refs.append(asset_id)
            if not asset.get("allowed_region_ids"):
                asset["allowed_region_ids"] = [region_id]
    for area in dynamic_areas:
        region_id = str(area.get("region_id") or "")
        if region_id and region_id in region_by_id:
            refs = region_by_id[region_id]["children"].setdefault("dynamic_area_refs", [])
            area_id = area.get("area_id")
            if area_id and area_id not in refs:
                refs.append(area_id)


def _best_region_for_bbox(bbox: Any, region_bboxes: list[tuple[str, Any]]) -> str | None:
    if not isinstance(bbox, dict):
        return None
    best_region_id: str | None = None
    best_score = 0.0
    for region_id, region_bbox in region_bboxes:
        score = _bbox_overlap_ratio(bbox, region_bbox)
        if score > best_score:
            best_score = score
            best_region_id = region_id
    return best_region_id if best_score > 0 else None


def _bbox_overlap_ratio(inner: dict[str, Any], outer: Any) -> float:
    if not isinstance(outer, dict):
        return 0.0
    ix, iy, iw, ih = _bbox_numbers(inner)
    ox, oy, ow, oh = _bbox_numbers(outer)
    if iw <= 0 or ih <= 0 or ow <= 0 or oh <= 0:
        return 0.0
    left = max(ix, ox)
    top = max(iy, oy)
    right = min(ix + iw, ox + ow)
    bottom = min(iy + ih, oy + oh)
    if right <= left or bottom <= top:
        return 0.0
    intersection = (right - left) * (bottom - top)
    return intersection / max(1.0, iw * ih)


def _bbox_numbers(bbox: dict[str, Any]) -> tuple[float, float, float, float]:
    return (
        float(bbox.get("x") or 0),
        float(bbox.get("y") or 0),
        float(bbox.get("w", bbox.get("width")) or 0),
        float(bbox.get("h", bbox.get("height")) or 0),
    )


def _first_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
    return None


def _dynamic_areas(graph: dict[str, Any], regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    areas: list[dict[str, Any]] = []
    for item in graph.get("dynamic_collections") or []:
        if not isinstance(item, dict):
            continue
        collection_id = str(item.get("collection_id") or "").strip()
        if not collection_id:
            continue
        areas.append(
            {
                "area_id": collection_id,
                "label": _dynamic_area_label(collection_id, item),
                "description": _dynamic_area_description(collection_id, item),
                "region_id": item.get("region_id"),
                "container_id": item.get("container_id"),
                "entity_type": item.get("entity_type"),
                "role": "ROI",
                "semantic_role": _dynamic_area_semantic_role(collection_id, item),
                "roi_policy": {
                    "source": "region_bbox_hint_then_current_detection",
                    "send_roi_to_model": True,
                    "full_screen_fallback": True,
                },
                "model_budget": {
                    "preferred_scope": "region_roi",
                    "avoid_full_screen_grounding": True,
                },
                "scroll_policy": {
                    "load_more_action_template_id": item.get("load_more_action_template_id"),
                    "wrong_scope_detection_required": True,
                },
            }
        )
    region_ids_with_area = {area["region_id"] for area in areas}
    for region in regions:
        if region["region_type"] == "detail_content" and region["region_id"] not in region_ids_with_area:
            areas.append(
                {
                    "area_id": f"{region['region_id']}:content_roi",
                    "label": _dynamic_area_label(f"{region['region_id']}:content_roi", {"entity_type": "detail_content"}),
                    "description": _dynamic_area_description(
                        f"{region['region_id']}:content_roi",
                        {"entity_type": "detail_content"},
                    ),
                    "region_id": region["region_id"],
                    "container_id": region.get("container_id"),
                    "entity_type": "detail_content",
                    "role": "ROI",
                    "semantic_role": _dynamic_area_semantic_role(
                        f"{region['region_id']}:content_roi",
                        {"entity_type": "detail_content"},
                    ),
                    "roi_policy": {
                        "source": "region_bbox_hint",
                        "send_roi_to_model": True,
                        "full_screen_fallback": True,
                    },
                    "model_budget": {
                        "preferred_scope": "region_roi",
                        "avoid_full_screen_grounding": True,
                    },
                    "scroll_policy": {
                        "wrong_scope_detection_required": True,
                    },
                }
            )
    return areas


def _dynamic_area_label(area_id: str, item: dict[str, Any]) -> str:
    if area_id == "seek:job_cards":
        return "Job cards list"
    if area_id == "job_detail:content_roi":
        return "Job detail pane content"
    if area_id == "detail_body:content_roi":
        return "Job description body text"
    if area_id == "seek:application:cover_letter_roi":
        return "Cover letter writing area"
    if area_id == "seek:application:question_fields_roi":
        return "Employer question fields"
    if area_id == "seek:application:profile_review_roi":
        return "Profile review fields"
    if area_id == "seek:application:final_review_roi":
        return "Final review summary"
    label = _first_text(item.get("label"))
    if label:
        return label
    entity_type = str(item.get("entity_type") or "").replace("_", " ").strip()
    return entity_type.title() if entity_type else area_id


def _dynamic_area_description(area_id: str, item: dict[str, Any]) -> str:
    if area_id == "seek:job_cards":
        return (
            "Repeatable job result cards inside the left results list. Each card usually contains "
            "title, company, location, summary, and opens the right job-detail pane."
        )
    if area_id == "job_detail:content_roi":
        return "Scrollable right detail pane content. Use this as the broad ROI when reading the selected job."
    if area_id == "detail_body:content_roi":
        return "Job description body text ROI. Batch screenshots/OCR should read this until the body reaches bottom."
    if area_id == "seek:application:cover_letter_roi":
        return "Application document step ROI containing the cover-letter input. Keep the default resume and rewrite only the cover letter."
    if area_id == "seek:application:question_fields_roi":
        return "Employer question ROI. Read labels and safe input fields; answer from the candidate profile and current job detail."
    if area_id == "seek:application:profile_review_roi":
        return "SEEK profile review ROI. Prefer continuing without mutating long-lived profile fields unless explicitly requested."
    if area_id == "seek:application:final_review_roi":
        return "Final review ROI. Read and audit the application summary, but never authorize final Submit automatically."
    description = _first_text(item.get("description"))
    if description:
        return description
    entity_type = str(item.get("entity_type") or "dynamic content").replace("_", " ")
    return f"Dynamic {entity_type} area. Use current screenshot evidence before execution."


def _dynamic_area_semantic_role(area_id: str, item: dict[str, Any]) -> str:
    if area_id == "seek:job_cards":
        return "repeatable_job_cards"
    if area_id == "job_detail:content_roi":
        return "detail_pane_reading_roi"
    if area_id == "detail_body:content_roi":
        return "detail_body_text_roi"
    if area_id == "seek:application:cover_letter_roi":
        return "cover_letter_text_input"
    if area_id == "seek:application:question_fields_roi":
        return "employer_question_fields"
    if area_id == "seek:application:profile_review_roi":
        return "profile_review_fields"
    if area_id == "seek:application:final_review_roi":
        return "final_review_summary"
    return str(item.get("semantic_role") or item.get("entity_type") or "dynamic_roi")


def _danger_zones(fixed_assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    zones = []
    for asset in fixed_assets:
        if not asset.get("is_high_risk"):
            continue
        zones.append(
            {
                "zone_id": f"danger:{asset.get('asset_id')}",
                "asset_id": asset.get("asset_id"),
                "label": asset.get("label"),
                "semantic_action": asset.get("semantic_action"),
                "danger_level": asset.get("danger_level"),
                "review_policy": asset.get("review_policy"),
                "click_permission": asset.get("click_permission"),
                "review_required": True,
                "fast_lane_allowed": False,
            }
        )
    return zones


def _interface_transitions(graph: dict[str, Any]) -> list[dict[str, Any]]:
    transitions = []
    for item in graph.get("transitions") or []:
        if not isinstance(item, dict):
            continue
        transitions.append(
            {
                "transition_id": item.get("transition_id"),
                "from_state_id": item.get("from_state_id"),
                "to_state_id": item.get("to_state_id"),
                "action_template_id": item.get("action_template_id"),
                "verification_refs": item.get("verification_refs") or [],
            }
        )
    return transitions


def _region_type(*, region_id: str, role: str) -> str:
    key = f"{region_id} {role}".casefold()
    if any(token in key for token in ("search", "navigation", "nav", "filter")):
        return "navigation"
    if any(token in key for token in ("job_card", "list", "collection", "repeat")):
        return "dynamic_collection"
    if any(token in key for token in ("form", "profile", "question")):
        return "form_flow"
    if any(token in key for token in ("header", "apply", "button")):
        return "fixed_controls"
    if any(token in key for token in ("detail", "body", "content")):
        return "detail_content"
    return "fixed_controls"


def _danger_for_action(semantic_action: str) -> str:
    if _is_high_risk(semantic_action, ""):
        return "final_submit"
    if semantic_action in {"open_apply_flow", "continue_next_step"}:
        return "low"
    return "low"


def _is_high_risk(semantic_action: str, danger_level: str) -> bool:
    text = f"{semantic_action} {danger_level}".casefold()
    return any(term in text for term in ("final_submit", "submit", "send", "confirm", "payment"))


def _interface_review_policy(semantic_action: str, danger_level: str) -> dict[str, Any]:
    if _is_high_risk(semantic_action, danger_level):
        return {
            "contract_version": "visual_asset_review_policy_v1",
            "risk_tier": "high",
            "click_permission": "manual_review_required",
            "requires_manual_review_before_click": True,
            "requires_structured_authorization": True,
            "fast_lane_eligible": False,
            "reason": "high_risk_visual_asset",
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


def _summary(interface_map: dict[str, Any]) -> dict[str, int]:
    return {
        "state_count": len([item for item in interface_map.get("states") or [] if isinstance(item, dict)]),
        "region_count": len([item for item in interface_map.get("regions") or [] if isinstance(item, dict)]),
        "fixed_visual_asset_count": len([item for item in interface_map.get("fixed_visual_assets") or [] if isinstance(item, dict)]),
        "dynamic_area_count": len([item for item in interface_map.get("dynamic_areas") or [] if isinstance(item, dict)]),
        "danger_zone_count": len([item for item in interface_map.get("danger_zones") or [] if isinstance(item, dict)]),
    }
