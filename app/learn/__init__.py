"""Lazy public surface for learning helpers.

This preserves the established exports while allowing offline UEI modules to
avoid unrelated vision and OCR runtime imports.
"""

from __future__ import annotations

from importlib import import_module


_EXPORTS = {
    "LEARNED_INTERFACE_MAP_CONTRACT": ("app.learn.interface_map", "LEARNED_INTERFACE_MAP_CONTRACT"),
    "build_learned_interface_map": ("app.learn.interface_map", "build_learned_interface_map"),
    "merge_visual_asset_match_evidence": ("app.learn.interface_map", "merge_visual_asset_match_evidence"),
    "build_roi_crop_metadata": ("app.learn.recognition.roi", "build_roi_crop_metadata"),
    "restore_local_point_to_screen": ("app.learn.recognition.roi", "restore_local_point_to_screen"),
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
