"""Lazy public surface for recognition helpers.

Keeping this package initializer dependency-light lets offline UEI contracts be
imported without loading OCR or vision runtime providers.
"""

from __future__ import annotations

from importlib import import_module


_EXPORTS = {
    "build_two_stage_screen_understanding": ("app.learn.recognition.two_stage", "build_two_stage_screen_understanding"),
    "fusion_status_from_two_stage": ("app.learn.recognition.two_stage", "fusion_status_from_two_stage"),
    "model_grounding_evidence_status_from_two_stage": ("app.learn.recognition.two_stage", "model_grounding_evidence_status_from_two_stage"),
    "build_roi_crop_metadata": ("app.learn.recognition.roi", "build_roi_crop_metadata"),
    "restore_local_point_to_screen": ("app.learn.recognition.roi", "restore_local_point_to_screen"),
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
