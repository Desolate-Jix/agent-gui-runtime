from __future__ import annotations

import re
from typing import Any

from app.page_structure.schemas import PageElement, PageStructure, PageText
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
) -> dict[str, Any]:
    """Build the agent-facing READ contract from current vision/OCR/fusion evidence."""

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
        "provider_slots": _provider_slots(),
        "learning_hooks": _learning_hooks(elements),
    }

    return {
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
        },
        "raw_refs": {
            "page_structure_contract": page_structure.contract_version,
            "vision_contract": vision.contract_version,
            "ocr_image_path": ocr.image_path,
        },
    }


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
        "icon_library_match": None,
        "catalog_status": "reserved_for_icon_provider",
        "learning_status": "reserved_for_ui_memory",
        "needed_evidence": ["icon_shape_match", "nearby_context", "post_action_verification_plan"],
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
    if icon_candidates:
        items.append(
            {
                "code": "icon_provider_not_connected",
                "message": "Icon-like UI candidates are exposed but no icon catalog/template provider has confirmed their role yet.",
                "affected_element_ids": [item["element_id"] for item in icon_candidates],
            }
        )
    visual_only = [item["id"] for item in elements if item["evidence_level"] == "visual_region_only"]
    if visual_only:
        items.append(
            {
                "code": "visual_only_ui_requires_grounding",
                "message": "Visual-only UI regions are reserved for future UIA, browser accessibility, icon, or learned-UI grounding before execution.",
                "affected_element_ids": visual_only,
            }
        )
    return items


def _provider_slots() -> dict[str, dict[str, Any]]:
    return {
        "uia": {
            "status": "reserved",
            "intended_use": "Windows desktop controls and browser chrome such as Back, Forward, Refresh, address bar, tabs, and window buttons.",
            "expected_fields": ["control_type", "name", "automation_id", "bounding_rectangle", "enabled", "patterns"],
            "merge_keys": ["bbox_overlap", "role_guess", "label_or_name", "window_process"],
        },
        "browser_accessibility": {
            "status": "reserved",
            "intended_use": "Web page DOM/accessibility roles, names, and bounding boxes.",
            "expected_fields": ["role", "name", "backend_node_id", "bounding_box", "states"],
            "merge_keys": ["bbox_overlap", "accessible_name", "role"],
        },
        "icon_library": {
            "status": "reserved",
            "intended_use": "No-text icons such as browser_back, refresh, close, search, settings, and menu.",
            "expected_fields": ["icon_id", "family", "bbox", "score", "template_or_model_version"],
            "merge_keys": ["bbox_overlap", "icon_id", "nearby_context"],
        },
        "learned_ui_memory": {
            "status": "reserved",
            "intended_use": "Store successful UI element signatures, click points, verification outcomes, and app/window context.",
            "expected_fields": ["memory_key", "success_rate", "last_verified_at", "preferred_locator", "verification_profile"],
            "merge_keys": ["memory_key", "layout_key", "app_name", "window_size_bucket"],
        },
    }


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
            "uia": {"status": "reserved", "candidate_query": {"name": label or None, "control_type": role}},
            "browser_accessibility": {"status": "reserved", "candidate_query": {"role": role, "name": label or None}},
            "icon_library": {"status": "reserved", "candidate_query": {"role_guess": role, "bbox": bbox.to_dict()}},
            "learned_ui_memory": {"status": "reserved", "candidate_query": {"memory_key": memory_key}},
        },
    }


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
