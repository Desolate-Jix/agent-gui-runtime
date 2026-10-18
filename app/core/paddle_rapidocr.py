"""用单一 OpenCV 依赖保留 Paddle OCR，并只加载显式的本地模型。"""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import math
import os
from pathlib import Path
import tempfile


def result_rows(result) -> list:
    boxes, texts, scores = result.boxes, result.txts, result.scores
    if boxes is None and texts is None and scores is None:
        return []
    if any(value is None for value in (boxes, texts, scores)):
        raise ValueError("Paddle OCR returned incomplete boxes/texts/scores")
    if not len(boxes) == len(texts) == len(scores):
        raise ValueError("Paddle OCR result lengths differ")
    rows = []
    for box, text, score in zip(boxes, texts, scores, strict=True):
        if not isinstance(text, str) or not text.strip() or len(box) != 4:
            raise ValueError("Paddle OCR returned invalid text or quadrilateral")
        score = float(score)
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("Paddle OCR returned invalid confidence")
        polygon = []
        for point in box:
            if len(point) != 2:
                raise ValueError("Paddle OCR returned invalid point")
            coordinates = [float(value) for value in point]
            if not all(math.isfinite(value) for value in coordinates):
                raise ValueError("Paddle OCR returned non-finite coordinates")
            polygon.append(coordinates)
        rows.append([polygon, text, score])
    return rows


def build_params(model_root: Path, cls_model: Path, cache: Path) -> dict:
    model_root, cls_model, cache = Path(model_root), Path(cls_model), Path(cache)
    det, rec = model_root / "PP-OCRv5_server_det", model_root / "PP-OCRv5_server_rec"
    assets = [directory / name for directory in (det, rec)
              for name in ("inference.json", "inference.pdiparams")]
    assets.extend([rec / "inference.yml", cls_model])
    for path in assets:
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError(f"Required local Paddle OCR model asset is missing: {path}")
    import yaml

    metadata = yaml.safe_load((rec / "inference.yml").read_text(encoding="utf-8"))
    characters = metadata.get("PostProcess", {}).get("character_dict") if isinstance(metadata, dict) else None
    if not isinstance(characters, list) or not characters or not all(
        isinstance(item, str) and item and "\n" not in item and "\r" not in item for item in characters
    ):
        raise ValueError("Local Paddle OCR character dictionary is invalid")
    payload = ("\n".join(characters) + "\n").encode("utf-8")
    keys = cache / ("ppocrv5-" + hashlib.sha256(payload).hexdigest() + ".txt")
    cache.mkdir(parents=True, exist_ok=True)
    if not keys.exists():
        descriptor, temporary = tempfile.mkstemp(dir=cache, prefix=".ocr-keys-")
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
            os.replace(temporary, keys)
        finally:
            Path(temporary).unlink(missing_ok=True)
    if keys.read_bytes() != payload:
        raise ValueError("Local Paddle OCR dictionary cache content differs")
    return {
        "Global.use_cls": False, "Global.model_root_dir": str(cache), "Global.log_level": "warning",
        "Det.engine_type": "paddle", "Det.ocr_version": "PP-OCRv5", "Det.model_type": "server",
        "Det.model_dir": str(det), "Det.mean": [0.485, 0.456, 0.406], "Det.std": [0.229, 0.224, 0.225],
        "Det.limit_side_len": 736, "Det.limit_type": "max", "Det.box_thresh": .6, "Det.unclip_ratio": 1.5,
        "Cls.model_path": str(cls_model),
        "Rec.engine_type": "paddle", "Rec.ocr_version": "PP-OCRv5", "Rec.model_type": "server",
        "Rec.model_dir": str(rec), "Rec.rec_keys_path": str(keys),
        "EngineConfig.paddle.cpu_math_library_num_threads": 2,
        "EngineConfig.onnxruntime.intra_op_num_threads": 2, "EngineConfig.onnxruntime.inter_op_num_threads": 2,
    }


def create_paddle_engine(model_root: Path, cache: Path):
    distribution = importlib.metadata.distribution("rapidocr-onnxruntime")
    classifier = Path(distribution.locate_file("rapidocr_onnxruntime/models/ch_ppocr_mobile_v2.0_cls_infer.onnx"))
    params = build_params(model_root, classifier, cache)
    # 先显式导入以保留真实缺项，避免上游将内部依赖失败误报为未安装 Paddle。
    importlib.import_module("paddle")
    from rapidocr import EngineType, ModelType, OCRVersion, RapidOCR

    # Python params 接口要求枚举；字符串仅适用于持久配置，不可直接传给构造器。
    for stage in ("Det", "Rec"):
        params[f"{stage}.engine_type"] = EngineType.PADDLE
        params[f"{stage}.ocr_version"] = OCRVersion.PPOCRV5
        params[f"{stage}.model_type"] = ModelType.SERVER
    engine = RapidOCR(params=params)

    def scan(image_path):
        return result_rows(engine(str(image_path)))

    return scan
