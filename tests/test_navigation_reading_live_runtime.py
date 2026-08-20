from __future__ import annotations

import hashlib

from app.agent.navigation_reading_live_runtime import (
    BufferedNavigationRuntimeObserver,
    RuntimeNavigationOperationAdapter,
)
from app.operation.reading import build_read_region_batch_report


def _record(
    capture_id: str,
    *,
    interface_id: str = "fixture_list",
    reached_bottom: bool = False,
) -> dict:
    return {
        "contract_version": "navigation_runtime_observation_record_v1",
        "observation": {
            "contract_version": "current_interface_observation_v1",
            "interface_id": interface_id,
            "surface_type": "content_collection",
            "capture_id": capture_id,
            "screenshot_sha256": hashlib.sha256(
                capture_id.encode("utf-8")
            ).hexdigest(),
            "trace_path": f"logs/traces/{capture_id}.json",
        },
        "image_path": f"artifacts/screenshots/{capture_id}.png",
        "window_size": {"width": 1000, "height": 700},
        "ocr_result": {
            "items": [
                {"text": f"Visible content {capture_id}"},
            ]
        },
        "resolved_read_targets": {
            "fixture_list:items": {
                "target_container_id": "fixture_list:items",
                "bbox": {"x": 120, "y": 150, "w": 700, "h": 480},
                "scroll_scope": "page",
                "target_pane": "page",
            }
        },
        "reached_bottom": reached_bottom,
    }


def _plan(action: str, capture_id: str, *, content_id: str | None = None) -> dict:
    return {
        "semantic_action": action,
        "content_id": content_id,
        "goal": "Read the fixture.",
        "freshness": _record(capture_id)["observation"]
        | {"interface_id": None, "surface_type": None, "contract_version": None},
    }


def _freshness(capture_id: str) -> dict:
    observation = _record(capture_id)["observation"]
    return {
        "capture_id": observation["capture_id"],
        "screenshot_sha256": observation["screenshot_sha256"],
        "trace_path": observation["trace_path"],
    }


def test_runtime_adapter_merges_current_read_evidence() -> None:
    observer = BufferedNavigationRuntimeObserver(
        capture_current=lambda expected_interface_id=None: _record("capture-1")
    )
    assert observer.observe_current()["capture_id"] == "capture-1"
    calls: list[tuple[str, dict]] = []

    def post_json(path: str, payload: dict) -> dict:
        calls.append((path, payload))
        return {
            "success": True,
            "data": {
                "contract_version": "read_region_batch_v1",
                "stop_reason": "captures_exhausted",
                "reached_bottom": False,
                "wrong_scope_detected": False,
                "unique_line_count": 1,
                "merged_text_lines": ["Visible content capture-1"],
                "trace_path": "logs/traces/read-1.json",
            },
        }

    adapter = RuntimeNavigationOperationAdapter(
        post_json=post_json,
        observer=observer,
        app_name="fixture",
    )
    result = adapter.execute(
        {
            "semantic_action": "read",
            "content_id": "fixture_list:items",
            "freshness": _freshness("capture-1"),
        },
        {
            "read_state": {},
            "choices": [
                {
                    "choice_id": "read:fixture_list:items",
                    "content_id": "fixture_list:items",
                    "max_scrolls": 3,
                }
            ],
        },
    )

    assert calls[0][0] == "/execute/read_region_batch"
    assert calls[0][1]["captures"][0]["ocr_result"]["items"]
    assert result["gate_result"]["allowed"] is True
    assert result["effect_verified"] is True
    assert result["source_freshness"] == _freshness("capture-1")


def test_runtime_adapter_scrolls_current_target_and_prefetches_observation() -> None:
    captures = iter(
        [
            _record("capture-before"),
            _record("capture-after", reached_bottom=True),
        ]
    )
    expected_interface_ids: list[str | None] = []

    def capture_current(*, expected_interface_id: str | None = None) -> dict:
        expected_interface_ids.append(expected_interface_id)
        return next(captures)

    observer = BufferedNavigationRuntimeObserver(capture_current=capture_current)
    assert observer.observe_current()["capture_id"] == "capture-before"
    calls: list[tuple[str, dict]] = []

    def post_json(path: str, payload: dict) -> dict:
        calls.append((path, payload))
        if path == "/action/scroll":
            return {
                "success": True,
                "data": {
                    "result": {
                        "precondition_decision": {"decision": "ALLOW"},
                        "execution_path": {"action_executed": True},
                        "scroll_effect_validation": {
                            "status": "moved",
                            "target_container_content_changed": True,
                            "wrong_scope_detected": False,
                        },
                        "trace_path": "logs/traces/scroll-1.json",
                    }
                },
            }
        return {
            "success": True,
            "data": {
                "contract_version": "read_region_batch_v1",
                "stop_reason": "reached_bottom",
                "reached_bottom": True,
                "wrong_scope_detected": False,
                "unique_line_count": 2,
                "merged_text_lines": [
                    "Visible content capture-before",
                    "Visible content capture-after",
                ],
                "trace_path": "logs/traces/read-2.json",
            },
        }

    adapter = RuntimeNavigationOperationAdapter(
        post_json=post_json,
        observer=observer,
        app_name="fixture",
    )
    result = adapter.execute(
        {
            "semantic_action": "scroll",
            "freshness": _freshness("capture-before"),
        },
        {
            "read_state": {
                "content_id": "fixture_list:items",
                "max_scrolls": 3,
            },
            "choices": [],
        },
    )

    assert [path for path, _payload in calls] == [
        "/action/scroll",
        "/execute/read_region_batch",
    ]
    scroll_payload = calls[0][1]
    assert scroll_payload["scroll_scope"] == "page"
    assert scroll_payload["coordinate_window_size"] == {
        "width": 1000,
        "height": 700,
    }
    assert scroll_payload["container_bbox"] == {
        "x": 120,
        "y": 150,
        "width": 700,
        "height": 480,
    }
    assert result["action_dispatched"] is True
    assert result["effect_verified"] is True
    assert result["read_report"]["reached_bottom"] is True
    assert observer.observe_current()["capture_id"] == "capture-after"
    assert expected_interface_ids == [None, "fixture_list"]


def test_runtime_adapter_does_not_treat_dispatch_without_new_items_as_effect() -> None:
    captures = iter(
        [
            _record("capture-before"),
            _record("capture-after"),
        ]
    )
    observer = BufferedNavigationRuntimeObserver(
        capture_current=lambda expected_interface_id=None: next(captures)
    )
    assert observer.observe_current()["capture_id"] == "capture-before"

    def post_json(path: str, payload: dict) -> dict:
        if path == "/action/scroll":
            return {
                "success": True,
                "data": {
                    "result": {
                        "precondition_decision": {"decision": "ALLOW"},
                        "execution_path": {"action_executed": True},
                        "scroll_effect_validation": {
                            "status": "moved",
                            "target_container_content_changed": True,
                            "wrong_scope_detected": False,
                        },
                        "trace_path": "logs/traces/scroll-no-new.json",
                    }
                },
            }
        return {
            "success": True,
            "data": {
                "contract_version": "read_region_batch_v1",
                "stop_reason": "no_new_content",
                "reached_bottom": False,
                "wrong_scope_detected": False,
                "unique_line_count": 1,
                "new_item_observations": [],
                "captures": [
                    {"scroll_dispatch_success": None, "scroll_effect_success": None},
                    {"scroll_dispatch_success": True, "scroll_effect_success": False},
                ],
                "merged_text_lines": ["Same visible job"],
                "trace_path": "logs/traces/read-no-new.json",
            },
        }

    adapter = RuntimeNavigationOperationAdapter(
        post_json=post_json,
        observer=observer,
        app_name="fixture",
    )
    result = adapter.execute(
        {
            "semantic_action": "scroll",
            "freshness": _freshness("capture-before"),
        },
        {
            "read_state": {
                "content_id": "fixture_list:items",
                "max_scrolls": 3,
            },
            "choices": [],
        },
    )

    assert result["action_dispatched"] is True
    assert result["effect_verified"] is False
    assert result["scroll_dispatch_success"] is True
    assert result["scroll_effect_success"] is False


def test_runtime_adapter_propagates_wrong_scope_into_read_batch() -> None:
    before = _record("capture-before")
    before["item_fingerprints"] = ["job-a"]
    after = _record("capture-after")
    after["item_fingerprints"] = ["job-a", "job-b"]
    captures = iter([before, after])
    observer = BufferedNavigationRuntimeObserver(
        capture_current=lambda expected_interface_id=None: next(captures)
    )
    assert observer.observe_current()["capture_id"] == "capture-before"
    read_payloads: list[dict] = []

    def post_json(path: str, payload: dict) -> dict:
        if path == "/action/scroll":
            return {
                "success": True,
                "data": {
                    "result": {
                        "precondition_decision": {"decision": "ALLOW"},
                        "execution_path": {"action_executed": True},
                        "scroll_effect_validation": {
                            "status": "wrong_scope_detected",
                            "target_container_content_changed": True,
                            "wrong_scope_detected": True,
                        },
                        "trace_path": "logs/traces/scroll-wrong-scope.json",
                    }
                },
            }
        read_payloads.append(payload)
        report = build_read_region_batch_report(
            target_container_id=payload["target_container_id"],
            target_bbox=payload["target_bbox"],
            captures=payload["captures"],
            max_captures=payload["max_captures"],
            stop_after_no_new_content=payload["stop_after_no_new_content"],
            wrong_scope_detected=payload["wrong_scope_detected"],
        )
        return {"success": True, "data": report}

    adapter = RuntimeNavigationOperationAdapter(
        post_json=post_json,
        observer=observer,
        app_name="fixture",
    )
    read_result = adapter.execute(
        {
            "semantic_action": "read",
            "content_id": "fixture_list:items",
            "freshness": _freshness("capture-before"),
        },
        {"read_state": {}, "choices": []},
    )
    assert read_result["effect_verified"] is True

    result = adapter.execute(
        {
            "semantic_action": "scroll",
            "freshness": _freshness("capture-before"),
        },
        {
            "read_state": {
                "content_id": "fixture_list:items",
                "max_scrolls": 3,
            },
            "choices": [],
        },
    )

    latest_capture = read_payloads[-1]["captures"][-1]
    assert latest_capture["scroll_dispatched"] is True
    assert latest_capture["wrong_scope_detected"] is True
    assert latest_capture["item_fingerprints"] == ["job-a", "job-b"]
    assert result["read_report"]["stop_reason"] == "wrong_scope_detected"
    assert result["scroll_effect_success"] is False


def test_runtime_adapter_uses_dry_run_approval_before_real_click() -> None:
    captures = iter(
        [
            _record("capture-list"),
            _record("capture-detail", interface_id="fixture_detail"),
        ]
    )
    expected_interface_ids: list[str | None] = []

    def capture_current(expected_interface_id=None):
        expected_interface_ids.append(expected_interface_id)
        return next(captures)

    observer = BufferedNavigationRuntimeObserver(capture_current=capture_current)
    assert observer.observe_current()["capture_id"] == "capture-list"
    calls: list[tuple[str, dict]] = []

    def post_json(path: str, payload: dict) -> dict:
        calls.append((path, payload))
        assert path == "/action/execute_recognition_plan"
        if payload["dry_run"]:
            return {
                "success": True,
                "data": {
                    "result": {
                        "approved_plan_id": "approved-1",
                        "pre_click_decision": {
                            "allowed": True,
                            "reason": "target_unambiguous",
                        },
                        "trace_path": "logs/traces/dry.json",
                    }
                },
            }
        assert payload["approved_plan_id"] == "approved-1"
        return {
            "success": True,
            "data": {
                "result": {
                    "execution_path": {"action_executed": True},
                    "post_click_verification": {"verified": True},
                    "trace_path": "logs/traces/click.json",
                }
            },
        }

    adapter = RuntimeNavigationOperationAdapter(
        post_json=post_json,
        observer=observer,
        app_name="fixture",
    )
    result = adapter.execute(
        {
            "semantic_action": "open_detail",
            "goal": "Open the selected report.",
            "operation_goal": "Open the Atlas report",
            "expected_target_interface_id": "fixture_detail",
            "freshness": _freshness("capture-list"),
        },
        {
            "interface": {
                "interface_id": "job_detail",
                "surface_type": "job_detail_apply_entry",
            },
            "active_flow_started": False,
            "read_state": {},
            "choices": [],
        },
    )

    assert len(calls) == 2
    assert calls[0][1]["dry_run"] is True
    assert calls[0][1]["goal"] == "Open the Atlas report"
    assert calls[0][1]["metadata"]["forbid_final_submit"] is True
    assert calls[0][1]["metadata"]["surface_context"] == "job_detail_apply_entry"
    assert calls[0][1]["metadata"]["source_interface_id"] == "job_detail"
    assert calls[0][1]["metadata"]["active_flow_started"] is False
    assert calls[1][1]["dry_run"] is False
    assert result["gate_result"]["allowed"] is True
    assert result["action_executed"] is True
    assert result["post_action_verified"] is True
    assert observer.observe_current()["interface_id"] == "fixture_detail"
    assert expected_interface_ids == [None, "fixture_detail"]


def test_runtime_adapter_reports_pre_click_rejection_as_safe_gate_result() -> None:
    observer = BufferedNavigationRuntimeObserver(
        capture_current=lambda expected_interface_id=None: _record("capture-list")
    )
    assert observer.observe_current()["capture_id"] == "capture-list"
    calls: list[tuple[str, dict]] = []

    def post_json(path: str, payload: dict) -> dict:
        calls.append((path, payload))
        return {
            "success": False,
            "error": {
                "code": "pre_click_rejected",
                "details": [
                    "no_candidate_passed_pre_click_checks",
                    "top_candidate_margin_too_small",
                ],
            },
        }

    adapter = RuntimeNavigationOperationAdapter(
        post_json=post_json,
        observer=observer,
        app_name="fixture",
    )
    result = adapter.execute(
        {
            "semantic_action": "open_detail",
            "operation_goal": "Open the Atlas report",
            "freshness": _freshness("capture-list"),
        },
        {"read_state": {}, "choices": []},
    )

    assert len(calls) == 1
    assert calls[0][1]["dry_run"] is True
    assert result["contract_version"] == "navigation_reading_operation_result_v1"
    assert result["gate_result"] == {
        "allowed": False,
        "reason": "pre_click_rejected",
        "details": [
            "no_candidate_passed_pre_click_checks",
            "top_candidate_margin_too_small",
        ],
    }
    assert result["action_executed"] is False
    assert result["post_action_verified"] is False
    assert result["source_freshness"] == _freshness("capture-list")


def test_runtime_adapter_reports_foreground_verification_failure_as_safe_intercept() -> None:
    observer = BufferedNavigationRuntimeObserver(
        capture_current=lambda expected_interface_id=None: _record("capture-list")
    )
    assert observer.observe_current()["capture_id"] == "capture-list"
    calls: list[tuple[str, dict]] = []

    def post_json(path: str, payload: dict) -> dict:
        calls.append((path, payload))
        if payload["dry_run"]:
            return {
                "success": True,
                "data": {
                    "result": {
                        "approved_plan_id": "approved-foreground",
                        "pre_click_decision": {
                            "allowed": True,
                            "reason": "target_unambiguous",
                        },
                        "trace_path": "logs/traces/dry-foreground.json",
                    }
                },
            }
        return {
            "success": False,
            "data": {
                "execution_path": {"action_executed": False},
                "trace_path": "logs/traces/click-foreground.json",
            },
            "error": {
                "code": "recognition_plan_click_failed",
                "details": (
                    "Bound window foreground verification failed: "
                    "expected_handle=3016730, actual_foreground_handle=67344"
                ),
            },
        }

    adapter = RuntimeNavigationOperationAdapter(
        post_json=post_json,
        observer=observer,
        app_name="fixture",
    )
    result = adapter.execute(
        {
            "semantic_action": "continue_next_step",
            "operation_goal": "Open workflow summary",
            "freshness": _freshness("capture-list"),
        },
        {"read_state": {}, "choices": []},
    )

    assert len(calls) == 2
    assert calls[0][1]["dry_run"] is True
    assert calls[1][1]["dry_run"] is False
    assert result["gate_result"] == {
        "allowed": False,
        "reason": "foreground_window_changed",
        "details": {
            "code": "recognition_plan_click_failed",
            "message": (
                "Bound window foreground verification failed: "
                "expected_handle=3016730, actual_foreground_handle=67344"
            ),
            "trace_path": "logs/traces/click-foreground.json",
        },
    }
    assert result["action_executed"] is False
    assert result["post_action_verified"] is False
    assert result["source_freshness"] == _freshness("capture-list")
