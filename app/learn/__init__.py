"""Lazy public surface for learning helpers.

This preserves the established exports while allowing offline UEI modules to
avoid unrelated vision and OCR runtime imports.
"""

from __future__ import annotations

from importlib import import_module


_EXPORTS = {
    "LEARNED_SKILL_CONTRACT": ("app.learn.path_graph_artifacts", "LEARNED_SKILL_CONTRACT"),
    "RUNTIME_PATH_GRAPH_CONTRACT": ("app.learn.path_graph_artifacts", "RUNTIME_PATH_GRAPH_CONTRACT"),
    "RUNTIME_PATH_GRAPH_EXPORT_CONTRACT": ("app.learn.path_graph_artifacts", "RUNTIME_PATH_GRAPH_EXPORT_CONTRACT"),
    "VISUAL_ASSET_CONTRACT": ("app.learn.path_graph_artifacts", "VISUAL_ASSET_CONTRACT"),
    "build_learned_skills_from_seek_artifact": ("app.learn.path_graph_artifacts", "build_learned_skills_from_seek_artifact"),
    "build_runtime_path_graph_from_seek_artifact": ("app.learn.path_graph_artifacts", "build_runtime_path_graph_from_seek_artifact"),
    "build_seek_runtime_path_graph_export": ("app.learn.path_graph_artifacts", "build_seek_runtime_path_graph_export"),
    "build_visual_assets_from_seek_artifact": ("app.learn.path_graph_artifacts", "build_visual_assets_from_seek_artifact"),
    "LEARNED_INTERFACE_MAP_CONTRACT": ("app.learn.interface_map", "LEARNED_INTERFACE_MAP_CONTRACT"),
    "build_learned_interface_map": ("app.learn.interface_map", "build_learned_interface_map"),
    "merge_visual_asset_match_evidence": ("app.learn.interface_map", "merge_visual_asset_match_evidence"),
    "LEARNING_MODEL_ATTEMPT_CONTRACT": ("app.learn.model_trial", "LEARNING_MODEL_ATTEMPT_CONTRACT"),
    "LEARNING_MODEL_TRIAL_CONTRACT": ("app.learn.model_trial", "LEARNING_MODEL_TRIAL_CONTRACT"),
    "LEARNING_TEMPLATE_DRAFT_CONTRACT": ("app.learn.model_trial", "LEARNING_TEMPLATE_DRAFT_CONTRACT"),
    "build_learning_model_trial": ("app.learn.model_trial", "build_learning_model_trial"),
    "score_learning_template_draft": ("app.learn.model_trial", "score_learning_template_draft"),
    "LEARN_CANDIDATE_CLASSIFICATION_CONTRACT": ("app.learn.recognition.contracts", "LEARN_CANDIDATE_CLASSIFICATION_CONTRACT"),
    "LEARN_OBSERVE_BUNDLE_CONTRACT": ("app.learn.recognition.contracts", "LEARN_OBSERVE_BUNDLE_CONTRACT"),
    "LEARNING_RECOGNITION_DRAFT_SOURCE": ("app.learn.recognition.contracts", "LEARNING_RECOGNITION_DRAFT_SOURCE"),
    "SCREEN_INVENTORY_ITEM_CONTRACT": ("app.learn.recognition.contracts", "SCREEN_INVENTORY_ITEM_CONTRACT"),
    "build_inventory_item": ("app.learn.recognition.contracts", "build_inventory_item"),
    "build_learning_template_draft_from_validated_items": ("app.learn.recognition.contracts", "build_learning_template_draft_from_validated_items"),
    "build_learning_recognition_trial": ("app.learn.recognition.pipeline", "build_learning_recognition_trial"),
    "build_roi_crop_metadata": ("app.learn.recognition.roi", "build_roi_crop_metadata"),
    "classify_inventory_items": ("app.learn.recognition.classifier", "classify_inventory_items"),
    "parse_existing_evidence_to_inventory": ("app.learn.recognition.parsers", "parse_existing_evidence_to_inventory"),
    "restore_local_point_to_screen": ("app.learn.recognition.roi", "restore_local_point_to_screen"),
    "validate_grounding_candidate": ("app.learn.recognition.validator", "validate_grounding_candidate"),
    "PATH_GRAPH_RESOLUTION_CONTRACT": ("app.learn.path_graph_resolver", "PATH_GRAPH_RESOLUTION_CONTRACT"),
    "resolve_runtime_path_graph": ("app.learn.path_graph_resolver", "resolve_runtime_path_graph"),
    "VISUAL_ASSET_CROP_EXPORT_CONTRACT": ("app.learn.visual_asset_crops", "VISUAL_ASSET_CROP_EXPORT_CONTRACT"),
    "VISUAL_ASSET_LEARNING_CONTRACT": ("app.learn.visual_asset_crops", "VISUAL_ASSET_LEARNING_CONTRACT"),
    "build_visual_asset_crop_export": ("app.learn.visual_asset_crops", "build_visual_asset_crop_export"),
    "build_visual_assets_from_screen_map": ("app.learn.visual_asset_crops", "build_visual_assets_from_screen_map"),
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
