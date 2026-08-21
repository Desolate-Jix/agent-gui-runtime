"""Universal Evidence Interface v1 public, non-authorizing surface."""

from app.learn.recognition.uei.contracts import UEIOuterBoundaryError
from app.learn.recognition.uei.projections import (
    project_ocr_result,
    project_screen_parser_result,
    project_uia_snapshot,
)
from app.learn.recognition.uei.store import UEIObjectStore

__all__ = [
    "UEIObjectStore",
    "UEIOuterBoundaryError",
    "project_ocr_result",
    "project_screen_parser_result",
    "project_uia_snapshot",
]
