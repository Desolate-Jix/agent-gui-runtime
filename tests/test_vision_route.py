from __future__ import annotations

from pathlib import Path
import json

from fastapi.testclient import TestClient
from PIL import Image

from app.main import app


def test_vision_analyze_returns_artifact_metadata(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "capture.png"
    Image.new("RGB", (120, 80), color=(255, 255, 255)).save(image_path)

    class DummyProvider:
        def analyze(self, req):
            from app.vision.schemas import ImageSize, VisionAnalyzeResponse

            return VisionAnalyzeResponse(
                provider="dummy",
                screen_summary="dummy page",
                state_guess="dummy_state",
                image_size=ImageSize(width=120, height=80),
                regions=[],
            )

    monkeypatch.setattr("app.api.vision.VisionProviderFactory.load_config", lambda: {"vision": {"mode": "local"}})
    monkeypatch.setattr("app.api.vision.VisionProviderFactory.create", lambda mode=None, config=None: DummyProvider())
    monkeypatch.setattr(
        "app.api.vision.save_region_artifacts",
        lambda image_path, response: {
            "bundle_dir": str(tmp_path / "bundle"),
            "annotated_image_path": str(tmp_path / "bundle" / "annotated.png"),
            "manifest_path": str(tmp_path / "bundle" / "regions.json"),
            "region_count": 0,
            "regions": [],
        },
    )

    client = TestClient(app)
    response = client.post(
        "/vision/analyze",
        json={
            "image_path": str(image_path),
            "task": "analyze_ui",
            "app_name": "demo",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    result = payload["data"]["result"]
    assert "artifacts" in result
    assert result["artifacts"]["region_count"] == 0


def test_vision_page_structure_returns_fused_elements(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "capture.png"
    Image.new("RGB", (420, 220), color=(255, 255, 255)).save(image_path)

    class DummyProvider:
        def analyze(self, req):
            from app.vision.schemas import BBox, Diagonal, ImageSize, NormalizedDiagonal, VisionAnalyzeResponse, VisionRegion

            return VisionAnalyzeResponse(
                provider="dummy",
                screen_summary="dummy page",
                state_guess="dummy_state",
                image_size=ImageSize(width=420, height=220),
                regions=[
                    VisionRegion(
                        region_id="region_start",
                        label="Start button",
                        role="button",
                        bbox=BBox(x=80, y=120, w=140, h=100),
                        diagonal=Diagonal(x1=80, y1=120, x2=220, y2=220),
                        normalized_diagonal=NormalizedDiagonal(nx1=0.1, ny1=0.1, nx2=0.2, ny2=0.2),
                        description="Start button",
                        ocr_text="Start",
                        text_lines=["Start"],
                        possible_destinations=["main"],
                        confidence=0.9,
                        layout_key="layout_start",
                        content_key="content_start",
                        match_key="layout_start:content_start",
                    )
                ],
            )

    class DummyOCR:
        def scan_image(self, image_path):
            from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch

            return OCRResult(
                image_path=image_path,
                metadata={"engine": "rapidocr_onnxruntime"},
                matches=[OCRTextMatch(text="Start", score=0.99, bbox=OCRBoundingBox(x=77, y=68, width=24, height=13))],
            )

    monkeypatch.setattr("app.api.vision.VisionProviderFactory.load_config", lambda: {"vision": {"mode": "local"}})
    monkeypatch.setattr("app.api.vision.VisionProviderFactory.create", lambda mode=None, config=None: DummyProvider())
    monkeypatch.setattr("app.api.vision.ocr_service", DummyOCR())

    client = TestClient(app)
    response = client.post(
        "/vision/page_structure",
        json={
            "image_path": str(image_path),
            "task": "analyze_ui",
            "app_name": "demo",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    result = payload["data"]["result"]
    assert result["contract_version"] == "page_structure_v1"
    assert len(result["elements"]) == 1
    assert result["elements"][0]["interaction_type"] == "click"
    assert result["elements"][0]["interaction_policy"]["allowed"] is True
    assert result["elements"][0]["memory_key"]
    assert result["links"][0]["relation"] == "semantic_text_binding"
    assert result["learning_summary"]["allowed_element_count"] == 1


def test_vision_layer_trace_returns_each_layer_result_and_validation(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "capture.png"
    Image.new("RGB", (420, 220), color=(255, 255, 255)).save(image_path)

    class DummyProvider:
        def analyze(self, req):
            from app.vision.schemas import BBox, Diagonal, ImageSize, NormalizedDiagonal, VisionAnalyzeResponse, VisionRegion

            return VisionAnalyzeResponse(
                provider="dummy",
                screen_summary="dummy page",
                state_guess="dummy_state",
                image_size=ImageSize(width=420, height=220),
                regions=[
                    VisionRegion(
                        region_id="region_start",
                        label="Start button",
                        role="button",
                        bbox=BBox(x=80, y=120, w=140, h=100),
                        diagonal=Diagonal(x1=80, y1=120, x2=220, y2=220),
                        normalized_diagonal=NormalizedDiagonal(nx1=0.1, ny1=0.1, nx2=0.2, ny2=0.2),
                        description="Start button",
                        ocr_text="Start",
                        text_lines=["Start"],
                        possible_destinations=["main"],
                        confidence=0.9,
                        layout_key="layout_start",
                        content_key="content_start",
                        match_key="layout_start:content_start",
                    )
                ],
            )

    class DummyOCR:
        def scan_image(self, image_path):
            from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch

            return OCRResult(
                image_path=image_path,
                metadata={"engine": "rapidocr_onnxruntime"},
                matches=[OCRTextMatch(text="Start", score=0.99, bbox=OCRBoundingBox(x=77, y=68, width=24, height=13))],
            )

    monkeypatch.setattr("app.api.vision.VisionProviderFactory.load_config", lambda: {"vision": {"mode": "local"}})
    monkeypatch.setattr("app.api.vision.VisionProviderFactory.create", lambda mode=None, config=None: DummyProvider())
    monkeypatch.setattr("app.api.vision.ocr_service", DummyOCR())

    client = TestClient(app)
    response = client.post(
        "/vision/layer_trace",
        json={
            "image_path": str(image_path),
            "task": "analyze_ui",
            "app_name": "demo",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    result = payload["data"]["result"]
    assert result["contract_version"] == "vision_layer_trace_v1"
    assert result["final_ok"] is True

    layers = {item["layer"]: item for item in result["layers"]}
    assert set(layers) == {"input_image", "vision_provider_raw", "vision_regions_v1", "ocr_result", "page_structure_v1"}
    assert layers["input_image"]["validation"]["ok"] is True
    assert layers["vision_regions_v1"]["summary"]["region_count"] == 1
    assert layers["ocr_result"]["summary"]["texts"] == ["Start"]
    assert layers["page_structure_v1"]["summary"]["element_count"] == 1
    assert layers["page_structure_v1"]["summary"]["allowed_element_count"] == 1
    assert layers["page_structure_v1"]["result"]["elements"][0]["memory_key"]


def test_vision_layer_trace_can_add_ocr_refined_region_layer(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "capture.png"
    Image.new("RGB", (420, 220), color=(255, 255, 255)).save(image_path)

    class DummyProvider:
        def analyze(self, req):
            from app.vision.schemas import BBox, Diagonal, ImageSize, NormalizedDiagonal, VisionAnalyzeResponse, VisionRegion

            return VisionAnalyzeResponse(
                provider="dummy",
                screen_summary="dummy page",
                state_guess="dummy_state",
                image_size=ImageSize(width=420, height=220),
                regions=[
                    VisionRegion(
                        region_id="region_start",
                        label="Start button",
                        role="button",
                        bbox=BBox(x=80, y=120, w=140, h=100),
                        diagonal=Diagonal(x1=80, y1=120, x2=220, y2=220),
                        normalized_diagonal=NormalizedDiagonal(nx1=0.1, ny1=0.1, nx2=0.2, ny2=0.2),
                        description="Start button",
                        ocr_text="Start",
                        text_lines=["Start"],
                        possible_destinations=["main"],
                        confidence=0.9,
                        layout_key="layout_start",
                        content_key="content_start",
                        match_key="layout_start:content_start",
                    )
                ],
            )

    class DummyOCR:
        def scan_image(self, image_path):
            from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch

            return OCRResult(
                image_path=image_path,
                metadata={"engine": "rapidocr_onnxruntime"},
                matches=[OCRTextMatch(text="Start", score=0.99, bbox=OCRBoundingBox(x=77, y=68, width=24, height=13))],
            )

    monkeypatch.setattr("app.api.vision.VisionProviderFactory.load_config", lambda: {"vision": {"mode": "local"}})
    monkeypatch.setattr("app.api.vision.VisionProviderFactory.create", lambda mode=None, config=None: DummyProvider())
    monkeypatch.setattr("app.api.vision.ocr_service", DummyOCR())

    client = TestClient(app)
    response = client.post(
        "/vision/layer_trace",
        json={
            "image_path": str(image_path),
            "task": "analyze_ui",
            "app_name": "demo",
            "metadata": {"ocr_region_refine": True},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    result = payload["data"]["result"]

    layers = {item["layer"]: item for item in result["layers"]}
    assert "vision_regions_refined_v1" in layers
    refined = layers["vision_regions_refined_v1"]["result"]
    assert refined["regions"][0]["bbox"] == {"x": 61, "y": 52, "w": 140, "h": 100}
    assert refined["artifacts"]["ocr_region_refine"]["adjusted_region_count"] == 1
    assert result["execution_path"]["ocr_region_refine_used"] is True


def test_render_review_overlay_returns_output_image(tmp_path) -> None:
    image_path = tmp_path / "capture.png"
    Image.new("RGB", (240, 160), color=(255, 255, 255)).save(image_path)

    trace_path = tmp_path / "trace.json"
    trace_payload = {
        "result": {
            "image_path": str(image_path),
            "layers": [
                {
                    "layer": "vision_provider_raw",
                    "result": {
                        "regions": [
                            {
                                "region_id": "region_1",
                                "label": "Start Button",
                                "diagonal": {"x1": 20, "y1": 30, "x2": 120, "y2": 90},
                            }
                        ]
                    },
                },
                {
                    "layer": "page_structure_v1",
                    "result": {
                        "regions": [
                            {
                                "region_id": "region_1",
                                "label": "Start Button Refined",
                                "bbox": {"x": 28, "y": 40, "w": 52, "h": 22},
                            }
                        ]
                    },
                },
                {
                    "layer": "ocr_result",
                    "result": {
                        "matches": [
                            {
                                "text": "Start",
                                "bbox": {"x": 30, "y": 42, "width": 40, "height": 14},
                            }
                        ]
                    },
                },
            ],
        }
    }
    trace_path.write_text(json.dumps(trace_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    client = TestClient(app)
    response = client.post(
        "/vision/render_review_overlay",
        json={
            "trace_path": str(trace_path),
            "region_layer": "page_structure_v1",
            "include_regions": True,
            "include_ocr": True,
            "label_regions": True,
            "label_ocr": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    result = payload["data"]["result"]
    output_path = Path(result["output_path"])
    assert output_path.exists()
    assert result["region_count"] == 1
    assert result["ocr_count"] == 1
    assert result["region_layer"] == "page_structure_v1"
