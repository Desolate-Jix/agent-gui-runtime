import json
from pathlib import Path

from scripts.run_model_learning_feedback_loop import evaluate_trial_acceptance, run_feedback_loop
from scripts.run_model_learning_template_benchmark import (
    LEARNING_TEMPLATE_REQUIRED_CONTRACT,
    _missing_required_field_reports,
    _required_field_validation,
    run_template_benchmark,
)
from scripts.run_model_learning_patch_retry import (
    build_missing_sections_patch_prompt_payload,
    merge_missing_sections_patch,
    post_merge_reject_reasons,
    validate_missing_sections_patch,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = PROJECT_ROOT / "artifacts" / "benchmarks" / "model_learning_template_dev_manifest_v1.json"
HOLDOUT_MANIFEST = PROJECT_ROOT / "artifacts" / "benchmarks" / "model_learning_template_holdout_manifest_v1.json"


def test_model_learning_template_benchmark_classifies_baseline_and_excludes_invalid(tmp_path):
    report = run_template_benchmark(MANIFEST, tmp_path / "baseline")

    assert report["attempted"] == 11
    assert report["usable_template_candidate"] == 1
    assert report["needs_human_review"] == 1
    assert report["invalid_cases"][0]["case_id"] == "invalid_fixture_checksum_mismatch"
    assert report["failure_category_counts"]["invalid_fixture"] == 1
    assert sum(1 for case in report["cases"] if case.get("fixture_status") == "valid") == 11
    assert report["source_breakdown"]["generated_template_source"]["fixture_only"] == 7
    assert report["source_breakdown"]["generated_template_source"]["recorded_model_output"] == 5
    assert report["source_breakdown"]["model_ability_denominator"]["attempted"] == 5


def test_missing_required_fields_triggers_strict_schema_trial_but_not_model_acceptance(tmp_path):
    report = run_feedback_loop(MANIFEST, tmp_path / "feedback", max_trials=1)

    trial = report["trials"][0]
    assert trial["changed_parameter"] == "prompt_profile"
    assert trial["new_value"] == "strict_schema"
    assert trial["failure_categories_targeted"] == ["missing_required_fields"]
    assert trial["accepted_for_runner_logic"] is True
    assert trial["accepted_for_model_ability"] is False
    assert trial["accepted"] is False
    assert trial["delta"]["missing_required_fields"] < 0
    assert trial["model_ability_delta"]["missing_required_fields"] == 0


def test_invalid_fixture_does_not_trigger_model_tuning(tmp_path):
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["cases"] = [
        case for case in manifest["cases"] if case["case_id"] == "invalid_fixture_checksum_mismatch"
    ]
    manifest_path = tmp_path / "invalid_only_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    report = run_feedback_loop(manifest_path, tmp_path / "feedback", max_trials=5)

    assert report["trials"] == []
    assert report["remaining_failure_categories"] == {"invalid_fixture": 1}


def test_unsafe_action_increase_rejects_candidate():
    baseline = _report(extra_unsafe_actions=0, loader_compatibility_failed=0)
    candidate = _report(extra_unsafe_actions=1, loader_compatibility_failed=0)

    decision = evaluate_trial_acceptance(baseline, candidate)

    assert decision == {"accepted": False, "reject_reason": "extra_unsafe_actions_increased"}


def test_alignment_improvement_with_unsafe_increase_rejects_candidate():
    baseline = _report(extra_unsafe_actions=0, score=0.5)
    candidate = _report(extra_unsafe_actions=1, score=0.9, usable_template_candidate=1)

    decision = evaluate_trial_acceptance(
        baseline,
        candidate,
        {
            "usable_template_candidate": 1,
            "needs_human_review": 0,
            "invalid_or_unsafe_template": 0,
            "loader_compatibility_failed": 0,
            "agent_usable_failed": 0,
            "extra_unsafe_actions": 1,
            "missing_required_fields": 0,
            "draft_reference_alignment_score": 0.4,
        },
    )

    assert decision["accepted"] is False
    assert decision["reject_reason"] == "extra_unsafe_actions_increased"


def test_loader_regression_rejects_candidate():
    baseline = _report(loader_compatibility_failed=0)
    candidate = _report(loader_compatibility_failed=1)

    decision = evaluate_trial_acceptance(baseline, candidate)

    assert decision == {"accepted": False, "reject_reason": "loader_compatibility_regressed"}


def test_raw_sensitive_value_leak_rejects_candidate():
    baseline = _report()
    candidate = _report(usable_template_candidate=1)
    candidate["cases"][0]["raw_value"] = "user@example.com"

    decision = evaluate_trial_acceptance(
        baseline,
        candidate,
        {
            "usable_template_candidate": 1,
            "needs_human_review": 0,
            "invalid_or_unsafe_template": 0,
            "loader_compatibility_failed": 0,
            "agent_usable_failed": 0,
            "extra_unsafe_actions": 0,
            "missing_required_fields": 0,
            "draft_reference_alignment_score": 0.1,
        },
    )

    assert decision == {"accepted": False, "reject_reason": "raw_sensitive_value_leak"}


def test_each_feedback_round_changes_one_parameter_and_accepted_trial_has_delta(tmp_path):
    report = run_feedback_loop(MANIFEST, tmp_path / "feedback", max_trials=5)

    assert report["trials"]
    for trial in report["trials"]:
        assert trial["changed_parameter"]
        assert trial["old_value"] != trial["new_value"]
        changed_keys = [
            key
            for key in ("prompt_profile", "retry_policy", "max_output_tokens", "temperature", "canonicalization")
            if key == trial["changed_parameter"]
        ]
        assert changed_keys == [trial["changed_parameter"]]
    runner_logic = [trial for trial in report["trials"] if trial["accepted_for_runner_logic"]]
    assert runner_logic
    assert not [trial for trial in report["trials"] if trial["accepted"]]
    for trial in runner_logic:
        delta = trial["delta"]
        assert (
            delta["usable_template_candidate"] > 0
            or delta["loader_compatibility_failed"] < 0
            or delta["agent_usable_failed"] < 0
            or delta["extra_unsafe_actions"] < 0
            or delta["missing_required_fields"] < 0
        )


def test_feedback_report_has_no_misleading_claim_words(tmp_path):
    report = run_feedback_loop(MANIFEST, tmp_path / "feedback", max_trials=5)
    text = json.dumps(report, ensure_ascii=False).casefold()

    assert "accuracy" not in text
    assert "success rate" not in text
    assert "seek e2e success" not in text


def test_feedback_loop_separates_dev_and_holdout_final_reruns(tmp_path):
    report = run_feedback_loop(
        MANIFEST,
        tmp_path / "feedback",
        holdout_manifest_path=HOLDOUT_MANIFEST,
        max_trials=5,
    )

    assert report["holdout_used_for_tuning"] is False
    assert report["selected_config_final_rerun"] is True
    assert report["dev_report"].replace("\\", "/").endswith(
        "dev_selected_final/model_learning_template_benchmark_report.json"
    )
    assert report["holdout_report"].replace("\\", "/").endswith(
        "holdout_selected_final/model_learning_template_benchmark_report.json"
    )
    for trial in report["trials"]:
        assert "holdout" not in trial["report_path"]


def test_selected_config_delta_tables_include_required_metrics(tmp_path):
    report = run_feedback_loop(
        MANIFEST,
        tmp_path / "feedback",
        holdout_manifest_path=HOLDOUT_MANIFEST,
        max_trials=5,
    )

    required = {
        "usable_template_candidate",
        "needs_human_review",
        "invalid_or_unsafe_template",
        "missing_required_fields",
        "extra_unsafe_actions",
        "loader_compatibility_failed",
        "agent_usable_failed",
        "hard_requirement_passed",
        "safety_violations",
        "invalid_fixtures_excluded",
    }
    assert required.issubset(report["baseline_vs_selected_delta"]["dev"])
    assert required.issubset(report["baseline_vs_selected_delta"]["holdout"])
    assert report["baseline_vs_selected_delta"]["dev"]["extra_unsafe_actions"]["selected"] == 1
    assert report["baseline_vs_selected_delta"]["holdout"]["extra_unsafe_actions"]["selected"] == 1
    assert report["dev_baseline_vs_selected"]["model_generated_only"] is True
    assert report["holdout_baseline_vs_selected"]["model_generated_only"] is True
    assert report["dev_baseline_vs_selected"]["delta"]["missing_required_fields"]["selected"] == 11


def test_reference_leakage_audit_and_source_breakdown(tmp_path):
    report = run_feedback_loop(
        MANIFEST,
        tmp_path / "feedback",
        holdout_manifest_path=HOLDOUT_MANIFEST,
        max_trials=5,
    )

    assert report["reference_leakage_audit"]["passed"] is True
    assert report["reference_leakage_audit"]["prompt_inputs_exclude_reference_template"] is True
    assert report["reference_leakage_audit"]["prompt_files_checked"] >= 8
    assert report["reference_leakage_audit"]["reference_read_stage"] == "scoring_only"
    assert report["source_breakdown"]["dev"]["model_ability_denominator"]["attempted"] == 5
    assert report["source_breakdown"]["holdout"]["model_ability_denominator"]["attempted"] == 3
    assert report["source_breakdown"]["holdout"]["generated_template_source"]["fixture_only"] == 6
    assert report["source_breakdown"]["holdout"]["generated_template_source"]["recorded_model_output"] == 3


def test_prompt_profile_safety_inheritance_keeps_hard_validator(tmp_path):
    report = run_feedback_loop(
        MANIFEST,
        tmp_path / "feedback",
        holdout_manifest_path=HOLDOUT_MANIFEST,
        max_trials=5,
    )

    audit = report["prompt_profile_safety_inheritance"]
    assert audit["passed"] is True
    assert audit["selected_prompt_profile"] == "baseline"
    assert audit["prompt_profile_is_not_the_safety_boundary"] is True
    assert audit["holdout_unsafe_action_still_detected"] is True


def test_model_generated_case_diagnosis_and_failure_taxonomy(tmp_path):
    report = run_feedback_loop(
        MANIFEST,
        tmp_path / "feedback",
        holdout_manifest_path=HOLDOUT_MANIFEST,
        max_trials=5,
    )

    diagnoses = report["model_generated_case_diagnosis"]["dev"] + report["model_generated_case_diagnosis"]["holdout"]
    assert len(diagnoses) == 8
    required = {
        "case_id",
        "source_type",
        "surface",
        "goal",
        "classification",
        "missing_required_fields",
        "required_field_retry_needed",
        "required_field_retry_executed",
        "retry_not_executed",
        "retry_not_executed_reason",
        "required_field_validation",
        "extra_unsafe_actions",
        "loader_compatibility_failed",
        "agent_usable_failed",
        "low_alignment_but_hard_requirements_passed",
        "raw_model_output_path",
        "parsed_template_path",
        "reference_template_path",
        "scoring_diff_path",
        "root_cause",
        "recommended_intervention",
    }
    assert required.issubset(diagnoses[0])
    assert all(item["source_type"] == "recorded_model_output" for item in diagnoses)
    assert all(item["scoring_diff_path"] for item in diagnoses)
    taxonomy = report["model_generated_failure_taxonomy"]
    assert taxonomy["missing_required_fields"]["count"] > 0
    assert "verification_rules" in taxonomy["missing_required_fields"]["common_missing_fields"]
    assert taxonomy["agent_usable_failed"]["count"] > 0
    assert "verification_rule_insufficient" in taxonomy["agent_usable_failed"]["common_root_causes"]


def test_required_field_post_validation_marks_retry_needed_without_fake_retry(tmp_path):
    report = run_template_benchmark(MANIFEST, tmp_path / "baseline")

    recorded_cases = [
        case
        for case in report["cases"]
        if case.get("fixture_status") == "valid"
        and case.get("generated_template_source") == "recorded_model_output"
    ]

    assert recorded_cases
    for case in recorded_cases:
        assert case["missing_required_fields"]
        assert case["required_field_retry_needed"] is True
        assert case["required_field_retry_executed"] is False
        assert case["retry_not_executed"] is True
        assert case["retry_not_executed_reason"] == "no_actual_model_call_or_recorded_output_per_config"
        assert case["usable_template_candidate"] is False
        validation = case["required_field_validation"]
        assert validation["passed"] is False
        assert validation["usable_blocked_until_required_fields_pass"] is True
        assert validation["result_source_if_deterministic_completion"] == "assisted_generation"


def test_required_field_contract_resolves_nested_schema_paths():
    draft = {
        "workflow_draft": {
            "states": [{"state_id": "s1"}],
            "action_templates": [{"action_template_id": "a1"}],
            "verification_rules": [{"rule_id": "v1"}],
        },
        "interface_draft": {
            "regions": [{"region_id": "r1"}],
        },
        "safety": {
            "observation_only": True,
            "promotion_allowed": False,
            "final_submit_blocked": True,
            "real_clicks_performed": 0,
            "blockers": [{"blocker_id": "final_submit"}],
        },
    }

    reports = _missing_required_field_reports(draft)

    assert [item["logical_field"] for item in reports if not item["found"]] == []
    assert LEARNING_TEMPLATE_REQUIRED_CONTRACT["action_templates"]["schema_paths"][0] == (
        "workflow_draft.action_templates"
    )


def test_required_field_contract_does_not_let_empty_safety_satisfy_blockers():
    draft = {
        "workflow_draft": {
            "states": [{"state_id": "s1"}],
            "action_templates": [{"action_template_id": "a1"}],
        },
        "interface_draft": {"regions": [{"region_id": "r1"}]},
        "safety": {
            "observation_only": True,
            "promotion_allowed": False,
            "final_submit_blocked": True,
            "real_clicks_performed": 0,
        },
    }

    reports = _missing_required_field_reports(draft)
    missing = {item["logical_field"]: item for item in reports if not item["found"]}

    assert set(missing) == {"blockers", "verification_rules"}
    assert missing["blockers"]["accepted_schema_paths"] == ["safety.blockers", "blockers"]
    assert missing["blockers"]["reason"] == "missing_required_section"


def test_required_field_validation_exposes_canonical_retry_plan():
    reports = _missing_required_field_reports({"workflow_draft": {}, "interface_draft": {}, "safety": {}})
    missing = [item["logical_field"] for item in reports if not item["found"]]

    validation = _required_field_validation(missing, "actual_model_call", field_reports=reports)

    assert validation["required_field_contract_version"] == "learning_template_required_contract_v1"
    assert validation["field_reports"] == reports
    assert validation["retry_plan"] == {
        "contract_version": "learning_template_required_field_retry_plan_v1",
        "retry_mode": "missing_sections_patch",
        "retry_executed": False,
        "missing_required_sections": [
            {
                "logical_field": "states",
                "target_schema_path": "workflow_draft.states",
                "accepted_schema_paths": ["workflow_draft.states", "states"],
            },
            {
                "logical_field": "regions",
                "target_schema_path": "interface_draft.regions",
                "accepted_schema_paths": ["interface_draft.regions", "regions"],
            },
            {
                "logical_field": "action_templates",
                "target_schema_path": "workflow_draft.action_templates",
                "accepted_schema_paths": ["workflow_draft.action_templates", "action_templates"],
            },
            {
                "logical_field": "safety_policy",
                "target_schema_path": "safety",
                "accepted_schema_paths": ["safety.policy", "safety_policy", "safety"],
            },
            {
                "logical_field": "blockers",
                "target_schema_path": "safety.blockers",
                "accepted_schema_paths": ["safety.blockers", "blockers"],
            },
            {
                "logical_field": "verification_rules",
                "target_schema_path": "workflow_draft.verification_rules",
                "accepted_schema_paths": ["workflow_draft.verification_rules", "verification_rules"],
            },
        ],
    }


def test_patch_retry_prompt_uses_missing_sections_without_reference_leakage():
    draft = _minimal_missing_patch_draft()
    reports = _missing_required_field_reports(draft)
    missing = [item["logical_field"] for item in reports if not item["found"]]
    validation = _required_field_validation(missing, "actual_model_call", field_reports=reports)

    payload = build_missing_sections_patch_prompt_payload(
        case_id="case_1",
        image_path="artifacts/example.png",
        original_draft=draft,
        required_field_validation=validation,
        hidden_reference_template={"secret": "do-not-copy"},
        scoring_diff={"checks_failed": [{"answer": "hidden"}]},
    )

    text = json.dumps(payload, ensure_ascii=False)
    assert payload["task"] == "repair_missing_required_sections_only"
    assert payload["missing_required_fields"] == ["blockers", "verification_rules"]
    assert "hidden_reference_template" not in text
    assert "do-not-copy" not in text
    assert "scoring_diff" not in text
    assert "hidden" not in text


def test_patch_schema_rejects_full_regenerated_template():
    retry_plan = {
        "missing_required_sections": [
            {"logical_field": "blockers", "target_schema_path": "safety.blockers"},
        ]
    }
    patch = {
        "contract_version": "learning_template_draft_v1",
        "workflow_draft": {"states": []},
        "patch_sections": {"blockers": []},
    }

    result = validate_missing_sections_patch(patch, retry_plan)

    assert result["status"] == "rejected"
    assert "full_template_regeneration_not_allowed" in result["reject_reasons"]


def test_patch_with_linked_blockers_and_verification_rules_is_accepted_and_merged():
    draft = _minimal_missing_patch_draft()
    reports = _missing_required_field_reports(draft)
    missing = [item["logical_field"] for item in reports if not item["found"]]
    validation = _required_field_validation(missing, "actual_model_call", field_reports=reports)
    patch = {
        "schema_version": "learning_template_missing_sections_patch_v1",
        "case_id": "case_1",
        "patch_sections": {
            "blockers": [
                {
                    "blocker_id": "final_submit_guard",
                    "applies_to_action_template_id": "a1",
                    "surface": "search_input_template",
                    "risk": "final_submit_or_wrong_surface",
                    "policy": "stop_or_request_review_before_submit_send_complete",
                }
            ],
            "verification_rules": [
                {
                    "rule_id": "verify_search_text_entered",
                    "applies_to_action_template_id": "a1",
                    "expected_observation": "search field contains requested query text",
                    "evidence_source": "post_action_observe_or_dom",
                }
            ],
        },
        "notes": [],
    }

    result = validate_missing_sections_patch(patch, validation["retry_plan"])
    merged = merge_missing_sections_patch(draft, patch, source_after_retry="mixed")

    assert result["status"] == "accepted"
    assert merged["safety"]["blockers"][0]["blocker_id"] == "final_submit_guard"
    assert merged["workflow_draft"]["verification_rules"][0]["rule_id"] == "verify_search_text_entered"
    assert merged["_source_tracking"]["source_after_retry"] == "mixed"
    assert merged["_source_tracking"]["patch_source"] == "actual_model_call_retry"
    assert merged["_source_tracking"]["counts_as_pure_model_generated"] is False


def test_patch_rejects_generic_unlinked_sections():
    retry_plan = {
        "missing_required_sections": [
            {"logical_field": "blockers", "target_schema_path": "safety.blockers"},
            {"logical_field": "verification_rules", "target_schema_path": "workflow_draft.verification_rules"},
        ]
    }
    patch = {
        "schema_version": "learning_template_missing_sections_patch_v1",
        "case_id": "case_1",
        "patch_sections": {
            "blockers": [{"blocker_id": "generic_blocker", "label": "be careful"}],
            "verification_rules": [{"rule_id": "generic_rule", "description": "verify it worked"}],
        },
    }

    result = validate_missing_sections_patch(patch, retry_plan)

    assert result["status"] == "rejected"
    assert "generic_or_unlinked_blockers" in result["reject_reasons"]
    assert "generic_or_unstructured_verification_rules" in result["reject_reasons"]


def test_patch_rejects_unrequested_sections_and_unsafe_actions():
    retry_plan = {
        "missing_required_sections": [
            {"logical_field": "blockers", "target_schema_path": "safety.blockers"},
        ]
    }
    patch = {
        "schema_version": "learning_template_missing_sections_patch_v1",
        "case_id": "case_1",
        "patch_sections": {
            "blockers": [
                {
                    "blocker_id": "b1",
                    "applies_to_action_template_id": "a1",
                    "surface": "search",
                    "risk": "wrong_surface",
                    "policy": "stop",
                }
            ],
            "verification_rules": [
                {
                    "rule_id": "v1",
                    "applies_to_action_template_id": "a1",
                    "expected_observation": "done",
                    "evidence_source": "observe",
                }
            ],
            "action_templates": [{"semantic_action": "final_submit", "label": "Submit"}],
        },
    }

    result = validate_missing_sections_patch(patch, retry_plan)

    assert result["status"] == "rejected"
    assert "unrequested_patch_sections" in result["reject_reasons"]
    assert "unsafe_action_in_patch" in result["reject_reasons"]


def test_rejected_patch_does_not_report_loader_regression_without_merge():
    reasons = post_merge_reject_reasons(
        patch_validation_status="rejected",
        existing_reject_reasons=["wrong_patch_schema_version"],
        before_unsafe=[],
        after_unsafe=[],
        before_loader={"passed": True},
        after_loader=None,
    )

    assert reasons == ["wrong_patch_schema_version"]


def test_recorded_outputs_without_per_config_do_not_accept_prompt_trials(tmp_path):
    report = run_feedback_loop(
        MANIFEST,
        tmp_path / "feedback",
        holdout_manifest_path=HOLDOUT_MANIFEST,
        max_trials=5,
    )

    assert report["actual_model_call"] == 0
    assert report["recorded_outputs_per_config"] is False
    assert report["model_ability_denominator"]["attempted"] == 8
    assert report["model_ability_denominator"]["prompt_config_improvement_attempted"] == 0
    assert report["feedback_loop_effectiveness"]["status"] == "evaluated_recorded_baseline_only_no_prompt_config_evidence"
    assert not [trial for trial in report["trials"] if trial["accepted"]]
    assert all(trial["accepted_for_model_ability"] is False for trial in report["trials"])


def test_fixture_only_improvement_is_not_reported_as_model_prompt_improvement(tmp_path):
    manifest = _fixture_only_manifest(tmp_path)

    report = run_feedback_loop(manifest, tmp_path / "feedback", max_trials=1)

    assert report["feedback_loop_effectiveness"]["status"] == "not_evaluated_for_model_ability"
    assert report["model_ability_denominator"]["attempted"] == 0
    assert report["model_ability_denominator"]["rate"] == "not_covered"
    assert report["trials"][0]["accepted_for_runner_logic"] is True
    assert report["trials"][0]["accepted_for_model_ability"] is False
    assert report["trials"][0]["accepted"] is False


def _report(
    *,
    usable_template_candidate=0,
    invalid_or_unsafe_template=0,
    loader_compatibility_failed=0,
    agent_usable_failed=0,
    extra_unsafe_actions=0,
    missing_required_fields=0,
    score=0.5,
):
    return {
        "attempted": 1,
        "usable_template_candidate": usable_template_candidate,
        "needs_human_review": 0,
        "invalid_or_unsafe_template": invalid_or_unsafe_template,
        "loader_compatibility_failed": loader_compatibility_failed,
        "agent_usable_failed": agent_usable_failed,
        "extra_unsafe_actions": extra_unsafe_actions,
        "missing_required_fields": missing_required_fields,
        "draft_reference_alignment_score": {"average": score},
        "cases": [{"fixture_status": "valid"}],
    }


def _fixture_only_manifest(tmp_path: Path) -> Path:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["cases"] = [
        case for case in manifest["cases"] if case.get("generated_template_source") == "fixture_only"
    ]
    path = tmp_path / "fixture_only_manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return path


def _minimal_missing_patch_draft():
    return {
        "contract_version": "learning_template_draft_v1",
        "image_size": {"width": 256, "height": 43},
        "learning_source": "observe_model",
        "screen_summary": "search field",
        "state_guess": "search_input_template",
        "workflow_draft": {
            "states": [{"state_id": "s1", "label": "search", "page_type": "search_input"}],
            "action_templates": [
                {
                    "action_template_id": "a1",
                    "label": "type query",
                    "semantic_action": "type_text",
                    "target_region_id": "r1",
                    "risk_level": "low",
                    "requires_gate": True,
                    "expected_effect": "populate search field",
                }
            ],
        },
        "interface_draft": {
            "regions": [{"region_id": "r1", "label": "search field", "role": "input"}],
        },
        "safety": {
            "observation_only": True,
            "promotion_allowed": False,
            "final_submit_blocked": True,
            "real_clicks_performed": 0,
        },
    }
