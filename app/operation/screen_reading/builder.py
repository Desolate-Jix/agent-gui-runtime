from __future__ import annotations

import re
from typing import Any

from app.operation.page_structure.schemas import PageElement, PageStructure, PageText
from app.operation.screen_reading.uia_provider import WindowsUIAProvider
from app.vision.schemas import BBox, VisionAnalyzeResponse, VisionRegion
from modules.ocr.contracts import OCRResult

EXECUTABLE_ROLES = {
    "button",
    "icon",
    "icon_button",
    "toolbar_button",
    "input",
    "textbox",
    "text_box",
    "tab",
    "menu",
    "menu_item",
    "link",
    "nav",
    "navigation",
    "checkbox",
    "radio",
    "toggle",
    "switch",
    "slider",
}
MODULE_ROLES = {"section", "panel", "card", "container", "toolbar", "header", "footer", "region", "group", "form"}
ICON_HINTS = {
    "arrow",
    "back",
    "forward",
    "reload",
    "refresh",
    "close",
    "menu",
    "search",
    "settings",
    "gear",
    "home",
    "chevron",
    "icon",
    "left",
    "right",
}


def build_screen_reading(
    *,
    image_path: str,
    vision: VisionAnalyzeResponse,
    ocr: OCRResult,
    page_structure: PageStructure,
    app_name: str | None = None,
    uia_provider: WindowsUIAProvider | None = None,
    uia_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the agent-facing READ contract from current vision/OCR/fusion evidence."""

    uia_provider = uia_provider or WindowsUIAProvider()
    texts = [_text_to_dict(item) for item in page_structure.texts]
    elements = [_element_from_page_element(item) for item in page_structure.elements]
    source_region_ids = {
        region_id
        for element in page_structure.elements
        for region_id in element.source_region_ids
    }

    visual_only_elements = [
        _element_from_visual_region(region)
        for region in vision.regions
        if region.region_id not in source_region_ids and _region_is_potential_ui(region)
    ]
    elements.extend(visual_only_elements)
    elements.sort(key=lambda item: (item["bbox"]["y"], item["bbox"]["x"], item["id"]))
    _attach_uia_matches(elements, uia_snapshot)

    modules = _build_modules(vision.regions, elements, page_structure.texts)
    icon_candidates = [_icon_candidate(item) for item in elements if _is_icon_candidate(item)]
    execution_relevance = _execution_relevance(elements)
    uncertainties = _uncertainties(elements, icon_candidates)

    ui_payload = {
        "summary": {
            "element_count": len(elements),
            "module_count": len(modules),
            "icon_candidate_count": len(icon_candidates),
            "text_backed_element_count": len([item for item in elements if item.get("label")]),
            "visual_only_element_count": len([item for item in elements if item["evidence_level"] == "visual_region_only"]),
        },
        "elements": elements,
        "modules": modules,
        "icon_candidates": icon_candidates,
        "provider_slots": _provider_slots(uia_provider, uia_snapshot),
        "learning_hooks": _learning_hooks(elements),
    }

    result = {
        "contract_version": "screen_reading_v1",
        "image_path": image_path,
        "app_name": app_name,
        "image_size": vision.image_size.to_dict() if vision.image_size is not None else None,
        "screen_summary": vision.screen_summary,
        "state_guess": vision.state_guess,
        "texts": texts,
        "ui": ui_payload,
        "ui_elements": elements,
        "modules": modules,
        "relationships": [item.to_dict() for item in page_structure.links],
        "execution_relevance": execution_relevance,
        "uncertainties": uncertainties,
        "source_layers": {
            "vision_regions_v1": {
                "provider": vision.provider,
                "region_count": len(vision.regions),
                "notes": list(vision.notes),
            },
            "ocr_result": {
                "engine": str(ocr.metadata.get("engine") or "ocr"),
                "match_count": len(ocr.matches),
            },
            "page_structure_v1": {
                "element_count": len(page_structure.elements),
                "text_count": len(page_structure.texts),
                "link_count": len(page_structure.links),
            },
            "windows_uia": _uia_source_layer(uia_snapshot),
        },
        "raw_refs": {
            "page_structure_contract": page_structure.contract_version,
            "vision_contract": vision.contract_version,
            "ocr_image_path": ocr.image_path,
        },
    }
    from app.operation.screen_inventory import build_screen_inventory

    result["screen_inventory"] = build_screen_inventory(result)
    return result


def _text_to_dict(text: PageText) -> dict[str, Any]:
    return {
        "id": text.text_id,
        "text": text.text,
        "bbox": text.bbox.to_dict(),
        "confidence": float(text.score),
        "source": text.source,
        "source_index": text.source_index,
    }


def _element_from_page_element(element: PageElement) -> dict[str, Any]:
    evidence_level = "ocr_text_and_semantic_region" if element.source_text_ids else "semantic_region_only"
    return {
        "id": element.element_id,
        "type": _ui_type(element.role, has_text=bool(element.text or element.label)),
        "role_guess": element.role,
        "label": element.label or None,
        "description": element.description,
        "bbox": element.bbox.to_dict(),
        "semantic_bbox": element.semantic_bbox.to_dict() if element.semantic_bbox is not None else None,
        "click_point": dict(element.click_point),
        "interaction_type": element.interaction_type,
        "confidence": float(element.fusion_confidence),
        "coordinate_confidence": element.coordinate_confidence,
        "evidence_level": evidence_level,
        "evidence": {
            "sources": list(element.sources),
            "source_region_ids": list(element.source_region_ids),
            "source_text_ids": list(element.source_text_ids),
            "click_strategy": element.click_strategy,
            "interaction_policy": element.interaction_policy.to_dict(),
            "verification_hints": element.verification_hints.to_dict(),
            "fusion": dict(element.evidence),
        },
        "locator_hints": _locator_hints(
            role=element.role,
            label=element.label,
            bbox=element.bbox,
            click_point=element.click_point,
            memory_key=element.memory_key,
            coordinate_source=element.click_strategy,
        ),
        "memory_key": element.memory_key,
        "provider_matches": {"uia": None},
    }


def _element_from_visual_region(region: VisionRegion) -> dict[str, Any]:
    role = _normalize_role(region.role)
    label = _best_visual_label(region)
    bbox = region.bbox
    click_point = _bbox_center(bbox)
    element_id = f"visual_{_slug(region.region_id or label or role)}"
    type_name = _ui_type(role, has_text=bool(region.ocr_text or region.text_lines))
    if _looks_like_icon(region):
        type_name = "icon_button"
    return {
        "id": element_id,
        "type": type_name,
        "role_guess": role,
        "label": label or None,
        "description": region.description,
        "bbox": bbox.to_dict(),
        "semantic_bbox": bbox.to_dict(),
        "click_point": click_point,
        "interaction_type": _interaction_type(role),
        "confidence": round(max(0.0, min(float(region.confidence) * 0.65, 1.0)), 4),
        "coordinate_confidence": "low",
        "evidence_level": "visual_region_only",
        "evidence": {
            "sources": ["vision_regions_v1"],
            "source_region_ids": [region.region_id],
            "source_text_ids": [],
            "click_strategy": "semantic_bbox_center_reserved",
            "interaction_policy": {
                "allowed": False,
                "zone_type": "unknown_visual_ui",
                "priority": "blocked",
                "ad_risk": 0.0,
                "reasons": ["visual_only_requires_grounding_provider"],
            },
            "verification_hints": {
                "expected_changes": ["unknown_change"],
                "target_scope": "local",
            },
        },
        "locator_hints": _locator_hints(
            role=role,
            label=label,
            bbox=bbox,
            click_point=click_point,
            memory_key=f"visual|role:{role}|label:{_normalize_text(label)}|layout:{region.layout_key or 'none'}",
            coordinate_source="semantic_bbox_center_reserved",
        ),
        "memory_key": f"visual|role:{role}|label:{_normalize_text(label)}|layout:{region.layout_key or 'none'}",
        "provider_matches": {"uia": None},
    }


def _build_modules(regions: list[VisionRegion], elements: list[dict[str, Any]], texts: list[PageText]) -> list[dict[str, Any]]:
    modules: list[dict[str, Any]] = []
    for region in regions:
        role = _normalize_role(region.role)
        area = region.bbox.w * region.bbox.h
        if role not in MODULE_ROLES and area < 20000:
            continue
        child_element_ids = [item["id"] for item in elements if _bbox_contains_point(region.bbox, item["click_point"])]
        child_text_ids = [item.text_id for item in texts if _bbox_contains_point(region.bbox, _bbox_center(item.bbox))]
        if not child_element_ids and role not in {"toolbar", "header", "form"}:
            continue
        modules.append(
            {
                "id": f"module_{_slug(region.region_id)}",
                "title": _best_visual_label(region) or role,
                "role_guess": role,
                "purpose_guess": region.description,
                "bbox": region.bbox.to_dict(),
                "child_element_ids": child_element_ids,
                "child_text_ids": child_text_ids,
                "confidence": round(max(0.0, min(float(region.confidence), 1.0)), 4),
                "source_region_id": region.region_id,
            }
        )
    return modules


def _icon_candidate(element: dict[str, Any]) -> dict[str, Any]:
    return {
        "element_id": element["id"],
        "role_guess": element["role_guess"],
        "label": element.get("label"),
        "bbox": element["bbox"],
        "click_point": element["click_point"],
        "confidence": element["confidence"],
        "uia_match": element.get("provider_matches", {}).get("uia"),
        "visual_recognition_status": "reserved_for_grounding",
        "learning_status": "reserved_for_ui_memory",
        "needed_evidence": _needed_icon_evidence(),
    }


def _execution_relevance(elements: list[dict[str, Any]]) -> dict[str, list[str]]:
    safe: list[str] = []
    risky: list[str] = []
    unknown: list[str] = []
    for element in elements:
        policy = element.get("evidence", {}).get("interaction_policy", {})
        if policy.get("allowed") is True and element.get("coordinate_confidence") in {"high", "medium"}:
            safe.append(element["id"])
        elif policy.get("zone_type") == "ad_candidate" or policy.get("allowed") is False:
            risky.append(element["id"])
        else:
            unknown.append(element["id"])
    return {
        "safe_action_candidates": safe,
        "risky_candidates": risky,
        "unknown_clickables": unknown,
    }


def _uncertainties(elements: list[dict[str, Any]], icon_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    visual_only = [item["id"] for item in elements if item["evidence_level"] == "visual_region_only"]
    if visual_only:
        items.append(
            {
                "code": "visual_only_ui_requires_grounding",
                "message": "Visual-only UI regions are reserved until stronger UIA, browser accessibility, icon shape, or learned-UI grounding confirms them before execution.",
                "affected_element_ids": visual_only,
            }
        )
    return items


def _provider_slots(
    uia_provider: WindowsUIAProvider,
    uia_snapshot: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    return {
        "uia": uia_provider.describe_slot(uia_snapshot),
        "browser_accessibility": {
            "status": "reserved",
            "intended_use": "Web page DOM/accessibility roles, names, and bounding boxes.",
            "expected_fields": ["role", "name", "backend_node_id", "bounding_box", "states"],
            "merge_keys": ["bbox_overlap", "accessible_name", "role"],
        },
        "learned_ui_memory": {
            "status": "reserved",
            "intended_use": "Store successful UI element signatures, click points, verification outcomes, and app/window context.",
            "expected_fields": ["memory_key", "success_rate", "last_verified_at", "preferred_locator", "verification_profile"],
            "merge_keys": ["memory_key", "layout_key", "app_name", "window_size_bucket"],
        },
    }


def _needed_icon_evidence() -> list[str]:
    return ["uia_or_browser_accessibility", "icon_shape_match", "nearby_context", "post_action_verification_plan"]


def _learning_hooks(elements: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "profile": "screen_reading_ui_learning_hooks_v1",
        "candidate_memory_records": [
            {
                "element_id": item["id"],
                "memory_key": item["memory_key"],
                "role_guess": item["role_guess"],
                "label": item.get("label"),
                "bbox": item["bbox"],
                "evidence_level": item["evidence_level"],
                "learn_after": ["successful_action", "failed_action", "manual_review_label"],
            }
            for item in elements
        ],
        "reserved_stores": ["ui_element_memory", "icon_signature_memory", "locator_success_history"],
    }


def _locator_hints(
    *,
    role: str,
    label: str,
    bbox: BBox,
    click_point: dict[str, int],
    memory_key: str,
    coordinate_source: str,
) -> dict[str, Any]:
    return {
        "coordinate": {
            "bbox": bbox.to_dict(),
            "click_point": dict(click_point),
            "source": coordinate_source,
        },
        "semantic": {
            "role_guess": role,
            "label": label or None,
        },
        "future_providers": {
            "uia": {
                "status": "connected",
                "provider": "windows_uia",
                "candidate_query": {"name": label or None, "control_type": role},
            },
            "browser_accessibility": {"status": "reserved", "candidate_query": {"role": role, "name": label or None}},
            "learned_ui_memory": {"status": "reserved", "candidate_query": {"memory_key": memory_key}},
        },
    }


def _attach_uia_matches(elements: list[dict[str, Any]], uia_snapshot: dict[str, Any] | None) -> None:
    controls = list((uia_snapshot or {}).get("controls") or [])
    if not controls:
        return
    for element in elements:
        match = _best_uia_match(element, controls)
        element.setdefault("provider_matches", {})["uia"] = match
        if match is not None:
            element["evidence"].setdefault("provider_matches", {})["uia"] = match


def _best_uia_match(element: dict[str, Any], controls: list[dict[str, Any]]) -> dict[str, Any] | None:
    best: tuple[float, dict[str, Any], list[str]] | None = None
    for control in controls:
        control_bbox = control.get("bbox")
        if not isinstance(control_bbox, dict):
            continue
        overlap = _bbox_iou(element["bbox"], control_bbox)
        name_score = _text_match_score(
            " ".join(str(value or "") for value in [element.get("label"), element.get("description"), element.get("memory_key")]),
            str(control.get("name") or ""),
        )
        role_score = _role_match_score(str(element.get("role_guess") or element.get("type") or ""), str(control.get("control_type") or ""))
        score = (overlap * 0.72) + (name_score * 0.2) + (role_score * 0.08)
        if score < 0.28:
            continue
        basis = [f"bbox_iou:{overlap:.3f}"]
        if name_score > 0:
            basis.append(f"name:{control.get('name')}")
        if role_score > 0:
            basis.append(f"control_type:{control.get('control_type')}")
        if best is None or score > best[0]:
            best = (score, control, basis)
    if best is None:
        return None

    score, control, basis = best
    return {
        "provider": control.get("provider") or "windows_uia",
        "control_id": control.get("control_id"),
        "name": control.get("name"),
        "control_type": control.get("control_type"),
        "automation_id": control.get("automation_id"),
        "class_name": control.get("class_name"),
        "bbox": control.get("bbox"),
        "enabled": control.get("enabled"),
        "visible": control.get("visible"),
        "patterns": list(control.get("patterns") or []),
        "score": round(score, 4),
        "match_basis": basis,
    }


def _uia_source_layer(uia_snapshot: dict[str, Any] | None) -> dict[str, Any]:
    snapshot = uia_snapshot or {}
    controls = [item for item in snapshot.get("controls") or [] if isinstance(item, dict)]
    return {
        "provider": snapshot.get("provider") or "windows_uia",
        "status": snapshot.get("status") or "not_scanned",
        "control_count": int(snapshot.get("control_count") or 0),
        "reason": snapshot.get("reason"),
        "controls": [_compact_uia_control(item) for item in controls[:150]],
    }


def _compact_uia_control(control: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": control.get("provider") or "windows_uia",
        "control_id": control.get("control_id"),
        "name": control.get("name"),
        "control_type": control.get("control_type"),
        "automation_id": control.get("automation_id"),
        "class_name": control.get("class_name"),
        "bbox": control.get("bbox"),
        "enabled": control.get("enabled"),
        "visible": control.get("visible"),
        "patterns": list(control.get("patterns") or []),
    }


def _bbox_iou(first: dict[str, Any], second: dict[str, Any]) -> float:
    left = max(float(first["x"]), float(second["x"]))
    top = max(float(first["y"]), float(second["y"]))
    right = min(float(first["x"]) + float(first["w"]), float(second["x"]) + float(second["w"]))
    bottom = min(float(first["y"]) + float(first["h"]), float(second["y"]) + float(second["h"]))
    if right <= left or bottom <= top:
        return 0.0
    intersection = (right - left) * (bottom - top)
    first_area = max(1.0, float(first["w"]) * float(first["h"]))
    second_area = max(1.0, float(second["w"]) * float(second["h"]))
    return intersection / (first_area + second_area - intersection)


def _text_match_score(first: str, second: str) -> float:
    first_norm = _normalize_text(first)
    second_norm = _normalize_text(second)
    if not first_norm or not second_norm:
        return 0.0
    if first_norm in second_norm or second_norm in first_norm:
        return 1.0
    first_tokens = set(first_norm.split())
    second_tokens = set(second_norm.split())
    if not first_tokens or not second_tokens:
        return 0.0
    return len(first_tokens & second_tokens) / len(first_tokens | second_tokens)


def _role_match_score(role: str, control_type: str) -> float:
    role_norm = _normalize_text(role)
    control_norm = _normalize_text(control_type)
    if not role_norm or not control_norm:
        return 0.0
    if "button" in role_norm and "button" in control_norm:
        return 1.0
    if "input" in role_norm and any(token in control_norm for token in ["edit", "document", "textbox"]):
        return 1.0
    if role_norm in control_norm or control_norm in role_norm:
        return 0.7
    return 0.0


def _region_is_potential_ui(region: VisionRegion) -> bool:
    role = _normalize_role(region.role)
    if role in EXECUTABLE_ROLES:
        return True
    label_text = _normalize_text(" ".join([region.label, region.description, region.ocr_text, *region.text_lines]))
    return any(hint in label_text for hint in ICON_HINTS)


def _is_icon_candidate(element: dict[str, Any]) -> bool:
    if element["type"] == "icon_button":
        return True
    if element["evidence_level"] != "visual_region_only":
        return False
    label_text = _normalize_text(" ".join(str(value or "") for value in [element.get("role_guess"), element.get("label"), element.get("description")]))
    return any(hint in label_text for hint in ICON_HINTS)


def _looks_like_icon(region: VisionRegion) -> bool:
    role = _normalize_role(region.role)
    if role in {"icon", "icon_button", "toolbar_button"}:
        return True
    text = _normalize_text(" ".join([region.label, region.description, region.ocr_text, *region.text_lines]))
    compact_box = region.bbox.w <= 96 and region.bbox.h <= 96
    return compact_box and any(hint in text for hint in ICON_HINTS)


def _ui_type(role: str, *, has_text: bool) -> str:
    role = _normalize_role(role)
    if role in {"icon", "icon_button", "toolbar_button"}:
        return "icon_button"
    if role in {"input", "textbox", "text_box"}:
        return "text_input"
    if role in {"tab", "menu_item", "checkbox", "radio", "slider", "toggle", "switch"}:
        return role
    if role in {"nav", "navigation", "menu", "link"}:
        return "menu_item"
    if role == "button" and not has_text:
        return "visual_button"
    return role or "ui_element"


def _interaction_type(role: str) -> str:
    role = _normalize_role(role)
    if role in {"input", "textbox", "text_box"}:
        return "focus"
    if role in {"slider"}:
        return "drag"
    return "click"


def _best_visual_label(region: VisionRegion) -> str:
    for value in [region.ocr_text, *region.text_lines, region.label]:
        if str(value or "").strip():
            return str(value).strip()
    return ""


def _bbox_center(bbox: BBox) -> dict[str, int]:
    return {
        "x": int(round(bbox.x + bbox.w / 2.0)),
        "y": int(round(bbox.y + bbox.h / 2.0)),
    }


def _bbox_contains_point(bbox: BBox, point: dict[str, int]) -> bool:
    return bbox.x <= int(point["x"]) <= bbox.x + bbox.w and bbox.y <= int(point["y"]) <= bbox.y + bbox.h


def _normalize_role(role: str) -> str:
    normalized = _normalize_text(role).replace(" ", "_")
    aliases = {
        "navigation": "nav",
        "toolbarbutton": "toolbar_button",
        "textinput": "input",
        "textbox": "textbox",
    }
    return aliases.get(normalized, normalized)


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", _normalize_text(value)).strip("_") or "item"
