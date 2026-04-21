from __future__ import annotations

import inspect
import os
from pathlib import Path
from typing import Any, Optional

from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch


class OCRService:
    """Run OCR lazily so the runtime can still import without the backend installed."""

    def __init__(self) -> None:
        self._rapid_engine: Any = None
        self._paddle_engine: Any = None
        self._engine_import_error: Optional[str] = None

    def scan_image(self, image_path: str) -> OCRResult:
        path = Path(image_path)
        if not path.exists():
            raise ValueError(f"OCR image path not found: {path}")

        errors: list[str] = []
        for engine_name, scanner in (
            ("rapidocr_onnxruntime", self._scan_with_rapidocr),
            ("paddleocr", self._scan_with_paddle),
        ):
            try:
                raw_result = scanner(path)
                matches = self._parse_matches(raw_result)
                return OCRResult(
                    image_path=str(path.resolve()),
                    matches=matches,
                    metadata={
                        "engine": engine_name,
                        "match_count": len(matches),
                    },
                )
            except Exception as exc:
                errors.append(f"{engine_name}: {exc}")

        raise RuntimeError(f"All OCR backends failed for {path.name}: {' | '.join(errors)}")

    def _scan_with_rapidocr(self, path: Path) -> Any:
        engine = self._get_rapidocr_engine()
        raw_result, _ = engine(str(path))
        return raw_result

    def _scan_with_paddle(self, path: Path) -> Any:
        engine = self._get_paddle_engine()
        if hasattr(engine, "predict"):
            return engine.predict(str(path))
        return engine.ocr(str(path), cls=False)

    def _get_rapidocr_engine(self) -> Any:
        if self._rapid_engine is not None:
            return self._rapid_engine

        try:
            from rapidocr_onnxruntime import RapidOCR
        except Exception as exc:  # pragma: no cover - depends on local install/runtime
            self._engine_import_error = str(exc)
            raise RuntimeError(f"RapidOCR backend is unavailable: {exc}") from exc

        self._rapid_engine = RapidOCR()
        return self._rapid_engine

    def _get_paddle_engine(self) -> Any:
        if self._paddle_engine is not None:
            return self._paddle_engine

        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

        try:
            from paddleocr import PaddleOCR
        except Exception as exc:  # pragma: no cover - depends on local install/runtime
            self._engine_import_error = str(exc)
            raise RuntimeError(f"PaddleOCR backend is unavailable: {exc}") from exc

        init_signature = inspect.signature(PaddleOCR.__init__)
        kwargs: dict[str, Any] = {}
        if "lang" in init_signature.parameters:
            # Chinese model handles mixed Chinese/English UI text more reliably for this runtime.
            kwargs["lang"] = "ch"
        if "use_angle_cls" in init_signature.parameters:
            kwargs["use_angle_cls"] = False
        if "show_log" in init_signature.parameters:
            kwargs["show_log"] = False
        for option_name in ("use_doc_orientation_classify", "use_doc_unwarping", "use_textline_orientation"):
            if option_name in init_signature.parameters:
                kwargs[option_name] = False

        self._paddle_engine = PaddleOCR(**kwargs)
        return self._paddle_engine

    def _parse_matches(self, raw_result: Any) -> list[OCRTextMatch]:
        if isinstance(raw_result, tuple) and raw_result:
            raw_result = raw_result[0]
        matches: list[OCRTextMatch] = []

        if not isinstance(raw_result, list):
            return matches

        for item in raw_result:
            parsed = self._parse_line(item)
            if parsed is not None:
                matches.append(parsed)

        return matches

    def _parse_line(self, item: Any) -> Optional[OCRTextMatch]:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            return None

        polygon = item[0]
        if not isinstance(polygon, (list, tuple)):
            return None

        text = ""
        score = 0.0

        # PaddleOCR legacy style: [polygon, [text, score]]
        if len(item) >= 2 and isinstance(item[1], (list, tuple)) and len(item[1]) >= 2:
            text = str(item[1][0]).strip()
            try:
                score = float(item[1][1])
            except Exception:
                score = 0.0
        # RapidOCR style: [polygon, text, score]
        elif len(item) >= 3:
            text = str(item[1]).strip()
            try:
                score = float(item[2])
            except Exception:
                score = 0.0

        if not text:
            return None

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
