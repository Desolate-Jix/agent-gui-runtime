from __future__ import annotations

import hashlib

import pytest

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


def _transition_freshness(capture_id: str) -> dict:
    return _freshness(capture_id) | {"viewport_size": {"width": 1000, "height": 700}}


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
    assert result["source_freshness"] == _transition_freshness("capture-list")


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
    assert calls[0][1]["metadata"]["require_current_grounding"] is True
    assert calls[0][1]["metadata"]["capture_lineage"] == {
        "capture_id": "capture-list",
        "screenshot_sha256": _record("capture-list")["observation"]["screenshot_sha256"],
        "viewport": {"width": 1000, "height": 700},
    }
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
    assert result["source_freshness"] == _transition_freshness("capture-list")



def _replay_context() -> dict:
    return {
        "contract_version": "reviewed_workflow_replay_execution_context_v1",
        "asset_content_sha256": "a" * 64,
        "transition_id": "homepage_to_detail",
        "selection_sha256": "b" * 64,
    }


def test_runtime_adapter_propagates_valid_replay_envelope_lineage_and_server_evidence() -> None:
    captures = iter([
        _record("capture-list"),
        _record("capture-detail", interface_id="fixture_detail"),
    ])
    observer = BufferedNavigationRuntimeObserver(
        capture_current=lambda expected_interface_id=None: next(captures)
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
                        "approved_plan_id": "approved-replay",
                        "pre_click_decision": {"allowed": True, "reason": "approved_plan"},
                        "trace_path": "logs/traces/dry-replay.json",
                    }
                },
            }
        return {
            "success": True,
            "data": {
                "result": {
                    "execution_path": {"action_executed": True},
                    "post_click_verification": {"verified": True},
                    "trace_path": "logs/traces/real-replay.json",
                    "evidence_path": "evidence/replay/real.json",
                }
            },
        }

    context = _replay_context()
    adapter = RuntimeNavigationOperationAdapter(
        post_json=post_json, observer=observer, app_name="fixture"
    )
    result = adapter.execute(
        {
            "semantic_action": "open_detail",
            "operation_goal": "Open the reviewed detail.",
            "expected_target_interface_id": "fixture_detail",
            "freshness": _freshness("capture-list") | {"viewport": {"width": 1000, "height": 700}},
            "replay_context": context,
        },
        {"read_state": {}, "choices": []},
    )

    assert len(calls) == 2
    assert calls[0][1]["metadata"]["replay_context"] == context
    assert calls[1][1]["metadata"]["replay_context"] == context
    assert result["replay_context"] == context
    assert result["source_freshness"] == {
        "capture_id": "capture-list",
        "screenshot_sha256": _record("capture-list")["observation"]["screenshot_sha256"],
        "viewport_size": {"width": 1000, "height": 700},
        "trace_path": "logs/traces/capture-list.json",
    }
    assert result["evidence_refs"] == [
        "evidence/replay/real.json",
        "logs/traces/dry-replay.json",
        "logs/traces/real-replay.json",
    ]


def test_runtime_adapter_rejects_invalid_replay_context_before_post() -> None:
    observer = BufferedNavigationRuntimeObserver(
        capture_current=lambda expected_interface_id=None: _record("capture-list")
    )
    assert observer.observe_current()["capture_id"] == "capture-list"
    calls: list[tuple[str, dict]] = []
    adapter = RuntimeNavigationOperationAdapter(
        post_json=lambda path, payload: calls.append((path, payload)) or {},
        observer=observer,
        app_name="fixture",
    )

    with pytest.raises(ValueError, match="invalid reviewed workflow replay context"):
        adapter.execute(
            {
                "semantic_action": "open_detail",
                "operation_goal": "Open the reviewed detail.",
                "freshness": _freshness("capture-list"),
                "replay_context": _replay_context() | {"selection_sha256": "not-a-sha"},
            },
            {"read_state": {}, "choices": []},
        )

    assert calls == []


def test_runtime_adapter_normalizes_replay_source_viewport_from_current_record_fallback() -> None:
    observer = BufferedNavigationRuntimeObserver(
        capture_current=lambda expected_interface_id=None: _record("capture-list")
    )
    assert observer.observe_current()["capture_id"] == "capture-list"
    context = _replay_context()
    adapter = RuntimeNavigationOperationAdapter(
        post_json=lambda path, payload: {
            "success": False,
            "error": {"code": "pre_click_rejected", "details": []},
        },
        observer=observer,
        app_name="fixture",
    )
    result = adapter.execute(
        {
            "semantic_action": "open_detail",
            "operation_goal": "Open the reviewed detail.",
            "freshness": _freshness("capture-list"),
            "replay_context": context,
        },
        {"read_state": {}, "choices": []},
    )

    assert result["replay_context"] == context
    assert result["source_freshness"]["viewport_size"] == {"width": 1000, "height": 700}
    assert "viewport" not in result["source_freshness"]
    assert result["evidence_refs"] == []


def test_runtime_adapter_preserves_safety_rejection_reason_with_replay_envelope() -> None:
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
                "data": {"result": {
                    "approved_plan_id": "approved-stale",
                    "pre_click_decision": {"allowed": True, "reason": "approved_plan"},
                    "trace_path": "logs/traces/dry-stale.json",
                }},
            }
        return {
            "success": False,
            "data": {"trace_path": "logs/traces/real-stale.json"},
            "error": {"code": "stale_approved_plan", "details": "content changed"},
        }

    context = _replay_context()
    adapter = RuntimeNavigationOperationAdapter(
        post_json=post_json, observer=observer, app_name="fixture"
    )
    result = adapter.execute(
        {
            "semantic_action": "open_detail",
            "operation_goal": "Open the reviewed detail.",
            "freshness": _freshness("capture-list"),
            "replay_context": context,
        },
        {"read_state": {}, "choices": []},
    )

    assert result["gate_result"]["reason"] == "stale_approved_plan"
    assert result["replay_context"] == context
    assert result["evidence_refs"] == [
        "logs/traces/dry-stale.json",
        "logs/traces/real-stale.json",
    ]



@pytest.mark.parametrize("action", ["read", "scroll"])
def test_runtime_adapter_blocks_replay_read_and_scroll_before_observe_or_post(action: str) -> None:
    capture_calls = 0
    post_calls: list[tuple[str, dict]] = []

    def capture_current(expected_interface_id=None) -> dict:
        nonlocal capture_calls
        capture_calls += 1
        return _record("unexpected-capture")

    adapter = RuntimeNavigationOperationAdapter(
        post_json=lambda path, payload: post_calls.append((path, payload)) or {},
        observer=BufferedNavigationRuntimeObserver(capture_current=capture_current),
        app_name="fixture",
    )
    context = _replay_context()
    result = adapter.execute(
        {
            "semantic_action": action,
            "freshness": _freshness("capture-list"),
            "replay_context": context,
        },
        {"read_state": {}, "choices": []},
    )

    assert capture_calls == 0
    assert post_calls == []
    assert result == {
        "contract_version": "navigation_reading_operation_result_v1",
        "action_type": action,
        "gate_result": {
            "allowed": False,
            "reason": "unsupported_reviewed_workflow_replay_action",
            "details": {"semantic_action": action},
        },
        "action_dispatched": False,
        "action_executed": False,
        "effect_verified": False,
        "post_action_verified": False,
        "replay_context": context,
        "evidence_refs": [],
    }


def test_runtime_adapter_rejects_malformed_replay_read_before_observe_or_post() -> None:
    capture_calls = 0
    post_calls: list[tuple[str, dict]] = []

    def capture_current(expected_interface_id=None) -> dict:
        nonlocal capture_calls
        capture_calls += 1
        return _record("unexpected-capture")

    adapter = RuntimeNavigationOperationAdapter(
        post_json=lambda path, payload: post_calls.append((path, payload)) or {},
        observer=BufferedNavigationRuntimeObserver(capture_current=capture_current),
        app_name="fixture",
    )

    with pytest.raises(ValueError, match="invalid reviewed workflow replay context"):
        adapter.execute(
            {
                "semantic_action": "read",
                "freshness": _freshness("capture-list"),
                "replay_context": {"contract_version": "bad"},
            },
            {"read_state": {}, "choices": []},
        )

    assert capture_calls == 0
    assert post_calls == []
