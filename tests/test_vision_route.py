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
    assert Path(result["trace_path"]).exists()


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
