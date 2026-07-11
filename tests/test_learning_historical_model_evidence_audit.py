import json
from pathlib import Path

from scripts.audit_learning_historical_model_evidence import (
    audit_historical_evidence_case,
    run_historical_model_evidence_audit,
)


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_visual_audit_is_display_only_not_model_accuracy(tmp_path: Path) -> None:
    source = _write_json(
        tmp_path / "artifacts" / "chatgpt_reports" / "stage2_v97.json",
        {
            "contract_version": "chatgpt_visual_audit_result_v1",
            "conclusions": {"python_org": "CONDITIONAL PASS"},
            "latest_assistant_text": "Python.org v97: CONDITIONAL PASS",
        },
    )

    result = audit_historical_evidence_case(
        {
            "case_id": "python_org_v97",
            "path": source.relative_to(tmp_path),
            "evidence_kind": "chatgpt_visual_audit",
            "surface": "python_org",
        },
        root=tmp_path,
    )

    assert result["classification"] == "display_review_only"
    assert result["display_review_only"] is True
    assert result["model_accuracy_claim_allowed"] is False
    assert result["model_grounding_claim_allowed"] is False
    assert "not valid evidence for model accuracy" in result["claim_boundary"]


def test_actual_parser_model_call_without_grounding_is_semantic_inventory_only(tmp_path: Path) -> None:
    source = _write_json(
        tmp_path / "logs" / "actual_parser_output.json",
        {
            "contract_version": "learn_recognition_actual_parser_output_v1",
            "actual_model_call_in_this_run": True,
            "layout_graph": {"nodes": {"c1": {"grounding_eligible": False}}},
        },
    )

    result = audit_historical_evidence_case(
        {
            "case_id": "python_org_actual_parser",
            "path": source.relative_to(tmp_path),
            "evidence_kind": "actual_parser_output",
            "surface": "python_org",
        },
        root=tmp_path,
    )

    assert result["classification"] == "model_semantic_inventory_only"
    assert result["actual_model_call_recorded"] is True
    assert result["model_grounding_attempted_count"] == 0
    assert result["model_accuracy_claim_allowed"] is False
    assert result["model_grounding_claim_allowed"] is False


def test_recorded_model_grounding_is_separated_from_accuracy_claim(tmp_path: Path) -> None:
    source = _write_json(
        tmp_path / "logs" / "grounded_report.json",
        {
            "model_grounding_evidence": {
                "model_grounding_attempted_count": 2,
            }
        },
    )

    result = audit_historical_evidence_case(
        {
            "case_id": "grounded_case",
            "path": source.relative_to(tmp_path),
            "evidence_kind": "two_stage_replay_report",
            "surface": "demo",
        },
        root=tmp_path,
    )

    assert result["classification"] == "has_recorded_model_grounding_attempts"
    assert result["model_grounding_claim_allowed"] is True
    assert result["model_accuracy_claim_allowed"] is False
    assert "separate coordinate/gate review" in result["claim_boundary"]


def test_audit_summary_counts_display_only_and_grounding_cases(tmp_path: Path) -> None:
    visual = _write_json(
        tmp_path / "visual.json",
        {"contract_version": "chatgpt_visual_audit_result_v1", "overall_verdict": "PASS"},
    )
    grounded = _write_json(
        tmp_path / "grounded.json",
        {"coordinate_validation": {"model_grounding_attempted": True}},
    )

    report = run_historical_model_evidence_audit(
        [
            {
                "case_id": "visual",
                "path": visual.relative_to(tmp_path),
                "evidence_kind": "chatgpt_visual_audit",
            },
            {
                "case_id": "grounded",
                "path": grounded.relative_to(tmp_path),
                "evidence_kind": "two_stage_replay_report",
            },
        ],
        root=tmp_path,
    )

    assert report["summary"]["attempted"] == 2
    assert report["summary"]["display_review_only_cases"] == 1
    assert report["summary"]["model_grounding_evidence_cases"] == 1
    assert report["summary"]["model_accuracy_claim_allowed"] is False
    assert report["safety_boundary"]["live_clicks"] == 0


def test_honest_fullscreen_summary_filters_counts_by_surface(tmp_path: Path) -> None:
    source = _write_json(
        tmp_path / "honest_summary.json",
        {
            "items": [
                {
                    "case": "seek_results_observe_honest",
                    "precise_supported_count": 3,
                    "rough_semantic_count": 11,
                },
                {
                    "case": "python_full_observe_honest",
                    "precise_supported_count": 0,
                    "rough_semantic_count": 12,
                },
            ]
        },
    )

    result = audit_historical_evidence_case(
        {
            "case_id": "python_org_honest_fullscreen_summary",
            "path": source.relative_to(tmp_path),
            "evidence_kind": "honest_fullscreen_summary",
            "surface": "python_org",
        },
        root=tmp_path,
    )

    assert result["classification"] == "rough_semantic_or_display_only"
    assert result["honest_fullscreen_counts"]["precise_supported_count"] == 0
    assert result["honest_fullscreen_counts"]["rough_semantic_count"] == 12
    assert result["honest_fullscreen_counts"]["matched_item_count"] == 1
    assert result["model_accuracy_claim_allowed"] is False
