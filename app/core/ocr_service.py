from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch


class OCRService:
    """Run PaddleOCR lazily so the runtime can still import without the backend installed."""

    def __init__(self) -> None:
        self._engine: Any = None
        self._engine_import_error: Optional[str] = None

    def scan_image(self, image_path: str) -> OCRResult:
        path = Path(image_path)
        if not path.exists():
            raise ValueError(f"OCR image path not found: {path}")

        engine = self._get_engine()
        raw_result = engine.ocr(str(path), cls=False)
        matches = self._parse_matches(raw_result)
        return OCRResult(
            image_path=str(path.resolve()),
            matches=matches,
            metadata={
                "engine": "paddleocr",
                "match_count": len(matches),
            },
        )

    def _get_engine(self) -> Any:
        if self._engine is not None:
            return self._engine

        try:
            from paddleocr import PaddleOCR
        except Exception as exc:  # pragma: no cover - depends on local install/runtime
            self._engine_import_error = str(exc)
            raise RuntimeError(f"PaddleOCR backend is unavailable: {exc}") from exc

        self._engine = PaddleOCR(use_angle_cls=False, lang="en", show_log=False)
        return self._engine

    def _parse_matches(self, raw_result: Any) -> list[OCRTextMatch]:
        lines = raw_result[0] if isinstance(raw_result, list) and raw_result and isinstance(raw_result[0], list) else raw_result
        matches: list[OCRTextMatch] = []

        if not isinstance(lines, list):
            return matches

        for item in lines:
            parsed = self._parse_line(item)
            if parsed is not None:
                matches.append(parsed)

        return matches

    def _parse_line(self, item: Any) -> Optional[OCRTextMatch]:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            return None

        polygon = item[0]
        text_score = item[1]
        if not isinstance(polygon, (list, tuple)) or not isinstance(text_score, (list, tuple)) or len(text_score) < 2:
            return None

        text = str(text_score[0]).strip()
        if not text:
            return None

        try:
            score = float(text_score[1])
        except Exception:
            score = 0.0

        xs: list[int] = []
        ys: list[int] = []
        for point in polygon:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            xs.append(int(round(float(point[0]))))
            ys.append(int(round(float(point[1]))))

        if not xs or not ys:
            return None

        bbox = OCRBoundingBox(
            x=min(xs),
            y=min(ys),
            width=max(1, max(xs) - min(xs)),
            height=max(1, max(ys) - min(ys)),
        )
        return OCRTextMatch(text=text, score=score, bbox=bbox)


ocr_service = OCRService()
