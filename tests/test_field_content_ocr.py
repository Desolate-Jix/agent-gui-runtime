"""本地字段内容读取合同：完整无缩放裁剪、短字符否决及绑定拒绝。"""
from copy import deepcopy
from hashlib import sha256
import importlib
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw
import pytest

from app.core.ocr_service import ocr_service


IDENTITY = {"handle": 10, "process_id": 20, "process_create_time": 123.0}


@pytest.fixture
def scene(tmp_path, monkeypatch):
    image = Image.new("RGB", (240, 120), "white")
    ImageDraw.Draw(image).rectangle((40, 30, 199, 79), outline="blue", width=2)
    path = tmp_path / "source.png"
    image.save(path)
    frame = {"capture_id": "field-content-source", "sha256": sha256(path.read_bytes()).hexdigest(),
        "image_path": str(path), "role": "after", "window_identity": deepcopy(IDENTITY)}
    field = {"bbox": {"x": 40, "y": 30, "w": 160, "h": 50},
        "window_rect": [20, 50, 240, 120], "window_identity": deepcopy(IDENTITY),
        "click_point": {"x": 80, "y": 55}, "field_goal": "Search field"}
    raw, scans = [], []

    def scan(crop_path):
        scans.append(Path(crop_path))
        return raw

    monkeypatch.setattr(ocr_service, "_scan_with_rapidocr", scan)
    monkeypatch.setattr(ocr_service, "_scan_with_paddle",
        lambda *args: pytest.fail("字段内容不得进入其他 OCR 后端"))
    monkeypatch.setattr(ocr_service, "scan_image",
        lambda *args: pytest.fail("字段内容不得进入带后备行为的通用入口"))
    return SimpleNamespace(root=tmp_path, path=path, image=image, frame=frame, field=field, raw=raw, scans=scans)


def read(s):
    module = importlib.import_module("app.execution.field_content_ocr")
    return module.read_field_content(frame=s.frame, field=s.field, session_dir=s.root)


def update(s):
    s.image.save(s.path)
    s.frame["sha256"] = sha256(s.path.read_bytes()).hexdigest()


def row(text="\u4e2d\u6587", score=.95, box=(30, 20, 80, 40)):
    left, top, right, bottom = box
    return [[[left, top], [right, top], [right, bottom], [left, bottom]], text, score]


def test_blank_field_uses_complete_unmarked_unscaled_crop_and_preserves_source(scene, monkeypatch):
    s = scene
    original_frame, original_field, original_bytes = deepcopy(s.frame), deepcopy(s.field), s.path.read_bytes()
    reference = read(s)
    assert reference["schema"] == "field_content_ocr.v1" and reference["state"] == "empty"
    assert reference["text"] == "" and reference["matches"] == []
    assert reference["crop_bbox"] == {"x": 24, "y": 14, "w": 192, "h": 82}
    path = Path(reference["crop_image_path"])
    assert path.parent == s.root / "field-content-ocr" and path == s.scans[0]
    with Image.open(path) as crop:
        assert crop.size == (192, 82)
        assert crop.convert("RGB").tobytes() == s.image.crop((24, 14, 216, 96)).tobytes()
    assert reference["crop_sha256"] == sha256(path.read_bytes()).hexdigest()
    assert reference["source_sha256"] == s.frame["sha256"] and reference["capture_id"] == s.frame["capture_id"]
    assert reference["engine"] == "rapidocr_onnxruntime" and reference["elapsed_ms"] >= 0
    assert s.frame == original_frame and s.field == original_field and s.path.read_bytes() == original_bytes
    module = importlib.import_module("app.execution.field_content_ocr")
    monkeypatch.setattr(ocr_service, "_scan_with_rapidocr", lambda *args: pytest.fail("校验引用不能再次 OCR"))
    reference["clear_existing"] = True
    assert module.validate_field_content(reference, frame=s.frame, field=s.field) == "empty"


def test_trusted_text_is_nonempty_and_padding_text_is_excluded_with_original_coordinates(scene):
    s = scene
    s.raw.extend([row(), row("outside", box=(1, 1, 12, 8))])
    reference = read(s)
    assert reference["state"] == "nonempty" and reference["text"] == "\u4e2d\u6587"
    assert reference["matches"] == [{"text": "\u4e2d\u6587", "score": .95,
        "crop_bbox": {"x": 30, "y": 20, "w": 50, "h": 20},
        "source_bbox": {"x": 54, "y": 34, "w": 50, "h": 20}}]
    module = importlib.import_module("app.execution.field_content_ocr")
    assert module.validate_field_content(reference, frame=s.frame, field=s.field) == "nonempty"


@pytest.mark.parametrize("text", ["Search", "AI", "\u641c\u7d22"])
def test_placeholder_or_button_text_is_never_inferred_to_be_empty(scene, text):
    scene.raw.append(row(text))
    assert read(scene)["state"] == "nonempty"


@pytest.mark.parametrize("mark", ["left_i", "right_i", "period", "faint_period", "small_x", "icon", "gradient"])
def test_no_detection_with_any_unexplained_interior_mark_is_uncertain(scene, mark):
    s = scene
    draw = ImageDraw.Draw(s.image)
    if mark in {"left_i", "right_i"}:
        x = 42 if mark == "left_i" else 197
        draw.line((x, 48, x, 56), fill="black")
        draw.point((x, 45), fill="black")
    elif mark in {"period", "faint_period"}:
        draw.point((42, 77), fill="black" if mark == "period" else (254, 254, 254))
    elif mark == "small_x":
        draw.line((110, 48, 113, 51), fill=(245, 245, 245))
        draw.line((110, 51, 113, 48), fill=(245, 245, 245))
    elif mark == "icon":
        draw.ellipse((175, 45, 185, 55), fill="gray")
    else:
        draw.line((60, 40, 170, 40), fill=(254, 254, 254))
    update(s)
    reference = read(s)
    assert reference["state"] == "uncertain" and reference["reason"]


@pytest.mark.parametrize("score,box", [(.3, (30, 20, 80, 40)), (.95, (1, 20, 20, 40))])
def test_weak_or_only_slightly_intersecting_text_does_not_prove_empty_or_nonempty(scene, score, box):
    scene.raw.append(row(score=score, box=box))
    assert read(scene)["state"] == "uncertain"


@pytest.mark.parametrize("failure", [RuntimeError, ValueError, OSError, ImportError])
def test_expected_ocr_failures_return_explicit_uncertainty(scene, monkeypatch, failure):
    def fail(path):
        raise failure("\u672c\u5730\u6a21\u578b\u89e3\u6790\u5931\u8d25:" + "x" * 600)
    monkeypatch.setattr(ocr_service, "_scan_with_rapidocr", fail)
    reference = read(scene)
    assert reference["state"] == "uncertain" and reference["reason"] == "ocr_failed:" + failure.__name__
    assert reference["error_detail"] == {"type": failure.__name__,
        "message": ("\u672c\u5730\u6a21\u578b\u89e3\u6790\u5931\u8d25:" + "x" * 600)[:512]}
    assert reference["error_detail"]["message"].startswith("\u672c\u5730\u6a21\u578b\u89e3\u6790\u5931\u8d25:")


def test_unexpected_programming_failure_is_not_hidden_as_ocr_uncertainty(scene, monkeypatch):
    def fail(path):
        raise AssertionError("synthetic programming failure")
    monkeypatch.setattr(ocr_service, "_scan_with_rapidocr", fail)
    with pytest.raises(AssertionError):
        read(scene)


@pytest.mark.parametrize("module_name,error_name", [
    ("rapidocr_onnxruntime.utils.load_image", "LoadImageError"),
    ("rapidocr_onnxruntime.utils.infer_engine", "ONNXRuntimeError"),
    ("rapidocr_onnxruntime.utils.process_img", "ResizeImgError"),
])
def test_installed_rapidocr_operational_errors_return_uncertainty(scene, monkeypatch, module_name, error_name):
    error = getattr(importlib.import_module(module_name), error_name)
    def fail(path):
        raise error("synthetic OCR failure")
    monkeypatch.setattr(ocr_service, "_scan_with_rapidocr", fail)
    reference = read(scene)
    assert reference["state"] == "uncertain" and reference["reason"] == "ocr_failed:" + error_name


def test_padding_only_text_does_not_make_uniform_field_nonempty(scene):
    scene.raw.append(row("padding", box=(1, 1, 12, 8)))
    reference = read(scene)
    assert reference["state"] == "empty" and reference["matches"] == []


@pytest.mark.parametrize("damage", ["hash", "window", "viewport", "bbox", "capture_id", "non_png"])
def test_source_or_geometry_failures_raise_before_ocr(scene, damage):
    s = scene
    if damage == "hash": s.frame["sha256"] = "0" * 64
    elif damage == "window": s.field["window_identity"]["process_create_time"] += 1
    elif damage == "viewport": s.field["window_rect"][2] += 1
    elif damage == "bbox": s.field["bbox"]["x"] = 239
    elif damage == "capture_id": s.frame["capture_id"] = ""
    else:
        s.image.save(s.path, format="JPEG")
        s.frame["sha256"] = sha256(s.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        read(s)
    assert s.scans == []


def test_source_replacement_during_ocr_is_rejected(scene, monkeypatch):
    def scan(path):
        Image.new("RGB", (240, 120), "black").save(scene.path)
        return []
    monkeypatch.setattr(ocr_service, "_scan_with_rapidocr", scan)
    with pytest.raises(ValueError):
        read(scene)


def test_crop_replacement_during_ocr_is_rejected(scene, monkeypatch):
    def scan(path):
        Image.new("RGBA", (192, 82), "black").save(path)
        return []
    monkeypatch.setattr(ocr_service, "_scan_with_rapidocr", scan)
    with pytest.raises(ValueError):
        read(scene)


@pytest.mark.parametrize("damage", ["metadata", "crop_file", "state_type", "source_box_type"])
def test_reference_validation_rejects_bad_types_or_persisted_evidence(scene, damage):
    scene.raw.append(row())
    reference = read(scene)
    if damage == "metadata": reference["roi_metadata"]["scale"] = 2
    elif damage == "crop_file": Path(reference["crop_image_path"]).write_bytes(b"not a PNG")
    elif damage == "state_type": reference["state"] = []
    else: reference["matches"][0]["source_bbox"]["x"] = True
    module = importlib.import_module("app.execution.field_content_ocr")
    with pytest.raises(ValueError):
        module.validate_field_content(reference, frame=scene.frame, field=scene.field)


@pytest.mark.parametrize("damage", ["capture_id", "source_hash", "window", "field", "crop", "crop_hash", "mapping", "state", "false_empty"])
def test_reference_validation_rejects_changed_binding_or_state(scene, damage):
    s = scene
    s.raw.append(row())
    reference = read(s)
    if damage == "capture_id": reference["capture_id"] += "-other"
    elif damage == "source_hash": reference["source_sha256"] = "0" * 64
    elif damage == "window": reference["window_identity"]["process_id"] += 1
    elif damage == "field": reference["field_bbox"]["x"] += 1
    elif damage == "crop": reference["crop_bbox"]["x"] += 1
    elif damage == "crop_hash": reference["crop_sha256"] = "0" * 64
    elif damage == "mapping": reference["matches"][0]["source_bbox"]["x"] += 1
    elif damage == "state": reference["state"] = "maybe"
    else: reference["state"] = "empty"
    module = importlib.import_module("app.execution.field_content_ocr")
    with pytest.raises(ValueError):
        module.validate_field_content(reference, frame=s.frame, field=s.field)
