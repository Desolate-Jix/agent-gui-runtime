from __future__ import annotations

import json
from pathlib import Path

from app.learn.skill_matrix import build_learned_skill_matrix
from scripts.learn_execute_checkpoint_report import (
    build_coordinate_policy_audit,
    build_seek_application_flow_checkpoint_report,
    build_seek_task_replay_report,
    run_seek_safe_validation,
)


def _read_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def test_seek_safe_validation_covers_click_scroll_and_blocks_input_apply() -> None:
    graph = _read_json("artifacts/seek/runtime_path_graph_seek_mvp_20260617.json")

    report = run_seek_safe_validation(graph)

    assert report["contract_version"] == "seek_learn_safe_validation_report_v1"
    assert report["status"] == "pass"
    action_types = {item["action_template_id"]: item["low_level_action_type"] for item in report["timeline"]}
    assert action_types["open_job_card"] == "click"
    assert action_types["read_detail"] == "scroll"
    assert action_types["load_more_results"] == "scroll"
    assert report["summary"]["apply_entry_visible"] is False
    assert report["summary"]["input_actions_exposed"] == 0
    assert report["summary"]["final_submissions"] == 0


def test_seek_task_replay_report_preserves_3_job_execution_baseline() -> None:
    source_report = _read_json("logs/smoke/seek_artifact_replay_readonly_3job_20260619_after_reset.json")

    report = build_seek_task_replay_report(source_report)

    assert report["contract_version"] == "seek_learn_task_run_report_v1"
    assert report["status"] == "pass"
    assert report["summary"]["jobs_opened"] == 3
    assert report["summary"]["jobs_fully_read"] == 3
    assert report["summary"]["card_click_open_rate"] == 1.0
    assert report["summary"]["post_click_layout_drift_count"] == 0
    assert report["summary"]["wrong_scope_scroll_count"] == 0
    assert report["summary"]["final_submissions"] == 0
    assert {"click", "scroll"} <= {item["low_level_action_type"] for item in report["timeline"]}


def test_learned_skill_matrix_covers_execute_mode_common_skills() -> None:
    graphs = [
        _read_json("artifacts/seek/runtime_path_graph_seek_mvp_20260617.json"),
        _read_json("artifacts/wikipedia/runtime_path_graph_wikipedia_search_v1.json"),
        _read_json("artifacts/github/runtime_path_graph_github_issues_v1.json"),
        _read_json("artifacts/docs_search/runtime_path_graph_python_docs_search_v1.json"),
        _read_json("artifacts/table_directory/runtime_path_graph_table_directory_v1.json"),
    ]

    matrix = build_learned_skill_matrix(graphs)

    assert matrix["contract_version"] == "learned_skill_matrix_v1"
    assert matrix["summary"]["covers_click"] is True
    assert matrix["summary"]["covers_scroll"] is True
    assert matrix["summary"]["covers_input"] is True
    assert matrix["summary"]["covers_read"] is True
    assert matrix["summary"]["covers_guarded_actions"] is True
    assert matrix["summary"]["covers_filter_or_tab"] is True
    assert matrix["summary"]["covers_sort_or_filter_click"] is True
    assert matrix["summary"]["covers_table_record_open"] is True
    assert matrix["summary"]["artifact_authorizes_click"] is False
    input_skill = next(item for item in matrix["skills"] if item["skill_ref"] == "skill:safe_public_search_input")
    assert input_skill["used_by"] == ["python_docs"]
    assert input_skill["low_level_action_types"] == ["input"]
    assert "public_search_query" in input_skill["safety_scope"]
    table_open_skill = next(item for item in matrix["skills"] if item["skill_ref"] == "skill:open_record_from_table")
    assert table_open_skill["used_by"] == ["table_directory"]
    assert table_open_skill["low_level_action_types"] == ["click"]


def test_seek_application_flow_checkpoint_keeps_submit_forbidden_and_safe_fill_required() -> None:
    artifact = _read_json("artifacts/seek/learned_seek_application_flow_plexure_20260620.json")

    report = build_seek_application_flow_checkpoint_report(artifact)

    assert report["contract_version"] == "seek_application_flow_checkpoint_report_v1"
    assert report["status"] == "pass"
    assert report["summary"]["audit_decision"] == "pass_stopped_before_final_submit"
    assert report["summary"]["employer_question_count"] == 0
    assert report["summary"]["state_machine_count"] == 8
    assert report["summary"]["transition_count"] == 5
    assert report["summary"]["artifact_authorizes_submit"] is False
    assert report["summary"]["final_submit_forbidden"] is True
    assert report["summary"]["safe_fill_required_for_future_replay"] is True
    assert report["summary"]["direct_type_text_is_milestone_evidence_only"] is True
    assert report["summary"]["submit_clicks"] == 0
    assert report["summary"]["final_submissions"] == 0
    assert [item["state_id"] for item in report["timeline"]] == [
        "choose_documents",
        "answer_employer_questions",
        "update_seek_profile",
        "review_and_submit",
    ]
    assert all(item["final_submit_allowed"] is False for item in report["timeline"])
    check_ids = {item["check_id"] for item in report["checks"]}
    assert {"source_record_path", "source_audit_path", "source_reached_review", "state_machine", "transitions"} <= check_ids


def test_coordinate_policy_audit_keeps_artifact_as_evidence_not_authorization() -> None:
    audit = build_coordinate_policy_audit()

    assert audit["seeded_candidate_is_primary"] is True
    assert audit["vista_can_override_seed"] is False
    assert audit["vista_disagreement_recorded"] is True
    assert audit["coordinate_window_size_checked"] is True
    assert audit["artifact_is_authorization"] is False


def test_checkpoint_summary_exposes_readiness_gate_fields(tmp_path: Path) -> None:
    from scripts.learn_execute_checkpoint_report import main

    checkpoint_out = tmp_path / "checkpoint.json"
    exit_code = main(
        [
            "--seek-safe-out",
            str(tmp_path / "safe.json"),
            "--seek-task-out",
            str(tmp_path / "task.json"),
            "--seek-application-flow-out",
            str(tmp_path / "application-flow.json"),
            "--skill-matrix-out",
            str(tmp_path / "skills.json"),
            "--checkpoint-out",
            str(checkpoint_out),
            "--fail-on-error",
        ]
    )

    checkpoint = json.loads(checkpoint_out.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert checkpoint["status"] == "pass"
    assert checkpoint["seek_application_flow_replay"]["summary"]["employer_question_count"] == 0
    assert checkpoint["summary"]["seek_application_flow"] == "pass"
    assert checkpoint["summary"]["seek_application_flow_replay"] == "pass"
    assert checkpoint["summary"]["seek_application_final_submit_forbidden"] is True
    assert checkpoint["summary"]["seek_application_safe_fill_required"] is True
    assert checkpoint["summary"]["seek_application_can_run_live_strict_replay"] is True
    assert checkpoint["summary"]["artifact_authorizes_click"] is False
    assert checkpoint["summary"]["write_actions_clicked"] == 0
    assert checkpoint["summary"]["final_submissions"] == 0
