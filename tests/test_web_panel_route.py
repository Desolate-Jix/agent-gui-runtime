from __future__ import annotations

import base64
import json

from fastapi.testclient import TestClient

from app.api import panel as panel_api
from app.main import app


def test_web_panel_serves_browser_control_surface() -> None:
    client = TestClient(app)

    response = client.get("/panel")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "charset=utf-8" in response.headers["content-type"]
    assert "agent-gui-runtime panel" in response.text
    assert "/panel/assets/panel.js" in response.text
    assert 'class="language-toggle"' in response.text
    assert 'data-language="zh-CN"' in response.text
    assert 'id="windowSelect"' in response.text
    assert 'id="observeModelProfile"' in response.text
    assert 'id="locateModelProfile"' in response.text
    assert 'id="modelTestSendBtn"' in response.text
    assert 'id="modelTestProfile"' in response.text
    assert 'id="modelTestImagePath"' in response.text
    assert 'id="applyObserveModelBtn"' in response.text
    assert 'id="applyLocateModelBtn"' in response.text
    assert 'nav-path-panel' in response.text
    assert 'id="flowDiagram"' in response.text
    assert 'id="savePathBtn"' in response.text
    assert 'id="navPathCanvas"' in response.text
    assert 'data-page="open_bind"' in response.text
    assert 'id="listAppsBtn"' in response.text
    assert 'data-page="model_test"' in response.text
    assert 'id="roiX"' in response.text
    assert 'id="analyzeBtn"' in response.text
    assert 'id="manualBoxBtn"' in response.text
    assert 'id="saveAsOverlay"' in response.text
    assert 'id="saveAsFileName"' in response.text
    assert 'id="saveAsConfirmBtn"' in response.text


def test_web_panel_serves_static_assets() -> None:
    client = TestClient(app)

    response = client.get("/panel/assets/panel.js")

    assert response.status_code == 200
    assert "renderNavPath" in response.text
    assert "renderFlowGraph" in response.text
    assert "detectFlowStagesFromResponse" in response.text
    assert "savePathGraph" in response.text
    assert "confirmSaveAs" in response.text
    assert "buildPathGraphPayload" in response.text
    assert "generateFakePathData" in response.text
    assert "ALL_FLOW_STAGES" in response.text
    assert "applyLanguage" in response.text
    assert "setWindowCandidates" in response.text
    assert "testModelService" in response.text
    assert "markWorkflow" in response.text
    assert "roiPayload" in response.text
    assert "callAnalyzeApi" in response.text
    assert "generateManualBox" in response.text
    assert "applyModelProfile" in response.text
    assert "collectControlsFromResult" in response.text
    assert "PATH_CANVAS_FONT" in response.text
    assert "traceDisplayValue" in response.text
    assert "collectTraceStageVisuals" in response.text
    assert "activateTraceStageVisuals" in response.text

    css_response = client.get("/panel/assets/panel.css")

    assert css_response.status_code == 200
    assert "path-detail-sections" in css_response.text
    assert "Microsoft YaHei" in css_response.text
    assert "grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr)" in css_response.text
    assert "tf-stage-visuals" in css_response.text
    assert "tf-stage-image-missing" in css_response.text


def test_web_panel_uploads_and_serves_image() -> None:
    client = TestClient(app)
    png_1x1 = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
    )

    upload = client.post(
        "/panel/upload_image",
        json={
            "filename": "sample.png",
            "content_base64": base64.b64encode(png_1x1).decode("ascii"),
            "content_type": "image/png",
        },
    )

    assert upload.status_code == 200
    assert upload.json()["success"] is True
    image_path = upload.json()["data"]["image_path"]

    served = client.get("/panel/file", params={"path": image_path})

    assert served.status_code == 200
    assert served.content == png_1x1


def test_web_panel_file_rejects_outside_paths() -> None:
    client = TestClient(app)

    response = client.get("/panel/file", params={"path": "C:/Windows/win.ini"})

    assert response.status_code == 404


def test_web_panel_renders_manual_candidate_box() -> None:
    client = TestClient(app)
    png_1x1 = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
    )
    upload = client.post(
        "/panel/upload_image",
        json={
            "filename": "manual-source.png",
            "content_base64": base64.b64encode(png_1x1).decode("ascii"),
            "content_type": "image/png",
        },
    )
    image_path = upload.json()["data"]["image_path"]

    response = client.post(
        "/panel/manual_box",
        json={"image_path": image_path, "x": 0, "y": 0, "width": 1, "height": 1, "label": "target"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["manual_overlay_path"].endswith(".png")
    assert body["data"]["bbox"] == {"x": 0, "y": 0, "w": 1, "h": 1}

    served = client.get("/panel/file", params={"path": body["data"]["manual_overlay_path"]})

    assert served.status_code == 200
    assert served.headers["content-type"].startswith("image/png")


def test_web_panel_applies_model_profile_to_temp_configs(tmp_path, monkeypatch) -> None:
    client = TestClient(app)
    vision_config = tmp_path / "vision.json"
    panel_config = tmp_path / "settings_panel.json"
    monkeypatch.setattr(panel_api, "VISION_CONFIG_PATH", vision_config)
    monkeypatch.setattr(panel_api, "PANEL_CONFIG_PATH", panel_config)
    monkeypatch.setattr(
        panel_api,
        "load_model_profiles",
        lambda: [
            {
                "profile_id": "demo_observe",
                "label": "Demo Observe",
                "model_name": "demo.gguf",
                "endpoint": "http://127.0.0.1:1240/v1/chat/completions",
                "start_script": "scripts/start.ps1",
                "stop_script": "scripts/stop.ps1",
            }
        ],
    )

    response = client.post(
        "/panel/apply_model_profile",
        json={
            "stage": "observe",
            "profile_id": "demo_observe",
            "timeout_seconds": 321,
            "language": "zh-CN",
            "observe_prompt": "observe rules",
            "locate_prompt": "locate rules",
        },
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert "demo.gguf" in vision_config.read_text(encoding="utf-8")
    assert "Demo Observe" in panel_config.read_text(encoding="utf-8")


def test_web_panel_inspects_trace_result_by_stage(tmp_path) -> None:
    client = TestClient(app)
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps(
            {
                "success": True,
                "request": {"goal": "click start", "app_name": "demo", "provider_mode": "local"},
                "result": {
                    "contract_version": "recognition_plan_v1",
                    "image_path": "artifacts/capture.png",
                    "parse_result": {
                        "ocr_result": {"matches": [{"text": "Start"}], "metadata": {}},
                        "vision_regions": {"screen_summary": "demo page"},
                    },
                    "candidate_result": {
                        "summary": {"returned_count": 1, "has_recommendation": True},
                        "candidates": [{"label": "Start"}],
                    },
                    "pre_click_decision": {"allowed": False, "reasons": ["blocked"]},
                    "execution_path": {"vision_provider_used": "dummy", "action_executed": False},
                    "timings": {"total_ms": 12, "steps": [{"name": "ocr", "elapsed_ms": 4}]},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = client.get("/panel/inspect_trace", params={"path": str(trace_path)})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["ocr_count"] == 1
    assert data["candidates"] == 1
    assert data["gate_allowed"] is False
    assert [stage["id"] for stage in data["flow_stages"]] == [
        "goal",
        "capture",
        "ocr",
        "vision",
        "candidates",
        "gate",
        "click",
        "timings",
    ]
    assert data["flow_stages"][2]["raw"]["matches"][0]["text"] == "Start"


def test_web_panel_inspects_legacy_overlay_trace(tmp_path) -> None:
    client = TestClient(app)
    trace_path = tmp_path / "overlay.json"
    trace_path.write_text(
        json.dumps(
            {
                "success": True,
                "request": {"trace_path": "recognition-plan.json"},
                "result": {
                    "trace_path": "recognition-plan.json",
                    "image_path": "capture.png",
                    "output_path": "overlay.png",
                    "candidate_count": 2,
                    "decision_count": 2,
                    "selected_candidate_id": "candidate_start",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8-sig",
    )

    response = client.get("/panel/inspect_trace", params={"path": str(trace_path)})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["contract"] == "recognition_overlay_trace"
    assert data["total_time"] == ""
    assert data["provider"] == ""
    assert [stage["id"] for stage in data["flow_stages"]] == ["goal", "capture", "overlay"]
    assert data["flow_stages"][2]["value"] == "2 candidates, 2 decisions"
    assert data["flow_stages"][2]["raw"]["output_path"] == "overlay.png"


def test_web_panel_inspects_legacy_layer_trace(tmp_path) -> None:
    client = TestClient(app)
    trace_path = tmp_path / "layer.json"
    trace_path.write_text(
        json.dumps(
            {
                "success": True,
                "request": {"app_name": "demo"},
                "result": {
                    "contract_version": "vision_layer_trace_v1",
                    "image_path": "capture.png",
                    "final_ok": True,
                    "layers": [
                        {"layer": "input_image", "ok": True, "summary": {"image_exists": True}},
                        {"layer": "vision_provider_raw", "ok": False, "summary": {"provider": "dummy"}},
                    ],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = client.get("/panel/inspect_trace", params={"path": str(trace_path)})

    assert response.status_code == 200
    stages = response.json()["data"]["flow_stages"]
    assert [stage["label"] for stage in stages] == ["input_image", "vision_provider_raw"]
    assert stages[0]["status"] == "done"
    assert stages[1]["status"] == "error"


def test_web_panel_inspects_screen_reading_trace(tmp_path) -> None:
    client = TestClient(app)
    trace_path = tmp_path / "screen-reading.json"
    trace_path.write_text(
        json.dumps(
            {
                "success": True,
                "request": {"task": "analyze_ui", "app_name": "demo"},
                "result": {
                    "contract_version": "screen_reading_v1",
                    "image_path": "capture.png",
                    "app_name": "demo",
                    "screen_summary": "dummy page",
                    "state_guess": "dummy_state",
                    "texts": [{"text": "Start"}],
                    "ui": {"summary": {"element_count": 1}, "elements": [{"label": "Start"}]},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = client.get("/panel/inspect_trace", params={"path": str(trace_path)})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["contract"] == "screen_reading_v1"
    assert data["screen_summary"] == "dummy page"
    stage_ids = [stage["id"] for stage in data["flow_stages"]]
    assert "screen" in stage_ids
    assert "click" not in stage_ids
