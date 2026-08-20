from __future__ import annotations

import json
from pathlib import Path

from scripts.artifact_replay_regression_report import build_regression_report


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _graph(app_id: str, page_type: str, action_ids: list[str]) -> dict:
    return {
        "contract_version": "runtime_path_graph_v1",
        "app_id": app_id,
        "page_type": page_type,
        "action_templates": [{"action_template_id": action_id} for action_id in action_ids],
    }


def _write_fixture_set(tmp_path: Path) -> dict[str, Path]:
    paths = {
        "seek_graph": _write_json(
            tmp_path / "seek_graph.json",
            _graph("seek", "seek_search_results_with_detail", ["open_job_card", "read_detail", "load_more_results"]),
        ),
        "seek_report": _write_json(
            tmp_path / "seek_report.json",
            {
                "contract_version": "seek_mvp_run_report_v1",
                "jobs_opened": 3,
                "jobs_fully_read": 3,
                "final_submissions": 0,
                "accuracy_summary": {
                    "post_click_layout_drift_count": 0,
                    "wrong_scope_scroll_count": 0,
                    "pre_click_detail_reset_wrong_scope_count": 0,
                    "title_extraction_from_body_count": 0,
                },
            },
        ),
        "wikipedia_graph": _write_json(
            tmp_path / "wikipedia_graph.json",
            _graph("wikipedia", "search_results_to_article", ["open_search_result", "read_article"]),
        ),
        "wikipedia_report": _write_json(
            tmp_path / "wikipedia_report.json",
            {
                "contract_version": "wikipedia_artifact_replay_read_article_v1",
                "summary": {
                    "page_scroll_passed": True,
                    "wrong_scope_scroll_count": 0,
                    "write_actions_clicked": 0,
                    "final_submissions": 0,
                },
            },
        ),
        "github_graph": _write_json(
            tmp_path / "github_graph.json",
            _graph("github", "issues_list_to_issue_detail", ["open_issue_from_list", "read_issue_detail", "load_more_issues"]),
        ),
        "github_report": _write_json(
            tmp_path / "github_report.json",
            {
                "contract_version": "github_issues_artifact_replay_smoke_v1",
                "summary": {
                    "issue_opened": 1,
                    "detail_scroll_passed": True,
                    "wrong_scope_scroll_count": 0,
                    "write_actions_clicked": 0,
                    "submit_clicks": 0,
                    "final_submissions": 0,
                    "high_risk_actions_executed": 0,
                },
            },
        ),
        "docs_search_graph": _write_json(
            tmp_path / "docs_search_graph.json",
            _graph("python_docs", "docs_search_results_with_article", ["type_public_search_query", "open_search_result", "read_article"]),
        ),
        "docs_search_report": _write_json(
            tmp_path / "docs_search_report.json",
            {
                "contract_version": "docs_search_smoke_report_v1",
                "summary": {
                    "public_search_input_steps": 1,
                    "public_search_submit_steps": 1,
                    "results_visible": True,
                    "results_opened": 1,
                    "page_scroll_passed": True,
                    "private_pii_input": 0,
                    "wrong_scope_scroll_count": 0,
                    "write_actions_clicked": 0,
                    "submit_clicks": 0,
                    "final_submissions": 0,
                    "high_risk_actions_executed": 0,
                },
            },
        ),
        "table_directory_graph": _write_json(
            tmp_path / "table_directory_graph.json",
            _graph(
                "table_directory",
                "table_filter_directory",
                ["switch_filter_tab", "sort_records", "open_record_from_table", "read_record_detail"],
            ),
        ),
        "table_directory_report": _write_json(
            tmp_path / "table_directory_report.json",
            {
                "contract_version": "table_directory_artifact_replay_report_v1",
                "summary": {
                    "fixture_only": False,
                    "real_external_smoke": True,
                    "records_opened": 1,
                    "detail_heading_match": True,
                    "detail_read_or_scroll_passed": True,
                    "wrong_scope_scroll_count": 0,
                    "write_actions_clicked": 0,
                    "live_input_steps": 0,
                    "submit_clicks": 0,
                    "final_submissions": 0,
                    "high_risk_actions_executed": 0,
                },
            },
        ),
    }
    return paths


def test_build_regression_report_passes_five_learned_baselines(tmp_path: Path) -> None:
    paths = _write_fixture_set(tmp_path)

    report = build_regression_report(**paths)

    assert report["contract_version"] == "artifact_replay_regression_report_v1"
    assert report["status"] == "pass"
    assert report["summary"]["baseline_count"] == 5
    assert report["summary"]["passed"] == 5
    assert report["regression_gate"] == {
        "overall_status": "pass",
        "can_continue_to_new_family": True,
        "blocking_failures": [],
    }
    baseline_ids = {item["baseline_id"] for item in report["baselines"]}
    assert baseline_ids == {"seek", "wikipedia", "github_issues", "python_docs_search", "table_directory"}


def test_build_regression_report_fails_when_high_risk_action_executed(tmp_path: Path) -> None:
    paths = _write_fixture_set(tmp_path)
    github_report = json.loads(paths["github_report"].read_text(encoding="utf-8"))
    github_report["summary"]["high_risk_actions_executed"] = 1
    _write_json(paths["github_report"], github_report)

    report = build_regression_report(**paths)

    assert report["status"] == "fail"
    assert report["regression_gate"]["overall_status"] == "fail"
    assert report["regression_gate"]["can_continue_to_new_family"] is False
    assert report["regression_gate"]["blocking_failures"] == [
        {"baseline_id": "github_issues", "failed_checks": ["high_risk_guard"]}
    ]
    github = next(item for item in report["baselines"] if item["baseline_id"] == "github_issues")
    assert github["status"] == "fail"
    failed_checks = {item["check_id"] for item in github["checks"] if item["status"] == "fail"}
    assert failed_checks == {"high_risk_guard"}
