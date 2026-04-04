from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any, Optional

from loguru import logger

PADDLEOCR_AVAILABLE = False
PADDLEOCR_IMPORT_ERROR: Optional[str] = None

try:
    from paddleocr import PaddleOCR

    PADDLEOCR_AVAILABLE = True
except Exception as exc:  # pragma: no cover - depends on runtime platform/environment
    PaddleOCR = None  # type: ignore[assignment]
    PADDLEOCR_IMPORT_ERROR = str(exc)

from app.core.screenshot import screenshot_service
from app.models.request import ROIModel

OCR_ENGINE_VERSION = "2026-04-04-ocr-debug-v2"
logger.info("Loaded ocr_engine.py version {}", OCR_ENGINE_VERSION)


class OCREngine:
    """Perform OCR against a region of the bound window using real screenshot data."""

    def __init__(self) -> None:
        self._ocr_instance: Optional[Any] = None
        self._ocr_image_dir = Path("logs")
        self._ocr_image_dir.mkdir(parents=True, exist_ok=True)

    def ocr_region(self, roi: ROIModel, save_image: bool = True, debug: bool = False) -> dict[str, Any]:
        """Run OCR on the supplied ROI from the currently bound window."""
        logger.info("Running OCR for roi={}", roi)
        self._ensure_ocr_backend()

        capture = screenshot_service.capture_window(roi=roi, save_image=save_image)
        image_path = capture.get("image_path")
        if save_image and not image_path:
            raise ValueError("OCR capture did not produce an image path")

        logger.info("OCR input image path: {}", image_path)
        ocr = self._get_ocr()
        logger.info("OCR call start: image_path={}", image_path)

        try:
            ocr_input = image_path
            if not ocr_input:
                raise ValueError("OCR requires save_image=true so the captured ROI is available as a file path")
            result = ocr.ocr(ocr_input)
            logger.info("OCR raw result type: {}", type(result))
            logger.info("OCR raw result preview: {}", repr(result)[:2500])
            if result and isinstance(result, list):
                sample = result[0]
                if isinstance(sample, dict):
                    logger.info("OCR raw top-level keys: {}", list(sample.keys()))
                    key_types = {k: type(v).__name__ for k, v in sample.items()}
                    logger.info("OCR raw top-level value types: {}", key_types)
                    logger.info("OCR raw sample item full: {}", repr(sample)[:5000])
        except Exception as exc:
            logger.error("OCR call failed for image_path={}: {}", image_path, exc)
            logger.error("OCR traceback:\n{}", traceback.format_exc())
            raise

        lines: list[dict[str, Any]] = []
        recognized_text_parts: list[str] = []

        page = result[0] if result and len(result) > 0 else {}
        dt_polys = page.get("dt_polys", []) if isinstance(page, dict) else []
        rec_texts = page.get("rec_texts", []) if isinstance(page, dict) else []
        rec_scores = page.get("rec_scores", []) if isinstance(page, dict) else []
        logger.info("OCR rec_texts: {}", rec_texts)
        logger.info("OCR rec_scores: {}", rec_scores)

        for idx, points in enumerate(dt_polys):
            text = rec_texts[idx] if idx < len(rec_texts) else ""
            confidence = rec_scores[idx] if idx < len(rec_scores) else None
            normalized_points = [
                {"x": int(point[0]), "y": int(point[1])}
                for point in points
            ]
            if text:
                recognized_text_parts.append(str(text))
            lines.append(
                {
                    "text": str(text),
                    "confidence": float(confidence) if confidence is not None else None,
                    "points": normalized_points,
                }
            )

        recognized_text = "\n".join(part for part in recognized_text_parts if part)
        non_null_scores = [
            line["confidence"]
            for line in lines
            if line.get("confidence") is not None
        ]
        avg_confidence = (
            sum(non_null_scores) / len(non_null_scores)
            if non_null_scores else None
        )
        logger.info("OCR parsed text: {!r}", recognized_text)

        response = {
            "text": recognized_text,
            "lines": lines,
            "line_count": len(lines),
            "confidence": avg_confidence,
            "roi": capture.get("roi") or roi.model_dump(),
            "roi_adjusted": capture.get("roi_adjusted", False),
            "image_size": {
                "width": capture["image_width"],
                "height": capture["image_height"],
            },
            "image_path": image_path,
        }
        if debug:
            response["debug"] = {
                "raw_result_keys": list(page.keys()) if isinstance(page, dict) else [],
                "rec_texts": rec_texts,
                "rec_scores": rec_scores,
                "window_size": capture.get("window_size"),
            }

        logger.info(
            "OCR completed: line_count={}, text_preview={!r}, image_path={}",
            len(lines),
            recognized_text[:120],
            image_path,
        )
        return response

    def _get_ocr(self) -> Any:
        if self._ocr_instance is None:
            self._ensure_ocr_backend()
            logger.info("Initializing PaddleOCR engine")
            self._ocr_instance = PaddleOCR(lang="en", enable_mkldnn=False)
            logger.info("OCR instance config: {}", self._ocr_instance)
        return self._ocr_instance

    def _ensure_ocr_backend(self) -> None:
        if not PADDLEOCR_AVAILABLE:
            raise RuntimeError(
                "PaddleOCR backend is unavailable. "
                f"Import error: {PADDLEOCR_IMPORT_ERROR}"
            )


ocr_engine = OCREngine()
