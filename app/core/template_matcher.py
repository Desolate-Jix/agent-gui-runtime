from __future__ import annotations

from typing import Any, Optional

from loguru import logger

from app.models.request import ROIModel


class TemplateMatcher:
    """Locate configured templates within the current window image.

    TODO:
    - Load template assets from configs/templates.
    - Implement OpenCV-based template matching.
    """

    def find_template(self, name: str, roi: Optional[ROIModel] = None) -> dict[str, Any]:
        """Find a named template within an optional ROI."""
        logger.info("Finding template: name={}, roi={}", name, roi)
        return {
            "template_name": name,
            "matched": False,
            "confidence": 0.0,
            "location": None,
            "roi": roi.model_dump() if roi else None,
        }


template_matcher = TemplateMatcher()
