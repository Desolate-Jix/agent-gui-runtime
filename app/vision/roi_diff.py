from __future__ import annotations

from typing import Any, Optional

CV2_AVAILABLE = False
CV2_IMPORT_ERROR: Optional[str] = None

try:
    import cv2
    import numpy as np

    CV2_AVAILABLE = True
except Exception as exc:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]
    CV2_IMPORT_ERROR = str(exc)


def compare_roi_images(before_path: Optional[str], after_path: Optional[str], threshold: int = 25) -> dict[str, Any]:
    if not before_path or not after_path:
        return {"available": False, "reason": "missing_before_or_after_image", "score": None, "changed": None}
    if not CV2_AVAILABLE:
        return {"available": False, "reason": f"opencv_unavailable: {CV2_IMPORT_ERROR}", "score": None, "changed": None}

    before = cv2.imread(before_path, cv2.IMREAD_GRAYSCALE)
    after = cv2.imread(after_path, cv2.IMREAD_GRAYSCALE)
    if before is None or after is None:
        return {"available": False, "reason": "failed_to_read_images", "score": None, "changed": None}
    if before.shape != after.shape:
        return {"available": False, "reason": f"image_size_mismatch: {before.shape} vs {after.shape}", "score": None, "changed": None}

    diff = cv2.absdiff(before, after)
    _, mask = cv2.threshold(diff, threshold, 255, cv2.THRESH_BINARY)
    changed_pixels = int((mask > 0).sum())
    total_pixels = int(mask.size) if mask.size else 0
    score = float(changed_pixels / total_pixels) if total_pixels else 0.0
    return {
        "available": True,
        "reason": None,
        "score": score,
        "changed": score > 0.0,
        "changed_pixels": changed_pixels,
        "total_pixels": total_pixels,
    }
