from __future__ import annotations

import math
import os
import time
from pathlib import Path
from typing import Any, Optional

from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PADDLEX_CACHE = PROJECT_ROOT / ".paddlex"


class OCRService:
    """Run OCR lazily so the runtime can still import without the backend installed."""

    def __init__(self, *, cpu_threads: int | None = None) -> None:
        if cpu_threads is not None and (type(cpu_threads) is not int or cpu_threads < 1):
            raise ValueError("cpu_threads must be a positive integer")
        # 限制 CPU 线程争抢；只调整调度，不降低模型精度或截图分辨率。
        self._cpu_threads = min(cpu_threads or 8, os.cpu_count() or 1)
        self._rapid_engine: Any = None
        self._paddle_engine: Any = None
        self._engine_import_error: Optional[str] = None

    def prepare(self) -> dict[str, Any]:
        """只读准备实际 OCR 引擎，并返回可审计的冷/复用计时。

        该方法只在当前服务实例内获取并缓存引擎，不截图、不派发输入，也不
        创建额外进程。引擎获取失败会继续尝试现有的 OCR fallback；若全部失败，
        则保留每个后端的错误并抛出异常，不把失败伪装成已就绪。
        """
        started_at = time.perf_counter()
        errors: list[str] = []
        backends = (
            ("rapidocr_onnxruntime", "_rapid_engine", self._get_rapidocr_engine),
            ("rapidocr_paddle", "_paddle_engine", self._get_paddle_engine),
        )
        for engine_name, attribute_name, getter in backends:
            was_ready = getattr(self, attribute_name) is not None
            acquisition_started_at = time.perf_counter()
            try:
                getter()
            except Exception as exc:
                errors.append(f"{engine_name}: {exc}")
                continue

            acquisition_seconds = time.perf_counter() - acquisition_started_at
            prepare_seconds = time.perf_counter() - started_at
            mode = "reuse" if was_ready else "cold"
            timing = {
                "mode": mode,
                "engine_acquisition_seconds": round(acquisition_seconds, 6),
                "prepare_seconds": round(prepare_seconds, 6),
            }
            return {
                "status": "ready",
                "engine": engine_name,
                "cold": not was_ready,
                "reused": was_ready,
                "timing": timing,
                "backend_errors": list(errors),
            }

        raise RuntimeError(
            "All OCR backends failed during preparation: " + " | ".join(errors)
        )

    def scan_image(self, image_path: str) -> OCRResult:
        path = Path(image_path)
        if not path.exists():
            raise ValueError(f"OCR image path not found: {path}")

        errors: list[str] = []
        for engine_name, scanner in (
            ("rapidocr_onnxruntime", self._scan_with_rapidocr),
            ("rapidocr_paddle", self._scan_with_paddle),
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
                        "fallback_used": bool(errors),
                        "backend_errors": list(errors),
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
        return engine(str(path))

    def _get_rapidocr_engine(self) -> Any:
        if self._rapid_engine is not None:
            return self._rapid_engine

        try:
            from rapidocr_onnxruntime import RapidOCR
        except Exception as exc:  # pragma: no cover - depends on local install/runtime
            self._engine_import_error = str(exc)
            raise RuntimeError(f"RapidOCR backend is unavailable: {exc}") from exc

        self._rapid_engine = RapidOCR(
            intra_op_num_threads=self._cpu_threads, inter_op_num_threads=1
        )
        return self._rapid_engine

    def _get_paddle_engine(self) -> Any:
        if self._paddle_engine is not None:
            return self._paddle_engine

        from app.core.paddle_rapidocr import create_paddle_engine

        self._paddle_engine = create_paddle_engine(
            DEFAULT_PADDLEX_CACHE / "official_models", DEFAULT_PADDLEX_CACHE / "rapidocr-bridge"
        )
        return self._paddle_engine

    def _parse_matches(self, raw_result: Any) -> list[OCRTextMatch]:
        if isinstance(raw_result, tuple) and raw_result:
            raw_result = raw_result[0]
        if raw_result is None:
            return []
        if not isinstance(raw_result, list):
            raise ValueError("OCR output must contain a list of recognized rows")
        return [self._parse_line(item) for item in raw_result]

    def _parse_line(self, item: Any) -> OCRTextMatch:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            raise ValueError("OCR returned an invalid result row")

        polygon = item[0]
        if not isinstance(polygon, (list, tuple)) or len(polygon) != 4:
            raise ValueError("OCR returned an invalid quadrilateral")

        text = ""
        score = 0.0

        # 保留旧嵌套行与 RapidOCR 行格式，但不把结构错误伪装成空结果。
        if len(item) >= 2 and isinstance(item[1], (list, tuple)) and len(item[1]) >= 2:
            text, score = item[1][0], item[1][1]
        elif len(item) >= 3:
            text, score = item[1], item[2]

        if not isinstance(text, str) or not text.strip():
            raise ValueError("OCR returned invalid or blank row text")
        text = text.strip()
        score = float(score)
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("OCR returned invalid confidence")

        xs: list[int] = []
        ys: list[int] = []
        for point in polygon:
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                raise ValueError("OCR returned invalid point coordinates")
            x, y = float(point[0]), float(point[1])
            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError("OCR returned non-finite point coordinates")
            xs.append(int(round(x)))
            ys.append(int(round(y)))

        if max(xs) <= min(xs) or max(ys) <= min(ys):
            raise ValueError("OCR returned a degenerate bounding box")

        bbox = OCRBoundingBox(
            x=min(xs),
            y=min(ys),
            width=max(xs) - min(xs),
            height=max(ys) - min(ys),
        )
        return OCRTextMatch(text=text, score=score, bbox=bbox)


ocr_service = OCRService()
