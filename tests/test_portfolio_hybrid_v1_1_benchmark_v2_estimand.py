from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ESTIMAND_PATH = (
    PROJECT_ROOT
    / "configs"
    / "benchmarks"
    / "portfolio_hybrid_v1_1_estimand.v2.json"
)
ARM_IDS_V2 = (
    "qwen_only",
    "omni_only_discovery",
    "omni_to_qwen",
    "omni_to_qwen_vista",
)
HYBRID_ARMS = ARM_IDS_V2[1:]
PAIR_ARMS = ("omni_to_qwen", "omni_to_qwen_vista")
PAIR_PARENT_FIELDS = (
    "fusion_ref",
    "candidate_id",
    "capture_ref",
    "target_binding_ref",
    "bbox_ref",
)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _exact_keys(value: object, expected: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{name} must have exact keys {sorted(expected)}")
    return value


def _validate_estimand(value: object) -> dict[str, Any]:
    estimand = _exact_keys(
        value,
        {
            "contract_version",
            "benchmark_release_id",
            "arms",
            "execution_units",
            "prediction",
            "semantic_target_metric",
            "point_metric",
            "regression_attempt_policy",
            "holdout_claim",
            "automatic_gates",
            "safety",
        },
        "estimand",
    )
    if estimand["contract_version"] != "portfolio_hybrid_v1_1_estimand_v2_1":
        raise ValueError("estimand contract_version is invalid")
    if estimand["benchmark_release_id"] != (
        "portfolio_hybrid_v1_1_benchmark_v2_release_1"
    ):
        raise ValueError("benchmark release is not closed")

    arms = _exact_keys(
        estimand["arms"],
        {"arm_ids", "release_arm", "statistical_arm_count"},
        "arms",
    )
    if tuple(arms["arm_ids"]) != ARM_IDS_V2:
        raise ValueError("statistical arm allowlist or order is invalid")
    if arms["release_arm"] != "omni_to_qwen_vista":
        raise ValueError("release arm is invalid")
    if arms["statistical_arm_count"] != 4:
        raise ValueError("statistical arm count is invalid")

    execution = _exact_keys(
        estimand["execution_units"],
        {
            "hybrid_arms",
            "hybrid_invocation_unit",
            "hybrid_invocations_per_screen_group",
            "incumbent_arm",
            "incumbent_invocation_unit",
            "targets_per_screen_group",
            "call_count_reports",
        },
        "execution_units",
    )
    if tuple(execution["hybrid_arms"]) != HYBRID_ARMS:
        raise ValueError("Hybrid arm set is invalid")
    if execution["hybrid_invocation_unit"] != "screen_group":
        raise ValueError("Hybrid invocation unit is invalid")
    if execution["hybrid_invocations_per_screen_group"] != 1:
        raise ValueError("Hybrid must run once per screen group")
    if execution["incumbent_arm"] != "qwen_only":
        raise ValueError("incumbent arm is invalid")
    if execution["incumbent_invocation_unit"] != "target":
        raise ValueError("incumbent invocation unit is invalid")
    if execution["targets_per_screen_group"] != 5:
        raise ValueError("screen-group target cardinality is invalid")
    if execution["call_count_reports"] != [
        "unique_invocation_count",
        "amortized_per_target_count",
    ]:
        raise ValueError("call-count reporting is invalid")

    prediction = _exact_keys(
        estimand["prediction"],
        {
            "automatic_split",
            "review_split",
            "logical_record_policy",
            "release_reads_split",
        },
        "prediction",
    )
    if prediction != {
        "automatic_split": "pre_review",
        "review_split": "post_review",
        "logical_record_policy": "immutable_pre_review_append_only_post_review",
        "release_reads_split": "pre_review",
    }:
        raise ValueError("prediction split policy is invalid")

    metric = _exact_keys(
        estimand["point_metric"],
        {
            "metric_id",
            "sealed",
            "coordinate_space",
            "row_key_fields",
            "pair_identity_fields",
            "pair_arm_ids",
            "pair_cardinality",
            "same_parent_fields",
            "target_binding",
            "baseline",
            "refined",
            "acceptable_region_hit_rule",
            "multi_region_rule",
            "submitted_failure_rule",
            "denominator",
            "gain_numerator",
            "gain",
            "comparison_arithmetic",
            "min_vista_submitted_count",
            "required_gain_numerator",
            "proposal_selection",
        },
        "point_metric",
    )
    if metric["metric_id"] != "acceptable_region_binary_gain_v1":
        raise ValueError("point metric is invalid")
    if metric["sealed"] is not True:
        raise ValueError("point metric must be sealed")
    if metric["coordinate_space"] != "capture_pixel_xyxy":
        raise ValueError("metric coordinate space is invalid")
    if metric["row_key_fields"] != [
        "case_id",
        "arm_id",
        "candidate_id",
        "vista_request_ref",
    ]:
        raise ValueError("private scorer row key is invalid")
    if metric["pair_identity_fields"] != [
        "case_id",
        "candidate_id",
        "vista_request_ref",
    ]:
        raise ValueError("pair identity is invalid")
    if tuple(metric["pair_arm_ids"]) != PAIR_ARMS or metric["pair_cardinality"] != 2:
        raise ValueError("paired Hybrid arms are invalid")
    if tuple(metric["same_parent_fields"]) != PAIR_PARENT_FIELDS:
        raise ValueError("paired parent fields are invalid")
    if metric["baseline"] != {
        "method": "strict_bbox_center_v1",
        "bbox_format": ["x1", "y1", "x2", "y2"],
        "formula": ["(x1+x2)/2", "(y1+y2)/2"],
    }:
        raise ValueError("baseline formula is invalid")
    if metric["refined"] != {
        "source": "unique_validated_proposal_for_vista_request_ref",
        "field": "canonical_capture_pixel_point",
        "validated_success_status": "validated",
        "terminal_status_allowlist": [
            "validated",
            "failed",
            "timeout",
            "out_of_bounds",
            "missing",
        ],
        "validated_proposal_lineage_fields": [
            "case_id",
            "vista_request_ref",
            "candidate_id",
            "fusion_ref",
            "capture_ref",
            "target_binding_ref",
            "bbox_ref",
        ],
        "unknown_status_policy": "run_invalid",
        "wrong_lineage_policy": "run_invalid",
    }:
        raise ValueError("refined point source is invalid")
    if metric["acceptable_region_hit_rule"] != (
        "x1 <= x < x2 && y1 <= y < y2"
    ):
        raise ValueError("acceptable region boundary is invalid")
    if metric["multi_region_rule"] != "logical_or":
        raise ValueError("multi-region rule is invalid")
    if metric["submitted_failure_rule"] != {
        "statuses": ["failed", "timeout", "out_of_bounds", "missing"],
        "refined_hit": 0,
        "remains_in_denominator": True,
    }:
        raise ValueError("submitted failure rule is invalid")
    if metric["denominator"] != "submitted_count":
        raise ValueError("metric denominator is invalid")
    if metric["gain_numerator"] != "sum(refined_hit-baseline_hit)":
        raise ValueError("gain numerator is invalid")
    if metric["gain"] != "gain_numerator/submitted_count":
        raise ValueError("gain formula is invalid")
    if metric["comparison_arithmetic"] != "exact_rational_no_rounding":
        raise ValueError("gain arithmetic is invalid")
    if metric["min_vista_submitted_count"] != 1:
        raise ValueError("minimum submitted count is invalid")
    if metric["required_gain_numerator"] != ">0":
        raise ValueError("required point gain is invalid")
    if metric["proposal_selection"] != "exact_request_only_no_cherry_pick":
        raise ValueError("proposal selection policy is invalid")
    if estimand["semantic_target_metric"] != {
        "metric_id": "private_unique_target_center_containment_v1",
        "private_join_field": "case_id",
        "group_field": "screen_group",
        "region_center_formula": ["(x1+x2)/2", "(y1+y2)/2"],
        "candidate_containment_rule": "x1 <= x < x2 && y1 <= y < y2",
        "correct_match_cardinality": 1,
        "zero_match_policy": "wrong_target",
        "different_match_policy": "wrong_target",
        "multiple_match_policy": "wrong_target",
    }:
        raise ValueError("semantic target metric is invalid")
    binding = _exact_keys(
        metric["target_binding"],
        {
            "ref_contract",
            "selection_timing",
            "candidate_cardinality",
            "ref_uniqueness_scope",
            "globally_unique_ref_fields",
            "binding_ref_exact_mapping_fields",
            "request_ref_exact_mapping_fields",
            "pair_must_join_selected_mapping",
            "eligibility_values",
            "eligible_submission_status",
            "eligible_request_cardinality",
            "ineligible_request_cardinality",
            "ineligible_reason_required",
            "invalid_conditions",
        },
        "target_binding",
    )
    if binding != {
        "ref_contract": "sealed_target_binding_ref_v1",
        "selection_timing": "before_vista",
        "candidate_cardinality": 1,
        "ref_uniqueness_scope": "run",
        "globally_unique_ref_fields": [
            "target_binding_ref",
            "candidate_id",
            "bbox_ref",
            "vista_request_ref",
        ],
        "binding_ref_exact_mapping_fields": [
            "case_id",
            "candidate_id",
            "fusion_ref",
            "capture_ref",
            "bbox_ref",
        ],
        "request_ref_exact_mapping_fields": [
            "case_id",
            "target_binding_ref",
            "candidate_id",
            "fusion_ref",
            "capture_ref",
            "bbox_ref",
        ],
        "pair_must_join_selected_mapping": True,
        "eligibility_values": ["ELIGIBLE", "INELIGIBLE"],
        "eligible_submission_status": "SUBMITTED",
        "eligible_request_cardinality": 1,
        "ineligible_request_cardinality": 0,
        "ineligible_reason_required": True,
        "invalid_conditions": [
            "duplicate_binding",
            "missing_binding",
            "ambiguous_binding",
            "duplicate_request",
            "missing_request",
            "cross_case_request",
            "cross_candidate_request",
            "cross_request_pair",
            "eligible_but_unsent",
            "ineligible_with_request",
        ],
    }:
        raise ValueError("target binding policy is invalid")

    attempts = _exact_keys(
        estimand["regression_attempt_policy"],
        {
            "accepted_run_selection",
            "cherry_pick_forbidden",
            "same_seal_retry_limit",
            "same_seal_retry_requires_independent_review",
            "same_seal_retryable_dispositions",
            "model_quality_or_gate_failure_action",
        },
        "regression_attempt_policy",
    )
    if attempts != {
        "accepted_run_selection": "first_complete_lifecycle_verified_attempt",
        "cherry_pick_forbidden": True,
        "same_seal_retry_limit": 1,
        "same_seal_retry_requires_independent_review": True,
        "same_seal_retryable_dispositions": [
            "pre_model_infrastructure_failure",
            "cleanup_indeterminate",
        ],
        "model_quality_or_gate_failure_action": "fix_and_generate_new_seal",
    }:
        raise ValueError("regression attempt policy is invalid")

    claim = _exact_keys(
        estimand["holdout_claim"],
        {
            "file_root_template",
            "registry_root_template",
            "claim_identity_schema",
            "claim_identity_payload",
            "claim_id_formula",
            "authorization_path_template",
            "sentinel_path_template",
            "registry_key_template",
            "attempt_id_formula",
            "authorization_task",
            "authorization_frozen_non_key_fields",
            "non_key_fields",
            "changed_non_key_field_policy",
            "runner_overrides_forbidden",
        },
        "holdout_claim",
    )
    expected_identity = {
        "benchmark_release_id": "portfolio_hybrid_v1_1_benchmark_v2_release_1",
        "corpus_parent_seal_sha256": (
            "8503010496a426893456e903b9d768f2a281ef0509f11230d312b073c0760757"
        ),
        "partition": "holdout",
    }
    if claim["claim_identity_schema"] != {
        "contract_version": "portfolio_hybrid_benchmark_v2_claim_identity_v1",
        "canonical_json": "utf8_sorted_keys_compact_no_nan",
        "exact_fields": [
            "benchmark_release_id",
            "corpus_parent_seal_sha256",
            "partition",
        ],
    }:
        raise ValueError("claim identity schema is invalid")
    if claim["claim_identity_payload"] != expected_identity:
        raise ValueError("claim identity payload is invalid")
    if claim["file_root_template"] != (
        "%LOCALAPPDATA%\\AgentGuiRuntime\\PortfolioHybridBenchmarkV2\\Claims"
    ):
        raise ValueError("claim file root is invalid")
    if claim["registry_root_template"] != (
        "HKCU\\Software\\AgentGuiRuntime\\PortfolioHybridBenchmarkV2\\Claims"
    ):
        raise ValueError("claim registry root is invalid")
    if claim["claim_id_formula"] != (
        "sha256(canonical_json(claim_identity_payload))"
    ):
        raise ValueError("claim ID formula is invalid")
    if claim["authorization_path_template"] != (
        "{claim_root}\\{claim_id}.authorization.json"
    ):
        raise ValueError("authorization path template is invalid")
    if claim["sentinel_path_template"] != (
        "{claim_root}\\{claim_id}--{authorization_envelope_sha256}.claim"
    ):
        raise ValueError("sentinel template is invalid")
    if claim["registry_key_template"] != "{registry_root}\\{claim_id}":
        raise ValueError("registry key template is invalid")
    if claim["attempt_id_formula"] != (
        "sha256(benchmark-v2-holdout-attempt\\0+claim_id+\\0+authorization_envelope_sha256)"
    ):
        raise ValueError("attempt ID formula is invalid")
    if claim["authorization_task"] != 14:
        raise ValueError("holdout authorization task is invalid")
    expected_non_key_fields = [
        "provider_manifest_sha256",
        "provider_manifest_contract_version",
        "code_sha256_by_path",
        "config_sha256_by_path",
        "profile_sha256_by_id",
        "arm_order",
        "exact_holdout_command",
        "exact_run_order",
        "owner_journal_root",
    ]
    if claim["authorization_frozen_non_key_fields"] != expected_non_key_fields:
        raise ValueError("authorization frozen fields are invalid")
    if claim["non_key_fields"] != expected_non_key_fields:
        raise ValueError("claim non-key fields are invalid")
    if claim["changed_non_key_field_policy"] != (
        "permanent_release_invalid_no_new_authorization_key_or_attempt"
    ):
        raise ValueError("changed authorization policy is invalid")
    runner_override_prefix = [
        "claim_root",
        "registry_root",
        "claim_id",
        "authorization_path",
        "benchmark_release_id",
        "corpus_parent_seal_sha256",
        "partition",
    ]
    runner_overrides = claim["runner_overrides_forbidden"]
    if runner_overrides != [*runner_override_prefix, *expected_non_key_fields]:
        raise ValueError("runner override policy is invalid")
    if not set(expected_non_key_fields).issubset(runner_overrides):
        raise ValueError("frozen authorization field escaped runner denylist")

    gates = _exact_keys(
        estimand["automatic_gates"],
        {
            "split",
            "wrong_target_count",
            "min_coverage",
            "important_target_correct_coverage_baseline_arm",
            "min_important_target_correct_coverage_delta",
            "semantic_precision_baseline_arm",
            "min_semantic_precision_delta",
            "min_vista_submitted_count",
            "required_vista_gain_numerator",
        },
        "automatic_gates",
    )
    if gates != {
        "split": "pre_review",
        "wrong_target_count": 0,
        "min_coverage": "1/5",
        "important_target_correct_coverage_baseline_arm": "qwen_only",
        "min_important_target_correct_coverage_delta": "1/20",
        "semantic_precision_baseline_arm": "qwen_only",
        "min_semantic_precision_delta": "0/1",
        "min_vista_submitted_count": 1,
        "required_vista_gain_numerator": ">0",
    }:
        raise ValueError("automatic gates are invalid")
    if estimand["safety"] != {
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "display_only": True,
        "real_action_allowed": False,
        "publish_allowed": False,
    }:
        raise ValueError("safety boundary is invalid")
    return estimand


def _load_estimand(path: Path = ESTIMAND_PATH) -> dict[str, Any]:
    return _validate_estimand(json.loads(path.read_text(encoding="utf-8")))


def _validate_invocations(
    config: dict[str, Any],
    invocations: list[dict[str, str]],
    *,
    screen_group: str,
    target_ids: list[str],
) -> dict[str, Fraction | int]:
    expected_targets = set(target_ids)
    if len(expected_targets) != config["execution_units"]["targets_per_screen_group"]:
        raise ValueError("screen group must contain five distinct targets")
    for arm in ARM_IDS_V2:
        rows = [row for row in invocations if row.get("arm_id") == arm]
        if arm in HYBRID_ARMS:
            if rows != [{"arm_id": arm, "screen_group": screen_group}]:
                raise ValueError("Hybrid arm must run once at screen-group scope")
        else:
            observed_targets = {
                row.get("target_id")
                for row in rows
                if row.get("screen_group") == screen_group
                and set(row) == {"arm_id", "screen_group", "target_id"}
            }
            if observed_targets != expected_targets or len(rows) != len(expected_targets):
                raise ValueError("incumbent arm must run once per target")
    unknown = {row.get("arm_id") for row in invocations} - set(ARM_IDS_V2)
    if unknown:
        raise ValueError("unknown statistical arm")
    hybrid_unique = len(HYBRID_ARMS)
    return {
        "hybrid_unique_invocation_count": hybrid_unique,
        "hybrid_amortized_per_target_count": Fraction(
            hybrid_unique,
            len(expected_targets),
        ),
        "incumbent_unique_invocation_count": len(expected_targets),
        "incumbent_amortized_per_target_count": Fraction(1, 1),
    }


def _validate_target_bindings(
    target_keys: set[str],
    bindings: list[dict[str, str]],
    requests: list[dict[str, str]],
) -> dict[str, dict[str, str] | None]:
    selected: dict[str, dict[str, str]] = {}
    global_ref_owners: dict[tuple[str, str], str] = {}
    for binding in bindings:
        key = binding.get("case_id", "")
        if key not in target_keys or key in selected:
            raise ValueError("duplicate, ambiguous, or cross-case binding")
        if not all(
            binding.get(field)
            for field in (
                "target_binding_ref",
                "candidate_id",
                "fusion_ref",
                "capture_ref",
                "bbox_ref",
            )
        ):
            raise ValueError("binding is not sealed to one candidate")
        for field in ("target_binding_ref", "candidate_id", "bbox_ref"):
            owner_key = (field, binding[field])
            if owner_key in global_ref_owners:
                raise ValueError(f"{field} must be globally unique within the run")
            global_ref_owners[owner_key] = key
        eligibility = binding.get("eligibility")
        if eligibility not in {"ELIGIBLE", "INELIGIBLE"}:
            raise ValueError("binding eligibility is invalid")
        selected[key] = binding
    if set(selected) != target_keys:
        raise ValueError("target binding is missing")

    request_ref_owners: dict[str, tuple[str, str, str]] = {}
    for request in requests:
        request_ref = str(request.get("vista_request_ref") or "")
        owner = (
            str(request.get("case_id") or ""),
            str(request.get("target_binding_ref") or ""),
            str(request.get("candidate_id") or ""),
        )
        if not request_ref or request_ref in request_ref_owners:
            raise ValueError("vista_request_ref must be globally unique within the run")
        request_ref_owners[request_ref] = owner

    request_by_target: dict[str, dict[str, str] | None] = {}
    for key, binding in selected.items():
        exact = [
            request
            for request in requests
            if request.get("case_id") == key
        ]
        if binding["eligibility"] == "INELIGIBLE":
            if not binding.get("reason") or exact:
                raise ValueError("ineligible target must have reason and zero requests")
            request_by_target[key] = None
            continue
        if binding.get("reason"):
            raise ValueError("eligible target cannot carry ineligible reason")
        if len(exact) != 1:
            raise ValueError("eligible target must have exactly one request")
        request = exact[0]
        if request.get("candidate_id") != binding["candidate_id"]:
            raise ValueError("request candidate crosses target binding")
        if request.get("target_binding_ref") != binding["target_binding_ref"]:
            raise ValueError("request crosses sealed target binding")
        for field in ("fusion_ref", "capture_ref", "bbox_ref"):
            if request.get(field) != binding[field]:
                raise ValueError(f"request selected mapping parent mismatch: {field}")
        if request.get("submission_status") != "SUBMITTED":
            raise ValueError("eligible target was not submitted")
        if not request.get("vista_request_ref"):
            raise ValueError("submitted request reference is missing")
        request_by_target[key] = request
    unexpected = [
        request
        for request in requests
        if request.get("case_id") not in target_keys
    ]
    if unexpected:
        raise ValueError("cross-case request is invalid")
    return request_by_target


def _validate_pair_rows(
    rows: list[dict[str, Any]],
    *,
    selected_mapping: dict[str, dict[str, str] | None],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    row_keys: set[tuple[str, str, str, str]] = set()
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = tuple(
            str(row.get(field) or "")
            for field in (
                "case_id",
                "arm_id",
                "candidate_id",
                "vista_request_ref",
            )
        )
        if not all(key) or key in row_keys:
            raise ValueError("private scorer four-key row is missing or duplicate")
        row_keys.add(key)
        pair_key = (key[0], key[2], key[3])
        grouped.setdefault(pair_key, []).append(row)
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    pair_ref_owners: dict[tuple[str, str], tuple[str, str]] = {}
    for pair_rows in grouped.values():
        if len(pair_rows) != 2 or {row["arm_id"] for row in pair_rows} != set(PAIR_ARMS):
            raise ValueError("exact Hybrid pair is incomplete")
        baseline = next(row for row in pair_rows if row["arm_id"] == PAIR_ARMS[0])
        refined = next(row for row in pair_rows if row["arm_id"] == PAIR_ARMS[1])
        for field in PAIR_PARENT_FIELDS:
            if baseline.get(field) != refined.get(field):
                raise ValueError(f"Hybrid pair parent mismatch: {field}")
        target_key = str(baseline["case_id"])
        selected = selected_mapping.get(target_key)
        if not isinstance(selected, dict):
            raise ValueError("Hybrid pair has no eligible selected mapping")
        for field in (
            "case_id",
            "candidate_id",
            "vista_request_ref",
            "target_binding_ref",
            "fusion_ref",
            "capture_ref",
            "bbox_ref",
        ):
            if baseline.get(field) != selected.get(field):
                raise ValueError(f"Hybrid pair does not join selected mapping: {field}")
        for field in (
            "vista_request_ref",
            "target_binding_ref",
            "candidate_id",
            "bbox_ref",
        ):
            ref_key = (field, str(baseline[field]))
            if ref_key in pair_ref_owners:
                raise ValueError(f"Hybrid pair {field} is not globally one-to-one")
            pair_ref_owners[ref_key] = target_key
        pairs.append((baseline, refined))
    expected_pair_targets = {
        key for key, selected in selected_mapping.items() if isinstance(selected, dict)
    }
    if {str(baseline["case_id"]) for baseline, _ in pairs} != expected_pair_targets:
        raise ValueError("Hybrid pairs do not exactly cover the selected mapping")
    return pairs


def _bbox_center(bbox: list[int]) -> tuple[Fraction, Fraction]:
    if len(bbox) != 4:
        raise ValueError("bbox must contain four coordinates")
    x1, y1, x2, y2 = bbox
    if x2 <= x1 or y2 <= y1:
        raise ValueError("bbox is invalid")
    return Fraction(x1 + x2, 2), Fraction(y1 + y2, 2)


def _hits_any_region(
    point: tuple[Fraction, Fraction],
    regions: list[list[int]],
) -> int:
    x, y = point
    return int(any(x1 <= x < x2 and y1 <= y < y2 for x1, y1, x2, y2 in regions))


def _score_submitted_pairs(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, int | Fraction]:
    if not pairs:
        raise ValueError("submitted_count is below the sealed minimum")
    numerator = 0
    for baseline, refined in pairs:
        regions = baseline["acceptable_regions"]
        baseline_hit = _hits_any_region(_bbox_center(baseline["bbox"]), regions)
        result_status = refined.get("result_status")
        failure_statuses = {
            "failed",
            "timeout",
            "out_of_bounds",
            "missing",
        }
        if result_status not in {"validated", *failure_statuses}:
            raise ValueError("refinement terminal status is outside the sealed allowlist")
        if result_status in failure_statuses:
            refined_hit = 0
        else:
            expected_lineage = {
                field: refined[field]
                for field in (
                    "case_id",
                    "vista_request_ref",
                    "candidate_id",
                    "fusion_ref",
                    "capture_ref",
                    "target_binding_ref",
                    "bbox_ref",
                )
            }
            if refined.get("proposal_lineage") != expected_lineage:
                raise ValueError("validated proposal lineage is stale or wrong")
            point = refined.get("canonical_capture_pixel_point")
            if not isinstance(point, list) or len(point) != 2:
                raise ValueError("validated refined point is missing")
            refined_hit = _hits_any_region(
                (Fraction(point[0]), Fraction(point[1])),
                regions,
            )
        numerator += refined_hit - baseline_hit
    submitted_count = len(pairs)
    return {
        "gain_numerator": numerator,
        "submitted_count": submitted_count,
        "gain": Fraction(numerator, submitted_count),
    }


def _accepted_regression_attempt(
    attempts: list[dict[str, Any]],
    *,
    seal_sha256: str,
) -> str:
    retryable = {
        "pre_model_infrastructure_failure",
        "cleanup_indeterminate",
    }
    retry_count = 0
    for attempt in attempts:
        if attempt.get("seal_sha256") != seal_sha256:
            raise ValueError("attempt seal drifted")
        if attempt.get("complete") is True and attempt.get("lifecycle_verified") is True:
            return str(attempt["attempt_ref"])
        disposition = attempt.get("independent_review_disposition")
        if disposition not in retryable:
            raise ValueError(
                "same-seal retry is forbidden for model or gate quality; generate new seal"
            )
        retry_count += 1
        if retry_count > 1:
            raise ValueError("same-seal retry limit exceeded")
    raise ValueError("no complete lifecycle-verified attempt")


def _claim_id(config: dict[str, Any], identity: dict[str, str]) -> str:
    expected = config["holdout_claim"]["claim_identity_payload"]
    if identity != expected:
        raise ValueError("claim identity drifted from preregistration")
    return _sha256(identity)


def _authorization_matches(
    existing: dict[str, Any],
    candidate: dict[str, Any],
) -> bool:
    return _canonical_bytes(existing) == _canonical_bytes(candidate)


def _reject_runner_overrides(
    config: dict[str, Any],
    overrides: dict[str, Any],
) -> None:
    forbidden = set(config["holdout_claim"]["runner_overrides_forbidden"])
    attempted = forbidden.intersection(overrides)
    if attempted:
        raise ValueError(
            "runner override would permanently invalidate release: "
            + ",".join(sorted(attempted))
        )


def _valid_selected_mapping(
    *,
    case_id: str = "case/1",
    candidate_id: str = "candidate/1",
    request_ref: str = "request/1",
    binding_ref: str = "binding/1",
    fusion_ref: str = "fusion/1",
    capture_ref: str = "capture/1",
    bbox_ref: str = "bbox/1",
) -> dict[str, dict[str, str] | None]:
    return {
        case_id: {
            "case_id": case_id,
            "candidate_id": candidate_id,
            "vista_request_ref": request_ref,
            "target_binding_ref": binding_ref,
            "fusion_ref": fusion_ref,
            "capture_ref": capture_ref,
            "bbox_ref": bbox_ref,
            "submission_status": "SUBMITTED",
        }
    }


def _valid_pair(
    *,
    case_id: str = "case/1",
    candidate_id: str = "candidate/1",
    request_ref: str = "request/1",
    binding_ref: str = "binding/1",
    fusion_ref: str = "fusion/1",
    capture_ref: str = "capture/1",
    bbox_ref: str = "bbox/1",
    result_status: str = "validated",
    point: list[int] | None = None,
) -> list[dict[str, Any]]:
    common: dict[str, Any] = {
        "case_id": case_id,
        "candidate_id": candidate_id,
        "vista_request_ref": request_ref,
        "fusion_ref": fusion_ref,
        "capture_ref": capture_ref,
        "target_binding_ref": binding_ref,
        "bbox_ref": bbox_ref,
        "bbox": [0, 0, 4, 4],
        "acceptable_regions": [[3, 3, 5, 5]],
    }
    baseline = {**deepcopy(common), "arm_id": "omni_to_qwen"}
    refined = {
        **deepcopy(common),
        "arm_id": "omni_to_qwen_vista",
        "result_status": result_status,
        "canonical_capture_pixel_point": point if point is not None else [3, 3],
        "proposal_lineage": {
            "case_id": case_id,
            "vista_request_ref": request_ref,
            "candidate_id": candidate_id,
            "fusion_ref": fusion_ref,
            "capture_ref": capture_ref,
            "target_binding_ref": binding_ref,
            "bbox_ref": bbox_ref,
        },
    }
    return [baseline, refined]


def test_estimand_config_has_exact_closed_values() -> None:
    config = _load_estimand()

    assert tuple(config["arms"]["arm_ids"]) == ARM_IDS_V2
    assert config["execution_units"]["hybrid_invocation_unit"] == "screen_group"
    assert config["execution_units"]["incumbent_invocation_unit"] == "target"
    assert config["prediction"]["release_reads_split"] == "pre_review"
    assert config["point_metric"]["metric_id"] == (
        "acceptable_region_binary_gain_v1"
    )


def test_estimand_rejects_pre_correction_contract_version() -> None:
    config = json.loads(ESTIMAND_PATH.read_text(encoding="utf-8"))
    config["contract_version"] = "portfolio_hybrid_v1_1_estimand_v2"

    with pytest.raises(ValueError, match="contract_version"):
        _validate_estimand(config)


def test_estimand_exposes_only_opaque_case_identity_to_predictions() -> None:
    config = _load_estimand()
    metric = config["point_metric"]

    assert metric["row_key_fields"] == [
        "case_id",
        "arm_id",
        "candidate_id",
        "vista_request_ref",
    ]
    assert metric["pair_identity_fields"] == [
        "case_id",
        "candidate_id",
        "vista_request_ref",
    ]
    assert "target_id" not in metric["target_binding"]["binding_ref_exact_mapping_fields"]
    assert "target_id" not in metric["target_binding"]["request_ref_exact_mapping_fields"]
    assert "target_id" not in metric["refined"]["validated_proposal_lineage_fields"]
    assert config["semantic_target_metric"] == {
        "metric_id": "private_unique_target_center_containment_v1",
        "private_join_field": "case_id",
        "group_field": "screen_group",
        "region_center_formula": ["(x1+x2)/2", "(y1+y2)/2"],
        "candidate_containment_rule": "x1 <= x < x2 && y1 <= y < y2",
        "correct_match_cardinality": 1,
        "zero_match_policy": "wrong_target",
        "different_match_policy": "wrong_target",
        "multiple_match_policy": "wrong_target",
    }


def test_estimand_rejects_extra_arm_and_target_level_hybrid_invocations() -> None:
    config = _load_estimand()
    mutated = deepcopy(config)
    mutated["arms"]["arm_ids"].append("parallel_vista")
    with pytest.raises(ValueError, match="arm allowlist"):
        _validate_estimand(mutated)

    screen_group = "screen/1"
    target_ids = [f"target/{index}" for index in range(5)]
    invocations = [
        {"arm_id": "qwen_only", "screen_group": screen_group, "target_id": target}
        for target in target_ids
    ] + [
        {"arm_id": arm, "screen_group": screen_group}
        for arm in HYBRID_ARMS
    ]
    counts = _validate_invocations(
        config,
        invocations,
        screen_group=screen_group,
        target_ids=target_ids,
    )
    assert counts == {
        "hybrid_unique_invocation_count": 3,
        "hybrid_amortized_per_target_count": Fraction(3, 5),
        "incumbent_unique_invocation_count": 5,
        "incumbent_amortized_per_target_count": Fraction(1, 1),
    }

    target_level_hybrid = deepcopy(invocations)
    target_level_hybrid.append(
        {
            "arm_id": "omni_to_qwen_vista",
            "screen_group": screen_group,
            "target_id": target_ids[0],
        }
    )
    with pytest.raises(ValueError, match="screen-group scope"):
        _validate_invocations(
            config,
            target_level_hybrid,
            screen_group=screen_group,
            target_ids=target_ids,
        )


def test_bbox_center_half_open_upper_edge_and_multi_region_or_are_exact() -> None:
    assert _bbox_center([1, 3, 4, 8]) == (Fraction(5, 2), Fraction(11, 2))
    regions = [[0, 0, 2, 2], [2, 2, 5, 5]]
    assert _hits_any_region((Fraction(2), Fraction(2)), regions) == 1
    assert _hits_any_region((Fraction(5), Fraction(4)), regions) == 0
    assert _hits_any_region((Fraction(4), Fraction(5)), regions) == 0


def test_four_key_pair_requires_exact_two_arms_and_same_parents() -> None:
    rows = _valid_pair()
    selected_mapping = _valid_selected_mapping()
    assert len(_validate_pair_rows(rows, selected_mapping=selected_mapping)) == 1

    for field in ("fusion_ref", "candidate_id", "capture_ref"):
        mismatched = deepcopy(rows)
        mismatched[1][field] = f"different/{field}"
        with pytest.raises(ValueError, match="pair|parent"):
            _validate_pair_rows(mismatched, selected_mapping=selected_mapping)

    duplicate = deepcopy(rows) + [deepcopy(rows[1])]
    with pytest.raises(ValueError, match="four-key"):
        _validate_pair_rows(duplicate, selected_mapping=selected_mapping)

    cross_request = deepcopy(rows)
    cross_request[1]["vista_request_ref"] = "request/other"
    with pytest.raises(ValueError, match="pair"):
        _validate_pair_rows(cross_request, selected_mapping=selected_mapping)


def test_target_binding_rejects_cherry_pick_duplicate_ambiguous_and_cross_request() -> None:
    target_keys = {"case/1", "case/2"}
    bindings = [
        {
            "case_id": "case/1",
            "target_binding_ref": "binding/1",
            "candidate_id": "candidate/1",
            "fusion_ref": "fusion/1",
            "capture_ref": "capture/1",
            "bbox_ref": "bbox/1",
            "eligibility": "ELIGIBLE",
        },
        {
            "case_id": "case/2",
            "target_binding_ref": "binding/2",
            "candidate_id": "candidate/2",
            "fusion_ref": "fusion/1",
            "capture_ref": "capture/1",
            "bbox_ref": "bbox/2",
            "eligibility": "INELIGIBLE",
            "reason": "no_fused_candidate",
        },
    ]
    requests = [
        {
            "case_id": "case/1",
            "target_binding_ref": "binding/1",
            "candidate_id": "candidate/1",
            "fusion_ref": "fusion/1",
            "capture_ref": "capture/1",
            "bbox_ref": "bbox/1",
            "vista_request_ref": "request/1",
            "submission_status": "SUBMITTED",
        }
    ]
    selected = _validate_target_bindings(target_keys, bindings, requests)
    assert selected["case/1"]["vista_request_ref"] == "request/1"
    assert selected["case/2"] is None

    multiple_same_screen_proposals = requests + [
        {
            "case_id": "case/1",
            "target_binding_ref": "binding/1",
            "candidate_id": "candidate/better-looking",
            "fusion_ref": "fusion/1",
            "capture_ref": "capture/1",
            "bbox_ref": "bbox/better-looking",
            "vista_request_ref": "request/cherry-pick",
            "submission_status": "SUBMITTED",
        }
    ]
    with pytest.raises(ValueError, match="exactly one request"):
        _validate_target_bindings(
            target_keys,
            bindings,
            multiple_same_screen_proposals,
        )

    ambiguous = bindings + [deepcopy(bindings[0])]
    with pytest.raises(ValueError, match="duplicate, ambiguous"):
        _validate_target_bindings(target_keys, ambiguous, requests)

    with pytest.raises(ValueError, match="missing"):
        _validate_target_bindings(target_keys, bindings[:-1], requests)

    eligible_unsent = deepcopy(requests)
    eligible_unsent[0]["submission_status"] = "NOT_SUBMITTED"
    with pytest.raises(ValueError, match="not submitted"):
        _validate_target_bindings(target_keys, bindings, eligible_unsent)

    cross_candidate = deepcopy(requests)
    cross_candidate[0]["candidate_id"] = "candidate/other"
    with pytest.raises(ValueError, match="candidate"):
        _validate_target_bindings(target_keys, bindings, cross_candidate)

    ineligible_request = requests + [
        {
            "case_id": "case/2",
            "target_binding_ref": "binding/2",
            "candidate_id": "candidate/2",
            "fusion_ref": "fusion/1",
            "capture_ref": "capture/1",
            "bbox_ref": "bbox/2",
            "vista_request_ref": "request/2",
            "submission_status": "SUBMITTED",
        }
    ]
    with pytest.raises(ValueError, match="zero requests"):
        _validate_target_bindings(target_keys, bindings, ineligible_request)

    missing_ineligible_reason = deepcopy(bindings)
    missing_ineligible_reason[1].pop("reason")
    with pytest.raises(ValueError, match="reason"):
        _validate_target_bindings(target_keys, missing_ineligible_reason, requests)

    cross_case = requests + [
        {
            "case_id": "case/other",
            "target_binding_ref": "binding/other",
            "candidate_id": "candidate/other",
            "fusion_ref": "fusion/1",
            "capture_ref": "capture/1",
            "bbox_ref": "bbox/other",
            "vista_request_ref": "request/other",
            "submission_status": "SUBMITTED",
        }
    ]
    with pytest.raises(ValueError, match="cross-case"):
        _validate_target_bindings(target_keys, bindings, cross_case)


def test_submitted_failures_remain_in_exact_rational_denominator() -> None:
    failed_pair_rows = _valid_pair(
        case_id="case/2",
        candidate_id="candidate/2",
        request_ref="request/2",
        binding_ref="binding/2",
        bbox_ref="bbox/2",
        result_status="timeout",
    )
    selected_mapping = {
        **_valid_selected_mapping(),
        **_valid_selected_mapping(
            case_id="case/2",
            candidate_id="candidate/2",
            request_ref="request/2",
            binding_ref="binding/2",
            bbox_ref="bbox/2",
        ),
    }
    pairs = _validate_pair_rows(
        [*_valid_pair(point=[3, 3]), *failed_pair_rows],
        selected_mapping=selected_mapping,
    )

    score = _score_submitted_pairs(pairs)
    assert score == {
        "gain_numerator": 1,
        "submitted_count": 2,
        "gain": Fraction(1, 2),
    }
    assert score["gain"] != Fraction(1, 1)

    with pytest.raises(ValueError, match="sealed minimum"):
        _score_submitted_pairs([])


def test_regression_uses_first_complete_lifecycle_verified_attempt_without_cherry_pick() -> None:
    seal = "a" * 64
    attempts = [
        {
            "attempt_ref": "attempt/first",
            "seal_sha256": seal,
            "complete": True,
            "lifecycle_verified": True,
            "quality_score": 0.1,
        },
        {
            "attempt_ref": "attempt/better",
            "seal_sha256": seal,
            "complete": True,
            "lifecycle_verified": True,
            "quality_score": 1.0,
        },
    ]
    assert _accepted_regression_attempt(attempts, seal_sha256=seal) == (
        "attempt/first"
    )

    retry_after_infrastructure = [
        {
            "attempt_ref": "attempt/infra",
            "seal_sha256": seal,
            "complete": False,
            "lifecycle_verified": False,
            "independent_review_disposition": "pre_model_infrastructure_failure",
        },
        attempts[0],
    ]
    assert _accepted_regression_attempt(
        retry_after_infrastructure,
        seal_sha256=seal,
    ) == "attempt/first"

    two_retries = [deepcopy(retry_after_infrastructure[0])] * 2 + [attempts[0]]
    with pytest.raises(ValueError, match="retry limit"):
        _accepted_regression_attempt(two_retries, seal_sha256=seal)

    quality_retry = deepcopy(retry_after_infrastructure)
    quality_retry[0]["independent_review_disposition"] = "model_quality_failure"
    with pytest.raises(ValueError, match="new seal"):
        _accepted_regression_attempt(quality_retry, seal_sha256=seal)


def test_holdout_claim_identity_is_closed_while_provider_manifest_is_non_key() -> None:
    config = _load_estimand()
    identity = deepcopy(config["holdout_claim"]["claim_identity_payload"])
    claim_id = _claim_id(config, identity)
    assert claim_id == _sha256(identity)
    assert claim_id == "7d8c5536500bbd3d26d3d3590b97a604473a9ab804c1cb99b968314b5a3c5fcc"

    authorization_a = {
        **identity,
        "provider_manifest_sha256": "1" * 64,
        "provider_manifest_contract_version": "provider_manifest_v2",
    }
    authorization_b = {
        **identity,
        "provider_manifest_sha256": "2" * 64,
        "provider_manifest_contract_version": "provider_manifest_v2",
    }
    assert _claim_id(config, identity) == claim_id
    assert _claim_id(config, {key: authorization_b[key] for key in identity}) == claim_id
    assert not _authorization_matches(authorization_a, authorization_b)

    for field, replacement in (
        ("benchmark_release_id", "release/other"),
        ("corpus_parent_seal_sha256", "0" * 64),
        ("partition", "regression"),
    ):
        drifted = deepcopy(identity)
        drifted[field] = replacement
        with pytest.raises(ValueError, match="drifted"):
            _claim_id(config, drifted)


def test_automatic_gates_are_exact_and_config_has_no_action_point_authority() -> None:
    raw = ESTIMAND_PATH.read_text(encoding="utf-8")
    config = _load_estimand()
    gates = config["automatic_gates"]

    assert gates["wrong_target_count"] == 0
    assert Fraction(gates["min_coverage"]) == Fraction(1, 5)
    assert gates["important_target_correct_coverage_baseline_arm"] == "qwen_only"
    assert Fraction(gates["min_important_target_correct_coverage_delta"]) == Fraction(
        1,
        20,
    )
    assert gates["semantic_precision_baseline_arm"] == "qwen_only"
    assert Fraction(gates["min_semantic_precision_delta"]) == 0
    assert gates["min_vista_submitted_count"] == 1
    assert gates["required_vista_gain_numerator"] == ">0"
    assert "click_point" not in raw.casefold()
    assert config["safety"]["artifact_is_authorization"] is False
    assert config["safety"]["execute_binding_enabled"] is False
    assert config["safety"]["real_action_allowed"] is False
    assert config["safety"]["publish_allowed"] is False


def test_run_wide_binding_and_request_refs_cannot_be_reused_across_valid_targets() -> None:
    target_keys = {"case/1", "case/2"}
    unique_bindings = [
        {
            "case_id": "case/1",
            "target_binding_ref": "binding/1",
            "candidate_id": "candidate/1",
            "fusion_ref": "fusion/1",
            "capture_ref": "capture/1",
            "bbox_ref": "bbox/1",
            "eligibility": "ELIGIBLE",
        },
        {
            "case_id": "case/2",
            "target_binding_ref": "binding/2",
            "candidate_id": "candidate/2",
            "fusion_ref": "fusion/1",
            "capture_ref": "capture/1",
            "bbox_ref": "bbox/2",
            "eligibility": "ELIGIBLE",
        },
    ]
    unique_requests = [
        {
            "case_id": case_id,
            "target_binding_ref": binding_ref,
            "candidate_id": candidate_id,
            "fusion_ref": "fusion/1",
            "capture_ref": "capture/1",
            "bbox_ref": "bbox/1" if case_id == "case/1" else "bbox/2",
            "vista_request_ref": request_ref,
            "submission_status": "SUBMITTED",
        }
        for case_id, binding_ref, candidate_id, request_ref in (
            ("case/1", "binding/1", "candidate/1", "request/1"),
            ("case/2", "binding/2", "candidate/2", "request/2"),
        )
    ]

    shared_binding = deepcopy(unique_bindings)
    shared_binding[1]["target_binding_ref"] = "binding/1"
    with pytest.raises(ValueError, match="globally unique"):
        _validate_target_bindings(target_keys, shared_binding, unique_requests)

    shared_request = deepcopy(unique_requests)
    shared_request[1]["vista_request_ref"] = "request/1"
    with pytest.raises(ValueError, match="globally unique"):
        _validate_target_bindings(target_keys, unique_bindings, shared_request)

    shared_candidate = deepcopy(unique_bindings)
    shared_candidate[1]["candidate_id"] = "candidate/1"
    with pytest.raises(ValueError, match="globally unique"):
        _validate_target_bindings(target_keys, shared_candidate, unique_requests)


def test_pair_rows_must_join_the_exact_preselected_request_mapping() -> None:
    selected_mapping = _validate_target_bindings(
        {"case/1"},
        [
            {
                "case_id": "case/1",
                "target_binding_ref": "binding/selected",
                "candidate_id": "candidate/selected",
                "fusion_ref": "fusion/1",
                "capture_ref": "capture/1",
                "bbox_ref": "bbox/selected",
                "eligibility": "ELIGIBLE",
            }
        ],
        [
            {
                "case_id": "case/1",
                "target_binding_ref": "binding/selected",
                "candidate_id": "candidate/selected",
                "fusion_ref": "fusion/1",
                "capture_ref": "capture/1",
                "bbox_ref": "bbox/selected",
                "vista_request_ref": "request/selected",
                "submission_status": "SUBMITTED",
            }
        ],
    )
    unselected = _valid_pair(request_ref="request/better")

    with pytest.raises(ValueError, match="selected mapping"):
        _validate_pair_rows(unselected, selected_mapping=selected_mapping)

    two_targets = _validate_target_bindings(
        {"case/1", "case/2"},
        [
            {
                "case_id": f"case/{index}",
                "target_binding_ref": f"binding/{index}",
                "candidate_id": f"candidate/{index}",
                "fusion_ref": "fusion/1",
                "capture_ref": "capture/1",
                "bbox_ref": f"bbox/{index}",
                "eligibility": "ELIGIBLE",
            }
            for index in (1, 2)
        ],
        [
            {
                "case_id": f"case/{index}",
                "target_binding_ref": f"binding/{index}",
                "candidate_id": f"candidate/{index}",
                "fusion_ref": "fusion/1",
                "capture_ref": "capture/1",
                "bbox_ref": f"bbox/{index}",
                "vista_request_ref": f"request/{index}",
                "submission_status": "SUBMITTED",
            }
            for index in (1, 2)
        ],
    )
    cross_attached = [
        *_valid_pair(
            case_id="case/1",
            candidate_id="candidate/2",
            request_ref="request/2",
            binding_ref="binding/2",
            bbox_ref="bbox/2",
        ),
        *_valid_pair(
            case_id="case/2",
            candidate_id="candidate/1",
            request_ref="request/1",
            binding_ref="binding/1",
            bbox_ref="bbox/1",
        ),
    ]

    with pytest.raises(ValueError, match="selected mapping"):
        _validate_pair_rows(cross_attached, selected_mapping=two_targets)


def test_unknown_refinement_status_is_not_treated_as_validated_success() -> None:
    for failure_status in ("failed", "timeout", "out_of_bounds", "missing"):
        pair = _validate_pair_rows(
            _valid_pair(result_status=failure_status),
            selected_mapping=_valid_selected_mapping(),
        )[0]
        assert _score_submitted_pairs([pair]) == {
            "gain_numerator": 0,
            "submitted_count": 1,
            "gain": Fraction(0, 1),
        }

    for unknown_status in ("clipped", "stale", "wrong_revision"):
        pair = _validate_pair_rows(
            _valid_pair(result_status=unknown_status),
            selected_mapping=_valid_selected_mapping(),
        )[0]
        with pytest.raises(ValueError, match="status"):
            _score_submitted_pairs([pair])

    wrong_lineage_rows = _valid_pair()
    wrong_lineage_rows[1]["proposal_lineage"]["capture_ref"] = "capture/stale"
    wrong_lineage_pair = _validate_pair_rows(
        wrong_lineage_rows,
        selected_mapping=_valid_selected_mapping(),
    )[0]
    with pytest.raises(ValueError, match="lineage"):
        _score_submitted_pairs([wrong_lineage_pair])


def test_all_frozen_authorization_fields_are_forbidden_runner_overrides() -> None:
    config = _load_estimand()
    claim = config["holdout_claim"]

    assert set(claim["authorization_frozen_non_key_fields"]).issubset(
        claim["runner_overrides_forbidden"]
    )
    assert not {"code_sha256", "config_sha256", "profile_sha256"}.intersection(
        claim["runner_overrides_forbidden"]
    )

    identity = deepcopy(claim["claim_identity_payload"])
    claim_id = _claim_id(config, identity)
    authorization = {
        "provider_manifest_sha256": "1" * 64,
        "provider_manifest_contract_version": "provider_manifest_v2",
        "code_sha256_by_path": {"code.py": "2" * 64},
        "config_sha256_by_path": {"config.json": "3" * 64},
        "profile_sha256_by_id": {"profile/1": "4" * 64},
        "arm_order": list(ARM_IDS_V2),
        "exact_holdout_command": ["runner", "--partition", "holdout"],
        "exact_run_order": ["screen/1", "screen/2"],
        "owner_journal_root": "C:/owner-journals/release-1",
    }
    for field in claim["authorization_frozen_non_key_fields"]:
        mutated = deepcopy(authorization)
        value = mutated[field]
        if isinstance(value, dict):
            value["mutation"] = "f" * 64
        elif isinstance(value, list):
            value.append("mutation")
        else:
            mutated[field] = f"{value}-mutation"
        assert _claim_id(config, identity) == claim_id
        assert not _authorization_matches(authorization, mutated)
        with pytest.raises(ValueError, match="permanently invalidate"):
            _reject_runner_overrides(config, {field: mutated[field]})
