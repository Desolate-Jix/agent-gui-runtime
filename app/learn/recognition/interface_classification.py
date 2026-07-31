from __future__ import annotations

from copy import deepcopy
from typing import Any


INTERFACE_CATEGORIES = {
    "media_catalog",
    "documentation_portal",
    "settings_dashboard",
    "conversation_workspace",
    "mail_workspace",
    "feed_workspace",
    "aggregate_portal",
    "search_workspace",
    "file_browser",
    "form_workflow",
    "employment_workflow",
    "generic",
}

_CATEGORY_ALIASES = {
    "media_library": "media_catalog",
    "media_gallery": "media_catalog",
    "documentation": "documentation_portal",
    "docs_portal": "documentation_portal",
    "settings": "settings_dashboard",
    "settings_grid": "settings_dashboard",
    "chat": "conversation_workspace",
    "conversation": "conversation_workspace",
    "mail": "mail_workspace",
    "email": "mail_workspace",
    "mailbox": "mail_workspace",
    "feed": "feed_workspace",
    "social_feed": "feed_workspace",
    "aggregate_dashboard": "aggregate_portal",
    "browser_portal": "aggregate_portal",
    "personalized_content_portal": "aggregate_portal",
    "web_search": "search_workspace",
    "search_results": "search_workspace",
    "file_manager": "file_browser",
    "file_explorer": "file_browser",
    "form": "form_workflow",
    "job_search": "employment_workflow",
    "job_application": "employment_workflow",
    "recruitment_workflow": "employment_workflow",
}

_CLASS_RULE_PROFILES = {
    "media_catalog": {
        "primary_content_strategy": "visual_card_first",
        "allow_media_card_synthesis": True,
        "allow_chat_semantics": False,
    },
    "documentation_portal": {
        "primary_content_strategy": "text_structure_first",
        "allow_media_card_synthesis": False,
        "allow_chat_semantics": False,
    },
    "settings_dashboard": {
        "primary_content_strategy": "independent_control_cards",
        "allow_media_card_synthesis": False,
        "allow_chat_semantics": False,
    },
    "conversation_workspace": {
        "primary_content_strategy": "conversation_rows",
        "stage1_nested_sidebar_policy": "main_content_child",
        "allow_media_card_synthesis": False,
        "allow_chat_semantics": True,
    },
    "mail_workspace": {
        "primary_content_strategy": "mail_rows",
        "stage1_nested_sidebar_policy": "main_content_child",
        "allow_media_card_synthesis": False,
        "allow_chat_semantics": False,
    },
    "feed_workspace": {
        "primary_content_strategy": "feed_items",
        "allow_media_card_synthesis": False,
        "allow_chat_semantics": False,
    },
    "aggregate_portal": {
        "primary_content_strategy": "independent_content_modules",
        "allow_media_card_synthesis": False,
        "allow_chat_semantics": False,
    },
    "search_workspace": {
        "primary_content_strategy": "search_results",
        "allow_media_card_synthesis": False,
        "allow_chat_semantics": False,
    },
    "file_browser": {
        "primary_content_strategy": "row_table_first",
        "stage1_nested_strip_policy": "main_content_child",
        "allow_media_card_synthesis": False,
        "allow_chat_semantics": False,
    },
    "form_workflow": {
        "primary_content_strategy": "field_group_first",
        "allow_media_card_synthesis": False,
        "allow_chat_semantics": False,
    },
    "employment_workflow": {
        "primary_content_strategy": "employment_workflow",
        "allow_media_card_synthesis": False,
        "allow_chat_semantics": False,
        "final_submit_action_allowed": False,
    },
    "generic": {
        "primary_content_strategy": "evidence_balanced",
        "allow_media_card_synthesis": None,
        "allow_chat_semantics": None,
    },
}

_CATEGORY_REQUIRED_SIGNALS = {
    "media_catalog": "media_cards",
    "documentation_portal": "article_or_document_sections",
    "settings_dashboard": "settings_controls",
    "conversation_workspace": "people_or_conversation_rows",
    "mail_workspace": "mail_or_email_rows",
    "feed_workspace": "feed_items",
    "aggregate_portal": "mixed_content_modules",
    "search_workspace": "search_results",
    "file_browser": "file_or_folder_rows",
    "form_workflow": "form_fields",
    "employment_workflow": "employment_workflow",
}


def classify_interface_surface(
    bundle: dict[str, Any],
    *,
    screen_inventory: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """规范化整屏理解模型给出的界面类别，只用于选择只读识别策略。"""

    source = bundle if isinstance(bundle, dict) else {}
    screen_reading = source.get("screen_reading") if isinstance(source.get("screen_reading"), dict) else {}
    sources = source.get("sources") if isinstance(source.get("sources"), dict) else {}
    vision_source = sources.get("vision") if isinstance(sources.get("vision"), dict) else {}
    raw = screen_reading.get("interface_classification")
    if not isinstance(raw, dict):
        raw = vision_source.get("interface_classification")
    if not isinstance(raw, dict):
        raw = source.get("interface_classification")
    raw = raw if isinstance(raw, dict) else {}
    raw_category = str(raw.get("category") or "").strip().casefold()
    normalized_category = _CATEGORY_ALIASES.get(raw_category, raw_category)
    confidence = _confidence(raw.get("confidence"))
    reason = str(raw.get("reason") or "").strip()
    structure_signals = raw.get("structure_signals") if isinstance(raw.get("structure_signals"), dict) else {}

    if raw_category:
        if normalized_category in INTERFACE_CATEGORIES:
            evidence_validation_status = _evidence_validation_status(normalized_category, structure_signals)
            if evidence_validation_status == "category_signal_conflict":
                return _result(
                    category="generic",
                    confidence=confidence,
                    source="model_output",
                    status="needs_review",
                    reason="model category conflicts with its visible structure signals",
                    raw_model_category=raw_category,
                    rejected_model_category=raw_category,
                    structure_signals=structure_signals,
                    evidence_validation_status=evidence_validation_status,
                )
            dominance_audit = _local_form_dominance_audit(
                category=normalized_category,
                bundle=source,
                screen_inventory=screen_inventory or [],
            )
            if dominance_audit["local_form_is_subordinate"]:
                result = _result(
                    category="generic",
                    confidence=confidence,
                    source="model_output",
                    status="needs_review",
                    reason="visible form fields occupy a local area inside a larger structured workspace",
                    raw_model_category=raw_category,
                    rejected_model_category=raw_category,
                    structure_signals=structure_signals,
                    evidence_validation_status="local_form_subordinate_to_dominant_workspace",
                )
                result["dominance_audit"] = dominance_audit
                return result
            status = "accepted" if confidence >= 0.55 else "needs_review"
            category = normalized_category if status == "accepted" else "generic"
            return _result(
                category=category,
                confidence=confidence,
                source="model_output",
                status=status,
                reason=reason or "model supplied an allowed interface category",
                raw_model_category=raw_category,
                structure_signals=structure_signals,
                evidence_validation_status=evidence_validation_status,
            )
        return _result(
            category="generic",
            confidence=confidence,
            source="model_output",
            status="needs_review",
            reason="model category is outside the allowed cross-application taxonomy",
            raw_model_category=raw_category,
            rejected_model_category=raw_category,
            structure_signals=structure_signals,
            evidence_validation_status="category_not_allowed",
        )

    return _result(
        category="generic",
        confidence=0.0,
        source="missing_model_classification",
        status="needs_review",
        reason="model did not provide an explicit interface category",
        raw_model_category="",
        structure_signals={},
        evidence_validation_status="not_available",
    )


def _result(
    *,
    category: str,
    confidence: float,
    source: str,
    status: str,
    reason: str,
    raw_model_category: str,
    rejected_model_category: str = "",
    structure_signals: dict[str, Any] | None = None,
    evidence_validation_status: str = "not_available",
) -> dict[str, Any]:
    result = {
        "contract_version": "learn_interface_classification_v1",
        "category": category,
        "confidence": round(confidence, 4),
        "source": source,
        "status": status,
        "reason": reason,
        "raw_model_category": raw_model_category,
        "structure_signals": deepcopy(structure_signals or {}),
        "evidence_validation_status": evidence_validation_status,
        "class_rule_profile": _class_rule_profile(
            category,
            structure_signals=structure_signals,
        ),
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "safety_policy_override_allowed": False,
    }
    if rejected_model_category:
        result["rejected_model_category"] = rejected_model_category
    return result


def _class_rule_profile(
    category: str,
    *,
    structure_signals: dict[str, Any] | None,
) -> dict[str, Any]:
    profile = deepcopy(_CLASS_RULE_PROFILES[category])
    signals = structure_signals if isinstance(structure_signals, dict) else {}
    if (
        category == "feed_workspace"
        and signals.get("feed_items") is True
        and signals.get("media_cards") is True
    ):
        profile["primary_content_strategy"] = "visual_feed_card_first"
        profile["allow_media_card_synthesis"] = True
    return profile


def _evidence_validation_status(category: str, structure_signals: dict[str, Any]) -> str:
    if not structure_signals or category == "generic":
        return "not_available"
    required_signal = _CATEGORY_REQUIRED_SIGNALS.get(category)
    if required_signal and structure_signals.get(required_signal) is False:
        return "category_signal_conflict"
    if (
        category == "file_browser"
        and structure_signals.get("people_or_conversation_rows") is True
        and structure_signals.get("file_or_folder_rows") is not True
    ):
        return "category_signal_conflict"
    if required_signal and structure_signals.get(required_signal) is True:
        return "validated"
    return "not_available"


def _local_form_dominance_audit(
    *,
    category: str,
    bundle: dict[str, Any],
    screen_inventory: list[dict[str, Any]],
) -> dict[str, Any]:
    if category != "form_workflow" or not screen_inventory:
        return {
            "local_form_is_subordinate": False,
            "reason": "not_applicable",
        }
    screen_size = bundle.get("screen_size") if isinstance(bundle.get("screen_size"), dict) else {}
    if not screen_size and isinstance(bundle.get("image_size"), dict):
        screen_size = bundle["image_size"]
    width = _positive_int(screen_size.get("width"))
    height = _positive_int(screen_size.get("height"))
    screen_area = max(1, width * height)
    field_tokens = {"input", "textarea", "combobox", "field", "textbox", "select"}
    workspace_tokens = {"code", "document", "list", "pane", "table", "tree", "diff", "grid"}
    field_items: list[dict[str, Any]] = []
    broad_workspace_items: list[dict[str, Any]] = []
    non_field_count = 0
    for item in screen_inventory:
        if not isinstance(item, dict):
            continue
        role_text = " ".join(
            str(item.get(key) or "").strip().casefold()
            for key in ("role", "item_type")
        )
        bbox = _inventory_bbox(item.get("bbox"))
        is_field = any(token in role_text for token in field_tokens)
        if is_field:
            field_items.append(item)
            continue
        non_field_count += 1
        if bbox and any(token in role_text for token in workspace_tokens):
            area_ratio = (bbox["w"] * bbox["h"]) / screen_area
            if area_ratio >= 0.08:
                broad_workspace_items.append(item)
    field_items = _dedupe_inventory_items_by_bbox(field_items)
    broad_workspace_items = _dedupe_inventory_items_by_bbox(broad_workspace_items)
    field_area = sum(
        bbox["w"] * bbox["h"]
        for item in field_items
        if (bbox := _inventory_bbox(item.get("bbox"))) is not None
    )
    field_area_ratio = field_area / screen_area
    local_form_is_subordinate = bool(
        1 <= len(field_items) <= 4
        and field_area_ratio < 0.1
        and len(broad_workspace_items) >= 2
        and non_field_count >= max(12, len(field_items) * 4)
    )
    return {
        "local_form_is_subordinate": local_form_is_subordinate,
        "reason": (
            "few_local_fields_inside_multiple_broad_workspace_regions"
            if local_form_is_subordinate
            else "form_dominance_not_disproved"
        ),
        "field_count": len(field_items),
        "field_area_ratio": round(field_area_ratio, 4),
        "broad_workspace_region_count": len(broad_workspace_items),
        "non_field_item_count": non_field_count,
    }


def _inventory_bbox(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    x = _positive_int(value.get("x"), allow_zero=True)
    y = _positive_int(value.get("y"), allow_zero=True)
    width = _positive_int(value.get("w", value.get("width")))
    height = _positive_int(value.get("h", value.get("height")))
    if width <= 0 or height <= 0:
        return None
    return {"x": x, "y": y, "w": width, "h": height}


def _dedupe_inventory_items_by_bbox(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: list[dict[str, Any]] = []
    seen: set[tuple[int, int, int, int]] = set()
    for item in items:
        bbox = _inventory_bbox(item.get("bbox"))
        if not bbox:
            continue
        key = (bbox["x"], bbox["y"], bbox["w"], bbox["h"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _positive_int(value: Any, *, allow_zero: bool = False) -> int:
    try:
        parsed = int(round(float(value)))
    except (TypeError, ValueError):
        return 0
    return max(0 if allow_zero else 1, parsed)


def _confidence(value: Any) -> float:
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
