from __future__ import annotations

from pathlib import Path

from PIL import Image

from app.api import vision as vision_api
from app.api.models.request import VisionRecognitionPlanRequestModel
from app.vision.ocr_region_refiner import OCRRegionRefineOptions
from app.vision.schemas import (
    BBox,
    Diagonal,
    ImageSize,
    NormalizedDiagonal,
    VisionAnalyzeResponse,
    VisionRegion,
)
from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch


def _ocr_result(path: str, *, text: str = "Start") -> OCRResult:
    return OCRResult(
        image_path=path,
        metadata={"engine": "test_ocr"},
        matches=[
            OCRTextMatch(
                text=text,
                score=0.99,
                bbox=OCRBoundingBox(x=100, y=90, width=80, height=24),
            )
        ],
    )


def _provider_response() -> VisionAnalyzeResponse:
    return VisionAnalyzeResponse(
        provider="test",
        screen_summary="test screen",
        state_guess="test_state",
        image_size=ImageSize(width=320, height=200),
        regions=[
            VisionRegion(
                region_id="start",
                label="Start",
                role="button",
                bbox=BBox(x=80, y=70, w=130, h=80),
                diagonal=Diagonal(x1=80, y1=70, x2=210, y2=150),
                normalized_diagonal=NormalizedDiagonal(nx1=0.2, ny1=0.3, nx2=0.7, ny2=0.8),
                description="Start button",
                confidence=0.95,
            )
        ],
    )


def test_recognition_plan_reuses_fresh_full_ocr_for_refine_once(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "capture.png"
    Image.new("RGB", (320, 200), "white").save(image_path)
    calls: list[str] = []

    class Provider:
        def analyze(self, _request):
            return _provider_response()

    def scan(path: str) -> OCRResult:
        calls.append(str(Path(path).resolve()))
        result = _ocr_result(str(Path(path).resolve()))
        if str(Path(path).resolve()) == str(image_path.resolve()):
            result.matches.append(
                OCRTextMatch(
                    text="Unbounded refine text",
                    score=0.98,
                    bbox=OCRBoundingBox(x=10, y=10, width=60, height=18),
                )
            )
        return result

    monkeypatch.setattr(vision_api.VisionProviderFactory, "load_config", lambda: {"vision": {"mode": "local"}})
    monkeypatch.setattr(vision_api.VisionProviderFactory, "create", lambda mode=None, config=None: Provider())
    monkeypatch.setattr(vision_api.ocr_service, "scan_image", scan)
    monkeypatch.setattr(
        vision_api.uia_provider,
        "snapshot_bound_window",
        lambda: {"provider": "windows_uia", "status": "unavailable", "controls": []},
    )

    response = vision_api.recognition_plan(
        VisionRecognitionPlanRequestModel(
            image_path=str(image_path),
            task="click_target",
            goal="Start",
            metadata={
                "ocr_anchors": {"enabled": True, "max_anchors": 1},
                "ocr_region_refine": True,
            },
            write_policy={"trace": False},
        )
    )

    assert response.success is True
    assert calls.count(str(image_path.resolve())) == 1
    result = response.data["result"]
    assert result["parse_result"]["ocr_anchors"]["anchor_count"] == 1
    assert len(result["parse_result"]["ocr_result"]["matches"]) == 2
    assert any(item["name"] == "ocr_region_refine" and item.get("ocr_reused_for_refine") is True for item in result["timings"]["steps"])


def test_refine_rejects_changed_capture_identity_and_rescans(tmp_path) -> None:
    image_path = tmp_path / "capture.png"
    Image.new("RGB", (320, 200), "white").save(image_path)
    source_identity = vision_api._capture_identity(image_path, image_size=ImageSize(width=320, height=200))
    assert source_identity is not None
    Image.new("RGB", (320, 200), "black").save(image_path)
    calls: list[str] = []

    def scan(path: str) -> OCRResult:
        calls.append(path)
        return _ocr_result(path, text="Changed")

    old_scan = vision_api.ocr_service.scan_image
    try:
        vision_api.ocr_service.scan_image = scan
        refined, result, _options = vision_api._maybe_refine_with_ocr(
            _provider_response(),
            request=VisionRecognitionPlanRequestModel(
                image_path=str(image_path),
                metadata={"ocr_region_refine": True},
            ),
            image_path=image_path,
            existing_ocr_result=_ocr_result(str(image_path.resolve())),
            existing_ocr_identity=source_identity,
        )
    finally:
        vision_api.ocr_service.scan_image = old_scan

    assert refined is not None
    assert result.matches[0].text == "Changed"
    assert len(calls) == 1


def test_refine_rejects_changed_capture_id_even_when_file_is_unchanged(tmp_path) -> None:
    image_path = tmp_path / "capture.png"
    Image.new("RGB", (320, 200), "white").save(image_path)
    source_identity = vision_api._capture_identity(
        image_path,
        image_size=ImageSize(width=320, height=200),
        capture_id="capture-a",
    )
    assert source_identity is not None
    calls: list[str] = []

    def scan(path: str) -> OCRResult:
        calls.append(path)
        return _ocr_result(path, text="Current")

    old_scan = vision_api.ocr_service.scan_image
    try:
        vision_api.ocr_service.scan_image = scan
        _refined, result, _options = vision_api._maybe_refine_with_ocr(
            _provider_response(),
            request=VisionRecognitionPlanRequestModel(image_path=str(image_path), metadata={"ocr_region_refine": True}),
            image_path=image_path,
            existing_ocr_result=_ocr_result(str(image_path.resolve())),
            existing_ocr_identity=source_identity,
            current_capture_id="capture-b",
        )
    finally:
        vision_api.ocr_service.scan_image = old_scan

    assert result.matches[0].text == "Current"
    assert len(calls) == 1


def test_refine_rejects_same_bytes_from_different_path(tmp_path) -> None:
    source_path = tmp_path / "source.png"
    current_path = tmp_path / "current.png"
    Image.new("RGB", (320, 200), "white").save(source_path)
    current_path.write_bytes(source_path.read_bytes())
    source_identity = vision_api._capture_identity(source_path, image_size=ImageSize(width=320, height=200))
    assert source_identity is not None
    calls: list[str] = []

    def scan(path: str) -> OCRResult:
        calls.append(path)
        return _ocr_result(path, text="Current path")

    old_scan = vision_api.ocr_service.scan_image
    try:
        vision_api.ocr_service.scan_image = scan
        _refined, result, _options = vision_api._maybe_refine_with_ocr(
            _provider_response(),
            request=VisionRecognitionPlanRequestModel(image_path=str(current_path), metadata={"ocr_region_refine": True}),
            image_path=current_path,
            existing_ocr_result=_ocr_result(str(source_path.resolve())),
            existing_ocr_identity=source_identity,
        )
    finally:
        vision_api.ocr_service.scan_image = old_scan

    assert result.matches[0].text == "Current path"
    assert len(calls) == 1


def test_disabled_refine_does_not_scan_or_reuse_ocr() -> None:
    called = False

    def fail_scan(_path: str):
        nonlocal called
        called = True
        raise AssertionError("disabled refine must not scan OCR")

    old_scan = vision_api.ocr_service.scan_image
    try:
        vision_api.ocr_service.scan_image = fail_scan
        response, result, options = vision_api._maybe_refine_with_ocr(
            _provider_response(),
            request=VisionRecognitionPlanRequestModel(image_path="unused.png", metadata={"ocr_region_refine": False}),
            image_path=Path("unused.png"),
            existing_ocr_result=_ocr_result("unused.png"),
            existing_ocr_identity={"path": "unused.png"},
        )
    finally:
        vision_api.ocr_service.scan_image = old_scan

    assert response is not None
    assert result is None
    assert options.enabled is False
    assert called is False


def test_full_ocr_handoff_survives_truncated_outgoing_anchors(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "capture.png"
    Image.new("RGB", (320, 200), "white").save(image_path)
    full_result = OCRResult(
        image_path=str(image_path.resolve()),
        metadata={"engine": "test_ocr"},
        matches=[
            OCRTextMatch(
                text="Needed for refine",
                score=0.99,
                bbox=OCRBoundingBox(x=100, y=90, width=80, height=24),
            ),
            OCRTextMatch(
                text="Other text omitted from anchors",
                score=0.98,
                bbox=OCRBoundingBox(x=10, y=10, width=80, height=20),
            ),
        ],
    )
    identity = vision_api._capture_identity(image_path, image_size=ImageSize(width=320, height=200))
    assert identity is not None

    refined, used_result, options = vision_api._maybe_refine_with_ocr(
        _provider_response(),
        request=VisionRecognitionPlanRequestModel(image_path=str(image_path), metadata={"ocr_region_refine": True}),
        image_path=image_path,
        existing_ocr_result=full_result,
        existing_ocr_identity=identity,
    )

    truncated_anchors = vision_api.build_ocr_anchor_payload(
        full_result,
        image_size=ImageSize(width=320, height=200),
        max_anchors=1,
    )
    assert truncated_anchors["anchor_count"] == 1
    assert used_result is full_result
    assert len(used_result.matches) == 2
    assert options == OCRRegionRefineOptions(enabled=True)
    assert refined.artifacts["ocr_region_refine"]["enabled"] is True


def test_observe_trace_reuse_is_not_treated_as_full_ocr(tmp_path) -> None:
    image_path = tmp_path / "capture.png"
    Image.new("RGB", (320, 200), "white").save(image_path)
    identity = vision_api._capture_identity(image_path, image_size=ImageSize(width=320, height=200))
    assert identity is not None
    partial = _ocr_result(str(image_path.resolve()))
    partial.metadata["engine"] = "observe_trace_reuse"
    calls: list[str] = []

    def scan(path: str) -> OCRResult:
        calls.append(path)
        return _ocr_result(path, text="Fresh OCR")

    old_scan = vision_api.ocr_service.scan_image
    try:
        vision_api.ocr_service.scan_image = scan
        _refined, result, _options = vision_api._maybe_refine_with_ocr(
            _provider_response(),
            request=VisionRecognitionPlanRequestModel(image_path=str(image_path), metadata={"ocr_region_refine": True}),
            image_path=image_path,
            existing_ocr_result=partial,
            existing_ocr_identity=identity,
        )
    finally:
        vision_api.ocr_service.scan_image = old_scan

    assert result.matches[0].text == "Fresh OCR"
    assert len(calls) == 1


def test_same_capture_identity_requires_canonical_fields() -> None:
    assert vision_api._same_capture_identity({}, {}) is False
