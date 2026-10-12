"""本地字段内容证据；只读原图，不把 OCR 无结果当成空框。"""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from math import isfinite
from pathlib import Path
from time import perf_counter

from PIL import Image, UnidentifiedImageError

from app.core.ocr_service import ocr_service
from app.judgment.field_roi import field_roi_metadata, render_field_roi


_ENGINE = "rapidocr_onnxruntime"
_MIN_SCORE = .7
_MAX_BYTES = 20 * 1024 * 1024


def _invalid(reason):
    raise ValueError("field_content_ocr_" + reason)


def _source_bytes(frame):
    if type(frame) is not dict or type(frame.get("image_path")) is not str or not frame["image_path"]:
        _invalid("source_path_invalid")
    try:
        path = Path(frame["image_path"])
        if path.stat().st_size > _MAX_BYTES:
            _invalid("source_bytes_invalid")
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError("field_content_ocr_source_unreadable") from exc
    if not data or len(data) > _MAX_BYTES or sha256(data).hexdigest() != frame.get("sha256"):
        _invalid("source_hash_mismatch")
    return data


def _prepare(frame, field):
    data = _source_bytes(frame)
    try:
        with Image.open(BytesIO(data)) as image:
            dimensions = image.size
        metadata = field_roi_metadata(frame, dimensions, field)
        crop = render_field_roi(data, metadata)
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError) as exc:
        raise ValueError("field_content_ocr_source_png_invalid") from exc
    return data, metadata, crop


def _persist_crop(session_dir, metadata, data):
    try:
        root = Path(session_dir).resolve()
        directory = root / "field-content-ocr"
        directory.mkdir(parents=True, exist_ok=True)
        if directory.resolve() != directory:
            _invalid("crop_directory_invalid")
        binding = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        path = directory / (sha256(binding).hexdigest() + ".png")
        try:
            with path.open("xb") as output:
                output.write(data)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != data:
                _invalid("persisted_crop_mismatch")
    except OSError as exc:
        raise ValueError("field_content_ocr_crop_unwritable") from exc
    return path


def _ocr_errors():
    # 通用入口有 Paddle 后备；这里只复用本地 RapidOCR，不加载其他后端。
    errors = (RuntimeError, ValueError, OSError, ImportError)
    try:
        from rapidocr_onnxruntime.utils.load_image import LoadImageError
        from rapidocr_onnxruntime.utils.infer_engine import ONNXRuntimeError
        from rapidocr_onnxruntime.utils.process_img import ResizeImgError
    except ImportError:
        return errors
    return errors + (LoadImageError, ONNXRuntimeError, ResizeImgError)


def _box(value):
    if (type(value) is not dict or set(value) != {"x", "y", "w", "h"}
            or any(type(value[k]) is not int for k in value)
            or min(value["x"], value["y"]) < 0 or min(value["w"], value["h"]) <= 0):
        _invalid("match_bbox_invalid")
    return dict(value)


def _field_overlap(box, field):
    width = max(0, min(box["x"] + box["w"], field["x"] + field["w"]) - max(box["x"], field["x"]))
    height = max(0, min(box["y"] + box["h"], field["y"] + field["h"]) - max(box["y"], field["y"]))
    return width * height / (box["w"] * box["h"])


def _mapping(crop_box, metadata):
    box = _box(crop_box)
    crop = metadata["crop_bbox"]
    if box["x"] + box["w"] > crop["w"] or box["y"] + box["h"] > crop["h"]:
        _invalid("match_outside_crop")
    return {**box, "x": box["x"] + crop["x"], "y": box["y"] + crop["y"]}


def _matches(raw, metadata):
    matches, ambiguous = [], False
    for match in ocr_service._parse_matches(raw):
        box = {"x": match.bbox.x, "y": match.bbox.y, "w": match.bbox.width, "h": match.bbox.height}
        source = _mapping(box, metadata)
        overlap = _field_overlap(source, metadata["field_bbox"])
        if overlap == 0:
            continue
        if overlap < .5:
            ambiguous = True
            continue
        matches.append({"text": match.text, "score": match.score, "crop_bbox": box, "source_bbox": source})
    return matches, ambiguous


def _uniform_interior(data, field_bbox):
    # 只剔除两像素边框；任何局部前景（包括单个灰像素）都否决空框。
    box = field_bbox
    if box["w"] <= 4 or box["h"] <= 4:
        return False
    with Image.open(BytesIO(data)) as source:
        inner = source.crop((box["x"] + 2, box["y"] + 2,
            box["x"] + box["w"] - 2, box["y"] + box["h"] - 2)).convert("RGBA")
        colors = inner.getcolors(maxcolors=1)
    return colors is not None and len(colors) == 1 and colors[0][1][3] == 255


def _state(matches, ambiguous, data, field_bbox):
    if any(match["score"] >= _MIN_SCORE for match in matches):
        return "nonempty", "ocr_field_text_detected"
    if matches:
        return "uncertain", "ocr_low_confidence_field_text"
    if ambiguous:
        return "uncertain", "ocr_ambiguous_field_overlap"
    if _uniform_interior(data, field_bbox):
        return "empty", "no_detection_uniform_field_interior"
    return "uncertain", "no_detection_visible_field_content"


def _check_crop(path, expected):
    if type(path) is not str:
        _invalid("crop_path_invalid")
    crop_path = Path(path)
    try:
        if (not crop_path.is_absolute() or crop_path.parent.name != "field-content-ocr"
                or crop_path.is_symlink() or crop_path.parent.resolve() != crop_path.parent
                or crop_path.stat().st_size > _MAX_BYTES or crop_path.read_bytes() != expected):
            _invalid("persisted_crop_mismatch")
    except OSError as exc:
        raise ValueError("field_content_ocr_crop_unreadable") from exc


def read_field_content(*, frame, field, session_dir) -> dict:
    """保存完整无标注 ROI，返回绑定原始截图的本地字段内容证据。"""
    started = perf_counter()
    data, metadata, crop = _prepare(frame, field)
    path = _persist_crop(session_dir, metadata, crop)
    matches, error_detail = [], None
    try:
        matches, ambiguous = _matches(ocr_service._scan_with_rapidocr(path), metadata)
        state, reason = _state(matches, ambiguous, data, metadata["field_bbox"])
    except _ocr_errors() as exc:
        state, reason = "uncertain", "ocr_failed:" + type(exc).__name__
        error_detail = {"type": type(exc).__name__, "message": str(exc)[:512]}
    # OCR 可以较慢；完成后再次核验两个只读证据文件，拒绝期间发生的替换。
    if _source_bytes(frame) != data:
        _invalid("source_changed")
    _check_crop(str(path), crop)
    return {"schema": "field_content_ocr.v1", "capture_id": metadata["source_capture_id"],
        "source_sha256": metadata["source_sha256"], "field_bbox": deepcopy(metadata["field_bbox"]),
        "window_identity": deepcopy(metadata["window_identity"]), "crop_bbox": deepcopy(metadata["crop_bbox"]),
        "crop_sha256": sha256(crop).hexdigest(), "crop_image_path": str(path), "roi_metadata": deepcopy(metadata),
        "state": state, "text": "\n".join(match["text"] for match in matches), "matches": matches,
        "engine": _ENGINE, "elapsed_ms": round((perf_counter() - started) * 1000, 3), "reason": reason,
        "error_detail": error_detail}


def validate_field_content(reference, *, frame, field) -> str:
    """只校验引用及像素绑定，不再次调用 OCR，也不签发动作授权。"""
    data, metadata, crop = _prepare(frame, field)
    if type(reference) is not dict or reference.get("schema") != "field_content_ocr.v1":
        _invalid("reference_invalid")
    expected = {"capture_id": metadata["source_capture_id"], "source_sha256": metadata["source_sha256"],
        "field_bbox": metadata["field_bbox"], "window_identity": metadata["window_identity"],
        "crop_bbox": metadata["crop_bbox"], "crop_sha256": sha256(crop).hexdigest(), "roi_metadata": metadata,
        "engine": _ENGINE}
    try:
        actual_binding = json.dumps({key: reference.get(key) for key in expected}, sort_keys=True, ensure_ascii=False)
        expected_binding = json.dumps(expected, sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("field_content_ocr_reference_binding_invalid") from exc
    if actual_binding != expected_binding:
        _invalid("reference_binding_mismatch")
    _check_crop(reference.get("crop_image_path"), crop)
    state, text, matches = reference.get("state"), reference.get("text"), reference.get("matches")
    if (type(state) is not str or state not in {"empty", "nonempty", "uncertain"}
            or type(text) is not str or type(matches) is not list
            or type(reference.get("reason")) is not str or not reference["reason"]
            or type(reference.get("elapsed_ms")) not in (int, float)
            or not isfinite(reference["elapsed_ms"]) or reference["elapsed_ms"] < 0):
        _invalid("reference_state_invalid")
    for match in matches:
        if (type(match) is not dict or set(match) != {"text", "score", "crop_bbox", "source_bbox"}
                or type(match["text"]) is not str or not match["text"].strip() or match["text"] != match["text"].strip()
                or type(match["score"]) not in (int, float) or not isfinite(match["score"]) or not 0 <= match["score"] <= 1):
            _invalid("reference_match_invalid")
        source = _mapping(match["crop_bbox"], metadata)
        if source != _box(match["source_bbox"]) or _field_overlap(source, metadata["field_bbox"]) < .5:
            _invalid("reference_mapping_mismatch")
    if text != "\n".join(match["text"] for match in matches):
        _invalid("reference_text_mismatch")
    if state == "empty" and (matches or reference["reason"] != "no_detection_uniform_field_interior"
            or not _uniform_interior(data, metadata["field_bbox"])):
        _invalid("reference_empty_unproven")
    if state == "nonempty" and (not any(match["score"] >= _MIN_SCORE for match in matches)
            or reference["reason"] != "ocr_field_text_detected"):
        _invalid("reference_nonempty_unproven")
    error_detail = reference.get("error_detail")
    if reference["reason"].startswith("ocr_failed:"):
        if (state != "uncertain" or matches or type(error_detail) is not dict
                or set(error_detail) != {"type", "message"} or type(error_detail["type"]) is not str
                or reference["reason"] != "ocr_failed:" + error_detail["type"]
                or type(error_detail["message"]) is not str or len(error_detail["message"]) > 512):
            _invalid("reference_error_invalid")
    elif error_detail is not None:
        _invalid("reference_error_invalid")
    return state
