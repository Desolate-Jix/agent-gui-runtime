"""Lazy public surface for recognition helpers.

Keeping this package initializer dependency-light lets offline UEI contracts be
imported without loading OCR or vision runtime providers.
"""

from __future__ import annotations

from importlib import import_module


_EXPORTS = {
    "LEARN_CANDIDATE_CLASSIFICATION_CONTRACT": ("app.learn.recognition.contracts", "LEARN_CANDIDATE_CLASSIFICATION_CONTRACT"),
    "LEARN_OBSERVE_BUNDLE_CONTRACT": ("app.learn.recognition.contracts", "LEARN_OBSERVE_BUNDLE_CONTRACT"),
    "LEARNING_RECOGNITION_DRAFT_SOURCE": ("app.learn.recognition.contracts", "LEARNING_RECOGNITION_DRAFT_SOURCE"),
    "SCREEN_INVENTORY_ITEM_CONTRACT": ("app.learn.recognition.contracts", "SCREEN_INVENTORY_ITEM_CONTRACT"),
    "build_inventory_item": ("app.learn.recognition.contracts", "build_inventory_item"),
    "build_learning_template_draft_from_validated_items": ("app.learn.recognition.contracts", "build_learning_template_draft_from_validated_items"),
    "build_grounding_request": ("app.learn.recognition.grounding", "build_grounding_request"),
    "build_inventory_layout_graph": ("app.learn.recognition.layout_graph", "build_inventory_layout_graph"),
    "build_locator_task_cards": ("app.learn.recognition.locator_tasks", "build_locator_task_cards"),
    "build_learning_recognition_trial": ("app.learn.recognition.pipeline", "build_learning_recognition_trial"),
    "build_two_stage_screen_understanding": ("app.learn.recognition.two_stage", "build_two_stage_screen_understanding"),
    "classify_inventory_items": ("app.learn.recognition.classifier", "classify_inventory_items"),
    "fusion_status_from_two_stage": ("app.learn.recognition.two_stage", "fusion_status_from_two_stage"),
    "model_grounding_evidence_status_from_two_stage": ("app.learn.recognition.two_stage", "model_grounding_evidence_status_from_two_stage"),
    "local_point_from_grounding_result": ("app.learn.recognition.grounding", "local_point_from_grounding_result"),
    "normalize_grounding_result_to_screen": ("app.learn.recognition.grounding", "normalize_grounding_result_to_screen"),
    "parse_existing_evidence_to_inventory": ("app.learn.recognition.parsers", "parse_existing_evidence_to_inventory"),
    "build_roi_crop_metadata": ("app.learn.recognition.roi", "build_roi_crop_metadata"),
    "restore_local_point_to_screen": ("app.learn.recognition.roi", "restore_local_point_to_screen"),
    "validate_grounding_candidate": ("app.learn.recognition.validator", "validate_grounding_candidate"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    """Resolve one established public name only when its module is requested."""
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as error:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from error
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
