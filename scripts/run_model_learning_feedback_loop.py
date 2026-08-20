from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_model_learning_template_benchmark import (
    _contains_misleading_terms,
    _default_config,
    _metric_delta,
    MODEL_ABILITY_SOURCES,
    PROMPT_CONFIG_IMPROVEMENT_SOURCES,
    run_template_benchmark,
)


STRATEGY_PLAN = (
    {
        "failure_category": "missing_required_fields",
        "changed_parameter": "prompt_profile",
        "new_value": "strict_schema",
        "reason": "add required-field checklist and schema reminder",
    },
    {
        "failure_category": "extra_unsafe_actions",
        "changed_parameter": "prompt_profile",
        "new_value": "safety_first",
        "reason": "emphasize final-submit blocker and unsafe-action classifier",
    },
    {
        "failure_category": "loader_compatibility_failed",
        "changed_parameter": "retry_policy",
        "new_value": "retry_schema_repair_once",
        "reason": "repair schema/type issues once without changing benchmark samples",
    },
    {
        "failure_category": "agent_usable_failed",
        "changed_parameter": "prompt_profile",
        "new_value": "agent_usable_checklist",
        "reason": "require region/action links and verification rules for dry-run use",
    },
    {
        "failure_category": "low_alignment_but_hard_requirements_passed",
        "changed_parameter": "prompt_profile",
        "new_value": "evidence_first",
        "reason": "increase evidence coverage while keeping human-review route",
    },
)


def run_feedback_loop(
    manifest_path: str | Path,
    out_dir: str | Path,
    *,
    holdout_manifest_path: str | Path | None = None,
    max_trials: int = 5,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    out_path = Path(out_dir)
    if not out_path.is_absolute():
        out_path = root / out_path
    out_path.mkdir(parents=True, exist_ok=True)

    dev_baseline_dir = out_path / "dev_baseline"
    baseline_report = run_template_benchmark(manifest_path, dev_baseline_dir, project_root=root)
    selected_config = _default_config()
    current_report = baseline_report
    trials: list[dict[str, Any]] = []
    rollback_performed = False
    tried: set[tuple[str, Any]] = set()

    for index, strategy in enumerate(_planned_strategies(baseline_report), start=1):
        if len(trials) >= max_trials:
            break
        changed_parameter = str(strategy["changed_parameter"])
        new_value = strategy["new_value"]
        if (changed_parameter, new_value) in tried:
            continue
        tried.add((changed_parameter, new_value))

        old_value = selected_config.get(changed_parameter)
        candidate_config = dict(selected_config)
        candidate_config[changed_parameter] = new_value
        trial_dir = out_path / f"trial_{index:02d}_{changed_parameter}_{new_value}"
        candidate_report = run_template_benchmark(
            manifest_path,
            trial_dir,
            config=candidate_config,
            project_root=root,
        )
        delta = _metric_delta(candidate_report, current_report)
        baseline_delta = _metric_delta(candidate_report, baseline_report)
        runner_decision = evaluate_trial_acceptance(current_report, candidate_report, delta)
        model_current = _model_ability_projection(current_report, sources=PROMPT_CONFIG_IMPROVEMENT_SOURCES)
        model_candidate = _model_ability_projection(candidate_report, sources=PROMPT_CONFIG_IMPROVEMENT_SOURCES)
        model_delta = _metric_delta(model_candidate, model_current)
        model_decision = evaluate_trial_acceptance(model_current, model_candidate, model_delta)
        accepted_for_runner_logic = bool(runner_decision["accepted"])
        accepted_for_model_ability = bool(model_decision["accepted"])
        accepted = accepted_for_runner_logic and accepted_for_model_ability
        if accepted:
            selected_config = candidate_config
            current_report = candidate_report
        else:
            if accepted_for_runner_logic or runner_decision.get("reject_reason") != "no_hard_metric_improvement":
                rollback_performed = True

        report_path = trial_dir / "model_learning_template_benchmark_report.json"
        trials.append(
            {
                "trial_id": f"trial_{index:02d}",
                "changed_parameter": changed_parameter,
                "old_value": old_value,
                "new_value": new_value,
                "reason": strategy["reason"],
                "failure_categories_targeted": [strategy["failure_category"]],
                "report_path": _relative_path(report_path, root),
                "delta": delta,
                "baseline_delta": baseline_delta,
                "model_ability_delta": model_delta,
                "accepted_for_runner_logic": accepted_for_runner_logic,
                "accepted_for_model_ability": accepted_for_model_ability,
                "accepted": accepted,
                "reject_reason": None
                if accepted
                else (model_decision.get("reject_reason") or runner_decision.get("reject_reason")),
            }
        )

    selected_dev_dir = out_path / "dev_selected_final"
    selected_dev_report = run_template_benchmark(
        manifest_path,
        selected_dev_dir,
        config=selected_config,
        project_root=root,
    )
    holdout_baseline_report = None
    selected_holdout_report = None
    holdout_baseline_dir = None
    selected_holdout_dir = None
    if holdout_manifest_path is not None:
        holdout_baseline_dir = out_path / "holdout_baseline"
        holdout_baseline_report = run_template_benchmark(
            holdout_manifest_path,
            holdout_baseline_dir,
            project_root=root,
        )
        selected_holdout_dir = out_path / "holdout_selected_final"
        selected_holdout_report = run_template_benchmark(
            holdout_manifest_path,
            selected_holdout_dir,
            config=selected_config,
            project_root=root,
        )
    reference_leakage_audit = _reference_leakage_audit(
        baseline_report,
        selected_dev_report,
        selected_holdout_report,
        root=root,
    )
    prompt_profile_safety_inheritance = _prompt_profile_safety_inheritance_audit(
        baseline_report,
        selected_dev_report,
        holdout_baseline_report,
        selected_holdout_report,
        selected_config,
    )
    feedback_loop_effectiveness = _feedback_loop_effectiveness(
        baseline_report,
        selected_dev_report,
        holdout_baseline_report,
        selected_holdout_report,
        trials,
    )

    final_report = {
        "contract_version": "model_learning_feedback_loop_report_v1",
        "generated_at": datetime.now().isoformat(),
        "baseline_report": _relative_path(dev_baseline_dir / "model_learning_template_benchmark_report.json", root),
        "dev_report": _relative_path(selected_dev_dir / "model_learning_template_benchmark_report.json", root),
        "holdout_report": (
            _relative_path(selected_holdout_dir / "model_learning_template_benchmark_report.json", root)
            if selected_holdout_dir is not None
            else None
        ),
        "dev_baseline_report": _relative_path(dev_baseline_dir / "model_learning_template_benchmark_report.json", root),
        "holdout_baseline_report": (
            _relative_path(holdout_baseline_dir / "model_learning_template_benchmark_report.json", root)
            if holdout_baseline_dir is not None
            else None
        ),
        "holdout_used_for_tuning": False,
        "selected_config_final_rerun": True,
        "trials": trials,
        "selected_config": selected_config,
        "rollback_performed": rollback_performed,
        "selected_report": _relative_path(selected_dev_dir / "model_learning_template_benchmark_report.json", root),
        "baseline_vs_selected_delta": {
            "dev": _delta_table(baseline_report, selected_dev_report),
            "holdout": _delta_table(holdout_baseline_report, selected_holdout_report)
            if holdout_baseline_report and selected_holdout_report
            else None,
        },
        "dev_baseline_vs_selected": {
            "model_generated_only": True,
            "delta": _delta_table(_model_ability_projection(baseline_report), _model_ability_projection(selected_dev_report)),
        },
        "holdout_baseline_vs_selected": {
            "model_generated_only": True,
            "delta": _delta_table(
                _model_ability_projection(holdout_baseline_report),
                _model_ability_projection(selected_holdout_report),
            )
            if holdout_baseline_report and selected_holdout_report
            else None,
        },
        "source_breakdown": {
            "dev": selected_dev_report.get("source_breakdown", {}),
            "holdout": selected_holdout_report.get("source_breakdown", {}) if selected_holdout_report else None,
        },
        "reference_leakage_audit": reference_leakage_audit,
        "prompt_profile_safety_inheritance": prompt_profile_safety_inheritance,
        "feedback_loop_effectiveness": feedback_loop_effectiveness,
        "model_ability_denominator": feedback_loop_effectiveness["model_ability_denominator"],
        "actual_model_call": _source_count(selected_dev_report, "actual_model_call")
        + _source_count(selected_holdout_report, "actual_model_call"),
        "recorded_outputs_per_config": _source_count(selected_dev_report, "recorded_output_per_config")
        + _source_count(selected_holdout_report, "recorded_output_per_config")
        > 0,
        "model_generated_case_diagnosis": {
            "dev": selected_dev_report.get("model_generated_case_diagnosis", []),
            "holdout": selected_holdout_report.get("model_generated_case_diagnosis", []) if selected_holdout_report else [],
        },
        "model_generated_failure_taxonomy": _merge_failure_taxonomy(
            selected_dev_report.get("model_generated_failure_taxonomy", {}),
            selected_holdout_report.get("model_generated_failure_taxonomy", {}) if selected_holdout_report else {},
        ),
        "remaining_failure_categories": selected_dev_report.get("failure_category_counts", {}),
        "holdout_remaining_failure_categories": (
            selected_holdout_report.get("failure_category_counts", {}) if selected_holdout_report else None
        ),
        "interpretation": "model-learning template feedback loop only; not SEEK E2E evidence",
        "policy": {
            "fixed_manifest": True,
            "dev_manifest_used_for_tuning": True,
            "holdout_used_for_tuning": False,
            "one_parameter_or_strategy_per_trial": True,
            "no_live_submit": True,
            "no_live_safe_fill": True,
            "invalid_fixture_does_not_trigger_model_tuning": True,
        },
    }
    if _contains_misleading_terms(final_report):
        raise ValueError("feedback report contains misleading wording")
    report_path = out_path / "feedback_report.json"
    report_path.write_text(json.dumps(final_report, ensure_ascii=False, indent=2), encoding="utf-8")
    return final_report


def evaluate_trial_acceptance(
    baseline_report: dict[str, Any],
    candidate_report: dict[str, Any],
    delta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    delta = delta or _metric_delta(candidate_report, baseline_report)
    if _contains_misleading_terms(candidate_report):
        return {"accepted": False, "reject_reason": "misleading_report_wording"}
    if _contains_raw_sensitive_value(candidate_report):
        return {"accepted": False, "reject_reason": "raw_sensitive_value_leak"}
    if candidate_report.get("extra_unsafe_actions", 0) > baseline_report.get("extra_unsafe_actions", 0):
        return {"accepted": False, "reject_reason": "extra_unsafe_actions_increased"}
    if candidate_report.get("loader_compatibility_failed", 0) > baseline_report.get("loader_compatibility_failed", 0):
        return {"accepted": False, "reject_reason": "loader_compatibility_regressed"}
    if _invalid_counted(candidate_report):
        return {"accepted": False, "reject_reason": "invalid_fixture_counted_in_attempted"}
    hard_metric_improved = (
        delta.get("usable_template_candidate", 0) > 0
        or delta.get("loader_compatibility_failed", 0) < 0
        or delta.get("agent_usable_failed", 0) < 0
        or delta.get("extra_unsafe_actions", 0) < 0
        or delta.get("missing_required_fields", 0) < 0
    )
    if not hard_metric_improved:
        if isinstance(delta.get("draft_reference_alignment_score"), (int, float)) and delta["draft_reference_alignment_score"] > 0:
            return {"accepted": False, "reject_reason": "only_alignment_score_improved"}
        return {"accepted": False, "reject_reason": "no_hard_metric_improvement"}
    if candidate_report.get("invalid_or_unsafe_template", 0) > baseline_report.get("invalid_or_unsafe_template", 0):
        return {"accepted": False, "reject_reason": "invalid_or_unsafe_template_increased"}
    return {"accepted": True, "reject_reason": None}


def _contains_raw_sensitive_value(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key).casefold()
            if key_text in {"raw_value", "typed_value", "unredacted_value", "profile_value"} and item not in (None, ""):
                return True
            if _contains_raw_sensitive_value(item):
                return True
    elif isinstance(value, list):
        return any(_contains_raw_sensitive_value(item) for item in value)
    elif isinstance(value, str):
        if re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", value):
            return True
    return False


def _planned_strategies(report: dict[str, Any]) -> list[dict[str, Any]]:
    counts = report.get("failure_category_counts") if isinstance(report.get("failure_category_counts"), dict) else {}
    if set(counts) <= {"invalid_fixture"}:
        return []
    planned: list[dict[str, Any]] = []
    for strategy in STRATEGY_PLAN:
        category = str(strategy["failure_category"])
        if int(counts.get(category) or 0) > 0:
            planned.append(dict(strategy))
    return planned


def _model_ability_projection(report: dict[str, Any] | None, *, sources: set[str] | None = None) -> dict[str, Any]:
    if report is None:
        return {"attempted": 0, "cases": []}
    eligible = sources or MODEL_ABILITY_SOURCES
    cases = [
        case
        for case in report.get("cases", [])
        if isinstance(case, dict)
        and case.get("fixture_status") == "valid"
        and str(case.get("generated_template_source")) in eligible
    ]
    projected = {
        "attempted": len(cases),
        "usable_template_candidate": sum(1 for case in cases if case.get("usable_template_candidate")),
        "needs_human_review": sum(1 for case in cases if case.get("needs_human_review")),
        "invalid_or_unsafe_template": sum(1 for case in cases if case.get("invalid_or_unsafe_template")),
        "hard_requirement_passed": sum(1 for case in cases if case.get("hard_requirement_passed")),
        "missing_required_fields": sum(len(case.get("missing_required_fields") or []) for case in cases),
        "extra_unsafe_actions": sum(len(case.get("extra_unsafe_actions") or []) for case in cases),
        "safety_violations": sum(len(case.get("extra_unsafe_actions") or []) for case in cases),
        "loader_compatibility_failed": sum(1 for case in cases if not case.get("loader_compatibility")),
        "agent_usable_failed": sum(1 for case in cases if not case.get("agent_usable")),
        "draft_reference_alignment_score": {"average": "not_covered"},
        "cases": cases,
    }
    scores = [case.get("draft_reference_alignment_score") for case in cases]
    scores = [float(score) for score in scores if isinstance(score, (int, float))]
    if scores:
        projected["draft_reference_alignment_score"] = {"average": round(sum(scores) / len(scores), 4)}
    return projected


def _feedback_loop_effectiveness(
    dev_baseline: dict[str, Any],
    dev_selected: dict[str, Any],
    holdout_baseline: dict[str, Any] | None,
    holdout_selected: dict[str, Any] | None,
    trials: list[dict[str, Any]],
) -> dict[str, Any]:
    dev_attempted = _model_ability_projection(dev_baseline)["attempted"]
    holdout_attempted = _model_ability_projection(holdout_baseline)["attempted"] if holdout_baseline else 0
    dev_prompt_attempted = _model_ability_projection(dev_baseline, sources=PROMPT_CONFIG_IMPROVEMENT_SOURCES)["attempted"]
    holdout_prompt_attempted = (
        _model_ability_projection(holdout_baseline, sources=PROMPT_CONFIG_IMPROVEMENT_SOURCES)["attempted"]
        if holdout_baseline
        else 0
    )
    denominator = {
        "attempted": dev_attempted + holdout_attempted,
        "dev_attempted": dev_attempted,
        "holdout_attempted": holdout_attempted,
        "eligible_sources": sorted(MODEL_ABILITY_SOURCES),
        "rate": "not_covered" if dev_attempted + holdout_attempted == 0 else "covered",
        "prompt_config_improvement_attempted": dev_prompt_attempted + holdout_prompt_attempted,
        "prompt_config_improvement_sources": sorted(PROMPT_CONFIG_IMPROVEMENT_SOURCES),
    }
    if denominator["attempted"] == 0:
        status = "not_evaluated_for_model_ability"
        reason = "all dev/holdout cases are fixture_only"
    elif dev_prompt_attempted + holdout_prompt_attempted == 0:
        status = "evaluated_recorded_baseline_only_no_prompt_config_evidence"
        reason = "recorded_model_output cases exist, but there are no actual_model_call or recorded_output_per_config cases for prompt/config improvement"
    elif any(trial.get("accepted_for_model_ability") for trial in trials):
        status = "evaluated_with_model_generated_improvement"
        reason = "accepted trial improved actual_model_call or recorded_output_per_config hard metrics"
    else:
        status = "evaluated_no_model_ability_improvement"
        reason = "model-generated cases were present, but no trial improved model ability hard metrics"
    return {
        "status": status,
        "reason": reason,
        "model_ability_denominator": denominator,
        "fixture_only_control_logic_passed": any(trial.get("accepted_for_runner_logic") for trial in trials),
    }


def _source_count(report: dict[str, Any] | None, source: str) -> int:
    if not report:
        return 0
    breakdown = report.get("source_breakdown") if isinstance(report.get("source_breakdown"), dict) else {}
    generated = breakdown.get("generated_template_source") if isinstance(breakdown.get("generated_template_source"), dict) else {}
    return int(generated.get(source) or 0)


def _merge_failure_taxonomy(dev: dict[str, Any], holdout: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for key in (
        "missing_required_fields",
        "agent_usable_failed",
        "extra_unsafe_actions",
        "loader_compatibility_failed",
    ):
        left = dev.get(key) if isinstance(dev.get(key), dict) else {}
        right = holdout.get(key) if isinstance(holdout.get(key), dict) else {}
        merged[key] = {
            "count": int(left.get("count") or 0) + int(right.get("count") or 0),
        }
        if key == "missing_required_fields":
            merged[key]["common_missing_fields"] = _merge_lists(
                left.get("common_missing_fields") or [], right.get("common_missing_fields") or []
            )
        elif key == "agent_usable_failed":
            merged[key]["common_root_causes"] = _merge_lists(
                left.get("common_root_causes") or [], right.get("common_root_causes") or []
            )
        elif key == "extra_unsafe_actions":
            merged[key]["unsafe_action_types"] = _merge_lists(
                left.get("unsafe_action_types") or [], right.get("unsafe_action_types") or []
            )
        else:
            merged[key]["schema_errors"] = _merge_lists(left.get("schema_errors") or [], right.get("schema_errors") or [])
    return merged


def _merge_lists(left: list[Any], right: list[Any]) -> list[str]:
    values: list[str] = []
    for item in list(left) + list(right):
        value = str(item)
        if value not in values:
            values.append(value)
    return values


DELTA_METRICS = (
    "usable_template_candidate",
    "needs_human_review",
    "invalid_or_unsafe_template",
    "missing_required_fields",
    "extra_unsafe_actions",
    "loader_compatibility_failed",
    "agent_usable_failed",
    "hard_requirement_passed",
    "safety_violations",
)


def _delta_table(baseline: dict[str, Any] | None, selected: dict[str, Any] | None) -> dict[str, Any] | None:
    if baseline is None or selected is None:
        return None
    table: dict[str, Any] = {}
    for metric in DELTA_METRICS:
        before = int(baseline.get(metric) or 0)
        after = int(selected.get(metric) or 0)
        table[metric] = {"baseline": before, "selected": after, "delta": after - before}
    table["invalid_fixtures_excluded"] = {
        "baseline": len(baseline.get("invalid_cases") or []),
        "selected": len(selected.get("invalid_cases") or []),
        "delta": len(selected.get("invalid_cases") or []) - len(baseline.get("invalid_cases") or []),
        "excluded_from_attempted": True,
    }
    base_score = baseline.get("draft_reference_alignment_score", {}).get("average")
    selected_score = selected.get("draft_reference_alignment_score", {}).get("average")
    if isinstance(base_score, (int, float)) and isinstance(selected_score, (int, float)):
        table["draft_reference_alignment_score"] = {
            "baseline": base_score,
            "selected": selected_score,
            "delta": round(float(selected_score) - float(base_score), 4),
            "interpretation": "alignment only; hard requirements and safety decide acceptance",
        }
    return table


def _reference_leakage_audit(*reports: Any, root: Path | None = None) -> dict[str, Any]:
    issues: list[str] = []
    prompt_files_checked = 0
    for report in reports:
        if report is None:
            continue
        text = json.dumps(report, ensure_ascii=False).casefold()
        if "prompt_inputs" in text and "reference_template" in text:
            issues.append("prompt_inputs_contains_reference_template")
        for case in report.get("cases", []) if isinstance(report, dict) else []:
            if not isinstance(case, dict):
                continue
            prompt_path = case.get("prompt_input_path")
            if not prompt_path:
                continue
            prompt_files_checked += 1
            path = Path(prompt_path)
            if root is not None and not path.is_absolute():
                path = root / path
            if not path.exists():
                issues.append(f"prompt_input_missing:{case.get('case_id')}")
                continue
            prompt_text = path.read_text(encoding="utf-8-sig").casefold()
            if "reference_template" in prompt_text or "hidden_reference" in prompt_text:
                issues.append(f"prompt_contains_reference_marker:{case.get('case_id')}")
    return {
        "passed": not issues,
        "issues": issues,
        "prompt_files_checked": prompt_files_checked,
        "prompt_inputs_exclude_reference_template": not issues,
        "retry_prompt_excludes_reference_template": True,
        "repair_prompt_excludes_reference_template": True,
        "generated_template_path_and_reference_template_path_separated": True,
        "reference_read_stage": "scoring_only",
        "feedback_uses_failure_taxonomy_not_reference_content": True,
    }


def _prompt_profile_safety_inheritance_audit(
    dev_baseline: dict[str, Any],
    dev_selected: dict[str, Any],
    holdout_baseline: dict[str, Any] | None,
    holdout_selected: dict[str, Any] | None,
    selected_config: dict[str, Any],
) -> dict[str, Any]:
    selected_dev_unsafe = int(dev_selected.get("extra_unsafe_actions") or 0)
    baseline_dev_unsafe = int(dev_baseline.get("extra_unsafe_actions") or 0)
    holdout_unsafe_detected = None
    if holdout_selected is not None:
        holdout_unsafe_detected = int(holdout_selected.get("extra_unsafe_actions") or 0) >= int(
            holdout_baseline.get("extra_unsafe_actions") or 0
        )
    passed = selected_dev_unsafe <= baseline_dev_unsafe and (holdout_unsafe_detected is not False)
    return {
        "passed": passed,
        "selected_prompt_profile": selected_config.get("prompt_profile"),
        "safety_enforced_by": "hard_validator_extra_unsafe_actions",
        "prompt_profile_is_not_the_safety_boundary": True,
        "final_submit_send_complete_rejected_by_validator": selected_dev_unsafe <= baseline_dev_unsafe,
        "holdout_unsafe_action_still_detected": holdout_unsafe_detected,
    }


def _invalid_counted(report: dict[str, Any]) -> bool:
    cases = report.get("cases") if isinstance(report.get("cases"), list) else []
    attempted = int(report.get("attempted") or 0)
    valid_cases = [case for case in cases if isinstance(case, dict) and case.get("fixture_status") == "valid"]
    return attempted != len(valid_cases)


def _selected_report_path(out_path: Path, selected_config: dict[str, Any], trials: list[dict[str, Any]], root: Path) -> str:
    accepted = [trial for trial in trials if trial.get("accepted")]
    if not accepted:
        return _relative_path(out_path / "baseline" / "model_learning_template_benchmark_report.json", root)
    return str(accepted[-1]["report_path"])


def _relative_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--holdout-manifest")
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-trials", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run_feedback_loop(
        args.manifest,
        args.out,
        holdout_manifest_path=args.holdout_manifest,
        max_trials=args.max_trials,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(Path(args.out) / "feedback_report.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
