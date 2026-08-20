from __future__ import annotations

import json
from pathlib import Path

from scripts.seek_demo_readiness_report import build_demo_readiness_report, load_step_reports, main


def test_demo_readiness_passes_for_review_stop_with_batch_read() -> None:
    report = build_demo_readiness_report(
        run_dir=Path("run"),
        step_reports=[
            {
                "step_name": "execute_card",
                "created_at": "2026-06-23T10:00:00",
                "before_image": "before.png",
                "after_image": "after.png",
                "trace_paths": ["click_trace.json"],
            },
            {
                "step_name": "read_detail_batch",
                "created_at": "2026-06-23T10:01:00",
                "read_region_batch": {
                    "contract_version": "read_region_batch_v1",
                    "unique_line_count": 42,
                    "capture_count": 4,
                },
                "before_image": "read_before.png",
                "after_image": "read_after.png",
            },
            {
                "step_name": "extract_final_review",
                "created_at": "2026-06-23T10:04:30",
                "observe_image": "review.png",
                "application_flow_state": {"current_step": "review_and_submit", "state_type": "final_submit_visible"},
                "final_submissions": 0,
                "submit_clicks": 0,
                "trace_paths": ["review_trace.json"],
            },
        ],
        application_fill_record={"contract_version": "seek_application_fill_record_v1"},
        time_budget_ms=5 * 60 * 1000,
    )

    assert report["status"] == "pass"
    assert report["summary"]["review_page_reached"] is True
    assert report["summary"]["final_submissions"] == 0
    assert report["summary"]["long_read_strategy"] == "read_detail_batch"
    assert report["summary"]["duration_ms"] == 270000.0


def test_demo_readiness_fails_when_submit_was_clicked() -> None:
    report = build_demo_readiness_report(
        run_dir=None,
        step_reports=[
            {
                "step_name": "extract_final_review",
                "application_flow_state": {"current_step": "review_and_submit"},
                "final_submissions": 1,
                "submit_clicks": 1,
            }
        ],
        application_fill_record={"contract_version": "seek_application_fill_record_v1"},
    )

    assert report["status"] == "needs_work"
    assert "no_final_submission" in [item["check_id"] for item in report["blocking_failures"]]


def test_load_step_reports_and_main(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    step_dir = run_dir / "step_001_extract_final_review"
    step_dir.mkdir(parents=True)
    (step_dir / "step_report.json").write_text(
        json.dumps(
            {
                "step_name": "extract_final_review",
                "created_at": "2026-06-23T10:00:00",
                "before_image": "a.png",
                "after_image": "b.png",
                "observe_image": "c.png",
                "trace_paths": ["trace.json"],
                "application_flow_state": {"current_step": "review_and_submit"},
                "final_submissions": 0,
                "submit_clicks": 0,
            }
        ),
        encoding="utf-8",
    )
    reports = load_step_reports(run_dir)

    assert len(reports) == 1
    assert reports[0]["_source_path"].endswith("step_report.json")

    fill_record = tmp_path / "record.json"
    fill_record.write_text(json.dumps({"contract_version": "seek_application_fill_record_v1"}), encoding="utf-8")
    out = tmp_path / "demo.json"
    assert main(["--run-dir", str(run_dir), "--application-fill-record", str(fill_record), "--out", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["summary"]["review_page_reached"] is True
