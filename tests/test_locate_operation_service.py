from __future__ import annotations

from typing import Any

from app.operation.locate.contracts import (
    LocateRecognitionPlanResult,
    LocateSingleTargetTaskInput,
)
from app.operation.locate.service import run_single_target_locate


def _task(**overrides: Any) -> LocateSingleTargetTaskInput:
    payload: dict[str, Any] = {
        "goal": "click home",
        "image_path": "screen.png",
        "live_capture": {"image_path": "screen.png"},
        "metadata": {
            "prompt_overrides": {"additional_rules": "keep this rule"},
        },
        "operation_context": {
            "contract_version": "operation_runtime_context_v1",
            "skill_id": "locate_element",
            "semantic_action": "locate_element",
            "capture_id": "screen.png",
            "viewport_size": {"width": 1280, "height": 720},
            "requires_gate": False,
        },
        "observe_reuse": {
            "status": "ready",
            "trace_path": "observe.json",
            "anchor_source": "observe_trace",
        },
    }
    payload.update(overrides)
    return LocateSingleTargetTaskInput.model_validate(payload)


def test_single_target_locate_returns_no_click_evidence() -> None:
    captured: dict[str, Any] = {}

    def recognition_runner(request):
        captured["request"] = request
        return LocateRecognitionPlanResult(
            success=True,
            message="ok",
            payload={
                "pre_click_decision": {
                    "allowed": True,
                    "selected_click_point": {"x": 10, "y": 20},
                },
                "recommended_target": {
                    "label": "home",
                    "element": {
                        "bbox": {"x": 4, "y": 14, "w": 12, "h": 12},
                        "click_point": {"x": 10, "y": 20},
                    },
                },
                "execution_path": {"ocr_anchor_grounding_used": True},
            },
        )

    result = run_single_target_locate(
        _task(),
        recognition_plan_runner=recognition_runner,
        path_map_review_builder=lambda **_kwargs: {
            "contract_version": "path_map_review_v1",
            "status": "skipped",
        },
    )

    assert result.outcome == "completed"
    assert result.failure is None
    assert captured["request"].metadata["ocr_anchors"] == {
        "enabled": True,
        "max_anchors": "all",
    }
    assert captured["request"].metadata["prompt_overrides"] == {
        "additional_rules": "keep this rule"
    }
    payload = result.payload
    assert payload["contract_version"] == "target_location_v1"
    assert payload["located_bbox"] == {"x": 4, "y": 14, "w": 12, "h": 12}
    assert payload["located_point"] == {"x": 10, "y": 20}
    assert payload["location_status"] == "pre_click_verified"
    assert payload["execution_path"]["action_executed"] is False
    assert (
        payload["execution_path"]["agent_must_call_for_click"]
        == "POST /action/execute_recognition_plan"
    )


def test_single_target_locate_keeps_rejected_candidate_for_review_only() -> None:
    result = run_single_target_locate(
        _task(),
        recognition_plan_runner=lambda _request: LocateRecognitionPlanResult(
            success=True,
            message="ok",
            payload={
                "pre_click_decision": {
                    "allowed": False,
                    "selected_click_point": None,
                },
                "recommended_target": None,
                "candidate_result": {
                    "candidates": [],
                    "rejected": [
                        {
                            "candidate_id": "review_target",
                            "element": {
                                "bbox": {
                                    "x": 53,
                                    "y": 425,
                                    "w": 172,
                                    "h": 21,
                                },
                                "click_point": {"x": 139, "y": 436},
                            },
                        }
                    ],
                },
            },
        ),
        path_map_review_builder=lambda **_kwargs: {
            "contract_version": "path_map_review_v1",
            "status": "skipped",
        },
    )

    assert result.outcome == "completed"
    assert result.payload["recommended_target"]["candidate_id"] == "review_target"
    assert result.payload["located_point"] == {"x": 139, "y": 436}
    assert result.payload["location_status"] == "requires_pre_click_confirmation"
    assert result.payload["execution_path"]["action_executed"] is False
    assert (
        result.payload["execution_path"]["located_coordinate_source"]
        == "candidate_result.rejected[0]"
    )


def test_single_target_locate_preserves_recognition_failure() -> None:
    result = run_single_target_locate(
        _task(),
        recognition_plan_runner=lambda _request: LocateRecognitionPlanResult(
            success=False,
            message="Recognition plan failed",
            payload={"trace_path": "recognition-failure.json"},
            error={"code": "recognition_plan_failed", "details": "bad output"},
        ),
        path_map_review_builder=lambda **_kwargs: {},
    )

    assert result.outcome == "failed"
    assert result.failure is not None
    assert result.failure.code == "recognition_plan_failed"
    assert result.failure.details == "bad output"
    assert result.payload["upstream_message"] == "Recognition plan failed"
    assert result.payload["upstream_data"] == {
        "trace_path": "recognition-failure.json"
    }
    assert result.payload["upstream_error"] == {
        "code": "recognition_plan_failed",
        "details": "bad output",
    }
