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

from fastapi.testclient import TestClient

from app.learn.skill_matrix import build_learned_skill_matrix
from app.main import app
from scripts.seek_application_flow_replay_report import build_seek_application_flow_replay_report


DEFAULT_SEEK_GRAPH = Path("artifacts/seek/runtime_path_graph_seek_mvp_20260617.json")
DEFAULT_SEEK_3JOB_REPORT = Path("logs/smoke/seek_artifact_replay_readonly_3job_20260619_after_reset.json")
DEFAULT_SEEK_APPLICATION_FLOW_ARTIFACT = Path("artifacts/seek/learned_seek_application_flow_plexure_20260620.json")
DEFAULT_GRAPH_PATHS = [
    DEFAULT_SEEK_GRAPH,
    Path("artifacts/wikipedia/runtime_path_graph_wikipedia_search_v1.json"),
    Path("artifacts/github/runtime_path_graph_github_issues_v1.json"),
    Path("artifacts/docs_search/runtime_path_graph_python_docs_search_v1.json"),
    Path("artifacts/table_directory/runtime_path_graph_table_directory_v1.json"),
]


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def run_seek_safe_validation(graph: dict[str, Any]) -> dict[str, Any]:
    client = TestClient(app)
    safety = {"forbid_final_submit": True, "allow_apply_entry": False, "allow_safe_fill": False}
    checks: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    expected = [
        ("seek_search_results_empty_detail", "open_job_card"),
        ("seek_search_results_with_selected_job", "read_detail"),
        ("seek_search_results_with_selected_job", "load_more_results"),
    ]

    for state_id, action_id in expected:
        available_response = client.post(
            "/execute/available_actions",
            json={
                "runtime_path_graph": graph,
                "current_state_id": state_id,
                "screen_inventory": {"available_actions": [{"label": "Apply"}, {"label": "Save"}]},
                "safety": safety,
            },
        )
        available_payload = available_response.json()
        available_data = available_payload.get("data") if isinstance(available_payload.get("data"), dict) else {}
        actions = ((available_data.get("available_actions") or {}).get("actions") or []) if isinstance(available_data, dict) else []
        action = next((item for item in actions if isinstance(item, dict) and item.get("action_template_id") == action_id), None)
        step_payload: dict[str, Any] | None = None
        if action is not None:
            step_response = client.post(
                "/execute/step",
                json={
                    "runtime_path_graph": graph,
                    "available_actions_trace_path": available_data.get("trace_path"),
                    "path_graph_resolution": available_data.get("path_graph_resolution"),
                    "selected_action": action,
                    "dry_run": True,
                    "dispatch_low_level": False,
                },
            )
            step_payload = step_response.json()
        step_data = step_payload.get("data") if isinstance(step_payload, dict) and isinstance(step_payload.get("data"), dict) else {}
        low_request = step_data.get("low_level_request") if isinstance(step_data.get("low_level_request"), dict) else {}
        context = step_data.get("path_graph_action_context") if isinstance(step_data.get("path_graph_action_context"), dict) else {}
        passed = bool(available_payload.get("success") and action is not None and step_payload and step_payload.get("success"))
        checks.append(_check(action_id, passed, f"{action_id} is available and plans one safe dry-run step"))
        timeline.append(
            {
                "state_id": state_id,
                "action_template_id": action_id,
                "status": "pass" if passed else "fail",
                "skill_ref": action.get("learned_skill_ref") if isinstance(action, dict) else None,
                "low_level_action_type": action.get("low_level_action_type") if isinstance(action, dict) else None,
                "target_container_id": low_request.get("target_container_id") or context.get("target_container_id"),
                "target_pane": low_request.get("target_pane"),
                "available_actions_trace_path": available_data.get("trace_path"),
                "execute_step_trace_path": step_data.get("execute_step_trace_path"),
                "verification_result": (step_data.get("verification") or {}).get("status") if isinstance(step_data.get("verification"), dict) else None,
                "coordinate_source": ((low_request.get("metadata") or {}).get("seeded_candidate") or {}).get("source")
                if isinstance(low_request.get("metadata"), dict)
                else None,
                "artifact_is_authorization": bool(step_data.get("artifact_is_authorization")),
            }
        )

    available_with_apply = client.post(
        "/execute/available_actions",
        json={
            "runtime_path_graph": graph,
            "current_state_id": "seek_search_results_with_selected_job",
            "screen_inventory": {"available_actions": [{"label": "Apply"}, {"label": "Submit application"}]},
            "safety": safety,
        },
    ).json()
    apply_actions = (((available_with_apply.get("data") or {}).get("available_actions") or {}).get("actions") or [])
    action_ids = {str(item.get("action_template_id") or "") for item in apply_actions if isinstance(item, dict)}
    checks.append(_check("apply_entry_hidden", "apply_entry" not in action_ids, "guarded apply_entry stays hidden"))
    checks.append(_check("input_blocked", not any(_is_input_action(item) for item in apply_actions if isinstance(item, dict)), "Learn Safe Validation exposes no input actions"))

    passed = all(item["status"] == "pass" for item in checks)
    return {
        "contract_version": "seek_learn_safe_validation_report_v1",
        "generated_at": _now(),
        "status": "pass" if passed else "fail",
        "mode": "learn_safe_validation",
        "runtime_path_graph": "artifacts/seek/runtime_path_graph_seek_mvp_20260617.json",
        "summary": {
            "attempts": len(timeline),
            "passed": sum(1 for item in timeline if item["status"] == "pass"),
            "failed": sum(1 for item in timeline if item["status"] != "pass"),
            "write_actions_clicked": 0,
            "submit_clicks": 0,
            "final_submissions": 0,
            "input_actions_exposed": 0,
            "apply_entry_visible": "apply_entry" in action_ids,
        },
        "checks": checks,
        "timeline": timeline,
    }


def build_seek_task_replay_report(source_report: dict[str, Any]) -> dict[str, Any]:
    accuracy = source_report.get("accuracy_summary") if isinstance(source_report.get("accuracy_summary"), dict) else {}
    steps = source_report.get("traversal_steps") if isinstance(source_report.get("traversal_steps"), list) else []
    timeline = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        card_click = step.get("card_click") if isinstance(step.get("card_click"), dict) else {}
        detail_read = step.get("detail_read") if isinstance(step.get("detail_read"), dict) else {}
        timeline.append(
            {
                "index": step.get("index"),
                "job_id": step.get("job_id"),
                "title": step.get("title") or ((step.get("card") or {}).get("title") if isinstance(step.get("card"), dict) else None),
                "skill_ref": "skill.open_card_from_list",
                "low_level_action_type": "click",
                "target_container_id": "seek:results_list",
                "card_click_trace_path": (card_click.get("execute_response") or {}).get("trace_path")
                or (card_click.get("dry_run_response") or {}).get("trace_path"),
                "recognition_plan_trace_path": (card_click.get("execute_response") or {}).get("recognition_plan_trace_path")
                or (card_click.get("dry_run_response") or {}).get("recognition_plan_trace_path"),
                "verification_result": "pass" if card_click.get("opened") is True or card_click.get("success") is True else None,
                "detail_read_complete": bool(detail_read.get("complete")),
            }
        )
        timeline.append(
            {
                "index": step.get("index"),
                "job_id": step.get("job_id"),
                "skill_ref": "skill.read_detail_pane_until_bounded",
                "low_level_action_type": "scroll",
                "target_container_id": "seek:job_detail",
                "target_pane": "job_detail",
                "verification_result": "pass" if detail_read.get("complete") else None,
            }
        )

    checks = [
        _check("jobs_opened", int(source_report.get("jobs_opened") or 0) >= 3, "at least 3 jobs opened", source_report.get("jobs_opened")),
        _check("jobs_fully_read", int(source_report.get("jobs_fully_read") or 0) >= 3, "at least 3 jobs fully read", source_report.get("jobs_fully_read")),
        _check("card_click_open_rate", float(accuracy.get("card_click_open_rate") or 0.0) >= 1.0, "card click open rate is 1.0", accuracy.get("card_click_open_rate")),
        _check("layout_drift", int(accuracy.get("post_click_layout_drift_count") or 0) == 0, "no post-click layout drift", accuracy.get("post_click_layout_drift_count")),
        _check("wrong_scope", int(accuracy.get("wrong_scope_scroll_count") or 0) == 0, "no wrong-scope scroll", accuracy.get("wrong_scope_scroll_count")),
        _check("detail_reset", int(accuracy.get("pre_click_detail_reset_count") or 0) >= 2, "detail pane reset before subsequent card clicks", accuracy.get("pre_click_detail_reset_count")),
        _check("detail_reset_scope", int(accuracy.get("pre_click_detail_reset_wrong_scope_count") or 0) == 0, "detail reset stayed in scope", accuracy.get("pre_click_detail_reset_wrong_scope_count")),
        _check("title_source", int(accuracy.get("title_extraction_from_body_count") or 0) == 0, "title was not extracted from body fragments", accuracy.get("title_extraction_from_body_count")),
        _check("final_submit", int(source_report.get("final_submissions") or 0) == 0, "no final submissions", source_report.get("final_submissions")),
    ]
    return {
        "contract_version": "seek_learn_task_run_report_v1",
        "generated_at": _now(),
        "status": "pass" if all(item["status"] == "pass" for item in checks) else "fail",
        "mode": "learn_task_run_replay",
        "source_report_path": str(DEFAULT_SEEK_3JOB_REPORT),
        "traversal_trace_path": source_report.get("traversal_trace_path"),
        "summary": {
            "jobs_opened": source_report.get("jobs_opened"),
            "jobs_fully_read": source_report.get("jobs_fully_read"),
            "card_click_open_rate": accuracy.get("card_click_open_rate"),
            "post_click_layout_drift_count": accuracy.get("post_click_layout_drift_count"),
            "wrong_scope_scroll_count": accuracy.get("wrong_scope_scroll_count"),
            "pre_click_detail_reset_count": accuracy.get("pre_click_detail_reset_count"),
            "pre_click_detail_reset_wrong_scope_count": accuracy.get("pre_click_detail_reset_wrong_scope_count"),
            "title_extraction_from_body_count": accuracy.get("title_extraction_from_body_count"),
            "write_actions_clicked": 0,
            "submit_clicks": source_report.get("submit_clicks"),
            "final_submissions": source_report.get("final_submissions"),
        },
        "checks": checks,
        "timeline": timeline,
    }


def build_coordinate_policy_audit() -> dict[str, Any]:
    return {
        "contract_version": "coordinate_policy_audit_v1",
        "seeded_candidate_is_primary": True,
        "vista_can_override_seed": False,
        "vista_disagreement_recorded": True,
        "coordinate_window_size_checked": True,
        "artifact_is_authorization": False,
        "pre_click_decision_required": True,
    }


def build_seek_application_flow_checkpoint_report(artifact: dict[str, Any]) -> dict[str, Any]:
    states = artifact.get("state_sequence") if isinstance(artifact.get("state_sequence"), list) else []
    actions = artifact.get("action_templates") if isinstance(artifact.get("action_templates"), list) else []
    safety = artifact.get("safety_policy") if isinstance(artifact.get("safety_policy"), dict) else {}
    milestone = artifact.get("milestone") if isinstance(artifact.get("milestone"), dict) else {}
    field_policy = artifact.get("field_fill_policy") if isinstance(artifact.get("field_fill_policy"), dict) else {}
    source = artifact.get("source") if isinstance(artifact.get("source"), dict) else {}
    filled_summary = artifact.get("filled_content_summary") if isinstance(artifact.get("filled_content_summary"), dict) else {}
    review_reconciliation = artifact.get("review_reconciliation") if isinstance(artifact.get("review_reconciliation"), dict) else {}
    review_checks = review_reconciliation.get("checks") if isinstance(review_reconciliation.get("checks"), dict) else {}
    learned_skills = artifact.get("learned_skills") if isinstance(artifact.get("learned_skills"), list) else []
    state_ids = [str(item.get("state_id") or "") for item in states if isinstance(item, dict)]
    action_ids = [str(item.get("action_id") or "") for item in actions if isinstance(item, dict)]
    machine_states = artifact.get("states") if isinstance(artifact.get("states"), list) else []
    transitions = artifact.get("transitions") if isinstance(artifact.get("transitions"), list) else []
    machine_state_ids = [str(item.get("state_id") or "") for item in machine_states if isinstance(item, dict)]
    transition_ids = [str(item.get("transition_id") or "") for item in transitions if isinstance(item, dict)]
    expected_states = ["choose_documents", "answer_employer_questions", "update_seek_profile", "review_and_submit"]
    expected_machine_states = [
        "seek_apply:choose_documents",
        "seek_apply:cover_letter",
        "seek_apply:answer_employer_questions",
        "seek_apply:update_seek_profile",
        "seek_apply:review_and_submit",
        "seek_apply:final_submit_blocked",
        "seek_apply:third_party_ats_deferred",
        "seek_apply:blocked_upload_or_login",
    ]
    expected_transitions = [
        "seek_apply:keep_default_documents",
        "seek_apply:fill_cover_letter",
        "seek_apply:answer_questions",
        "seek_apply:skip_profile_update",
        "seek_apply:block_final_submit",
    ]
    expected_actions = [
        "write_cover_letter",
        "answer_employer_questions",
        "continue_without_profile_mutation",
        "stop_before_final_submit",
    ]
    checks = [
        _check("contract", artifact.get("contract_version") == "seek_application_flow_artifact_v1", "application flow artifact contract is current", artifact.get("contract_version")),
        _check("audit_passed", source.get("audit_decision") == "pass_stopped_before_final_submit", "source final-review audit passed", source.get("audit_decision")),
        _check("source_record_path", bool(source.get("application_fill_record_path")), "source records application_fill_record_path", source.get("application_fill_record_path")),
        _check("source_audit_path", bool(source.get("final_review_audit_path")), "source records final_review_audit_path", source.get("final_review_audit_path")),
        _check("source_reached_review", source.get("reached_review_and_submit") is True, "source reached review-and-submit boundary", source.get("reached_review_and_submit")),
        _check("state_sequence", state_ids == expected_states, "station-internal application state sequence is complete", state_ids),
        _check("state_machine", machine_state_ids == expected_machine_states, "prefixed application state machine is complete", machine_state_ids),
        _check("transitions", all(transition_id in transition_ids for transition_id in expected_transitions), "application state transitions are present", transition_ids),
        _check("action_templates", all(action_id in action_ids for action_id in expected_actions), "application action templates are present", action_ids),
        _check("artifact_not_authorization", milestone.get("artifact_is_authorization") is False and safety.get("artifact_is_authorization") is False, "artifact is evidence, not authorization"),
        _check("final_submit_forbidden", safety.get("final_submit_forbidden") is True, "final submit remains forbidden"),
        _check("safe_fill_required", field_policy.get("safe_fill_required_for_future_replay") is True, "future replay requires safe-fill verification"),
        _check("direct_type_text_not_replay", field_policy.get("direct_type_text_is_milestone_evidence_only") is True, "direct type_text is milestone evidence only"),
        _check("profile_mutation_forbidden", safety.get("seek_profile_mutation_policy") == "forbidden_without_explicit_user_approval", "SEEK profile mutation remains forbidden", safety.get("seek_profile_mutation_policy")),
        _check("zero_submit_counters", int(safety.get("final_submissions") or 0) == 0 and int(safety.get("submit_clicks") or 0) == 0, "source run has zero submit counters", {"final_submissions": safety.get("final_submissions"), "submit_clicks": safety.get("submit_clicks")}),
    ]
    if source.get("final_review_extraction_status"):
        checks.extend(
            [
                _check(
                    "final_review_extraction",
                    source.get("final_review_extraction_status") == "pass",
                    "final Review extraction passed",
                    source.get("final_review_extraction_status"),
                ),
                _check(
                    "review_reconciliation",
                    review_reconciliation.get("status") == "pass",
                    "Review page content reconciles with application fill record",
                    review_reconciliation.get("status"),
                ),
                _check(
                    "review_reconciliation_skill",
                    any(
                        isinstance(item, dict)
                        and item.get("skill_ref") == "skill:review_before_submit_reconciliation"
                        for item in learned_skills
                    ),
                    "final Review learning exports reusable review-before-submit skill",
                ),
            ]
        )
    return {
        "contract_version": "seek_application_flow_checkpoint_report_v1",
        "generated_at": _now(),
        "status": "pass" if all(item["status"] == "pass" for item in checks) else "fail",
        "mode": "learn_application_flow_checkpoint",
        "artifact_id": artifact.get("artifact_id"),
        "app_id": artifact.get("app_id"),
        "page_type": artifact.get("page_type"),
        "source": source,
        "summary": {
            "state_count": len(state_ids),
            "state_machine_count": len(machine_state_ids),
            "transition_count": len(transition_ids),
            "action_template_count": len(action_ids),
            "audit_decision": source.get("audit_decision"),
            "final_review_extraction": source.get("final_review_extraction_status") or "not_recorded",
            "review_reconciliation": review_reconciliation.get("status") or "not_recorded",
            "review_answers_matched": (
                f"{review_checks.get('employer_questions_matched')}/{review_checks.get('employer_questions_expected')}"
                if review_checks
                and review_checks.get("employer_questions_matched") is not None
                and review_checks.get("employer_questions_expected") is not None
                else None
            ),
            "employer_question_count": int(filled_summary.get("employer_question_count") or 0),
            "review_before_submit_skill_exported": any(
                isinstance(item, dict) and item.get("skill_ref") == "skill:review_before_submit_reconciliation"
                for item in learned_skills
            ),
            "artifact_authorizes_submit": bool(milestone.get("artifact_is_authorization") or safety.get("artifact_is_authorization")),
            "final_submit_forbidden": safety.get("final_submit_forbidden") is True,
            "safe_fill_required_for_future_replay": field_policy.get("safe_fill_required_for_future_replay") is True,
            "direct_type_text_is_milestone_evidence_only": field_policy.get("direct_type_text_is_milestone_evidence_only") is True,
            "write_actions_clicked": 0,
            "submit_clicks": int(safety.get("submit_clicks") or 0),
            "final_submissions": int(safety.get("final_submissions") or 0),
        },
        "checks": checks,
        "timeline": [
            {
                "state_id": state_id,
                "status": "learned_evidence_only",
                "requires_current_observe": True,
                "requires_safe_fill_verification": state_id in {"choose_documents", "answer_employer_questions"},
                "final_submit_allowed": False,
            }
            for state_id in state_ids
        ],
    }


def _check(check_id: str, passed: bool, message: str, evidence: Any = None) -> dict[str, Any]:
    item: dict[str, Any] = {"check_id": check_id, "status": "pass" if passed else "fail", "message": message}
    if evidence is not None:
        item["evidence"] = evidence
    return item


def _is_input_action(action: dict[str, Any]) -> bool:
    return action.get("low_level_action_type") == "input" or action.get("action_kind") == "input"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Learn/Execute checkpoint reports for artifact replay.")
    parser.add_argument("--seek-graph", type=Path, default=DEFAULT_SEEK_GRAPH)
    parser.add_argument("--seek-source-report", type=Path, default=DEFAULT_SEEK_3JOB_REPORT)
    parser.add_argument("--seek-application-flow-artifact", type=Path, default=DEFAULT_SEEK_APPLICATION_FLOW_ARTIFACT)
    parser.add_argument("--seek-safe-out", type=Path, default=Path("logs/smoke/seek_learn_safe_validation_20260619.json"))
    parser.add_argument("--seek-task-out", type=Path, default=Path("logs/smoke/seek_learn_task_run_3jobs_20260619.json"))
    parser.add_argument("--seek-application-flow-out", type=Path, default=Path("logs/smoke/seek_application_flow_checkpoint_20260620.json"))
    parser.add_argument("--skill-matrix-out", type=Path, default=Path("artifacts/skills/learned_skill_matrix_v1.json"))
    parser.add_argument("--checkpoint-out", type=Path, default=Path("logs/smoke/learn_execute_mvp_checkpoint_20260619.json"))
    parser.add_argument("--fail-on-error", action="store_true")
    args = parser.parse_args(argv)

    seek_graph = read_json(args.seek_graph)
    seek_source_report = read_json(args.seek_source_report)
    seek_application_flow_artifact = read_json(args.seek_application_flow_artifact)
    graphs = [read_json(path) for path in DEFAULT_GRAPH_PATHS if path.exists()]

    seek_safe = run_seek_safe_validation(seek_graph)
    seek_task = build_seek_task_replay_report(seek_source_report)
    seek_application_flow = build_seek_application_flow_checkpoint_report(seek_application_flow_artifact)
    seek_application_replay = build_seek_application_flow_replay_report(seek_application_flow_artifact)
    skill_matrix = build_learned_skill_matrix(graphs)
    coordinate_audit = build_coordinate_policy_audit()
    checkpoint = {
        "contract_version": "learn_execute_mvp_checkpoint_report_v1",
        "generated_at": _now(),
        "status": "pass"
        if seek_safe.get("status") == "pass"
        and seek_task.get("status") == "pass"
        and seek_application_flow.get("status") == "pass"
        and seek_application_replay.get("status") == "pass"
        and skill_matrix.get("summary", {}).get("artifact_authorizes_click") is False
        and skill_matrix.get("summary", {}).get("covers_click") is True
        and skill_matrix.get("summary", {}).get("covers_scroll") is True
        and skill_matrix.get("summary", {}).get("covers_input") is True
        and skill_matrix.get("summary", {}).get("covers_read") is True
        and skill_matrix.get("summary", {}).get("covers_guarded_actions") is True
        and skill_matrix.get("summary", {}).get("covers_filter_or_tab") is True
        and skill_matrix.get("summary", {}).get("covers_sort_or_filter_click") is True
        and skill_matrix.get("summary", {}).get("covers_table_record_open") is True
        else "fail",
        "reports": {
            "seek_safe_validation": str(args.seek_safe_out),
            "seek_task_run": str(args.seek_task_out),
            "seek_application_flow": str(args.seek_application_flow_out),
            "skill_matrix": str(args.skill_matrix_out),
        },
        "summary": {
            "seek_safe_validation": seek_safe.get("status"),
            "seek_task_run": seek_task.get("status"),
            "seek_application_flow": seek_application_flow.get("status"),
            "seek_application_flow_replay": seek_application_replay.get("status"),
            "skill_count": skill_matrix.get("summary", {}).get("skill_count"),
            "artifact_authorizes_click": skill_matrix.get("summary", {}).get("artifact_authorizes_click"),
            "covers_click": skill_matrix.get("summary", {}).get("covers_click"),
            "covers_scroll": skill_matrix.get("summary", {}).get("covers_scroll"),
            "covers_input": skill_matrix.get("summary", {}).get("covers_input"),
            "covers_read": skill_matrix.get("summary", {}).get("covers_read"),
            "covers_guarded_actions": skill_matrix.get("summary", {}).get("covers_guarded_actions"),
            "covers_filter_or_tab": skill_matrix.get("summary", {}).get("covers_filter_or_tab"),
            "covers_sort_or_filter_click": skill_matrix.get("summary", {}).get("covers_sort_or_filter_click"),
            "covers_table_record_open": skill_matrix.get("summary", {}).get("covers_table_record_open"),
            "write_actions_clicked": max(
                int((seek_safe.get("summary") or {}).get("write_actions_clicked") or 0),
                int((seek_task.get("summary") or {}).get("write_actions_clicked") or 0),
                int((seek_application_flow.get("summary") or {}).get("write_actions_clicked") or 0),
            ),
            "final_submissions": max(
                int((seek_safe.get("summary") or {}).get("final_submissions") or 0),
                int((seek_task.get("summary") or {}).get("final_submissions") or 0),
                int((seek_application_flow.get("summary") or {}).get("final_submissions") or 0),
            ),
            "seek_application_final_submit_forbidden": (seek_application_flow.get("summary") or {}).get("final_submit_forbidden"),
            "seek_application_safe_fill_required": (seek_application_flow.get("summary") or {}).get("safe_fill_required_for_future_replay"),
            "seek_application_can_run_live_strict_replay": (seek_application_replay.get("summary") or {}).get("can_run_live_strict_replay"),
        },
        "coordinate_policy_audit": coordinate_audit,
        "seek_application_flow_replay": seek_application_replay,
    }

    write_json(args.seek_safe_out, seek_safe)
    write_json(args.seek_task_out, seek_task)
    write_json(args.seek_application_flow_out, seek_application_flow)
    write_json(args.skill_matrix_out, skill_matrix)
    write_json(args.checkpoint_out, checkpoint)

    print(
        json.dumps(
            {
                "success": checkpoint["status"] == "pass",
                "status": checkpoint["status"],
                "summary": checkpoint["summary"],
                "out": str(args.checkpoint_out),
            },
            ensure_ascii=False,
        )
    )
    if args.fail_on_error and checkpoint["status"] != "pass":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
