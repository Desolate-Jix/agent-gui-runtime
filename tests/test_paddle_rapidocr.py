from pathlib import Path
from types import SimpleNamespace

import pytest


def test_modern_result_preserves_chinese_coordinates_and_confidence():
    from app.core.paddle_rapidocr import result_rows

    result = SimpleNamespace(boxes=[[[10, 20], [60, 20], [60, 40], [10, 40]]],
                             txts=("开始审核",), scores=(.93,))
    assert result_rows(result) == [[[[10., 20.], [60., 20.], [60., 40.], [10., 40.]], "开始审核", .93]]


@pytest.mark.parametrize("result", [
    SimpleNamespace(boxes=None, txts=("漏框",), scores=(.9,)),
    SimpleNamespace(boxes=[], txts=("缺行",), scores=(.9,)),
    SimpleNamespace(boxes=[[[0, 0]] * 4], txts=("坏分数",), scores=(float("nan"),)),
    SimpleNamespace(boxes=[[[0, 0]] * 4], txts=("坏分数",), scores=(1.2,)),
    SimpleNamespace(boxes=[[[float("inf"), 0]] * 4], txts=("坏框",), scores=(.9,)),
    SimpleNamespace(boxes=[[[0, 0]] * 3], txts=("残缺框",), scores=(.9,)),
])
def test_malformed_modern_results_fail_instead_of_becoming_empty_success(result):
    from app.core.paddle_rapidocr import result_rows

    with pytest.raises(ValueError):
        result_rows(result)


def test_empty_modern_result_is_a_valid_no_text_result():
    from app.core.paddle_rapidocr import result_rows

    assert result_rows(SimpleNamespace(boxes=None, txts=None, scores=None)) == []


def test_missing_local_models_fail_without_creating_cache_or_importing_model(tmp_path):
    from app.core.paddle_rapidocr import build_params

    with pytest.raises(FileNotFoundError, match="local Paddle OCR model"):
        build_params(tmp_path / "models", tmp_path / "cls.onnx", tmp_path / "cache")
    assert list(tmp_path.iterdir()) == []


def test_local_model_parameters_use_pinned_assets_and_utf8_dictionary(tmp_path):
    import yaml
    from app.core.paddle_rapidocr import build_params

    model_root = tmp_path / "models"
    for name in ("PP-OCRv5_server_det", "PP-OCRv5_server_rec"):
        directory = model_root / name
        directory.mkdir(parents=True)
        (directory / "inference.json").write_text("{}", encoding="utf-8")
        (directory / "inference.pdiparams").write_bytes(b"model-fixture")
    (model_root / "PP-OCRv5_server_rec/inference.yml").write_text(
        yaml.safe_dump({"PostProcess": {"character_dict": ["审", "核", "A"]}}, allow_unicode=True), encoding="utf-8")
    cls = tmp_path / "cls.onnx"
    cls.write_bytes(b"cls-fixture")
    params = build_params(model_root, cls, tmp_path / "cache")
    assert params["Det.model_dir"] == str(model_root / "PP-OCRv5_server_det")
    assert params["Rec.model_dir"] == str(model_root / "PP-OCRv5_server_rec")
    assert params["Det.engine_type"] == params["Rec.engine_type"] == "paddle"
    assert params["Det.ocr_version"] == params["Rec.ocr_version"] == "PP-OCRv5"
    assert params["Det.mean"] == [0.485, 0.456, 0.406]
    assert params["Cls.model_path"] == str(cls)
    assert params["Global.use_cls"] is False
    assert Path(params["Rec.rec_keys_path"]).read_text(encoding="utf-8") == "审\n核\nA\n"


def test_actual_ocr_service_names_paddle_engine_and_exposes_primary_failure(tmp_path):
    from app.core.ocr_service import OCRService

    image = tmp_path / "image.png"
    image.write_bytes(b"fixture")
    service = OCRService()

    def primary_failure(path):
        raise RuntimeError("primary unavailable")

    service._scan_with_rapidocr = primary_failure
    service._scan_with_paddle = lambda path: [[[[1, 2], [11, 2], [11, 12], [1, 12]], "审核", .9]]
    result = service.scan_image(str(image))
    assert result.metadata["engine"] == "rapidocr_paddle"
    assert result.metadata["fallback_used"] is True
    assert result.metadata["backend_errors"] == ["rapidocr_onnxruntime: primary unavailable"]
    assert result.matches[0].text == "审核"


@pytest.mark.parametrize("raw", [
    {"bad": "container"},
    [["bad-row"]],
    [[[[1, 2], [11, 2], [11, 12], [1, 12]], "坏分数", float("nan")]],
    [[[[1, 2], [11, 2], [11, 12], [1, 12]], "坏分数", "not-a-number"]],
    [[[[1, 2], [11, 2], [11, 12], [1, 12]], "坏分数", 1.2]],
    [[[[0, 0]] * 4, "退化框", .9]],
])
def test_invalid_primary_structure_is_reported_and_reaches_verified_fallback(tmp_path, raw):
    from app.core.ocr_service import OCRService

    image = tmp_path / "image.png"
    image.write_bytes(b"fixture")
    service = OCRService()
    service._scan_with_rapidocr = lambda path: raw
    service._scan_with_paddle = lambda path: [[[[1, 2], [11, 2], [11, 12], [1, 12]], "审核", .9]]
    result = service.scan_image(str(image))
    assert result.metadata["engine"] == "rapidocr_paddle"
    assert result.metadata["fallback_used"] is True and result.metadata["backend_errors"]
    assert result.matches[0].text == "审核"


@pytest.mark.parametrize("raw", [None, []])
def test_valid_blank_primary_result_does_not_trigger_fallback(tmp_path, raw):
    from app.core.ocr_service import OCRService

    image = tmp_path / "image.png"
    image.write_bytes(b"fixture")
    service = OCRService()
    service._scan_with_rapidocr = lambda path: raw
    calls = []
    service._scan_with_paddle = lambda path: calls.append(path)
    result = service.scan_image(str(image))
    assert result.matches == [] and calls == []
    assert result.metadata["engine"] == "rapidocr_onnxruntime"
    assert result.metadata["fallback_used"] is False


def test_paddle_factory_parameters_pass_the_real_rapidocr_config_loader(tmp_path, monkeypatch):
    import rapidocr
    import yaml
    import app.core.paddle_rapidocr as bridge

    for name in ("PP-OCRv5_server_det", "PP-OCRv5_server_rec"):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "inference.json").write_text("{}", encoding="utf-8")
        (directory / "inference.pdiparams").write_bytes(b"fixture")
    (tmp_path / "PP-OCRv5_server_rec/inference.yml").write_text(
        yaml.safe_dump({"PostProcess": {"character_dict": ["审", "核"]}}, allow_unicode=True), encoding="utf-8")
    original = rapidocr.RapidOCR
    loaded = []

    def load_config_without_inference(*, params):
        instance = original.__new__(original)
        loaded.append(instance._load_config(None, params))
        return lambda path: SimpleNamespace(boxes=None, txts=None, scores=None)

    original_import = bridge.importlib.import_module
    monkeypatch.setattr(bridge.importlib, "import_module",
                        lambda name, *args, **kwargs: object() if name == "paddle" else original_import(name, *args, **kwargs))
    monkeypatch.setattr(rapidocr, "RapidOCR", load_config_without_inference)
    scanner = bridge.create_paddle_engine(tmp_path, tmp_path / "cache")
    assert callable(scanner)
    assert loaded[0].Det.engine_type is rapidocr.EngineType.PADDLE
    assert loaded[0].Rec.ocr_version is rapidocr.OCRVersion.PPOCRV5
