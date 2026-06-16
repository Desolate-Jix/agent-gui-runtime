from __future__ import annotations

import importlib.util
import json
from pathlib import Path


RUNNER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "execute_smoke_runner.py"
spec = importlib.util.spec_from_file_location("execute_smoke_runner", RUNNER_PATH)
assert spec is not None and spec.loader is not None
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def _case(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "id": "demo_click",
                "app": {"app_name": "edge"},
                "goal": "Click Demo",
                "expect": {"allow": True, "action_type": "click", "max_attempt_count": 2},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _dry_response() -> dict:
    return {
        "success": True,
        "message": "Dry-run ready",
        "data": {
            "result": {
                "approved_plan_id": "approved-1",
                "trace_path": "logs/traces/actions/dry.json",
                "agent_step_result": {
                    "status": "dry_run_ready",
                    "goal": "Click Demo",
                    "approved_plan_id": "approved-1",
                    "selected_click_point": {"x": 10, "y": 20},
                    "next_agent_action": "execute_approved_plan",
                    "evidence": {
                        "recognition_plan_trace_path": "logs/traces/vision/plan.json",
                        "coordinate_overlay_path": "artifacts/review-overlays/plan.png",
                    },
                },
                "model_io": {"attempt_count": 1},
            }
        },
    }


def _real_response() -> dict:
    return {
        "success": True,
        "message": "Clicked",
        "data": {
            "result": {
                "trace_path": "logs/traces/actions/click.json",
                "agent_step_result": {
                    "status": "verified",
                    "goal": "Click Demo",
                    "selected_click_point": {"x": 10, "y": 20},
                    "next_agent_action": "done",
                    "post_click": {"success": True},
                },
                "model_io": {"attempt_count": 1},
            }
        },
    }


def test_runner_defaults_to_dry_run_and_writes_jsonl(tmp_path, monkeypatch) -> None:
    case_path = tmp_path / "case.json"
    out_path = tmp_path / "results.jsonl"
    _case(case_path)
    calls: list[tuple[str, dict]] = []

    def fake_post(base_url, endpoint, payload, timeout):
        calls.append((endpoint, payload))
        assert payload["dry_run"] is True
        return _dry_response()

    monkeypatch.setattr(runner, "_post_json", fake_post)

    code = runner.main(["--case", str(case_path), "--out", str(out_path)])

    assert code == 0
    assert [endpoint for endpoint, _ in calls] == ["/action/execute_recognition_plan"]
    row = json.loads(out_path.read_text(encoding="utf-8"))
    assert row["contract_version"] == "execute_smoke_result_v1"
    assert row["case_id"] == "demo_click"
    assert row["dry_run"] is True
    assert row["executed"] is False
    assert row["pass"] is True
    assert row["allowed"] is True
    assert row["dry_run_latency_ms"] == row["latency_ms"]
    assert row["attempt_count"] == 1


def test_runner_can_open_app_before_execute(tmp_path, monkeypatch) -> None:
    case_path = tmp_path / "case.json"
    out_path = tmp_path / "results.jsonl"
    case_path.write_text(
        json.dumps(
            {
                "id": "open_then_click",
                "app": {
                    "app_name": "edge",
                    "app_id": "edge",
                    "url": "file:///D:/agent-gui-runtime/app/web_panel/seek_resume_fixture.html",
                    "window_title_contains": "SEEK Resume Screening Fixture",
                    "open_before": True,
                    "wait_seconds": 0,
                },
                "goal": "Click Shortlist Avery Chen",
                "expect": {"allow": True, "action_type": "click", "max_attempt_count": 2},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calls: list[tuple[str, dict]] = []

    def fake_post(base_url, endpoint, payload, timeout):
        calls.append((endpoint, payload))
        if endpoint == "/apps/open":
            assert payload["app_id"] == "edge"
            assert payload["url"].endswith("seek_resume_fixture.html")
            assert payload["title"] == "SEEK Resume Screening Fixture"
            return {"success": True, "message": "App open requested", "data": {"bound_window": {"title": "fixture"}}}
        assert endpoint == "/action/execute_recognition_plan"
        return _dry_response()

    monkeypatch.setattr(runner, "_post_json", fake_post)

    code = runner.main(["--case", str(case_path), "--out", str(out_path)])

    assert code == 0
    assert [endpoint for endpoint, _ in calls] == ["/apps/open", "/action/execute_recognition_plan"]
    row = json.loads(out_path.read_text(encoding="utf-8"))
    assert row["open_success"] is True
    assert row["bind_success"] is None


def test_runner_can_resize_bound_window_before_execute(tmp_path, monkeypatch) -> None:
    case_path = tmp_path / "case.json"
    out_path = tmp_path / "results.jsonl"
    case_path.write_text(
        json.dumps(
            {
                "id": "resize_then_click",
                "app": {
                    "app_name": "edge",
                    "app_id": "edge",
                    "url": "https://example.com",
                    "window_title_contains": "Example",
                    "open_before": True,
                    "wait_seconds": 0,
                    "resize_before": {"width": 1100, "height": 900, "left": 20, "top": 20},
                },
                "goal": "Click Demo",
                "expect": {"allow": True, "action_type": "click", "max_attempt_count": 2},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calls: list[tuple[str, dict]] = []

    def fake_post(base_url, endpoint, payload, timeout):
        calls.append((endpoint, payload))
        if endpoint == "/apps/open":
            return {"success": True, "message": "App open requested", "data": {"bound_window": {"title": "Example"}}}
        if endpoint == "/session/resize_bound_window":
            assert payload == {"width": 1100, "height": 900, "left": 20, "top": 20, "focus": True}
            return {"success": True, "message": "Bound window resized", "data": {"after": {"rect": {}}}}
        assert endpoint == "/action/execute_recognition_plan"
        return _dry_response()

    monkeypatch.setattr(runner, "_post_json", fake_post)

    code = runner.main(["--case", str(case_path), "--out", str(out_path)])

    assert code == 0
    assert [endpoint for endpoint, _ in calls] == [
        "/apps/open",
        "/session/resize_bound_window",
        "/action/execute_recognition_plan",
    ]
    row = json.loads(out_path.read_text(encoding="utf-8"))
    assert row["resize_success"] is True


def test_runner_stops_when_resize_fails(monkeypatch) -> None:
    case = {
        "id": "resize_fail",
        "app": {
            "app_name": "edge",
            "process_name": "msedge.exe",
            "resize_before": {"width": 1100, "height": 900},
        },
        "goal": "Click Demo",
        "expect": {"allow": True},
    }
    calls: list[str] = []

    def fake_post(base_url, endpoint, payload, timeout):
        calls.append(endpoint)
        if endpoint == "/session/bind_window":
            return {"success": True, "message": "Window bound", "data": {"bound": True}}
        if endpoint == "/session/resize_bound_window":
            return {"success": False, "message": "Failed to resize bound window", "error": {"code": "window_resize_failed"}}
        raise AssertionError("Execute API should not be called after resize failure")

    monkeypatch.setattr(runner, "_post_json", fake_post)

    row = runner.run_case(case, base_url="http://runtime", execute=False, timeout=1)

    assert calls == ["/session/bind_window", "/session/resize_bound_window"]
    assert row["pass"] is False
    assert row["status"] == "resize_failed"
    assert row["fail_reasons"] == ["resize_window_failed"]


def test_runner_repeat_runs_case_set_multiple_times(tmp_path, monkeypatch) -> None:
    case_path = tmp_path / "case.json"
    out_path = tmp_path / "results.jsonl"
    _case(case_path)
    calls: list[tuple[str, dict]] = []

    def fake_post(base_url, endpoint, payload, timeout):
        calls.append((endpoint, payload))
        return _dry_response()

    monkeypatch.setattr(runner, "_post_json", fake_post)

    code = runner.main(["--case", str(case_path), "--out", str(out_path), "--repeat", "2"])

    assert code == 0
    assert [endpoint for endpoint, _ in calls] == [
        "/action/execute_recognition_plan",
        "/action/execute_recognition_plan",
    ]
    rows = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines()]
    assert [row["repeat_index"] for row in rows] == [1, 2]
    assert {row["repeat_count"] for row in rows} == {2}


def test_runner_execute_reuses_approved_plan_only_with_execute_flag(tmp_path, monkeypatch) -> None:
    case_path = tmp_path / "case.json"
    out_path = tmp_path / "results.jsonl"
    _case(case_path)
    calls: list[tuple[str, dict]] = []

    def fake_post(base_url, endpoint, payload, timeout):
        calls.append((endpoint, payload))
        if len(calls) == 1:
            assert payload["dry_run"] is True
            return _dry_response()
        assert payload["dry_run"] is False
        assert payload["approved_plan_id"] == "approved-1"
        return _real_response()

    monkeypatch.setattr(runner, "_post_json", fake_post)

    code = runner.main(["--case", str(case_path), "--out", str(out_path), "--execute"])

    assert code == 0
    assert [endpoint for endpoint, _ in calls] == [
        "/action/execute_recognition_plan",
        "/action/execute_recognition_plan",
    ]
    row = json.loads(out_path.read_text(encoding="utf-8"))
    assert row["dry_run"] is False
    assert row["executed"] is True
    assert row["dry_run_latency_ms"] >= 0
    assert row["execute_latency_ms"] >= 0
    assert row["dry_run_trace_path"] == "logs/traces/actions/dry.json"
    assert row["post_click_verification"]["success"] is True
    assert row["pass"] is True


def test_runner_fails_when_click_point_is_outside_expected_rect(tmp_path, monkeypatch) -> None:
    case_path = tmp_path / "case.json"
    out_path = tmp_path / "results.jsonl"
    case_path.write_text(
        json.dumps(
            {
                "id": "demo_click",
                "app": {"app_name": "edge"},
                "goal": "Click Demo",
                "expect": {
                    "allow": True,
                    "action_type": "click",
                    "point_in_rect": {"min_x": 100, "max_x": 200, "min_y": 100, "max_y": 200},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_post(base_url, endpoint, payload, timeout):
        return _dry_response()

    monkeypatch.setattr(runner, "_post_json", fake_post)

    code = runner.main(["--case", str(case_path), "--out", str(out_path)])

    assert code == 1
    row = json.loads(out_path.read_text(encoding="utf-8"))
    assert row["pass"] is False
    assert any(reason.startswith("point_outside_rect") for reason in row["fail_reasons"])


def test_runner_stops_when_requested_bind_fails(monkeypatch) -> None:
    case = {
        "id": "bind_fail",
        "app": {"process_name": "missing.exe"},
        "goal": "Click Demo",
        "expect": {"allow": True},
    }
    calls: list[str] = []

    def fake_post(base_url, endpoint, payload, timeout):
        calls.append(endpoint)
        if endpoint == "/session/bind_window":
            return {"success": False, "message": "Window not found", "error": {"code": "window_not_found"}}
        raise AssertionError("Execute API should not be called after bind failure")

    monkeypatch.setattr(runner, "_post_json", fake_post)

    row = runner.run_case(case, base_url="http://runtime", execute=False, timeout=1)

    assert calls == ["/session/bind_window"]
    assert row["pass"] is False
    assert row["status"] == "bind_failed"
    assert row["fail_reasons"] == ["bind_window_failed"]


def test_runner_refuses_destructive_case_with_execute(tmp_path) -> None:
    case = {"id": "danger", "goal": "Delete item", "mode": {"destructive": True}}

    try:
        runner.run_case(case, base_url="http://runtime", execute=True, timeout=1)
    except runner.SmokeRunnerError as exc:
        assert "destructive" in str(exc)
    else:
        raise AssertionError("Expected destructive execute case to be refused")
