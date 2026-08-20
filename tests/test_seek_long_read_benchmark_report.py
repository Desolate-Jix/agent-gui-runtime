from __future__ import annotations

import json
from pathlib import Path

from scripts.seek_long_read_benchmark_report import build_benchmark_report, load_step_reports, main


def test_build_benchmark_report_prefers_batch_when_faster_and_complete() -> None:
    report = build_benchmark_report(
        [
            {
                "step_name": "read_detail_scroll",
                "timings": {"total_ms": 9000},
                "right_detail_scroll_validation": {
                    "new_unique_line_count": 5,
                    "wrong_scope": False,
                    "no_progress_count": 0,
                },
            },
            {
                "step_name": "read_detail_scroll",
                "timings": {"total_ms": 8000},
                "right_detail_scroll_validation": {
                    "new_unique_line_count": 5,
                    "wrong_scope": False,
                    "no_progress_count": 1,
                },
            },
            {
                "step_name": "read_detail_batch",
                "timings": {"total_ms": 7000},
                "read_region_batch": {
                    "contract_version": "read_region_batch_v1",
                    "capture_count": 3,
                    "unique_line_count": 12,
                    "wrong_scope_detected": False,
                    "stop_reason": "no_new_content",
                    "captures": [],
                },
            },
        ]
    )

    assert report["contract_version"] == "seek_long_read_benchmark_report_v1"
    assert report["summary"]["old_unique_line_count"] == 10
    assert report["summary"]["batch_unique_line_count"] == 12
    assert report["summary"]["recommended_path"] == "read_detail_batch"
    assert report["comparison"]["elapsed_delta_ms"] == -10000


def test_build_benchmark_report_blocks_batch_low_recall() -> None:
    report = build_benchmark_report(
        [
            {
                "step_name": "read_detail_scroll",
                "right_detail_scroll_validation": {"new_unique_line_count": 10, "wrong_scope": False},
            },
            {
                "step_name": "read_detail_batch",
                "read_region_batch": {
                    "contract_version": "read_region_batch_v1",
                    "capture_count": 1,
                    "unique_line_count": 3,
                    "wrong_scope_detected": False,
                },
            },
        ]
    )

    assert report["summary"]["recommended_path"] == "needs_more_evidence"
    assert "batch_unique_line_recall_too_low" in report["comparison"]["blockers"]


def test_load_step_reports_and_main(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    step_dir = run_dir / "step_001_read_detail_batch"
    step_dir.mkdir(parents=True)
    (step_dir / "step_report.json").write_text(
        json.dumps(
            {
                "step_name": "read_detail_batch",
                "read_region_batch": {
                    "contract_version": "read_region_batch_v1",
                    "capture_count": 2,
                    "unique_line_count": 4,
                    "wrong_scope_detected": False,
                },
            }
        ),
        encoding="utf-8",
    )
    reports = load_step_reports([run_dir])

    assert len(reports) == 1
    assert reports[0]["_source_path"].endswith("step_report.json")

    out = tmp_path / "benchmark.json"
    assert main([str(run_dir), "--out", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["summary"]["batch_report_count"] == 1
