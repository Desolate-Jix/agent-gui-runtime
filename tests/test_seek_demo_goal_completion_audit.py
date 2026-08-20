import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "seek_demo_goal_completion_audit.py"
spec = importlib.util.spec_from_file_location("seek_demo_goal_completion_audit", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def _complete_step_reports() -> list[dict]:
    return [
        {
            "step_name": "read_detail_batch",
            "read_region_batch": {"contract_version": "read_region_batch_v1", "unique_line_count": 12},
            "trace_paths": ["logs/traces/vision/observe-screen.json"],
        },
        {
            "step_name": "continue_application_flow",
            "execute_observation": {"contract_version": "execute_observation_v1"},
            "form_field_inventory": {"contract_version": "form_field_inventory_v1", "fields": [{"label": "Cover letter"}]},
            "ui_diff_verification": {"contract_version": "ui_diff_verification_v1"},
            "post_fill_verification": {"status": "pass"},
            "trace_paths": ["logs/traces/vision/observe-screen-application.json", "logs/traces/actions/scroll-down.json"],
        },
        {
            "step_name": "extract_final_review",
            "execute_observation": {"contract_version": "execute_observation_v1"},
            "form_field_inventory": {"contract_version": "form_field_inventory_v1", "fields": [{"label": "Submit application"}]},
            "trace_paths": ["logs/traces/vision/observe-screen-review.json"],
        },
    ]


def test_goal_completion_audit_passes_complete_speed_demo_evidence(tmp_path: Path) -> None:
    report = audit.build_goal_completion_audit(
        run_dir=tmp_path,
        speed_report={
            "total_ms": 212048.417,
            "within_budget": True,
            "result_scrolls": [{"wheel_clicks": 9, "card_fingerprint_changed": True}],
        },
        readiness_report={
            "status": "pass",
            "summary": {"final_submissions": 0, "submit_clicks": 0, "long_read_strategy": "read_detail_batch"},
            "long_read": {"strategy": "read_detail_batch", "batch_unique_line_count": 81},
        },
        application_fill_record={
            "final_submissions": 0,
            "submit_clicks": 0,
            "filled_fields": [{"field": "cover_letter"}, {"field": "work_rights"}],
        },
        final_review_extraction={"status": "pass", "final_submissions": 0, "submit_clicks": 0},
        step_reports=_complete_step_reports(),
    )

    assert report["contract_version"] == "seek_demo_goal_completion_audit_v1"
    assert report["status"] == "pass"
    assert {item["check_id"]: item["status"] for item in report["checks"]} == {
        "adaptive_scroll": "pass",
        "multi_capture_batch_read": "pass",
        "screen_understanding_after_page_change": "pass",
        "visual_form_fill_with_scroll_and_verification": "pass",
        "diff_verifier_present": "pass",
        "five_minute_review_boundary_no_submit": "pass",
    }


def test_goal_completion_audit_fails_when_core_goal_evidence_is_missing(tmp_path: Path) -> None:
    report = audit.build_goal_completion_audit(
        run_dir=tmp_path,
        speed_report={"total_ms": 2_100_000, "result_scrolls": []},
        readiness_report={"status": "needs_work", "summary": {"final_submissions": 0, "submit_clicks": 0}, "long_read": {}},
        application_fill_record={"filled_fields": []},
        final_review_extraction={"status": "needs_work"},
        step_reports=[],
    )

    assert report["status"] == "needs_work"
    failed = {item["check_id"] for item in report["blocking_failures"]}
    assert "adaptive_scroll" in failed
    assert "multi_capture_batch_read" in failed
    assert "five_minute_review_boundary_no_submit" in failed
