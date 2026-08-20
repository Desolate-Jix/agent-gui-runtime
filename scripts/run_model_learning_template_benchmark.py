from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.learn.model_artifact_loader import load_model_learning_artifact
from app.learn.model_trial import score_learning_template_draft


REQUIRED_TEMPLATE_FIELDS = (
    "states",
    "regions",
    "action_templates",
    "safety_policy",
    "blockers",
    "verification_rules",
)
LEARNING_TEMPLATE_REQUIRED_CONTRACT_VERSION = "learning_template_required_contract_v1"
LEARNING_TEMPLATE_REQUIRED_CONTRACT = {
    "states": {
        "target_schema_path": "workflow_draft.states",
        "schema_paths": ["workflow_draft.states", "states"],
        "required": True,
    },
    "regions": {
        "target_schema_path": "interface_draft.regions",
        "schema_paths": ["interface_draft.regions", "regions"],
        "required": True,
    },
    "action_templates": {
        "target_schema_path": "workflow_draft.action_templates",
        "schema_paths": ["workflow_draft.action_templates", "action_templates"],
        "required": True,
    },
    "safety_policy": {
        "target_schema_path": "safety",
        "schema_paths": ["safety.policy", "safety_policy", "safety"],
        "required": True,
    },
    "blockers": {
        "target_schema_path": "safety.blockers",
        "schema_paths": ["safety.blockers", "blockers"],
        "required": True,
    },
    "verification_rules": {
        "target_schema_path": "workflow_draft.verification_rules",
        "schema_paths": ["workflow_draft.verification_rules", "verification_rules"],
        "required": True,
    },
}
UNSAFE_ACTION_TERMS = (
    "submit",
    "send",
    "complete",
    "final apply",
    "final_submit",
)
MISLEADING_REPORT_TERMS = (
    "accuracy",
    "success rate",
    "seek e2e success",
)
MODEL_ABILITY_SOURCES = {"actual_model_call", "recorded_model_output", "recorded_output_per_config"}
PROMPT_CONFIG_IMPROVEMENT_SOURCES = {"actual_model_call", "recorded_output_per_config"}
ALLOWED_SOURCES = MODEL_ABILITY_SOURCES | {"fixture_only", "human_curated", "mixed", "assisted_generation"}
REQUIRED_FIELD_RETRY_POLICY = "one_targeted_missing_required_sections_retry"
NO_MODEL_RETRY_EVIDENCE_REASON = "no_actual_model_call_or_recorded_output_per_config"


def run_template_benchmark(
    manifest_path: str | Path,
    out_dir: str | Path,
    *,
    config: dict[str, Any] | None = None,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    manifest_file = _resolve_path(manifest_path, root)
    out_path = Path(out_dir)
    if not out_path.is_absolute():
        out_path = root / out_path
    out_path.mkdir(parents=True, exist_ok=True)

    manifest = _load_json(manifest_file)
    if not isinstance(manifest, dict):
        raise ValueError(f"{manifest_file} must contain a JSON object")
    config = _default_config(config)
    cases = manifest.get("cases") or []
    if not isinstance(cases, list):
        raise ValueError("manifest cases must be a list")

    results: list[dict[str, Any]] = []
    invalid_cases: list[dict[str, Any]] = []
    failure_category_counts: dict[str, int] = {}
    counters = {
        "attempted": 0,
        "usable_template_candidate": 0,
        "needs_human_review": 0,
        "invalid_or_unsafe_template": 0,
        "hard_requirement_passed": 0,
        "missing_required_fields": 0,
        "extra_unsafe_actions": 0,
        "loader_compatibility": 0,
        "agent_usable": 0,
        "loader_compatibility_failed": 0,
        "agent_usable_failed": 0,
        "safety_violations": 0,
    }
    score_values: list[float] = []
    source_breakdown = _empty_source_breakdown()
    model_ability_summary = _empty_model_ability_summary()
    model_generated_case_diagnosis: list[dict[str, Any]] = []

    for raw_case in cases:
        if not isinstance(raw_case, dict):
            continue
        case_result = _evaluate_case(raw_case, manifest_file, out_path, config, root)
        if case_result.get("fixture_status") == "invalid":
            invalid_cases.append(case_result)
            _bump(failure_category_counts, str(case_result.get("failure_category") or "invalid_fixture"))
            _record_source(source_breakdown, case_result, valid=False)
            results.append(case_result)
            continue

        counters["attempted"] += 1
        _record_source(source_breakdown, case_result, valid=True)
        if _is_model_ability_case(case_result):
            _record_model_ability_case(model_ability_summary, case_result)
            model_generated_case_diagnosis.append(_case_diagnosis(case_result))
        if case_result.get("hard_requirement_passed"):
            counters["hard_requirement_passed"] += 1
        counters["missing_required_fields"] += len(case_result.get("missing_required_fields") or [])
        counters["extra_unsafe_actions"] += len(case_result.get("extra_unsafe_actions") or [])
        counters["safety_violations"] += len(case_result.get("extra_unsafe_actions") or [])
        if case_result.get("loader_compatibility"):
            counters["loader_compatibility"] += 1
        else:
            counters["loader_compatibility_failed"] += 1
        if case_result.get("agent_usable"):
            counters["agent_usable"] += 1
        else:
            counters["agent_usable_failed"] += 1
        if case_result.get("usable_template_candidate"):
            counters["usable_template_candidate"] += 1
        if case_result.get("needs_human_review"):
            counters["needs_human_review"] += 1
        if case_result.get("invalid_or_unsafe_template"):
            counters["invalid_or_unsafe_template"] += 1
        for category in case_result.get("failure_categories") or []:
            _bump(failure_category_counts, str(category))
        score = case_result.get("draft_reference_alignment_score")
        if isinstance(score, (int, float)):
            score_values.append(float(score))
        results.append(case_result)

    report = {
        "contract_version": "model_learning_template_benchmark_report_v1",
        "generated_at": datetime.now().isoformat(),
        "manifest_path": _relative_path(manifest_file, root),
        "config": config,
        "attempted": counters["attempted"],
        "usable_template_candidate": counters["usable_template_candidate"],
        "needs_human_review": counters["needs_human_review"],
        "invalid_or_unsafe_template": counters["invalid_or_unsafe_template"],
        "draft_reference_alignment_score": {
            "metric_name": "draft_reference_alignment_score",
            "average": round(sum(score_values) / len(score_values), 4) if score_values else "not_covered",
            "attempted": len(score_values),
            "interpretation": "template similarity/alignment only; not model capability, click, gate, or SEEK E2E evidence",
        },
        "hard_requirement_passed": counters["hard_requirement_passed"],
        "missing_required_fields": counters["missing_required_fields"],
        "extra_unsafe_actions": counters["extra_unsafe_actions"],
        "safety_violations": counters["safety_violations"],
        "loader_compatibility": counters["loader_compatibility"],
        "agent_usable": counters["agent_usable"],
        "loader_compatibility_failed": counters["loader_compatibility_failed"],
        "agent_usable_failed": counters["agent_usable_failed"],
        "failure_category_counts": failure_category_counts,
        "source_breakdown": source_breakdown,
        "model_ability_denominator": source_breakdown["model_ability_denominator"],
        "model_ability_summary": model_ability_summary,
        "model_generated_case_diagnosis": model_generated_case_diagnosis,
        "model_generated_failure_taxonomy": _failure_taxonomy_summary(model_generated_case_diagnosis),
        "invalid_cases": invalid_cases,
        "cases": results,
        "report_policy": {
            "fixture_only": True,
            "no_live_submit": True,
            "no_live_safe_fill": True,
            "invalid_fixture_excluded_from_attempted": True,
        },
    }
    if _contains_misleading_terms(report):
        raise ValueError("benchmark report contains misleading wording")

    report_path = out_path / "model_learning_template_benchmark_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _evaluate_case(
    raw_case: dict[str, Any],
    manifest_file: Path,
    out_path: Path,
    config: dict[str, Any],
    root: Path,
) -> dict[str, Any]:
    case_id = str(raw_case.get("case_id") or "unnamed_case")
    fixture_errors = _validate_fixture(raw_case, manifest_file.parent, root)
    generated_path = _select_generated_path(raw_case, config)
    reference_path = raw_case.get("reference_template_path")
    screenshot_path = raw_case.get("screenshot_path")
    if generated_path is None:
        fixture_errors.append("generated_template_path_missing")
    if reference_path is None:
        fixture_errors.append("reference_template_path_missing")
    source_mode = _source_mode(raw_case)
    if source_mode in MODEL_ABILITY_SOURCES:
        for evidence_key in ("prompt_input_path", "raw_model_output_path", "model_config_path"):
            evidence_path = raw_case.get(evidence_key)
            if not evidence_path:
                fixture_errors.append(f"{evidence_key}_missing")
            elif not _resolve_path(str(evidence_path), root).exists():
                fixture_errors.append(f"{evidence_key}_not_found")
    if fixture_errors:
        return {
            "case_id": case_id,
            "fixture_status": "invalid",
            "failure_category": "invalid_fixture",
            "failure_reason": fixture_errors,
            "case_source": str(raw_case.get("case_source") or "fixture_only"),
            "generated_template_source": source_mode,
            "reference_template_source": str(raw_case.get("reference_template_source") or "human_curated_hidden"),
            "generated_template_path": generated_path,
            "reference_template_path": reference_path,
            "screenshot_path": screenshot_path,
        }

    generated_file = _resolve_path(str(generated_path), root)
    reference_file = _resolve_path(str(reference_path), root)
    draft = _load_json(generated_file)
    reference = _load_json(reference_file)
    target_contract = dict(raw_case.get("target_contract") or {})
    target_contract["reference_template"] = reference
    target_contract.setdefault("draft_reference_alignment_threshold", raw_case.get("draft_reference_alignment_threshold", 0.9))
    score_report = score_learning_template_draft(draft if isinstance(draft, dict) else {}, target_contract)
    alignment = float(score_report["draft_reference_alignment_score"]["score_ratio"])
    threshold = float(score_report["draft_reference_alignment_score"]["threshold"])

    field_reports = _missing_required_field_reports(draft)
    missing_fields = _missing_required_fields(draft)
    required_field_validation = _required_field_validation(missing_fields, source_mode, field_reports=field_reports)
    unsafe_actions = _extra_unsafe_actions(draft)
    scoring_diff = _scoring_diff(score_report)
    scoring_diff_path = _write_case_artifact(out_path, case_id, "scoring_diff.json", scoring_diff)
    loader_result = _check_loader_compatibility(draft, case_id, out_path, root)
    agent_result = _check_agent_usable(draft)
    hard_requirement_passed = not missing_fields
    failure_categories: list[str] = []
    if missing_fields:
        failure_categories.append("missing_required_fields")
    if unsafe_actions:
        failure_categories.append("extra_unsafe_actions")
    if not loader_result["passed"]:
        failure_categories.append("loader_compatibility_failed")
    if not agent_result["passed"]:
        failure_categories.append("agent_usable_failed")

    safety_ok = not unsafe_actions
    usable = (
        hard_requirement_passed
        and safety_ok
        and loader_result["passed"]
        and agent_result["passed"]
        and alignment >= threshold
    )
    needs_review = (
        hard_requirement_passed
        and safety_ok
        and loader_result["passed"]
        and agent_result["passed"]
        and alignment < threshold
    )
    if needs_review:
        failure_categories.append("low_alignment_but_hard_requirements_passed")

    return {
        "case_id": case_id,
        "fixture_status": "valid",
        "goal": raw_case.get("goal"),
        "case_source": str(raw_case.get("case_source") or "fixture_only"),
        "generated_template_source": _generated_template_source(raw_case, draft),
        "reference_template_source": str(raw_case.get("reference_template_source") or "human_curated_hidden"),
        "source_mode": source_mode,
        "prompt_input_path": raw_case.get("prompt_input_path"),
        "observe_trace_path": raw_case.get("observe_trace_path"),
        "model_config_path": raw_case.get("model_config_path"),
        "model_config": _report_model_config(raw_case.get("model_config")),
        "raw_model_output_path": raw_case.get("raw_model_output_path"),
        "parsed_generated_template_path": _relative_path(generated_file, root),
        "hidden_reference_path": _relative_path(reference_file, root),
        "generated_template_path": _relative_path(generated_file, root),
        "reference_template_path": _relative_path(reference_file, root),
        "screenshot_path": screenshot_path,
        "draft_reference_alignment_score": alignment,
        "draft_reference_alignment_threshold": threshold,
        "hard_requirement_passed": hard_requirement_passed,
        "missing_required_fields": missing_fields,
        "required_field_validation": required_field_validation,
        "required_field_retry_needed": required_field_validation["required_field_retry_needed"],
        "required_field_retry_executed": required_field_validation["required_field_retry_executed"],
        "retry_not_executed": required_field_validation["retry_not_executed"],
        "retry_not_executed_reason": required_field_validation["retry_not_executed_reason"],
        "extra_unsafe_actions": unsafe_actions,
        "safety_validator_result": {
            "passed": not unsafe_actions,
            "violations": unsafe_actions,
        },
        "scoring_diff": scoring_diff,
        "scoring_diff_path": _relative_path(scoring_diff_path, root),
        "loader_compatibility": loader_result["passed"],
        "loader_error": loader_result.get("error"),
        "agent_usable": agent_result["passed"],
        "agent_usable_errors": agent_result["errors"],
        "usable_template_candidate": usable,
        "needs_human_review": needs_review,
        "invalid_or_unsafe_template": not usable and not needs_review,
        "failure_categories": failure_categories,
        "failure_reason": failure_categories or None,
    }


def _validate_fixture(raw_case: dict[str, Any], manifest_dir: Path, root: Path) -> list[str]:
    errors: list[str] = []
    screenshot_path = raw_case.get("screenshot_path")
    screenshot_sha256 = raw_case.get("screenshot_sha256")
    for key in ("generated_template_path", "reference_template_path"):
        selected = raw_case.get(key)
        if not selected:
            continue
        try:
            if not _resolve_path(str(selected), root).exists():
                errors.append(f"{key}_not_found")
        except ValueError as exc:
            errors.append(f"{key}_invalid:{exc}")
    if screenshot_path:
        try:
            screenshot_file = _resolve_path(str(screenshot_path), root)
            if not screenshot_file.exists():
                errors.append("screenshot_not_found")
            elif screenshot_sha256:
                actual = _sha256_file(screenshot_file)
                if actual != screenshot_sha256:
                    errors.append("screenshot_checksum_mismatch")
        except ValueError as exc:
            errors.append(f"screenshot_path_invalid:{exc}")
    elif screenshot_sha256:
        errors.append("screenshot_path_missing")
    return errors


def _select_generated_path(raw_case: dict[str, Any], config: dict[str, Any]) -> str | None:
    for config_key, path_group_key in (
        ("prompt_profile", "generated_template_by_prompt_profile"),
        ("retry_policy", "generated_template_by_retry_policy"),
        ("canonicalization", "generated_template_by_canonicalization"),
    ):
        group = raw_case.get(path_group_key)
        value = config.get(config_key)
        if isinstance(group, dict) and value in group:
            return str(group[value])
    return str(raw_case["generated_template_path"]) if raw_case.get("generated_template_path") else None


def _missing_required_fields(draft: Any) -> list[str]:
    return [item["logical_field"] for item in _missing_required_field_reports(draft) if not item["found"]]


def _missing_required_field_reports(draft: Any) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    for logical_field in REQUIRED_TEMPLATE_FIELDS:
        contract = LEARNING_TEMPLATE_REQUIRED_CONTRACT[logical_field]
        accepted_paths = list(contract["schema_paths"])
        found_path = None
        if isinstance(draft, dict):
            for path in accepted_paths:
                if _required_field_path_has_content(logical_field, _path_get(draft, path)):
                    found_path = path
                    break
        reports.append(
            {
                "logical_field": logical_field,
                "accepted_schema_paths": accepted_paths,
                "target_schema_path": str(contract.get("target_schema_path") or accepted_paths[0]),
                "found": found_path is not None,
                "found_schema_path": found_path,
                "reason": "present" if found_path is not None else "missing_required_section",
            }
        )
    return reports


def _required_field_validation(
    missing_fields: list[str],
    source_mode: str,
    *,
    field_reports: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    retry_needed = bool(missing_fields)
    retry_capable_source = source_mode in PROMPT_CONFIG_IMPROVEMENT_SOURCES
    retry_not_executed_reason = None
    if retry_needed:
        retry_not_executed_reason = (
            "required_field_retry_output_not_available"
            if retry_capable_source
            else NO_MODEL_RETRY_EVIDENCE_REASON
        )
    return {
        "passed": not retry_needed,
        "required_fields": list(REQUIRED_TEMPLATE_FIELDS),
        "required_field_contract_version": LEARNING_TEMPLATE_REQUIRED_CONTRACT_VERSION,
        "required_field_contract": LEARNING_TEMPLATE_REQUIRED_CONTRACT,
        "field_reports": list(field_reports or _field_reports_from_missing(missing_fields)),
        "missing_required_fields": list(missing_fields),
        "retry_plan": _required_field_retry_plan(missing_fields),
        "required_field_retry_needed": retry_needed,
        "required_field_retry_policy": REQUIRED_FIELD_RETRY_POLICY if retry_needed else None,
        "required_field_retry_executed": False,
        "retry_not_executed": retry_needed,
        "retry_not_executed_reason": retry_not_executed_reason,
        "retry_capable_source": retry_capable_source,
        "eligible_retry_sources": sorted(PROMPT_CONFIG_IMPROVEMENT_SOURCES),
        "result_source_if_deterministic_completion": "assisted_generation",
        "usable_blocked_until_required_fields_pass": retry_needed,
    }


def _required_field_retry_plan(missing_fields: list[str]) -> dict[str, Any] | None:
    if not missing_fields:
        return None
    return {
        "contract_version": "learning_template_required_field_retry_plan_v1",
        "retry_mode": "missing_sections_patch",
        "retry_executed": False,
        "missing_required_sections": [
            {
                "logical_field": field,
                "target_schema_path": str(
                    LEARNING_TEMPLATE_REQUIRED_CONTRACT[field].get("target_schema_path")
                    or LEARNING_TEMPLATE_REQUIRED_CONTRACT[field]["schema_paths"][0]
                ),
                "accepted_schema_paths": list(LEARNING_TEMPLATE_REQUIRED_CONTRACT[field]["schema_paths"]),
            }
            for field in missing_fields
        ],
    }


def _field_reports_from_missing(missing_fields: list[str]) -> list[dict[str, Any]]:
    missing = set(missing_fields)
    reports: list[dict[str, Any]] = []
    for logical_field in REQUIRED_TEMPLATE_FIELDS:
        accepted_paths = list(LEARNING_TEMPLATE_REQUIRED_CONTRACT[logical_field]["schema_paths"])
        reports.append(
            {
                "logical_field": logical_field,
                "accepted_schema_paths": accepted_paths,
                "target_schema_path": str(
                    LEARNING_TEMPLATE_REQUIRED_CONTRACT[logical_field].get("target_schema_path") or accepted_paths[0]
                ),
                "found": logical_field not in missing,
                "found_schema_path": None,
                "reason": "missing_required_section" if logical_field in missing else "present",
            }
        )
    return reports


def _required_field_path_has_content(logical_field: str, value: Any) -> bool:
    if logical_field in {"states", "regions", "action_templates", "blockers", "verification_rules"}:
        return bool(_list_of_dicts(value))
    if logical_field == "safety_policy":
        if not isinstance(value, dict):
            return False
        if any(key in value for key in ("policy_id", "rules", "allowed_actions", "blocked_actions")):
            return True
        return all(
            key in value
            for key in ("observation_only", "promotion_allowed", "final_submit_blocked", "real_clicks_performed")
        )
    return value not in (None, "", [], {})


def _path_get(payload: dict[str, Any], dotted_path: str) -> Any:
    current: Any = payload
    for part in dotted_path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _extra_unsafe_actions(draft: Any) -> list[dict[str, Any]]:
    if not isinstance(draft, dict):
        return []
    workflow = draft.get("workflow_draft") if isinstance(draft.get("workflow_draft"), dict) else {}
    interface = draft.get("interface_draft") if isinstance(draft.get("interface_draft"), dict) else {}
    candidates = list(_list_of_dicts(workflow.get("action_templates")))
    candidates.extend(_list_of_dicts(interface.get("danger_zones")))
    unsafe: list[dict[str, Any]] = []
    for item in candidates:
        haystack = " ".join(
            str(item.get(key) or "")
            for key in ("action_template_id", "label", "semantic_action", "description")
        ).casefold()
        if not any(term in haystack for term in UNSAFE_ACTION_TERMS):
            continue
        blocked = bool(item.get("hard_block")) and bool(item.get("final_submit_guard_required"))
        blocked = blocked or (item.get("fast_lane_allowed") is False and item.get("semantic_action") == "final_submit")
        if not blocked:
            unsafe.append(
                {
                    "action_template_id": item.get("action_template_id") or item.get("zone_id"),
                    "label": item.get("label"),
                    "semantic_action": item.get("semantic_action"),
                    "reason": "final_or_send_action_not_hard_blocked",
                }
            )
    return unsafe


def _check_loader_compatibility(draft: Any, case_id: str, out_path: Path, root: Path) -> dict[str, Any]:
    trial_parent = out_path / "loader_trials"
    try:
        relative = trial_parent.resolve().relative_to(root)
        if relative.parts[:1] not in (("logs",), ("artifacts",)):
            raise ValueError("loader trial path is outside allowed project evidence dirs")
    except ValueError:
        out_hash = hashlib.sha256(str(out_path.resolve()).encode("utf-8")).hexdigest()[:12]
        trial_parent = root / "logs" / "benchmarks" / "model_learning_template_loader_trials" / out_hash
    trial_dir = trial_parent / _safe_name(case_id)
    trial_dir.mkdir(parents=True, exist_ok=True)
    trial_path = trial_dir / "trial_result.json"
    trial = {
        "contract_version": "learning_model_trial_v1",
        "app_name": "model_learning_benchmark",
        "status": "passed",
        "best_attempt_index": 0,
        "best_learning_draft": draft,
        "attempts": [{"parsed_result": draft}],
        "safety": {"posthoc_optimization_allowed": False},
    }
    trial_path.write_text(json.dumps(trial, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        loaded = load_model_learning_artifact(trial_path, project_root=root)
        summary = loaded.get("summary") if isinstance(loaded, dict) else {}
        if not summary or not summary.get("state_count") or not summary.get("region_count"):
            return {"passed": False, "error": "loader_output_missing_states_or_regions"}
        return {"passed": True, "error": None}
    except Exception as exc:
        return {"passed": False, "error": str(exc)}


def _check_agent_usable(draft: Any) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(draft, dict):
        return {"passed": False, "errors": ["draft_not_object"]}
    workflow = draft.get("workflow_draft") if isinstance(draft.get("workflow_draft"), dict) else {}
    actions = _list_of_dicts(workflow.get("action_templates"))
    verification_rules = _list_of_dicts(draft.get("verification_rules"))
    if not verification_rules:
        errors.append("verification_rules_missing")
    actionable = [
        item
        for item in actions
        if item.get("semantic_action") not in ("final_submit", "send", "complete")
        and not item.get("hard_block")
    ]
    if not actionable:
        errors.append("no_non_destructive_action_template")
    for item in actionable:
        if not item.get("semantic_action"):
            errors.append("action_template_missing_semantic_action")
        if not (item.get("target_region_id") or item.get("region_id") or item.get("target") or item.get("candidate_selector")):
            errors.append(f"action_template_missing_target:{item.get('action_template_id')}")
        if not (item.get("expected_effect") or item.get("verification_rule_id")):
            errors.append(f"action_template_missing_verification:{item.get('action_template_id')}")
    return {"passed": not errors, "errors": sorted(set(errors))}


def _write_case_artifact(out_path: Path, case_id: str, filename: str, payload: dict[str, Any]) -> Path:
    case_dir = out_path / "case_diagnostics" / _safe_name(case_id)
    case_dir.mkdir(parents=True, exist_ok=True)
    path = case_dir / filename
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _case_diagnosis(case_result: dict[str, Any]) -> dict[str, Any]:
    root_cause = _root_cause(case_result)
    intervention = _recommended_intervention(root_cause)
    return {
        "case_id": case_result.get("case_id"),
        "source_type": case_result.get("generated_template_source"),
        "surface": _surface_from_case(case_result),
        "goal": case_result.get("goal"),
        "classification": _classification(case_result),
        "missing_required_fields": case_result.get("missing_required_fields") or [],
        "required_field_retry_needed": bool(case_result.get("required_field_retry_needed")),
        "required_field_retry_executed": bool(case_result.get("required_field_retry_executed")),
        "retry_not_executed": bool(case_result.get("retry_not_executed")),
        "retry_not_executed_reason": case_result.get("retry_not_executed_reason"),
        "required_field_validation": case_result.get("required_field_validation") or {},
        "extra_unsafe_actions": case_result.get("extra_unsafe_actions") or [],
        "loader_compatibility_failed": not bool(case_result.get("loader_compatibility")),
        "agent_usable_failed": not bool(case_result.get("agent_usable")),
        "low_alignment_but_hard_requirements_passed": "low_alignment_but_hard_requirements_passed"
        in (case_result.get("failure_categories") or []),
        "raw_model_output_path": case_result.get("raw_model_output_path"),
        "parsed_template_path": case_result.get("parsed_generated_template_path")
        or case_result.get("generated_template_path"),
        "reference_template_path": case_result.get("hidden_reference_path")
        or case_result.get("reference_template_path"),
        "scoring_diff_path": case_result.get("scoring_diff_path"),
        "root_cause": root_cause,
        "recommended_intervention": intervention,
    }


def _surface_from_case(case_result: dict[str, Any]) -> str:
    text = " ".join(str(case_result.get(key) or "") for key in ("case_id", "goal", "screenshot_path")).casefold()
    if "python" in text or "homepage" in text:
        return "homepage_search_surface"
    if "search" in text:
        return "search_input_template"
    if "detail" in text:
        return "job_detail_template"
    if "apply" in text:
        return "apply_entry_template"
    if "submit" in text or "complete" in text:
        return "final_submit_blocker_template"
    return "unknown_surface"


def _classification(case_result: dict[str, Any]) -> str:
    if case_result.get("usable_template_candidate"):
        return "usable_template_candidate"
    if case_result.get("needs_human_review"):
        return "needs_human_review"
    if case_result.get("extra_unsafe_actions"):
        return "invalid_or_unsafe_template"
    if case_result.get("invalid_or_unsafe_template"):
        return "invalid_or_unsafe_template"
    return "not_agent_usable_template"


def _root_cause(case_result: dict[str, Any]) -> dict[str, Any]:
    missing = list(case_result.get("missing_required_fields") or [])
    agent_errors = list(case_result.get("agent_usable_errors") or [])
    unsafe = list(case_result.get("extra_unsafe_actions") or [])
    loader_error = case_result.get("loader_error")
    causes: list[str] = []
    if missing:
        causes.append("missing_required_fields")
    if any("missing_target" in item for item in agent_errors):
        causes.append("action_region_linkage_missing")
    if any("missing_verification" in item or item == "verification_rules_missing" for item in agent_errors):
        causes.append("verification_rule_insufficient")
    if any("missing_semantic_action" in item for item in agent_errors):
        causes.append("action_semantic_type_missing")
    if unsafe:
        causes.append("extra_unsafe_actions")
    if loader_error:
        causes.append("loader_compatibility_failed")
    if not causes and case_result.get("needs_human_review"):
        causes.append("low_alignment_but_hard_requirements_passed")
    return {
        "primary": causes[0] if causes else "none",
        "all": causes,
        "missing_required_fields": missing,
        "agent_usable_errors": agent_errors,
        "loader_error": loader_error,
        "unsafe_action_types": [_unsafe_action_type(item) for item in unsafe],
    }


def _recommended_intervention(root_cause: dict[str, Any]) -> list[str]:
    interventions: list[str] = []
    causes = set(root_cause.get("all") or [])
    missing = set(root_cause.get("missing_required_fields") or [])
    if missing:
        interventions.append("stronger_schema_checklist")
        interventions.append("required_field_post_validation_retry")
    if {"safety_policy", "blockers"} & missing:
        interventions.append("hard_safety_validator")
    if "verification_rules" in missing or "verification_rule_insufficient" in causes:
        interventions.append("agent_usable_checklist")
        interventions.append("dry_run_compatibility_validator")
    if "action_region_linkage_missing" in causes:
        interventions.append("action_region_linking_validator")
    if "extra_unsafe_actions" in causes:
        interventions.append("unsafe_action_post_filter")
        interventions.append("submit_vocabulary_blocker")
    if "loader_compatibility_failed" in causes:
        interventions.append("schema_canonicalization")
        interventions.append("field_normalizer")
    if root_cause.get("primary") == "low_alignment_but_hard_requirements_passed":
        interventions.append("human_review_or_rubric_mismatch_adjudication")
    return sorted(set(interventions))


def _unsafe_action_type(item: dict[str, Any]) -> str:
    text = " ".join(str(item.get(key) or "") for key in ("label", "semantic_action", "action_template_id")).casefold()
    if "send" in text:
        return "send_as_click"
    if "complete" in text:
        return "complete_as_click"
    if "submit" in text:
        return "submit_as_click"
    if "final" in text:
        return "final_apply_as_click"
    return "unsafe_action"


def _failure_taxonomy_summary(diagnoses: list[dict[str, Any]]) -> dict[str, Any]:
    missing_counter: dict[str, int] = {}
    root_counter: dict[str, int] = {}
    unsafe_counter: dict[str, int] = {}
    schema_errors: dict[str, int] = {}
    missing_count = 0
    agent_count = 0
    unsafe_count = 0
    loader_count = 0
    for item in diagnoses:
        missing = item.get("missing_required_fields") or []
        if missing:
            missing_count += 1
        for field in missing:
            _bump(missing_counter, str(field))
        root = item.get("root_cause") if isinstance(item.get("root_cause"), dict) else {}
        for cause in root.get("all") or []:
            _bump(root_counter, str(cause))
        if item.get("agent_usable_failed"):
            agent_count += 1
        unsafe = item.get("extra_unsafe_actions") or []
        if unsafe:
            unsafe_count += 1
        for action in unsafe:
            _bump(unsafe_counter, _unsafe_action_type(action))
        if item.get("loader_compatibility_failed"):
            loader_count += 1
            _bump(schema_errors, str(root.get("loader_error") or "loader_error"))
    return {
        "missing_required_fields": {
            "count": missing_count,
            "common_missing_fields": _sorted_counter_keys(missing_counter),
        },
        "agent_usable_failed": {
            "count": agent_count,
            "common_root_causes": _sorted_counter_keys(root_counter),
        },
        "extra_unsafe_actions": {
            "count": unsafe_count,
            "unsafe_action_types": _sorted_counter_keys(unsafe_counter),
        },
        "loader_compatibility_failed": {
            "count": loader_count,
            "schema_errors": _sorted_counter_keys(schema_errors),
        },
    }


def _sorted_counter_keys(counter: dict[str, int]) -> list[str]:
    return [key for key, _ in sorted(counter.items(), key=lambda item: (-item[1], item[0]))]


def _default_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = {
        "max_output_tokens": 2048,
        "temperature": 0.0,
        "prompt_profile": "baseline",
        "retry_policy": "none",
        "canonicalization": "off",
    }
    if config:
        merged.update(config)
    return merged


def _source_mode(raw_case: dict[str, Any]) -> str:
    value = str(raw_case.get("generated_template_source") or raw_case.get("case_source") or "fixture_only")
    return value if value in ALLOWED_SOURCES else "fixture_only"


def _generated_template_source(raw_case: dict[str, Any], draft: Any) -> str:
    case_source = raw_case.get("generated_template_source")
    if case_source:
        value = str(case_source)
        return value if value in ALLOWED_SOURCES else "fixture_only"
    if isinstance(draft, dict):
        tracking = draft.get("_source_tracking")
        if isinstance(tracking, dict) and tracking.get("template_source"):
            value = str(tracking["template_source"])
            return value if value in ALLOWED_SOURCES else "fixture_only"
    return "fixture_only"


def _report_model_config(config: Any) -> dict[str, Any] | None:
    if not isinstance(config, dict):
        return None
    learning = config.get("learning_parameters") if isinstance(config.get("learning_parameters"), dict) else {}
    return {
        "source_kind": config.get("source_kind"),
        "trial_path": config.get("trial_path"),
        "learning_model_profile_id": learning.get("learning_model_profile_id"),
        "max_output_tokens": learning.get("max_output_tokens"),
        "temperature": learning.get("temperature"),
        "prompt_detail_mode": learning.get("prompt_detail_mode"),
        "model_provider": config.get("model_provider"),
        "model_name": config.get("model_name"),
        "result_kind": config.get("result_kind"),
        "quality_score_applicable": config.get("quality_score_applicable"),
    }


def _empty_source_breakdown() -> dict[str, Any]:
    return {
        "case_source": {},
        "generated_template_source": {},
        "reference_template_source": {},
        "valid_cases": 0,
        "invalid_cases": 0,
        "model_ability_denominator": {
            "attempted": 0,
            "rate": "not_covered",
            "eligible_sources": sorted(MODEL_ABILITY_SOURCES),
            "interpretation": "only actual_model_call or compliant recorded_model_output valid cases can support model-learning capability claims",
        },
    }


def _record_source(breakdown: dict[str, Any], case_result: dict[str, Any], *, valid: bool) -> None:
    if valid:
        breakdown["valid_cases"] += 1
    else:
        breakdown["invalid_cases"] += 1
    for key in ("case_source", "generated_template_source", "reference_template_source"):
        value = str(case_result.get(key) or "fixture_only")
        bucket = breakdown[key]
        bucket[value] = bucket.get(value, 0) + 1
    if valid and _is_model_ability_case(case_result):
        breakdown["model_ability_denominator"]["attempted"] += 1
        breakdown["model_ability_denominator"]["rate"] = "covered"


def _empty_model_ability_summary() -> dict[str, Any]:
    return {
        "attempted": 0,
        "usable_template_candidate": 0,
        "needs_human_review": 0,
        "invalid_or_unsafe_template": 0,
        "hard_requirement_passed": 0,
        "missing_required_fields": 0,
        "extra_unsafe_actions": 0,
        "safety_violations": 0,
        "loader_compatibility_failed": 0,
        "agent_usable_failed": 0,
        "source_modes": {},
    }


def _record_model_ability_case(summary: dict[str, Any], case_result: dict[str, Any]) -> None:
    summary["attempted"] += 1
    if case_result.get("usable_template_candidate"):
        summary["usable_template_candidate"] += 1
    if case_result.get("needs_human_review"):
        summary["needs_human_review"] += 1
    if case_result.get("invalid_or_unsafe_template"):
        summary["invalid_or_unsafe_template"] += 1
    if case_result.get("hard_requirement_passed"):
        summary["hard_requirement_passed"] += 1
    summary["missing_required_fields"] += len(case_result.get("missing_required_fields") or [])
    summary["extra_unsafe_actions"] += len(case_result.get("extra_unsafe_actions") or [])
    summary["safety_violations"] += len(case_result.get("extra_unsafe_actions") or [])
    if not case_result.get("loader_compatibility"):
        summary["loader_compatibility_failed"] += 1
    if not case_result.get("agent_usable"):
        summary["agent_usable_failed"] += 1
    source = str(case_result.get("generated_template_source") or "fixture_only")
    summary["source_modes"][source] = summary["source_modes"].get(source, 0) + 1


def _is_model_ability_case(case_result: dict[str, Any]) -> bool:
    return str(case_result.get("generated_template_source")) in MODEL_ABILITY_SOURCES


def _scoring_diff(score_report: dict[str, Any]) -> dict[str, Any]:
    return {
        "section_scores": score_report.get("section_scores", {}),
        "template_similarity": score_report.get("template_similarity", {}),
        "checks_failed": [
            {
                "check_id": item.get("check_id"),
                "severity": item.get("severity"),
                "score_ratio": item.get("score_ratio"),
            }
            for item in score_report.get("checks", [])
            if isinstance(item, dict) and not item.get("passed")
        ],
    }


def _metric_delta(candidate: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "usable_template_candidate",
        "needs_human_review",
        "invalid_or_unsafe_template",
        "loader_compatibility_failed",
        "agent_usable_failed",
        "extra_unsafe_actions",
        "missing_required_fields",
        "hard_requirement_passed",
        "safety_violations",
    )
    delta = {key: int(candidate.get(key) or 0) - int(baseline.get(key) or 0) for key in keys}
    base_score = baseline.get("draft_reference_alignment_score", {}).get("average")
    candidate_score = candidate.get("draft_reference_alignment_score", {}).get("average")
    if isinstance(base_score, (int, float)) and isinstance(candidate_score, (int, float)):
        delta["draft_reference_alignment_score"] = round(float(candidate_score) - float(base_score), 4)
    else:
        delta["draft_reference_alignment_score"] = "not_comparable"
    return delta


def _contains_misleading_terms(report: dict[str, Any]) -> bool:
    text = json.dumps(report, ensure_ascii=False).casefold()
    text = text.replace("direct_use_accuracy_threshold", "legacy_threshold_field")
    allowed = "not model capability, click, gate, or seek e2e evidence"
    for term in MISLEADING_REPORT_TERMS:
        if term in text and allowed not in text:
            return True
    return False


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _resolve_path(path: str | Path, root: Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    return candidate.resolve()


def _relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value)[:120] or "case"


def _bump(counter: dict[str, int], key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--config-json")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    config = json.loads(args.config_json) if args.config_json else None
    report = run_template_benchmark(args.manifest, args.out, config=config)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(Path(args.out) / "model_learning_template_benchmark_report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
