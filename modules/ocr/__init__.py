"""OCR contracts and helpers for the post-OpenClaw runtime."""

from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch
from modules.ocr.matching import bbox_center, find_text_matches, select_best_text_match

__all__ = [
    "OCRBoundingBox",
    "OCRResult",
    "OCRTextMatch",
    "bbox_center",
    "find_text_matches",
    "select_best_text_match",
]
