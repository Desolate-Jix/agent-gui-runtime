from __future__ import annotations

from pathlib import Path
import json

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from app.main import app
from app.api import vision as vision_api


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

            if "recognition-crops" in str(image_path):
                return OCRResult(
                    image_path=image_path,
                    metadata={"engine": "rapidocr_onnxruntime"},
                    matches=[
                        OCRTextMatch(text="Start detection", score=0.99, bbox=OCRBoundingBox(x=24, y=24, width=96, height=16)),
                    ],
                )

            return OCRResult(
                image_path=image_path,
                metadata={"engine": "rapidocr_onnxruntime"},
                matches=[OCRTextMatch(text="Start", score=0.99, bbox=OCRBoundingBox(x=77, y=68, width=24, height=13))],
            )

    monkeypatch.setattr("app.api.vision.VisionProviderFactory.load_config", lambda: {"vision": {"mode": "local"}})
    monkeypatch.setattr("app.api.vision.VisionProviderFactory.create", lambda mode=None, config=None: DummyProvider())
    monkeypatch.setattr("app.api.vision.ocr_service", DummyOCR())
    monkeypatch.setattr(
        "app.api.vision.uia_provider.snapshot_bound_window",
        lambda: {
            "provider": "windows_uia",
            "provider_version": "windows_uia_provider_v1",
            "status": "unavailable",
            "reason": "no_bound_window",
            "control_count": 0,
            "controls": [],
        },
    )

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


def test_vision_screen_reading_returns_ui_provider_slots(tmp_path, monkeypatch) -> None:
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
                        label="Start",
                        role="button",
                        bbox=BBox(x=80, y=120, w=140, h=80),
                        diagonal=Diagonal(x1=80, y1=120, x2=220, y2=200),
                        normalized_diagonal=NormalizedDiagonal(nx1=0.1, ny1=0.5, nx2=0.5, ny2=0.9),
                        description="Start button",
                        ocr_text="Start",
                        text_lines=["Start"],
                        confidence=0.9,
                        layout_key="layout_start",
                        content_key="content_start",
                        match_key="layout_start:content_start",
                    ),
                    VisionRegion(
                        region_id="region_back",
                        label="Back arrow",
                        role="icon_button",
                        bbox=BBox(x=12, y=50, w=34, h=34),
                        diagonal=Diagonal(x1=12, y1=50, x2=46, y2=84),
                        normalized_diagonal=NormalizedDiagonal(nx1=0.02, ny1=0.22, nx2=0.1, ny2=0.38),
                        description="Left arrow icon in a toolbar",
                        confidence=0.82,
                        layout_key="toolbar_left",
                        content_key="back_arrow",
                        match_key="toolbar_left:back_arrow",
                    ),
                ],
                raw_text='{"screen_summary":"dummy page"}',
                raw_response={
                    "contract_version": "provider_model_trace_v1",
                    "provider": "dummy",
                    "model_name": "dummy-model",
                    "raw_text": '{"screen_summary":"dummy page"}',
                    "attempts": [
                        {
                            "status": "success",
                            "model_io": {
                                "contract_version": "model_io_attempt_v1",
                                "input": {"prompt": "read the screen", "image_path": str(image_path)},
                                "output": {"raw_text": '{"screen_summary":"dummy page"}'},
                            },
                        }
                    ],
                },
            )

    class DummyOCR:
        def scan_image(self, image_path):
            from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch

            return OCRResult(
                image_path=image_path,
                metadata={"engine": "rapidocr_onnxruntime"},
                matches=[OCRTextMatch(text="Start", score=0.99, bbox=OCRBoundingBox(x=112, y=150, width=44, height=18))],
            )

    monkeypatch.setattr("app.api.vision.VisionProviderFactory.load_config", lambda: {"vision": {"mode": "local"}})
    monkeypatch.setattr("app.api.vision.VisionProviderFactory.create", lambda mode=None, config=None: DummyProvider())
    monkeypatch.setattr("app.api.vision.ocr_service", DummyOCR())
    monkeypatch.setattr(
        "app.api.vision.uia_provider.snapshot_bound_window",
        lambda: {
            "provider": "windows_uia",
            "provider_version": "windows_uia_provider_v1",
            "status": "unavailable",
            "reason": "no_bound_window",
            "control_count": 0,
            "controls": [],
        },
    )

    client = TestClient(app)
    response = client.post(
        "/vision/screen_reading",
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
    assert result["contract_version"] == "screen_reading_v1"
    assert result["ui"]["summary"]["element_count"] == 2
    assert result["ui"]["summary"]["icon_candidate_count"] == 1
    assert result["ui"]["provider_slots"]["uia"]["status"] == "connected"
    assert result["ui"]["provider_slots"]["uia"]["last_scan_status"] == "unavailable"
    assert "icon_library" not in result["ui"]["provider_slots"]
    assert result["ui"]["icon_candidates"][0]["visual_recognition_status"] == "reserved_for_grounding"
    assert "icon_library_match" not in result["ui"]["icon_candidates"][0]
    assert result["execution_path"]["screen_reading_used"] is True
    assert result["execution_path"]["uia_provider_connected"] is True
    assert result["execution_path"]["uia_scan_status"] == "unavailable"
    assert result["model_io"]["contract_version"] == "model_io_trace_v1"
    assert result["model_io"]["raw_text"] == '{"screen_summary":"dummy page"}'
    assert result["model_io"]["attempts"][0]["model_io"]["input"]["prompt"] == "read the screen"
    assert Path(result["trace_path"]).exists()
    trace_payload = json.loads(Path(result["trace_path"]).read_text(encoding="utf-8"))
    assert trace_payload["result"]["model_io"]["raw_response"]["model_name"] == "dummy-model"


def test_vision_screen_reading_failure_trace_keeps_model_io(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "bad-model-output.png"
    Image.new("RGB", (420, 220), color=(255, 255, 255)).save(image_path)

    class FailingProvider:
        def analyze(self, req):
            error = RuntimeError("local vision endpoint failed after 1 attempt(s): invalid json")
            error.diagnostics = {
                "contract_version": "model_io_trace_v1",
                "status": "failed",
                "provider": "local",
                "model_name": "dummy-model",
                "image_path": str(image_path),
                "attempt_count": 1,
                "attempts": [
                    {
                        "status": "failed",
                        "model_io": {
                            "contract_version": "model_io_attempt_v1",
                            "input": {"prompt": "read the screen", "image_path": str(image_path)},
                            "output": {"raw_text": "{bad json"},
                            "raw_text": "{bad json",
                        },
                    }
                ],
            }
            raise error

    monkeypatch.setattr("app.api.vision.VisionProviderFactory.load_config", lambda: {"vision": {"mode": "local"}})
    monkeypatch.setattr("app.api.vision.VisionProviderFactory.create", lambda mode=None, config=None: FailingProvider())

    client = TestClient(app)
    response = client.post(
        "/vision/screen_reading",
        json={
            "image_path": str(image_path),
            "task": "observe_screen",
            "app_name": "demo",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    model_io = payload["data"]["model_io"]
    assert model_io["status"] == "failed"
    assert model_io["attempts"][0]["model_io"]["output"]["raw_text"] == "{bad json"
    trace_payload = json.loads(Path(payload["data"]["trace_path"]).read_text(encoding="utf-8"))
    assert trace_payload["model_io"]["attempts"][0]["model_io"]["input"]["prompt"] == "read the screen"


def test_vision_recognition_plan_returns_ranked_candidates(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "capture.png"
    Image.new("RGB", (420, 220), color=(255, 255, 255)).save(image_path)

    class DummyProvider:
        def analyze(self, req):
            from app.vision.schemas import BBox, Diagonal, ImageSize, NormalizedDiagonal, VisionAnalyzeResponse, VisionRegion

            assert req.metadata["ocr_anchors"]["contract_version"] == "ocr_anchors_v1"
            assert req.metadata["ocr_anchors"]["anchor_count"] == 2
            assert req.metadata["ocr_anchors"]["anchors"][0]["text"] == "Start detection"
            return VisionAnalyzeResponse(
                provider="dummy",
                screen_summary="dummy page",
                state_guess="dummy_state",
                image_size=ImageSize(width=420, height=220),
                regions=[
                    VisionRegion(
                        region_id="region_start",
                        label="Start detection",
                        role="button",
                        bbox=BBox(x=40, y=40, w=180, h=80),
                        diagonal=Diagonal(x1=40, y1=40, x2=220, y2=120),
                        normalized_diagonal=NormalizedDiagonal(nx1=0.1, ny1=0.1, nx2=0.5, ny2=0.5),
                        description="Start detection button",
                        ocr_text="Start detection",
                        text_lines=["Start detection"],
                        possible_destinations=["test_running"],
                        anchor_relations=[
                            {
                                "anchor_id": "ocr_anchor_1",
                                "text": "Start detection",
                                "relation": "inside",
                                "axis": "both",
                            }
                        ],
                        grounding_constraints={
                            "text_inclusion_policy": "include_referenced_text",
                            "text_anchor_frame": {"bottom_anchor_id": "ocr_anchor_1"},
                        },
                        confidence=0.9,
                        layout_key="layout_start",
                        content_key="content_start",
                        match_key="layout_start:content_start",
                    ),
                    VisionRegion(
                        region_id="region_help",
                        label="Help",
                        role="button",
                        bbox=BBox(x=240, y=40, w=120, h=80),
                        diagonal=Diagonal(x1=240, y1=40, x2=360, y2=120),
                        normalized_diagonal=NormalizedDiagonal(nx1=0.6, ny1=0.1, nx2=0.8, ny2=0.5),
                        description="Help button",
                        ocr_text="Help",
                        text_lines=["Help"],
                        possible_destinations=["help"],
                        confidence=0.8,
                        layout_key="layout_help",
                        content_key="content_help",
                        match_key="layout_help:content_help",
                    ),
                ],
            )

    class DummyOCR:
        def scan_image(self, image_path):
            from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch

            if "recognition-crops" in str(image_path):
                return OCRResult(
                    image_path=image_path,
                    metadata={"engine": "rapidocr_onnxruntime"},
                    matches=[
                        OCRTextMatch(text="Start detection", score=0.99, bbox=OCRBoundingBox(x=24, y=24, width=96, height=16)),
                    ],
                )

            return OCRResult(
                image_path=image_path,
                metadata={"engine": "rapidocr_onnxruntime"},
                matches=[
                    OCRTextMatch(text="Start detection", score=0.99, bbox=OCRBoundingBox(x=70, y=66, width=96, height=16)),
                    OCRTextMatch(text="Help", score=0.95, bbox=OCRBoundingBox(x=270, y=66, width=40, height=16)),
                ],
            )

    monkeypatch.setattr("app.api.vision.VisionProviderFactory.load_config", lambda: {"vision": {"mode": "local"}})
    monkeypatch.setattr("app.api.vision.VisionProviderFactory.create", lambda mode=None, config=None: DummyProvider())
    monkeypatch.setattr("app.api.vision.ocr_service", DummyOCR())

    client = TestClient(app)
    response = client.post(
        "/vision/recognition_plan",
        json={
            "image_path": str(image_path),
            "task": "click_target",
            "goal": "click start detection",
            "app_name": "demo",
            "top_k": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    result = payload["data"]["result"]
    assert result["contract_version"] == "recognition_plan_v1"
    assert result["candidate_result"]["contract_version"] == "candidate_rank_v1"
    assert result["recommended_target"]["element_id"].startswith("element_start")
    assert result["parse_result"]["ocr_anchors"]["contract_version"] == "ocr_anchors_v1"
    region_constraints = result["parse_result"]["vision_regions"]["regions"][0]["grounding_constraints"]
    assert region_constraints["grounding_evaluation"]["contract_version"] == "anchor_grounding_evaluation_v1"
    assert region_constraints["grounding_evaluation"]["ok"] is True
    assert region_constraints["grounding_evaluation"]["included_anchor_ids"] == ["ocr_anchor_1"]
    assert result["execution_path"]["ocr_anchor_grounding_used"] is True
    assert result["execution_path"]["ocr_anchor_count"] == 2
    assert result["parse_result"]["screen_reading"]["contract_version"] == "screen_reading_v1"
    assert result["execution_path"]["candidate_rank_used"] is True
    assert result["execution_path"]["screen_reading_used"] is True
    assert result["execution_path"]["screen_reading_rank_evidence_used"] is True
    assert result["execution_path"]["narrow_search_used"] is True
    assert result["execution_path"]["pre_click_decision_used"] is True
    assert result["execution_path"]["action_executed"] is False
    assert result["narrow_search_result"]["contract_version"] == "narrow_search_v1"
    assert result["narrow_search_result"]["results"][0]["status"] == "grounded"
    assert result["pre_click_decision"]["contract_version"] == "pre_click_decision_v1"
    assert result["pre_click_decision"]["allowed"] is True
    assert Path(result["trace_path"]).exists()


def test_vision_recognition_plan_retries_without_ocr_anchors_when_provider_rejects_them(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "capture.png"
    Image.new("RGB", (420, 220), color=(255, 255, 255)).save(image_path)
    calls: list[dict] = []

    class DummyProvider:
        def analyze(self, req):
            from app.vision.schemas import BBox, Diagonal, ImageSize, NormalizedDiagonal, VisionAnalyzeResponse, VisionRegion

            calls.append(req.metadata)
            if req.metadata.get("ocr_anchors"):
                raise RuntimeError("prompt too large")
            return VisionAnalyzeResponse(
                provider="dummy",
                screen_summary="dummy page",
                state_guess="dummy_state",
                image_size=ImageSize(width=420, height=220),
                regions=[
                    VisionRegion(
                        region_id="region_start",
                        label="Start detection",
                        role="button",
                        bbox=BBox(x=40, y=40, w=180, h=80),
                        diagonal=Diagonal(x1=40, y1=40, x2=220, y2=120),
                        normalized_diagonal=NormalizedDiagonal(nx1=0.1, ny1=0.1, nx2=0.5, ny2=0.5),
                        description="Start detection button",
                        ocr_text="Start detection",
                        text_lines=["Start detection"],
                        possible_destinations=["test_running"],
                        confidence=0.9,
                    )
                ],
            )

    class DummyOCR:
        def scan_image(self, image_path):
            from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch

            return OCRResult(
                image_path=image_path,
                metadata={"engine": "rapidocr_onnxruntime"},
                matches=[
                    OCRTextMatch(text="Start detection", score=0.99, bbox=OCRBoundingBox(x=70, y=66, width=96, height=16)),
                ],
            )

    monkeypatch.setattr("app.api.vision.VisionProviderFactory.load_config", lambda: {"vision": {"mode": "local"}})
    monkeypatch.setattr("app.api.vision.VisionProviderFactory.create", lambda mode=None, config=None: DummyProvider())
    monkeypatch.setattr("app.api.vision.ocr_service", DummyOCR())

    client = TestClient(app)
    response = client.post(
        "/vision/recognition_plan",
        json={
            "image_path": str(image_path),
            "task": "click_target",
            "goal": "click start detection",
            "app_name": "demo",
            "top_k": 1,
        },
    )

    result = response.json()["data"]["result"]
    assert response.json()["success"] is True
    assert len(calls) == 2
    assert calls[0]["ocr_anchors"]["anchor_count"] == 1
    assert "ocr_anchors" not in calls[1]
    assert result["execution_path"]["ocr_anchor_grounding_used"] is False
    assert result["execution_path"]["ocr_anchor_grounding_fallback_used"] is True
    assert result["parse_result"]["ocr_anchors"] is None


def test_vision_recognition_plan_recalls_path_graph_from_observe_trace(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "capture.png"
    Image.new("RGB", (420, 220), color=(255, 255, 255)).save(image_path)
    trace_path = tmp_path / "observe.json"
    trace_path.write_text(
        json.dumps(
            {
                "success": True,
                "result": {
                    "image_path": str(image_path),
                    "parse_result": {
                        "ocr_anchors": {
                            "contract_version": "ocr_anchors_v1",
                            "image_path": str(image_path),
                            "coordinate_space": "original_image",
                            "anchor_count": 2,
                            "anchors": [
                                {
                                    "anchor_id": "ocr_anchor_1",
                                    "text": "Start detection",
                                    "bbox": {"x": 70, "y": 66, "w": 96, "h": 16},
                                    "center": {"x": 118, "y": 74},
                                    "confidence": 0.99,
                                },
                                {
                                    "anchor_id": "ocr_anchor_2",
                                    "text": "Help",
                                    "bbox": {"x": 270, "y": 66, "w": 40, "h": 16},
                                    "center": {"x": 290, "y": 74},
                                    "confidence": 0.95,
                                },
                            ],
                        }
                    },
                    "screen_map": {
                        "contract_version": "screen_map_v1",
                        "state_id": "state_demo",
                        "candidates": [
                            {
                                "contract_version": "screen_map_candidate_v1",
                                "candidate_id": "start_btn",
                                "label": "Start detection",
                                "role": "button",
                                "section_id": "main_content",
                                "bbox": {"x": 40, "y": 40, "w": 180, "h": 80},
                                "click_point": {"x": 130, "y": 80},
                                "risk_class": "safe_click_allowed",
                                "expected_effect": "test starts",
                                "source": "screen_map",
                            },
                            {
                                "contract_version": "screen_map_candidate_v1",
                                "candidate_id": "help_link",
                                "label": "Help",
                                "role": "link",
                                "section_id": "page_header",
                                "bbox": {"x": 260, "y": 40, "w": 80, "h": 80},
                                "click_point": {"x": 300, "y": 80},
                                "risk_class": "safe_click_allowed",
                                "expected_effect": "help opens",
                                "source": "screen_map",
                            },
                        ],
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    provider_metadata: list[dict] = []
    ocr_scan_paths: list[str] = []

    class DummyProvider:
        def analyze(self, req):
            from app.vision.schemas import BBox, Diagonal, ImageSize, NormalizedDiagonal, VisionAnalyzeResponse, VisionRegion

            provider_metadata.append(req.metadata)
            return VisionAnalyzeResponse(
                provider="dummy",
                screen_summary="dummy page",
                state_guess="dummy_state",
                image_size=ImageSize(width=420, height=220),
                regions=[
                    VisionRegion(
                        region_id="region_start",
                        label="Start detection",
                        role="button",
                        bbox=BBox(x=40, y=40, w=180, h=80),
                        diagonal=Diagonal(x1=40, y1=40, x2=220, y2=120),
                        normalized_diagonal=NormalizedDiagonal(nx1=0.1, ny1=0.1, nx2=0.5, ny2=0.5),
                        description="Start detection button",
                        ocr_text="Start detection",
                        text_lines=["Start detection"],
                        possible_destinations=["test_running"],
                        confidence=0.9,
                    )
                ],
            )

    class DummyOCR:
        def scan_image(self, image_path):
            from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch

            ocr_scan_paths.append(image_path)
            return OCRResult(
                image_path=image_path,
                metadata={"engine": "local_crop_ocr"},
                matches=[
                    OCRTextMatch(text="Start detection", score=0.99, bbox=OCRBoundingBox(x=30, y=26, width=96, height=16)),
                ],
            )

    monkeypatch.setattr("app.api.vision.VisionProviderFactory.load_config", lambda: {"vision": {"mode": "local"}})
    monkeypatch.setattr("app.api.vision.VisionProviderFactory.create", lambda mode=None, config=None: DummyProvider())
    monkeypatch.setattr("app.api.vision.ocr_service", DummyOCR())

    client = TestClient(app)
    response = client.post(
        "/vision/recognition_plan",
        json={
            "image_path": str(image_path),
            "observe_trace_path": str(trace_path),
            "task": "click_target",
            "goal": "click start detection",
            "app_name": "demo",
            "top_k": 2,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    result = payload["data"]["result"]
    assert provider_metadata[0]["path_graph_recall"]["contract_version"] == "path_graph_recall_v1"
    assert provider_metadata[0]["path_graph_recall"]["candidates"][0]["candidate_id"] == "start_btn"
    assert provider_metadata[0]["ocr_anchors"]["anchor_count"] == 2
    assert result["observe_trace_reuse"]["status"] == "ready"
    assert result["path_graph_recall"]["status"] == "ready"
    assert result["path_graph_recall"]["candidates"][0]["candidate_id"] == "start_btn"
    assert result["path_graph_recall"]["candidates"][0]["local_ocr_roi"] == {"x": 16, "y": 16, "w": 228, "h": 128}
    assert result["execution_path"]["path_graph_recall_used"] is True
    assert result["execution_path"]["path_graph_recall_count"] == 2
    assert result["execution_path"]["ocr_anchor_reused_from_observe"] is True
    assert str(image_path) not in ocr_scan_paths


def test_vision_recognition_plan_uses_path_graph_recall_as_grounding_candidate(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "capture.png"
    Image.new("RGB", (500, 260), color=(255, 255, 255)).save(image_path)
    trace_path = tmp_path / "observe.json"
    trace_path.write_text(
        json.dumps(
            {
                "success": True,
                "result": {
                    "image_path": str(image_path),
                    "parse_result": {
                        "ocr_anchors": {
                            "contract_version": "ocr_anchors_v1",
                            "image_path": str(image_path),
                            "coordinate_space": "original_image",
                            "anchor_count": 1,
                            "anchors": [
                                {
                                    "anchor_id": "ocr_anchor_help",
                                    "text": "Help",
                                    "bbox": {"x": 20, "y": 20, "w": 40, "h": 16},
                                    "confidence": 0.95,
                                }
                            ],
                        }
                    },
                    "screen_map": {
                        "contract_version": "screen_map_v1",
                        "state_id": "state_dashboard",
                        "candidates": [
                            {
                                "contract_version": "screen_map_candidate_v1",
                                "candidate_id": "launch_btn",
                                "label": "Launch dashboard",
                                "role": "button",
                                "section_id": "main_content",
                                "bbox": {"x": 180, "y": 110, "w": 160, "h": 56},
                                "click_point": {"x": 260, "y": 138},
                                "risk_class": "safe_click_allowed",
                                "expected_effect": "dashboard opens",
                                "source": "screen_map",
                            }
                        ],
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    ocr_scan_paths: list[str] = []

    class DummyProvider:
        def analyze(self, req):
            from app.vision.schemas import ImageSize, VisionAnalyzeResponse

            return VisionAnalyzeResponse(
                provider="dummy",
                screen_summary="dashboard shell",
                state_guess="dashboard_home",
                image_size=ImageSize(width=500, height=260),
                regions=[],
            )

    class DummyOCR:
        def scan_image(self, image_path):
            from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch

            ocr_scan_paths.append(image_path)
            return OCRResult(
                image_path=image_path,
                metadata={"engine": "local_crop_ocr"},
                matches=[
                    OCRTextMatch(text="Launch dashboard", score=0.99, bbox=OCRBoundingBox(x=40, y=24, width=120, height=18)),
                ],
            )

    monkeypatch.setattr("app.api.vision.VisionProviderFactory.load_config", lambda: {"vision": {"mode": "local"}})
    monkeypatch.setattr("app.api.vision.VisionProviderFactory.create", lambda mode=None, config=None: DummyProvider())
    monkeypatch.setattr("app.api.vision.ocr_service", DummyOCR())

    client = TestClient(app)
    response = client.post(
        "/vision/recognition_plan",
        json={
            "image_path": str(image_path),
            "observe_trace_path": str(trace_path),
            "task": "click_target",
            "goal": "click Launch dashboard",
            "app_name": "demo",
            "top_k": 3,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    result = payload["data"]["result"]
    selected_id = result["pre_click_decision"]["selected_candidate_id"]
    assert selected_id == "path_graph_launch_btn"
    assert result["pre_click_decision"]["allowed"] is True
    assert result["candidate_result"]["candidates"][0]["candidate_id"] == "path_graph_launch_btn"
    assert result["candidate_result"]["candidates"][0]["element"]["sources"] == ["path_graph_recall_v1"]
    assert result["candidate_result"]["summary"]["path_graph_recall_selected_count"] == 1
    assert result["narrow_search_result"]["results"][0]["candidate_id"] == "path_graph_launch_btn"
    assert result["narrow_search_result"]["results"][0]["status"] == "grounded"
    assert result["execution_path"]["path_graph_recall_candidates_ranked"] is True
    assert result["execution_path"]["path_graph_recall_selected_count"] == 1
    assert str(image_path) not in ocr_scan_paths
    assert ocr_scan_paths


def test_vision_recognition_plan_uses_vista_point_grounding_with_path_graph(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "capture.png"
    Image.new("RGB", (500, 260), color=(255, 255, 255)).save(image_path)
    trace_path = tmp_path / "observe.json"
    trace_path.write_text(
        json.dumps(
            {
                "success": True,
                "result": {
                    "image_path": str(image_path),
                    "parse_result": {
                        "ocr_anchors": {
                            "contract_version": "ocr_anchors_v1",
                            "image_path": str(image_path),
                            "coordinate_space": "original_image",
                            "anchor_count": 1,
                            "anchors": [
                                {
                                    "anchor_id": "ocr_anchor_home",
                                    "text": "Home",
                                    "bbox": {"x": 34, "y": 136, "w": 44, "h": 16},
                                    "confidence": 0.95,
                                }
                            ],
                        }
                    },
                    "screen_map": {
                        "contract_version": "screen_map_v1",
                        "state_id": "state_news",
                        "candidates": [
                            {
                                "contract_version": "screen_map_candidate_v1",
                                "candidate_id": "home",
                                "label": "Home",
                                "role": "nav text action",
                                "section_id": "top_navigation",
                                "bbox": {"x": 30, "y": 120, "w": 80, "h": 60},
                                "click_point": {"x": 56, "y": 150},
                                "risk_class": "safe_click_allowed",
                                "expected_effect": "home opens",
                                "source": "screen_map",
                            }
                        ],
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calls: list[dict] = []

    def fake_vista(**kwargs):
        calls.append(kwargs)
        return {
            "contract_version": "vista_point_grounding_v1",
            "status": "ready",
            "provider": "vista_point_grounding",
            "model_name": "inclusionAI/VISTA-4B",
            "output_contract": "vista_point_v1",
            "image_path": str(image_path),
            "goal": kwargs["goal"],
            "prompt": "Locate Home",
            "raw_text": "[112, 577]",
            "raw_response": {"choices": [{"message": {"content": "[112, 577]"}}]},
            "parsed": {
                "contract_version": "vista_point_v1",
                "point": {"x": 112.0, "y": 577.0, "coordinate_space": "normalized_0_1000"},
            },
            "point": {"x": 56, "y": 150},
            "image_size": {"width": 900, "height": 760},
        }

    monkeypatch.setattr(
        "app.api.vision.VisionProviderFactory.load_config",
        lambda: {
            "vision": {
                "mode": "local",
                "timeout_seconds": 600,
                "local_grounding": {
                    "model_name": "inclusionAI/VISTA-4B",
                    "endpoint": "http://127.0.0.1:1244/v1/chat/completions",
                    "runtime": "transformers",
                    "output_contract": "vista_point_v1",
                },
            }
        },
    )
    monkeypatch.setattr("app.api.vision.VisionProviderFactory.create", lambda mode=None, config=None: object())
    monkeypatch.setattr("app.api.vision._call_vista_point_grounding", fake_vista)

    client = TestClient(app)
    response = client.post(
        "/vision/recognition_plan",
        json={
            "image_path": str(image_path),
            "observe_trace_path": str(trace_path),
            "provider_mode": "local_grounding",
            "task": "click_target",
            "goal": "click Home",
            "app_name": "Google News",
            "top_k": 3,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    result = payload["data"]["result"]
    assert calls
    assert result["execution_path"]["vista_point_grounding_used"] is True
    assert result["execution_path"]["vista_point_inside_candidate_bbox"] is True
    assert result["pre_click_decision"]["allowed"] is True
    assert result["pre_click_decision"]["selected_click_point"] == {"x": 56, "y": 150}
    assert result["narrow_search_result"]["results"][0]["coordinate_source"] == "vista_point_v1"
    assert result["parse_result"]["vista_point_grounding"]["point"] == {"x": 56, "y": 150}
    assert result["model_io"]["attempts"][0]["raw_text"] == "[112, 577]"


def test_vision_recognition_plan_uses_path_graph_candidate_roi_for_vista(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "capture.png"
    Image.new("RGB", (500, 260), color=(255, 255, 255)).save(image_path)
    trace_path = tmp_path / "observe.json"
    trace_path.write_text(
        json.dumps(
            {
                "success": True,
                "result": {
                    "image_path": str(image_path),
                    "parse_result": {
                        "ocr_anchors": {
                            "contract_version": "ocr_anchors_v1",
                            "image_path": str(image_path),
                            "coordinate_space": "original_image",
                            "anchor_count": 1,
                            "anchors": [
                                {
                                    "anchor_id": "ocr_anchor_start",
                                    "text": "Start",
                                    "bbox": {"x": 190, "y": 120, "w": 60, "h": 18},
                                    "confidence": 0.95,
                                }
                            ],
                        }
                    },
                    "screen_map": {
                        "contract_version": "screen_map_v1",
                        "state_id": "state_demo",
                        "candidates": [
                            {
                                "contract_version": "screen_map_candidate_v1",
                                "candidate_id": "start",
                                "label": "Start",
                                "role": "button",
                                "section_id": "main_content",
                                "bbox": {"x": 180, "y": 110, "w": 160, "h": 56},
                                "click_point": {"x": 260, "y": 138},
                                "risk_class": "safe_click_allowed",
                                "expected_effect": "start",
                                "source": "screen_map",
                            }
                        ],
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calls: list[dict] = []

    monkeypatch.setattr("app.api.vision.VISTA_DIRECT_IMAGES_DIR", tmp_path / "vista-direct")
    monkeypatch.setattr(
        "app.api.vision.VisionProviderFactory.load_config",
        lambda: {
            "vision": {
                "mode": "local",
                "timeout_seconds": 600,
                "local_grounding": {
                    "model_name": "inclusionAI/VISTA-4B",
                    "endpoint": "http://127.0.0.1:1244/v1/chat/completions",
                    "runtime": "transformers",
                    "output_contract": "vista_point_v1",
                },
            }
        },
    )
    monkeypatch.setattr("app.api.vision.VisionProviderFactory.create", lambda mode=None, config=None: object())

    def fake_endpoint(self, request_image_path, prompt, max_tokens=32):
        calls.append({"image_path": Path(request_image_path), "prompt": prompt, "max_tokens": max_tokens})
        return {"choices": [{"message": {"content": "[500, 500]"}}]}

    monkeypatch.setattr("app.api.vision.LocalVisionProvider._call_openai_compatible_endpoint", fake_endpoint)

    client = TestClient(app)
    response = client.post(
        "/vision/recognition_plan",
        json={
            "image_path": str(image_path),
            "observe_trace_path": str(trace_path),
            "provider_mode": "local_grounding",
            "task": "click_target",
            "goal": "click Start",
            "app_name": "demo",
            "agent_mode": "execute",
            "top_k": 3,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    result = payload["data"]["result"]
    assert len(calls) == 1
    assert calls[0]["image_path"] != image_path
    assert "Candidate bboxes are in processed ROI image pixel coordinates" in calls[0]["prompt"]
    assert "bbox=[48,106,160,56]" in calls[0]["prompt"]
    vista = result["parse_result"]["vista_point_grounding"]
    assert vista["vista_stage"] == "pathgraph_candidate_roi_refine"
    assert vista["image_preprocess"]["locate_strategy"] == "pathgraph_candidate_roi_refine"
    assert vista["image_preprocess"]["roi_source"] == "top1_only"
    assert vista["image_preprocess"]["crop_bounds_original"] == {"x": 132, "y": 4, "w": 256, "h": 256}
    assert vista["processed_point"] == {"x": 128, "y": 128}
    assert vista["point"] == {"x": 260, "y": 132}
    assert result["pre_click_decision"]["allowed"] is True
    assert result["model_io"]["attempt_count"] == 1
    assert result["model_io"]["attempts"][0]["vista_stage"] == "pathgraph_candidate_roi_refine"


def test_vision_recognition_plan_uses_seeded_candidate_roi_for_vista(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "capture.png"
    Image.new("RGB", (900, 760), color=(255, 255, 255)).save(image_path)
    calls: list[dict] = []

    def fake_vista(**kwargs):
        calls.append(kwargs)
        return {
            "contract_version": "vista_point_grounding_v1",
            "status": "ready",
            "provider": "vista_point_grounding",
            "model_name": "inclusionAI/VISTA-4B",
            "output_contract": "vista_point_v1",
            "image_path": str(kwargs["image_path"]),
            "goal": kwargs["goal"],
            "prompt": "Locate seeded card",
            "raw_text": "[500, 500]",
            "raw_response": {"choices": [{"message": {"content": "[500, 500]"}}]},
            "parsed": {
                "contract_version": "vista_point_v1",
                "point": {"x": 500.0, "y": 500.0, "coordinate_space": "normalized_0_1000"},
            },
            "point": {"x": 220, "y": 510},
            "image_size": {"width": 500, "height": 260},
            "image_preprocess": kwargs["image_preprocess"],
        }

    monkeypatch.setattr("app.api.vision.VISTA_DIRECT_IMAGES_DIR", tmp_path / "vista-direct")
    monkeypatch.setattr(
        "app.api.vision.VisionProviderFactory.load_config",
        lambda: {
            "vision": {
                "mode": "local",
                "timeout_seconds": 600,
                "local_grounding": {
                    "model_name": "inclusionAI/VISTA-4B",
                    "endpoint": "http://127.0.0.1:1244/v1/chat/completions",
                    "runtime": "transformers",
                    "output_contract": "vista_point_v1",
                },
            }
        },
    )
    monkeypatch.setattr("app.api.vision.VisionProviderFactory.create", lambda mode=None, config=None: object())
    monkeypatch.setattr("app.api.vision._call_vista_point_grounding", fake_vista)

    client = TestClient(app)
    response = client.post(
        "/vision/recognition_plan",
        json={
            "image_path": str(image_path),
            "provider_mode": "local_grounding",
            "task": "click_target",
            "goal": "Click the SEEK job result card titled Software Engineer",
            "app_name": "SEEK",
            "agent_mode": "execute",
            "top_k": 3,
            "metadata": {
                "seeded_candidate": {
                    "contract_version": "seeded_candidate_v1",
                    "candidate_id": "seek-card-1",
                    "source": "seek_job_card_v1",
                    "label": "Software Engineer | Example Co",
                    "role": "button",
                    "bbox": {"x": 24, "y": 400, "w": 410, "h": 220},
                    "click_point": {"x": 220, "y": 510},
                    "risk_class": "safe_click_allowed",
                    "expected_effect": "open SEEK job detail pane",
                }
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    result = payload["data"]["result"]
    assert calls
    assert [candidate.candidate_id for candidate in calls[0]["candidates"]] == ["seeded_seek-card-1"]
    assert calls[0]["image_preprocess"]["roi_source"] == "seeded_candidate_v1"
    candidate = result["candidate_result"]["candidates"][0]
    assert candidate["candidate_id"] == "seeded_seek-card-1"
    assert candidate["element"]["sources"] == ["seeded_candidate_v1"]
    assert result["candidate_result"]["summary"]["seeded_candidate_used"] is True
    assert result["execution_path"]["seeded_candidate_selected"] is True
    assert result["pre_click_decision"]["allowed"] is True
    assert result["pre_click_decision"]["selected_click_point"] == {"x": 220, "y": 510}
    assert result["narrow_search_result"]["results"][0]["coordinate_source"] == "seeded_candidate_v1_validated_by_vista_point_v1"
    assert result["parse_result"]["vista_point_grounding"]["image_preprocess"]["roi_source"] == "seeded_candidate_v1"


def test_seeded_candidate_rejects_point_outside_bbox() -> None:
    candidate = vision_api._recognition_candidate_from_seeded_candidate(
        {
            "contract_version": "seeded_candidate_v1",
            "candidate_id": "bad-seed",
            "label": "Bad seed",
            "bbox": {"x": 100, "y": 100, "w": 50, "h": 50},
            "click_point": {"x": 300, "y": 300},
            "risk_class": "safe_click_allowed",
        },
        rank=1,
    )

    assert candidate is None


def test_seeded_candidate_uses_seed_point_when_vista_roi_point_disagrees(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "capture.png"
    Image.new("RGB", (900, 760), color=(255, 255, 255)).save(image_path)

    def fake_vista(**kwargs):
        return {
            "contract_version": "vista_point_grounding_v1",
            "status": "ready",
            "provider": "vista_point_grounding",
            "model_name": "inclusionAI/VISTA-4B",
            "output_contract": "vista_point_v1",
            "image_path": str(kwargs["image_path"]),
            "goal": kwargs["goal"],
            "prompt": "Locate seeded button",
            "raw_text": "[100, 100]",
            "raw_response": {"choices": [{"message": {"content": "[100, 100]"}}]},
            "parsed": {
                "contract_version": "vista_point_v1",
                "point": {"x": 100.0, "y": 100.0, "coordinate_space": "normalized_0_1000"},
            },
            "point": {"x": 160, "y": 140},
            "image_size": {"width": 500, "height": 260},
            "image_preprocess": kwargs["image_preprocess"],
        }

    monkeypatch.setattr("app.api.vision.VISTA_DIRECT_IMAGES_DIR", tmp_path / "vista-direct")
    monkeypatch.setattr(
        "app.api.vision.VisionProviderFactory.load_config",
        lambda: {
            "vision": {
                "mode": "local",
                "timeout_seconds": 600,
                "local_grounding": {
                    "model_name": "inclusionAI/VISTA-4B",
                    "endpoint": "http://127.0.0.1:1244/v1/chat/completions",
                    "runtime": "transformers",
                    "output_contract": "vista_point_v1",
                },
            }
        },
    )
    monkeypatch.setattr("app.api.vision.VisionProviderFactory.create", lambda mode=None, config=None: object())
    monkeypatch.setattr("app.api.vision._call_vista_point_grounding", fake_vista)

    client = TestClient(app)
    response = client.post(
        "/vision/recognition_plan",
        json={
            "image_path": str(image_path),
            "provider_mode": "local_grounding",
            "task": "click_target",
            "goal": "Click search",
            "app_name": "Docs",
            "agent_mode": "execute",
            "top_k": 3,
            "metadata": {
                "seeded_candidate": {
                    "contract_version": "seeded_candidate_v1",
                    "candidate_id": "docs-search",
                    "label": "search",
                    "role": "button",
                    "bbox": {"x": 497, "y": 272, "w": 57, "h": 22},
                    "click_point": {"x": 525, "y": 283},
                    "risk_class": "safe_click_allowed",
                    "expected_effect": "search results visible",
                }
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    result = payload["data"]["result"]
    narrow = result["narrow_search_result"]
    pre_click = result["pre_click_decision"]
    assert narrow["results"][0]["status"] == "grounded"
    assert narrow["results"][0]["coordinate_source"] == "seeded_candidate_v1_model_disagreed"
    assert "vista_point_disagrees_with_seed_bbox" in narrow["results"][0]["reasons"]
    assert narrow["summary"]["vista_point_inside_candidate_bbox"] is False
    assert narrow["summary"]["seeded_candidate_primary_point_used"] is True
    assert pre_click["allowed"] is True
    assert pre_click["selected_click_point"] == {"x": 525, "y": 283}
    assert result["execution_path"]["seeded_candidate_primary_point_used"] is True


def test_parse_vista_point_text_accepts_pixel_bbox_quad() -> None:
    parsed = vision_api._parse_vista_point_text("[36, 48, 426, 350]")

    assert parsed == {
        "contract_version": "vista_point_v1",
        "point": {"x": 249.0, "y": 223.0, "coordinate_space": "pixel"},
    }


def test_parse_vista_point_text_accepts_wrapped_unparsed_bbox_quad() -> None:
    parsed = vision_api._parse_vista_point_text(
        json.dumps(
            {
                "contract_version": "vista_point_v1",
                "status": "unparsed",
                "point": None,
                "raw_text": "[36, 48, 426, 350]",
            }
        )
    )

    assert parsed["point"] == {"x": 249.0, "y": 223.0, "coordinate_space": "pixel"}
    assert parsed["wrapped_unparsed_payload"]["status"] == "unparsed"


def test_vista_pixel_point_outside_inference_image_is_not_clamped() -> None:
    parsed = {
        "contract_version": "vista_point_v1",
        "point": {"x": 9999.0, "y": 120.0, "coordinate_space": "pixel"},
    }

    with pytest.raises(ValueError, match="outside inference image bounds"):
        vision_api._vista_point_to_original_pixel(parsed, image_size=vision_api.ImageSize(width=640, height=480))


def test_execute_recognition_plan_uses_vista_direct_grounding_without_path_graph(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "capture.png"
    Image.new("RGB", (500, 260), color=(255, 255, 255)).save(image_path)
    calls: list[dict] = []

    def fake_vista_point_prompt(**kwargs):
        calls.append(kwargs)
        return {
            "contract_version": "vista_point_grounding_v1",
            "status": "ready",
            "provider": kwargs["provider_name"],
            "model_name": "inclusionAI/VISTA-4B",
            "output_contract": "vista_point_v1",
            "image_path": str(image_path),
            "goal": kwargs["goal"],
            "prompt": kwargs["prompt"],
            "raw_text": "[400, 500]",
            "raw_response": {"choices": [{"message": {"content": "[400, 500]"}}]},
            "parsed": {
                "contract_version": "vista_point_v1",
                "point": {"x": 400.0, "y": 500.0, "coordinate_space": "normalized_0_1000"},
            },
            "point": {"x": 200, "y": 130},
            "image_size": {"width": 500, "height": 260},
        }

    monkeypatch.setattr(
        "app.api.vision.VisionProviderFactory.load_config",
        lambda: {
            "vision": {
                "mode": "local",
                "timeout_seconds": 600,
                "local_grounding": {
                    "model_name": "inclusionAI/VISTA-4B",
                    "endpoint": "http://127.0.0.1:1244/v1/chat/completions",
                    "runtime": "transformers",
                    "output_contract": "vista_point_v1",
                },
            }
        },
    )
    monkeypatch.setattr("app.api.vision.VisionProviderFactory.create", lambda mode=None, config=None: object())
    monkeypatch.setattr("app.api.vision._call_vista_point_prompt", fake_vista_point_prompt)

    client = TestClient(app)
    response = client.post(
        "/vision/recognition_plan",
        json={
            "image_path": str(image_path),
            "provider_mode": "local_grounding",
            "task": "click_target",
            "goal": "Click Start",
            "app_name": "demo",
            "agent_mode": "execute",
            "top_k": 3,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    result = payload["data"]["result"]
    assert calls
    assert calls[0]["provider_name"] == "vista_direct_point_grounding"
    assert result["path_graph_recall"]["status"] == "unavailable"
    assert result["execution_path"]["vista_direct_point_grounding_used"] is True
    assert result["pre_click_decision"]["allowed"] is True
    assert result["pre_click_decision"]["selected_click_point"] == {"x": 200, "y": 130}
    candidate = result["candidate_result"]["candidates"][0]
    assert candidate["candidate_id"].startswith("vista_direct_")
    assert candidate["element"]["sources"] == ["vista_point_v1_direct"]
    assert result["narrow_search_result"]["results"][0]["reasons"] == ["vista_direct_point_grounding"]


def test_execute_recognition_plan_builds_fast_inventory_from_uia_for_vista_direct(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "capture.png"
    Image.new("RGB", (500, 260), color=(255, 255, 255)).save(image_path)

    monkeypatch.setattr(
        "app.api.vision.VisionProviderFactory.load_config",
        lambda: {
            "vision": {
                "mode": "local",
                "timeout_seconds": 600,
                "local_grounding": {
                    "model_name": "inclusionAI/VISTA-4B",
                    "endpoint": "http://127.0.0.1:1244/v1/chat/completions",
                    "runtime": "transformers",
                    "output_contract": "vista_point_v1",
                },
            }
        },
    )
    monkeypatch.setattr("app.api.vision.VisionProviderFactory.create", lambda mode=None, config=None: object())
    monkeypatch.setattr(
        "app.api.vision._call_vista_point_prompt",
        lambda **kwargs: {
            "contract_version": "vista_point_grounding_v1",
            "status": "ready",
            "provider": kwargs["provider_name"],
            "model_name": "inclusionAI/VISTA-4B",
            "output_contract": "vista_point_v1",
            "image_path": str(image_path),
            "goal": kwargs["goal"],
            "prompt": kwargs["prompt"],
            "raw_text": "[400, 500]",
            "raw_response": {"choices": [{"message": {"content": "[400, 500]"}}]},
            "parsed": {
                "contract_version": "vista_point_v1",
                "point": {"x": 400.0, "y": 500.0, "coordinate_space": "normalized_0_1000"},
            },
            "point": {"x": 200, "y": 130},
            "image_size": {"width": 500, "height": 260},
        },
    )
    monkeypatch.setattr(
        "app.api.vision.uia_provider.snapshot_bound_window",
        lambda max_controls=250: {
            "provider": "windows_uia",
            "provider_version": "windows_uia_provider_v1",
            "status": "ok",
            "control_count": 2,
            "controls": [
                {
                    "provider": "windows_uia",
                    "control_id": "btn_start",
                    "name": "Start",
                    "control_type": "Button",
                    "automation_id": "startButton",
                    "class_name": "Button",
                    "bbox": {"x": 170, "y": 112, "w": 80, "h": 36},
                    "screen_bbox": {"x": 170, "y": 112, "w": 80, "h": 36},
                    "enabled": True,
                    "visible": True,
                    "patterns": ["InvokePattern"],
                },
                {
                    "provider": "windows_uia",
                    "control_id": "txt_status",
                    "name": "Ready",
                    "control_type": "Text",
                    "automation_id": "statusText",
                    "class_name": "Text",
                    "bbox": {"x": 20, "y": 20, "w": 100, "h": 20},
                    "screen_bbox": {"x": 20, "y": 20, "w": 100, "h": 20},
                    "enabled": True,
                    "visible": True,
                    "patterns": [],
                },
            ],
        },
    )

    client = TestClient(app)
    response = client.post(
        "/vision/recognition_plan",
        json={
            "image_path": str(image_path),
            "provider_mode": "local_grounding",
            "task": "click_target",
            "goal": "Click Start",
            "app_name": "demo",
            "agent_mode": "execute",
            "top_k": 3,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    result = payload["data"]["result"]
    assert result["screen_inventory"]["contract_version"] == "screen_inventory_v1"
    assert result["screen_inventory"]["available_actions"][0]["label"] == "Start"
    assert result["screen_inventory"]["page_elements"][0]["text"] == "Ready"
    assert result["parse_result"]["screen_reading"]["contract_version"] == "screen_reading_v1"
    assert result["parse_result"]["execute_fast_inventory"]["status"] == "ready"
    assert result["execution_path"]["screen_inventory_source"] == "execute_fast_inventory_uia"
    assert result["execution_path"]["screen_inventory_available_action_count"] == 1
    assert result["execution_path"]["screen_inventory_page_element_count"] == 1
    assert result["execution_path"]["uia_scan_status"] == "ok"


def test_execute_fast_inventory_filters_browser_chrome_controls() -> None:
    controls = [
        {
            "name": "Back",
            "control_type": "Button",
            "bbox": {"x": 12, "y": 44, "w": 32, "h": 32},
            "enabled": True,
            "visible": True,
            "patterns": ["InvokePattern"],
        },
        {
            "name": "https://nz.seek.com/software-engineer-jobs",
            "control_type": "Edit",
            "bbox": {"x": 112, "y": 48, "w": 600, "h": 24},
            "enabled": True,
            "visible": True,
            "patterns": ["ValuePattern"],
        },
        {
            "name": "Pay",
            "control_type": "Button",
            "bbox": {"x": 52, "y": 256, "w": 78, "h": 41},
            "enabled": True,
            "visible": True,
            "patterns": ["InvokePattern"],
        },
        {
            "name": "Software engineer",
            "control_type": "Hyperlink",
            "bbox": {"x": 52, "y": 532, "w": 280, "h": 36},
            "enabled": True,
            "visible": True,
            "patterns": ["InvokePattern"],
        },
        {
            "name": "",
            "control_type": "Pane",
            "bbox": {"x": 8, "y": 0, "w": 1230, "h": 1186},
            "enabled": True,
            "visible": True,
            "patterns": [],
        },
    ]

    filtered = vision_api._filter_execute_fast_inventory_controls(
        controls,
        image_size=vision_api.ImageSize(width=1246, height=1194),
        app_name="edge",
    )

    assert [item["name"] for item in filtered] == ["Pay", "Software engineer"]


def test_execute_recognition_plan_blocks_vista_direct_point_in_browser_chrome(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "browser_capture.png"
    Image.new("RGB", (1265, 1380), color=(255, 255, 255)).save(image_path)

    def fake_vista_point_prompt(**kwargs):
        return {
            "contract_version": "vista_point_grounding_v1",
            "status": "ready",
            "provider": kwargs["provider_name"],
            "model_name": "inclusionAI/VISTA-4B",
            "output_contract": "vista_point_v1",
            "image_path": str(image_path),
            "goal": kwargs["goal"],
            "prompt": kwargs["prompt"],
            "raw_text": "[569, 42]",
            "raw_response": {"choices": [{"message": {"content": "[569, 42]"}}]},
            "parsed": {
                "contract_version": "vista_point_v1",
                "point": {"x": 569.0, "y": 42.0, "coordinate_space": "normalized_0_1000"},
            },
            "point": {"x": 720, "y": 58},
            "image_size": {"width": 1265, "height": 1380},
        }

    monkeypatch.setattr(
        "app.api.vision.VisionProviderFactory.load_config",
        lambda: {
            "vision": {
                "mode": "local",
                "timeout_seconds": 600,
                "local_grounding": {
                    "model_name": "inclusionAI/VISTA-4B",
                    "endpoint": "http://127.0.0.1:1244/v1/chat/completions",
                    "runtime": "transformers",
                    "output_contract": "vista_point_v1",
                },
            }
        },
    )
    monkeypatch.setattr("app.api.vision.VisionProviderFactory.create", lambda mode=None, config=None: object())
    monkeypatch.setattr("app.api.vision._call_vista_point_prompt", fake_vista_point_prompt)

    client = TestClient(app)
    response = client.post(
        "/vision/recognition_plan",
        json={
            "image_path": str(image_path),
            "provider_mode": "local_grounding",
            "task": "click_target",
            "goal": "Click the Date filter",
            "app_name": "edge",
            "agent_mode": "execute",
            "metadata": {"vista_direct_grounding": {"enabled": True, "refine": False}},
            "top_k": 3,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    result = payload["data"]["result"]
    assert result["candidate_result"]["candidates"] == []
    assert result["narrow_search_result"]["summary"]["error"] == "vista_direct_point_in_browser_chrome"
    assert result["parse_result"]["vista_point_grounding"]["blocked_reason"] == "vista_direct_point_in_browser_chrome"
    assert result["pre_click_decision"]["allowed"] is False
    assert result["execution_path"]["vista_direct_point_grounding_attempted"] is True
    assert result["execution_path"]["vista_direct_point_grounding_used"] is False


def test_execute_recognition_plan_resizes_vista_direct_image_and_maps_point(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "large_capture.png"
    Image.new("RGB", (1265, 1380), color=(255, 255, 255)).save(image_path)
    calls: list[dict] = []

    monkeypatch.setattr("app.api.vision.VISTA_DIRECT_IMAGES_DIR", tmp_path / "vista-direct")
    monkeypatch.setattr(
        "app.api.vision.VisionProviderFactory.load_config",
        lambda: {
            "vision": {
                "mode": "local",
                "timeout_seconds": 600,
                "local_grounding": {
                    "model_name": "inclusionAI/VISTA-4B",
                    "endpoint": "http://127.0.0.1:1244/v1/chat/completions",
                    "runtime": "transformers",
                    "output_contract": "vista_point_v1",
                },
            }
        },
    )
    monkeypatch.setattr("app.api.vision.VisionProviderFactory.create", lambda mode=None, config=None: object())

    def fake_endpoint(self, request_image_path, prompt, max_tokens=32):
        calls.append({"image_path": Path(request_image_path), "prompt": prompt, "max_tokens": max_tokens})
        return {"choices": [{"message": {"content": "[500, 500]"}}]}

    monkeypatch.setattr("app.api.vision.LocalVisionProvider._call_openai_compatible_endpoint", fake_endpoint)

    client = TestClient(app)
    response = client.post(
        "/vision/recognition_plan",
        json={
            "image_path": str(image_path),
            "provider_mode": "local_grounding",
            "task": "click_target",
            "goal": "Click Start",
            "app_name": "demo",
            "agent_mode": "execute",
            "metadata": {"vista_direct_grounding": {"enabled": True, "timeout_seconds": 45.0, "max_edge": 640, "refine": True}},
            "top_k": 3,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    result = payload["data"]["result"]
    assert len(calls) == 2
    assert calls[0]["image_path"] != image_path
    assert calls[0]["image_path"].exists()
    assert calls[1]["image_path"] != image_path
    assert calls[1]["image_path"].exists()
    vista = result["parse_result"]["vista_point_grounding"]
    assert vista["vista_stage"] == "final_refine_roi"
    assert vista["image_path"] == str(calls[1]["image_path"])
    assert vista["image_preprocess"]["status"] == "processed"
    assert vista["image_preprocess"]["strategy"] == "crop_roi"
    assert vista["image_preprocess"]["crop_bounds_original"] == {"x": 378, "y": 434, "w": 512, "h": 512}
    assert vista["image_preprocess"]["processed_size"] == {"width": 512, "height": 512}
    assert vista["processed_point"] == {"x": 256, "y": 256}
    assert vista["point"] == {"x": 634, "y": 690}
    assert vista["image_size"] == {"width": 1265, "height": 1380}
    assert vista["inference_image_size"] == {"width": 512, "height": 512}
    assert vista["coarse_vista_point_grounding"]["processed_point"] == {"x": 294, "y": 320}
    assert vista["coarse_vista_point_grounding"]["inference_image_size"] == {"width": 587, "height": 640}
    assert vista["refine_vista_point_grounding"]["point"] == {"x": 634, "y": 690}
    assert result["model_io"]["attempt_count"] == 2
    assert result["model_io"]["attempts"][0]["vista_stage"] == "coarse_full"
    assert result["model_io"]["attempts"][1]["vista_stage"] == "refine_roi"
    assert result["pre_click_decision"]["selected_click_point"] == {"x": 634, "y": 690}
    assert result["recommended_target"]["element"]["bbox"] == {"x": 610, "y": 666, "w": 48, "h": 48}


def test_execute_recognition_plan_blocks_when_vista_direct_grounding_times_out(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "capture.png"
    Image.new("RGB", (500, 260), color=(255, 255, 255)).save(image_path)

    monkeypatch.setattr(
        "app.api.vision.VisionProviderFactory.load_config",
        lambda: {
            "vision": {
                "mode": "local",
                "timeout_seconds": 600,
                "local_grounding": {
                    "model_name": "inclusionAI/VISTA-4B",
                    "endpoint": "http://127.0.0.1:1244/v1/chat/completions",
                    "runtime": "transformers",
                    "output_contract": "vista_point_v1",
                },
            }
        },
    )
    monkeypatch.setattr("app.api.vision.VisionProviderFactory.create", lambda mode=None, config=None: object())
    monkeypatch.setattr("app.api.vision._call_vista_point_prompt", lambda **_kwargs: (_ for _ in ()).throw(TimeoutError("timed out")))

    client = TestClient(app)
    response = client.post(
        "/vision/recognition_plan",
        json={
            "image_path": str(image_path),
            "provider_mode": "local_grounding",
            "task": "click_target",
            "goal": "Click Start",
            "app_name": "demo",
            "agent_mode": "execute",
            "top_k": 3,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    result = payload["data"]["result"]
    assert result["execution_path"]["vista_direct_point_grounding_attempted"] is True
    assert result["execution_path"]["vista_direct_point_grounding_used"] is False
    assert result["pre_click_decision"]["allowed"] is False
    assert result["model_io"]["status"] == "failed"
    assert result["narrow_search_result"]["summary"]["error"] == "vista_direct_point_grounding_failed: timed out"


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


def test_render_recognition_plan_overlay_returns_output_image(tmp_path) -> None:
    image_path = tmp_path / "capture.png"
    Image.new("RGB", (240, 160), color=(255, 255, 255)).save(image_path)

    trace_path = tmp_path / "recognition-plan.json"
    trace_payload = {
        "result": {
            "contract_version": "recognition_plan_v1",
            "image_path": str(image_path),
            "candidate_result": {
                "candidates": [
                    {
                        "candidate_id": "candidate_start",
                        "rank": 1,
                        "element_id": "element_start",
                        "label": "Start",
                        "score": 0.91,
                        "eligible": True,
                        "element": {
                            "bbox": {"x": 30, "y": 40, "w": 80, "h": 40},
                        },
                    }
                ],
                "rejected": [
                    {
                        "candidate_id": "candidate_ad",
                        "rank": 1,
                        "element_id": "element_ad",
                        "label": "Ad",
                        "score": 0.2,
                        "eligible": False,
                        "element": {
                            "bbox": {"x": 130, "y": 40, "w": 70, "h": 40},
                        },
                    }
                ],
            },
            "narrow_search_result": {
                "results": [
                    {
                        "candidate_id": "candidate_start",
                        "refined_click_point": {"x": 70, "y": 60},
                        "coordinate_source": "local_ocr_text_center",
                        "matched_text": "Start",
                    }
                ]
            },
            "pre_click_decision": {
                "selected_candidate_id": "candidate_start",
                "candidate_decisions": [
                    {
                        "candidate_id": "candidate_start",
                        "allowed": True,
                        "reasons": ["pre_click_checks_passed"],
                    },
                    {
                        "candidate_id": "candidate_ad",
                        "allowed": False,
                        "reasons": ["ad_like_candidate"],
                    },
                ],
            },
        }
    }
    trace_path.write_text(json.dumps(trace_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    client = TestClient(app)
    response = client.post(
        "/vision/render_recognition_plan_overlay",
        json={
            "trace_path": str(trace_path),
            "include_rejected": True,
            "include_points": True,
            "label_candidates": True,
            "label_reasons": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    result = payload["data"]["result"]
    output_path = Path(result["output_path"])
    assert output_path.exists()
    assert result["candidate_count"] == 2
    assert result["decision_count"] == 2
    assert result["selected_candidate_id"] == "candidate_start"
