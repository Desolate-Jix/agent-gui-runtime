from __future__ import annotations

import json

from app.evaluation.mousetester_trace_eval import MouseTesterEvalCase, evaluate_cases


def test_mousetester_trace_eval_scores_action_trace(tmp_path) -> None:
    trace = tmp_path / "action.json"
    trace.write_text(
        json.dumps(
            {
                "success": True,
                "result": {
                    "recognition_plan": {
                        "goal": "点击此处测试",
                        "recommended_target": {"label": "双击测试 点击此处测试", "score": 0.8},
                        "pre_click_decision": {"allowed": True, "selected_click_point": {"x": 10, "y": 20}},
                    },
                    "execution_path": {"action_executed": True, "retry_count": 1},
                    "semantic_post_click_verification": {"applicable": True, "verified": True},
                    "attempts": [{"verified": False}, {"verified": True}],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    report = evaluate_cases(
        [
            MouseTesterEvalCase(
                case_id="success",
                trace_path=str(trace),
                expected_goal="点击此处测试",
                expected_label_contains="点击此处测试",
                expected_pre_click_allowed=True,
                expected_action_executed=True,
                expected_success=True,
                expected_semantic_verified=True,
            )
        ],
        root=tmp_path,
    )

    assert report["summary"]["passed_case_count"] == 1
    assert report["summary"]["pass_rate"] == 1.0
    assert report["results"][0]["facts"]["retry_count"] == 1
    assert report["results"][0]["checks"]["top1_label_contains"]["passed"] is True


def test_mousetester_trace_eval_reports_failed_expectation_and_missing_case(tmp_path) -> None:
    trace = tmp_path / "recognition.json"
    trace.write_text(
        json.dumps(
            {
                "success": True,
                "result": {
                    "goal": "点击此处测试",
                    "recommended_target": {"label": "鼠标测试 导航", "score": 0.4},
                    "pre_click_decision": {"allowed": False, "reasons": ["no_candidate_passed_pre_click_checks"]},
                    "execution_path": {"action_executed": False},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = evaluate_cases(
        [
            MouseTesterEvalCase(
                case_id="wrong_top1",
                trace_path=str(trace),
                expected_goal="点击此处测试",
                expected_label_contains="点击此处测试",
                expected_pre_click_allowed=True,
            ),
            MouseTesterEvalCase(case_id="missing", trace_path="missing.json", expected_success=True),
        ],
        root=tmp_path,
    )

    assert report["summary"]["case_count"] == 2
    assert report["summary"]["present_case_count"] == 1
    assert report["summary"]["missing_case_count"] == 1
    assert report["summary"]["passed_case_count"] == 0
    assert report["results"][0]["checks"]["top1_label_contains"]["passed"] is False
    assert report["results"][0]["checks"]["pre_click_allowed"]["passed"] is False
    assert report["results"][1]["missing"] is True

