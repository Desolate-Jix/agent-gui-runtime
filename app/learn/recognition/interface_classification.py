from __future__ import annotations

from copy import deepcopy
from typing import Any


INTERFACE_CATEGORIES = {
    "media_catalog",
    "documentation_portal",
    "settings_dashboard",
    "conversation_workspace",
    "file_browser",
    "form_workflow",
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
    "file_manager": "file_browser",
    "file_explorer": "file_browser",
    "form": "form_workflow",
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
    "generic": {
        "primary_content_strategy": "evidence_balanced",
        "allow_media_card_synthesis": None,
        "allow_chat_semantics": False,
    },
}

_CATEGORY_REQUIRED_SIGNALS = {
    "media_catalog": "media_cards",
    "documentation_portal": "article_or_document_sections",
    "settings_dashboard": "settings_controls",
    "conversation_workspace": "people_or_conversation_rows",
    "file_browser": "file_or_folder_rows",
    "form_workflow": "form_fields",
}


def classify_interface_surface(bundle: dict[str, Any]) -> dict[str, Any]:
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
        "class_rule_profile": deepcopy(_CLASS_RULE_PROFILES[category]),
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "safety_policy_override_allowed": False,
    }
    if rejected_model_category:
        result["rejected_model_category"] = rejected_model_category
    return result


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


def _confidence(value: Any) -> float:
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0.0
