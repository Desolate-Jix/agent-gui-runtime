from __future__ import annotations

import json
from pathlib import Path

from scripts.report_learn_fusion_gate_rejection_diagnosis import report_gate_rejection_diagnosis


def test_report_gate_rejection_diagnosis_classifies_missing_open_detail_semantic_action(tmp_path: Path) -> None:
    trace = tmp_path / "trace.json"
    trace.write_text(
        json.dumps(
            {
                "request": {
                    "task": "click_target",
                    "operation_context": {"semantic_action": None},
                },
                "result": {
                    "pre_click_decision": {
                        "allowed": False,
                        "reasons": ["no_candidate_passed_pre_click_checks"],
                        "candidate_decisions": [
                            {
                                "candidate_id": "seeded_numbered_region_4_c4",
                                "allowed": False,
                                "reasons": [
                                    "candidate_goal_action_mismatch",
                                    "goal_explicitly_mentions_candidate_label",
                                    "local_ocr_text_match",
                                ],
                                "resolved_click_point": {
                                    "inside_bbox": True,
                                    "chosen_point": {"x": 100, "y": 120},
                                },
                            }
                        ],
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    status = tmp_path / "fusion_status.json"
    status.write_text(
        json.dumps(
            {
                "contract_version": "learn_precise_understanding_fusion_status_report_v1",
                "items": [
                    {
                        "region_no": 4,
                        "label": "Job listing card",
                        "role": "card",
                        "calibration_status": "gate_rejected",
                        "gate_safety": "passed_rejected",
                        "point_quality": "vista_point_inside_seed_bbox",
                        "trace_path": str(trace),
                        "recognition_plan_trace_path": "plan.json",
                        "overlay_path": "overlay.png",
                        "real_clicks": 0,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = report_gate_rejection_diagnosis(fusion_status_path=status, out_dir=tmp_path / "out")

    assert result["contract_version"] == "learn_fusion_gate_rejection_diagnosis_report_v1"
    assert result["summary"]["attempted"] == 1
    assert result["summary"]["classification_counts"] == {"missing_open_detail_semantic_action": 1}
    case = result["cases"][0]
    assert case["classification"] == "missing_open_detail_semantic_action"
    assert case["pre_click_reasons"] == ["no_candidate_passed_pre_click_checks"]
    assert case["candidate_decision_reasons"] == [
        "candidate_goal_action_mismatch",
        "goal_explicitly_mentions_candidate_label",
        "local_ocr_text_match",
    ]
    assert case["requested_task"] == "click_target"
    assert case["requested_semantic_action"] == ""
    assert case["proposed_fix"] == "rerun_locator_probe_with_operation_context_semantic_action_open_detail"
    assert case["safety_interpretation"] == "safe_intercept_not_unsafe_failure"
    assert result["execute_binding_enabled"] is False
    assert result["artifact_is_authorization"] is False
    assert Path(result["report_path"]).exists()
