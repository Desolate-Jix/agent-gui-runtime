from __future__ import annotations

import json
from pathlib import Path

from app.core import runtime_artifacts


def test_build_screenshot_path_uses_purpose_and_roi(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(runtime_artifacts, "SCREENSHOTS_DIR", tmp_path / "screenshots")
    monkeypatch.setattr(runtime_artifacts, "timestamp_label", lambda: "20260504-190000-000001")

    path = runtime_artifacts.build_screenshot_path(
        title="MouseTester.cn - Microsoft Edge",
        process_name="msedge.exe",
        handle=123,
        purpose="click_text_scan",
        roi={"x": 720, "y": 340, "width": 1076, "height": 900},
        name_hint="点击开始检测",
    )

    assert path.parent == tmp_path / "screenshots"
    assert "mousetester-cn-microsoft-edge" in path.name
    assert "click-text-scan" in path.name
    assert "roi-x720-y340-w1076-h900" in path.name
    assert path.name.endswith(".png")


def test_write_trace_writes_json(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(runtime_artifacts, "TRACES_DIR", tmp_path / "traces")
    monkeypatch.setattr(runtime_artifacts, "timestamp_label", lambda: "20260504-190000-000002")

    path = runtime_artifacts.write_trace(
        category="vision",
        operation="layer_trace",
        payload={"success": True, "result": {"final_ok": True}},
        name_hint="demo",
    )

    saved = Path(path)
    assert saved.exists()
    assert saved.parent == tmp_path / "traces" / "vision"

    payload = json.loads(saved.read_text(encoding="utf-8"))
    assert payload["success"] is True
    assert payload["result"]["final_ok"] is True


def test_write_trace_limits_long_name_hint(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(runtime_artifacts, "TRACES_DIR", tmp_path / "traces")
    monkeypatch.setattr(runtime_artifacts, "timestamp_label", lambda: "20260504-190000-000003")
    long_title = "Software Engineer Jobs in All Auckland Job Vacancies Jun 2026 SEEK Microsoft Edge " * 8

    path = runtime_artifacts.write_trace(
        category="vision",
        operation="render_recognition_plan_overlay",
        payload={"success": True},
        name_hint=long_title,
    )

    saved = Path(path)
    assert saved.exists()
    assert len(saved.name) < 180
    assert saved.name.startswith("20260504-190000-000003__render-recognition-plan-overlay__software-engineer")


def test_runtime_timer_records_steps() -> None:
    timer = runtime_artifacts.RuntimeTimer()

    with timer.step("demo_step", stage="demo"):
        pass

    payload = timer.to_dict()
    assert payload["contract_version"] == "runtime_timing_v1"
    assert payload["total_ms"] >= 0
    assert payload["steps"][0]["name"] == "demo_step"
    assert payload["steps"][0]["stage"] == "demo"
    assert payload["steps"][0]["elapsed_ms"] >= 0
