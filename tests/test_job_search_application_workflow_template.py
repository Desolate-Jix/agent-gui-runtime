from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = ROOT / "artifacts" / "templates" / "job_search_application_workflow_template_v1.json"
SKILL_PATH = ROOT / "artifacts" / "skills" / "job_search_application_workflow_skill_v1.json"


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_job_search_workflow_template_keeps_submit_forbidden() -> None:
    template = _read(TEMPLATE_PATH)

    assert template["contract_version"] == "path_graph_template_v1"
    assert template["template_version"] == "job_search_application_workflow_template_v1"
    assert template["artifact_is_authorization"] is False
    assert template["safety_policy"]["final_submit_forbidden"] is True
    assert template["safety_policy"]["strong_apply_required_before_application_entry"] is True
    assert template["safety_policy"]["external_ats_deferred"] is True
    assert template["smoke_acceptance"]["submit_clicks"] == 0
    assert template["smoke_acceptance"]["final_submissions"] == 0


def test_job_search_workflow_template_models_seek_learned_flow_boundaries() -> None:
    template = _read(TEMPLATE_PATH)

    transition_ids = {item["transition_id"] for item in template["transitions"]}
    assert {
        "job_search:select_job_card",
        "job_search:read_detail",
        "job_search:screen_job",
        "job_search:enter_internal_application",
        "job_search:defer_external_ats",
        "job_search:block_final_submit",
    } <= transition_ids

    enter_transition = next(
        item for item in template["transitions"] if item["transition_id"] == "job_search:enter_internal_application"
    )
    assert "screening_decision == 'strong_apply'" in enter_transition["conditions"]
    assert "application_surface == 'same_site_internal'" in enter_transition["conditions"]
    assert "entry_is_final_submit == false" in enter_transition["conditions"]

    children = {item["template_ref"] for item in template["child_templates"]}
    assert {"list_detail_path_pattern_v1", "multi_step_form_review_template_v1"} <= children


def test_job_search_application_skill_is_orchestration_not_authorization() -> None:
    skill = _read(SKILL_PATH)

    assert skill["contract_version"] == "learned_orchestration_skill_v1"
    assert skill["skill_ref"] == "skill:job_search_application_workflow"
    assert skill["source"]["template_path"] == "artifacts/templates/job_search_application_workflow_template_v1.json"
    assert skill["safety_policy"]["artifact_is_authorization"] is False
    assert skill["safety_policy"]["one_backend_step_at_a_time"] is True
    assert skill["safety_policy"]["final_submit_forbidden"] is True
    assert "final submit" in skill["scope"]["forbidden"]
    assert "external ATS form filling" in skill["scope"]["forbidden"]


def test_job_search_skill_records_company_screening_and_application_outputs() -> None:
    skill = _read(SKILL_PATH)

    assert {
        "job_record_v1",
        "company_record_v1",
        "job_screening_decision_v1",
        "application_fill_record_v1",
        "review_reconciliation_v1",
        "job_search_application_run_report_v1",
    } <= set(skill["outputs"])

    composed = set(skill["composed_skills"])
    assert {
        "skill:record_job_and_company_snapshot",
        "skill:screen_job_against_candidate_profile",
        "skill:review_before_submit_reconciliation",
        "skill:block_final_submit",
    } <= composed
