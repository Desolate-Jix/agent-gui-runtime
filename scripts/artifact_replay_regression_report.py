from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


DEFAULT_SEEK_GRAPH = Path("artifacts/seek/runtime_path_graph_seek_mvp_20260617.json")
DEFAULT_SEEK_REPORT = Path("logs/smoke/seek_artifact_replay_readonly_3job_20260619_after_reset.json")
DEFAULT_WIKIPEDIA_GRAPH = Path("artifacts/wikipedia/runtime_path_graph_wikipedia_search_v1.json")
DEFAULT_WIKIPEDIA_REPORT = Path("logs/smoke/wikipedia_artifact_replay_read_article_20260619.json")
DEFAULT_GITHUB_GRAPH = Path("artifacts/github/runtime_path_graph_github_issues_v1.json")
DEFAULT_GITHUB_REPORT = Path("logs/smoke/github_issues_artifact_replay_readonly_20260619.json")
DEFAULT_DOCS_SEARCH_GRAPH = Path("artifacts/docs_search/runtime_path_graph_python_docs_search_v1.json")
DEFAULT_DOCS_SEARCH_REPORT = Path("logs/smoke/python_docs_search_artifact_replay_public_input_20260619.json")
DEFAULT_TABLE_DIRECTORY_GRAPH = Path("artifacts/table_directory/runtime_path_graph_table_directory_v1.json")
DEFAULT_TABLE_DIRECTORY_REPORT = Path("logs/smoke/table_directory_datatables_real_1record_20260619.json")


def read_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def unwrap_graph(payload: dict[str, Any]) -> dict[str, Any]:
    graph = payload.get("runtime_path_graph", payload)
    if not isinstance(graph, dict):
        raise ValueError("runtime_path_graph must be a JSON object")
    return graph


def get_path(payload: dict[str, Any], path: str, default: Any = None) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def action_ids(graph: dict[str, Any]) -> set[str]:
    return {
        str(action.get("action_template_id"))
        for action in graph.get("action_templates") or []
        if isinstance(action, dict) and action.get("action_template_id")
    }


def check(check_id: str, passed: bool, message: str, evidence: Any = None) -> dict[str, Any]:
    item: dict[str, Any] = {
        "check_id": check_id,
        "status": "pass" if passed else "fail",
        "message": message,
    }
    if evidence is not None:
        item["evidence"] = evidence
    return item


def summarize_baseline(
    *,
    baseline_id: str,
    graph_path: Path,
    report_path: Path,
    graph: dict[str, Any],
    smoke_report: dict[str, Any],
    checks: list[dict[str, Any]],
) -> dict[str, Any]:
    status = "pass" if all(item.get("status") == "pass" for item in checks) else "fail"
    return {
        "baseline_id": baseline_id,
        "status": status,
        "graph_path": str(graph_path),
        "report_path": str(report_path),
        "graph_summary": {
            "contract_version": graph.get("contract_version"),
            "app_id": graph.get("app_id"),
            "page_type": graph.get("page_type"),
            "action_templates": sorted(action_ids(graph)),
        },
        "report_summary": {
            "contract_version": smoke_report.get("contract_version"),
            "summary": smoke_report.get("summary"),
            "accuracy_summary": smoke_report.get("accuracy_summary"),
        },
        "checks": checks,
    }


def validate_seek(graph_path: Path, report_path: Path) -> dict[str, Any]:
    graph = unwrap_graph(read_json(graph_path))
    smoke_report = read_json(report_path)
    actions = action_ids(graph)
    accuracy = smoke_report.get("accuracy_summary") if isinstance(smoke_report.get("accuracy_summary"), dict) else {}
    checks = [
        check("graph_contract", graph.get("contract_version") == "runtime_path_graph_v1", "SEEK graph uses runtime_path_graph_v1", graph.get("contract_version")),
        check("graph_app", graph.get("app_id") == "seek", "SEEK graph app_id is seek", graph.get("app_id")),
        check("graph_actions", {"open_job_card", "read_detail", "load_more_results"} <= actions, "SEEK graph exposes open/read/load-more actions", sorted(actions)),
        check("jobs_opened", int(smoke_report.get("jobs_opened") or 0) >= 3, "SEEK smoke opened at least 3 jobs", smoke_report.get("jobs_opened")),
        check("jobs_fully_read", int(smoke_report.get("jobs_fully_read") or 0) >= 3, "SEEK smoke fully read at least 3 jobs", smoke_report.get("jobs_fully_read")),
        check("layout_drift", int(accuracy.get("post_click_layout_drift_count") or 0) == 0, "SEEK post-click layout did not drift", accuracy.get("post_click_layout_drift_count")),
        check("wrong_scope", int(accuracy.get("wrong_scope_scroll_count") or 0) == 0, "SEEK scroll stayed in the intended scope", accuracy.get("wrong_scope_scroll_count")),
        check("detail_reset_scope", int(accuracy.get("pre_click_detail_reset_wrong_scope_count") or 0) == 0, "SEEK detail reset stayed in the intended scope", accuracy.get("pre_click_detail_reset_wrong_scope_count")),
        check("title_source", int(accuracy.get("title_extraction_from_body_count") or 0) == 0, "SEEK title extraction did not come from body fragments", accuracy.get("title_extraction_from_body_count")),
        check("final_submit", int(smoke_report.get("final_submissions") or 0) == 0, "SEEK smoke did not submit applications", smoke_report.get("final_submissions")),
    ]
    return summarize_baseline(
        baseline_id="seek",
        graph_path=graph_path,
        report_path=report_path,
        graph=graph,
        smoke_report=smoke_report,
        checks=checks,
    )


def validate_wikipedia(graph_path: Path, report_path: Path) -> dict[str, Any]:
    graph = unwrap_graph(read_json(graph_path))
    smoke_report = read_json(report_path)
    summary = smoke_report.get("summary") if isinstance(smoke_report.get("summary"), dict) else {}
    actions = action_ids(graph)
    checks = [
        check("graph_contract", graph.get("contract_version") == "runtime_path_graph_v1", "Wikipedia graph uses runtime_path_graph_v1", graph.get("contract_version")),
        check("graph_app", graph.get("app_id") == "wikipedia", "Wikipedia graph app_id is wikipedia", graph.get("app_id")),
        check("graph_actions", {"open_search_result", "read_article"} <= actions, "Wikipedia graph exposes open/read actions", sorted(actions)),
        check("page_scroll", summary.get("page_scroll_passed") is True, "Wikipedia article page scroll passed", summary.get("page_scroll_passed")),
        check("wrong_scope", int(summary.get("wrong_scope_scroll_count") or 0) == 0, "Wikipedia scroll stayed in the intended scope", summary.get("wrong_scope_scroll_count")),
        check("write_guard", int(summary.get("write_actions_clicked") or 0) == 0, "Wikipedia smoke clicked no write actions", summary.get("write_actions_clicked")),
        check("final_submit", int(summary.get("final_submissions") or 0) == 0, "Wikipedia smoke did not submit anything", summary.get("final_submissions")),
    ]
    return summarize_baseline(
        baseline_id="wikipedia",
        graph_path=graph_path,
        report_path=report_path,
        graph=graph,
        smoke_report=smoke_report,
        checks=checks,
    )


def validate_github(graph_path: Path, report_path: Path) -> dict[str, Any]:
    graph = unwrap_graph(read_json(graph_path))
    smoke_report = read_json(report_path)
    summary = smoke_report.get("summary") if isinstance(smoke_report.get("summary"), dict) else {}
    actions = action_ids(graph)
    checks = [
        check("graph_contract", graph.get("contract_version") == "runtime_path_graph_v1", "GitHub graph uses runtime_path_graph_v1", graph.get("contract_version")),
        check("graph_app", graph.get("app_id") == "github", "GitHub graph app_id is github", graph.get("app_id")),
        check("graph_actions", {"open_issue_from_list", "read_issue_detail", "load_more_issues"} <= actions, "GitHub graph exposes open/read/load-more actions", sorted(actions)),
        check("issue_opened", int(summary.get("issue_opened") or 0) >= 1, "GitHub smoke opened at least one issue", summary.get("issue_opened")),
        check("detail_scroll", summary.get("detail_scroll_passed") is True, "GitHub issue detail page scroll passed", summary.get("detail_scroll_passed")),
        check("wrong_scope", int(summary.get("wrong_scope_scroll_count") or 0) == 0, "GitHub scroll stayed in the intended scope", summary.get("wrong_scope_scroll_count")),
        check("write_guard", int(summary.get("write_actions_clicked") or 0) == 0, "GitHub smoke clicked no write actions", summary.get("write_actions_clicked")),
        check("submit_guard", int(summary.get("submit_clicks") or 0) == 0 and int(summary.get("final_submissions") or 0) == 0, "GitHub smoke did not click submit/final-submit", {"submit_clicks": summary.get("submit_clicks"), "final_submissions": summary.get("final_submissions")}),
        check("high_risk_guard", int(summary.get("high_risk_actions_executed") or 0) == 0, "GitHub smoke executed no high-risk actions", summary.get("high_risk_actions_executed")),
    ]
    return summarize_baseline(
        baseline_id="github_issues",
        graph_path=graph_path,
        report_path=report_path,
        graph=graph,
        smoke_report=smoke_report,
        checks=checks,
    )


def validate_docs_search(graph_path: Path, report_path: Path) -> dict[str, Any]:
    graph = unwrap_graph(read_json(graph_path))
    smoke_report = read_json(report_path)
    summary = smoke_report.get("summary") if isinstance(smoke_report.get("summary"), dict) else {}
    actions = action_ids(graph)
    checks = [
        check("graph_contract", graph.get("contract_version") == "runtime_path_graph_v1", "Python Docs graph uses runtime_path_graph_v1", graph.get("contract_version")),
        check("graph_app", graph.get("app_id") == "python_docs", "Python Docs graph app_id is python_docs", graph.get("app_id")),
        check("graph_actions", {"type_public_search_query", "open_search_result", "read_article"} <= actions, "Python Docs graph exposes input/open/read actions", sorted(actions)),
        check("public_search_input", int(summary.get("public_search_input_steps") or 0) >= 1, "Python Docs smoke typed a public search query", summary.get("public_search_input_steps")),
        check("public_search_submit", int(summary.get("public_search_submit_steps") or 0) >= 1, "Python Docs smoke explicitly submitted the public search", summary.get("public_search_submit_steps")),
        check("results_visible", summary.get("results_visible") is True, "Python Docs search results became visible", summary.get("results_visible")),
        check("result_opened", int(summary.get("results_opened") or 0) >= 1, "Python Docs smoke opened a search result", summary.get("results_opened")),
        check("page_scroll", summary.get("page_scroll_passed") is True, "Python Docs article page scroll passed", summary.get("page_scroll_passed")),
        check("private_input_guard", int(summary.get("private_pii_input") or 0) == 0, "Python Docs smoke typed no private/PII input", summary.get("private_pii_input")),
        check("wrong_scope", int(summary.get("wrong_scope_scroll_count") or 0) == 0, "Python Docs scroll stayed in the intended scope", summary.get("wrong_scope_scroll_count")),
        check("write_guard", int(summary.get("write_actions_clicked") or 0) == 0, "Python Docs smoke clicked no write actions", summary.get("write_actions_clicked")),
        check("submit_guard", int(summary.get("submit_clicks") or 0) == 0 and int(summary.get("final_submissions") or 0) == 0, "Python Docs smoke did not click submit/final-submit buttons", {"submit_clicks": summary.get("submit_clicks"), "final_submissions": summary.get("final_submissions")}),
        check("high_risk_guard", int(summary.get("high_risk_actions_executed") or 0) == 0, "Python Docs smoke executed no high-risk actions", summary.get("high_risk_actions_executed")),
    ]
    return summarize_baseline(
        baseline_id="python_docs_search",
        graph_path=graph_path,
        report_path=report_path,
        graph=graph,
        smoke_report=smoke_report,
        checks=checks,
    )


def validate_table_directory(graph_path: Path, report_path: Path) -> dict[str, Any]:
    graph = unwrap_graph(read_json(graph_path))
    smoke_report = read_json(report_path)
    summary = smoke_report.get("summary") if isinstance(smoke_report.get("summary"), dict) else {}
    actions = action_ids(graph)
    checks = [
        check("graph_contract", graph.get("contract_version") == "runtime_path_graph_v1", "Table Directory graph uses runtime_path_graph_v1", graph.get("contract_version")),
        check("graph_app", graph.get("app_id") == "table_directory", "Table Directory graph app_id is table_directory", graph.get("app_id")),
        check("graph_page_type", graph.get("page_type") == "table_filter_directory", "Table Directory graph models table/filter/sort family", graph.get("page_type")),
        check(
            "graph_actions",
            {"switch_filter_tab", "sort_records", "open_record_from_table", "read_record_detail"} <= actions,
            "Table Directory graph exposes filter/sort/open/read actions",
            sorted(actions),
        ),
        check("real_external_smoke", summary.get("real_external_smoke") is True, "Table Directory report comes from a real external website smoke", summary.get("real_external_smoke")),
        check("not_fixture_only", summary.get("fixture_only") is False, "Table Directory report is not fixture-only", summary.get("fixture_only")),
        check("record_opened", int(summary.get("records_opened") or 0) >= 1, "Table Directory replay opened at least one record", summary.get("records_opened")),
        check("detail_heading_match", summary.get("detail_heading_match") is True, "Record detail heading matched the selected row", summary.get("detail_heading_match")),
        check("detail_scroll", summary.get("detail_read_or_scroll_passed") is True, "Record detail read/scroll passed", summary.get("detail_read_or_scroll_passed")),
        check("wrong_scope", int(summary.get("wrong_scope_scroll_count") or 0) == 0, "Table Directory scroll stayed in the intended scope", summary.get("wrong_scope_scroll_count")),
        check("write_guard", int(summary.get("write_actions_clicked") or 0) == 0, "Table Directory replay clicked no write actions", summary.get("write_actions_clicked")),
        check("input_guard", int(summary.get("live_input_steps") or 0) == 0, "Table Directory replay used no live input", summary.get("live_input_steps")),
        check("submit_guard", int(summary.get("submit_clicks") or 0) == 0 and int(summary.get("final_submissions") or 0) == 0, "Table Directory replay did not submit anything", {"submit_clicks": summary.get("submit_clicks"), "final_submissions": summary.get("final_submissions")}),
        check("high_risk_guard", int(summary.get("high_risk_actions_executed") or 0) == 0, "Table Directory replay executed no high-risk actions", summary.get("high_risk_actions_executed")),
    ]
    return summarize_baseline(
        baseline_id="table_directory",
        graph_path=graph_path,
        report_path=report_path,
        graph=graph,
        smoke_report=smoke_report,
        checks=checks,
    )


def build_regression_report(
    *,
    seek_graph: Path = DEFAULT_SEEK_GRAPH,
    seek_report: Path = DEFAULT_SEEK_REPORT,
    wikipedia_graph: Path = DEFAULT_WIKIPEDIA_GRAPH,
    wikipedia_report: Path = DEFAULT_WIKIPEDIA_REPORT,
    github_graph: Path = DEFAULT_GITHUB_GRAPH,
    github_report: Path = DEFAULT_GITHUB_REPORT,
    docs_search_graph: Path = DEFAULT_DOCS_SEARCH_GRAPH,
    docs_search_report: Path = DEFAULT_DOCS_SEARCH_REPORT,
    table_directory_graph: Path = DEFAULT_TABLE_DIRECTORY_GRAPH,
    table_directory_report: Path = DEFAULT_TABLE_DIRECTORY_REPORT,
) -> dict[str, Any]:
    baselines = [
        validate_seek(seek_graph, seek_report),
        validate_wikipedia(wikipedia_graph, wikipedia_report),
        validate_github(github_graph, github_report),
        validate_docs_search(docs_search_graph, docs_search_report),
        validate_table_directory(table_directory_graph, table_directory_report),
    ]
    failed = [item for item in baselines if item.get("status") != "pass"]
    blocking_failures = [
        {
            "baseline_id": str(item.get("baseline_id")),
            "failed_checks": [
                str(check_item.get("check_id"))
                for check_item in item.get("checks") or []
                if isinstance(check_item, dict) and check_item.get("status") != "pass"
            ],
        }
        for item in failed
    ]
    return {
        "contract_version": "artifact_replay_regression_report_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if not failed else "fail",
        "summary": {
            "baseline_count": len(baselines),
            "passed": len(baselines) - len(failed),
            "failed": len(failed),
            "baseline_ids": [str(item.get("baseline_id")) for item in baselines],
        },
        "regression_gate": {
            "overall_status": "pass" if not failed else "fail",
            "can_continue_to_new_family": not failed,
            "blocking_failures": blocking_failures,
        },
        "baselines": baselines,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a unified Artifact Replay regression report from learned website baselines.")
    parser.add_argument("--seek-graph", type=Path, default=DEFAULT_SEEK_GRAPH)
    parser.add_argument("--seek-report", type=Path, default=DEFAULT_SEEK_REPORT)
    parser.add_argument("--wikipedia-graph", type=Path, default=DEFAULT_WIKIPEDIA_GRAPH)
    parser.add_argument("--wikipedia-report", type=Path, default=DEFAULT_WIKIPEDIA_REPORT)
    parser.add_argument("--github-graph", type=Path, default=DEFAULT_GITHUB_GRAPH)
    parser.add_argument("--github-report", type=Path, default=DEFAULT_GITHUB_REPORT)
    parser.add_argument("--docs-search-graph", type=Path, default=DEFAULT_DOCS_SEARCH_GRAPH)
    parser.add_argument("--docs-search-report", type=Path, default=DEFAULT_DOCS_SEARCH_REPORT)
    parser.add_argument("--table-directory-graph", type=Path, default=DEFAULT_TABLE_DIRECTORY_GRAPH)
    parser.add_argument("--table-directory-report", type=Path, default=DEFAULT_TABLE_DIRECTORY_REPORT)
    parser.add_argument("--out", type=Path, default=Path("logs/smoke/artifact_replay_regression_report.json"))
    parser.add_argument("--fail-on-error", action="store_true", help="Exit 2 when any baseline fails.")
    args = parser.parse_args(argv)

    report = build_regression_report(
        seek_graph=args.seek_graph,
        seek_report=args.seek_report,
        wikipedia_graph=args.wikipedia_graph,
        wikipedia_report=args.wikipedia_report,
        github_graph=args.github_graph,
        github_report=args.github_report,
        docs_search_graph=args.docs_search_graph,
        docs_search_report=args.docs_search_report,
        table_directory_graph=args.table_directory_graph,
        table_directory_report=args.table_directory_report,
    )
    write_json(args.out, report)
    print(
        json.dumps(
            {
                "success": report.get("status") == "pass",
                "status": report.get("status"),
                "summary": report.get("summary"),
                "out": str(args.out),
            },
            ensure_ascii=False,
        )
    )
    if args.fail_on_error and report.get("status") != "pass":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
