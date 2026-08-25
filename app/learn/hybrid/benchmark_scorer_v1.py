"""Frozen scorer and fail-closed release gate for Portfolio Hybrid v1.1."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from copy import deepcopy
import hashlib
from typing import Any

from app.learn.hybrid.benchmark import (
    ARM_IDS,
    canonical_json_bytes,
    content_sha256,
    validate_prediction_record,
    verify_benchmark_manifest,
)


SCORER_CONTRACT = "portfolio_hybrid_v1_1_scorer_report_v1"
GATE_CONFIG_CONTRACT = "portfolio_hybrid_v1_1_release_gate_v1"
GATE_DECISION_CONTRACT = "portfolio_hybrid_v1_1_release_gate_decision_v1"
SCORER_SCHEMA_V1 = {
    "arm_fields": ["pre_review", "post_review", "vista"],
    "selection_metric_fields": [
        "case_count",
        "selected_count",
        "correct_selected_count",
        "wrong_selected_count",
        "unselected_count",
        "selection_precision",
        "target_recall",
    ],
    "vista_metric_fields": [
        "case_count",
        "attempted_count",
        "succeeded_count",
        "review_required_count",
        "failed_count",
        "status_counts",
    ],
    "evidence_splits": ["public_evidence", "private_evidence"],
}
_NON_AUTHORIZING = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
}


def score_benchmark_predictions(
    sealed_manifest: Mapping[str, Any], predictions: list[Mapping[str, Any]]
) -> dict[str, Any]:
    manifest = verify_benchmark_manifest(sealed_manifest)
    if not isinstance(predictions, list) or not predictions:
        raise ValueError("predictions must be a non-empty list")
    records = [validate_prediction_record(item, manifest) for item in predictions]
    seen: set[tuple[str, str]] = set()
    partitions: set[str] = set()
    for record in records:
        identity = (record["arm_id"], record["case_id"])
        if identity in seen:
            raise ValueError("duplicate arm/case prediction")
        seen.add(identity)
        partitions.add(record["partition"])
    if len(partitions) != 1:
        raise ValueError("one scorer report cannot mix partitions")
    partition = next(iter(partitions))
    case_by_id = {
        case["case_id"]: case
        for case in manifest["cases"]
        if case["partition"] == partition
    }
    expected = {(arm_id, case_id) for arm_id in ARM_IDS for case_id in case_by_id}
    if seen != expected:
        missing = sorted(expected - seen)
        unknown = sorted(seen - expected)
        raise ValueError(f"prediction matrix must be complete (missing={missing}, unknown={unknown})")

    case_results: list[dict[str, Any]] = []
    arms: dict[str, dict[str, Any]] = {}
    for arm_id in ARM_IDS:
        arm_records = sorted(
            (record for record in records if record["arm_id"] == arm_id),
            key=lambda item: item["case_id"],
        )
        split_results: dict[str, list[dict[str, Any]]] = {
            "pre_review": [],
            "post_review": [],
        }
        for record in arm_records:
            gold = case_by_id[record["case_id"]]["gold"]
            for split in ("pre_review", "post_review"):
                selection = record[split]
                correct = _selection_is_correct(selection, gold)
                result = {
                    "arm_id": arm_id,
                    "case_id": record["case_id"],
                    "partition": partition,
                    "split": split,
                    "selected": selection["selected"],
                    "correct": correct,
                    "review_status": record["post_review"]["status"]
                    if split == "post_review"
                    else "not_applicable",
                }
                split_results[split].append(result)
                case_results.append(result)
        arms[arm_id] = {
            "pre_review": _selection_metrics(split_results["pre_review"]),
            "post_review": _selection_metrics(split_results["post_review"]),
            "vista": _vista_metrics(arm_records),
        }

    public_evidence = {
        "visibility": "public_aggregate",
        "partition": partition,
        "case_count": len(case_by_id),
        "arms": deepcopy(arms),
    }
    private_evidence = {
        "visibility": "private_gold_evaluation",
        "partition": partition,
        "case_results": case_results,
    }
    private_ref = {
        "id": f"private-evidence/{manifest['benchmark_id']}/{partition}",
        "content_sha256": hashlib.sha256(canonical_json_bytes(private_evidence)).hexdigest(),
    }
    report = {
        "contract_version": SCORER_CONTRACT,
        "benchmark_ref": {
            "id": manifest["benchmark_id"],
            "content_sha256": manifest["content_sha256"],
        },
        "partition": partition,
        "provider_ids": sorted(manifest["provider_revisions"]),
        "arms": arms,
        "public_evidence": public_evidence,
        "private_evidence_ref": private_ref,
        "private_evidence": private_evidence,
        **_NON_AUTHORIZING,
    }
    report["content_sha256"] = content_sha256(report)
    return report


def evaluate_release_gate(
    score_report: Mapping[str, Any],
    gate_config: Mapping[str, Any],
    lifecycle_evidence: Mapping[str, Any] | None,
) -> dict[str, Any]:
    report = _validate_score_report(score_report)
    config = _validate_gate_config(gate_config)
    failures: list[dict[str, Any]] = []
    quality = config["quality"]
    arm_id = quality["release_arm"]
    split = quality["split"]
    metrics = report["arms"].get(arm_id, {}).get(split)
    if not isinstance(metrics, Mapping):
        _failure(failures, "quality.release_arm", "release arm metrics are missing", arm_id, None)
    else:
        _at_least(
            failures,
            "quality.min_selected_count",
            metrics.get("selected_count"),
            quality["min_selected_count"],
        )
        _at_least(
            failures,
            "quality.min_selection_precision",
            metrics.get("selection_precision"),
            quality["min_selection_precision"],
        )
        _at_least(
            failures,
            "quality.min_target_recall",
            metrics.get("target_recall"),
            quality["min_target_recall"],
        )
        _at_most(
            failures,
            "quality.max_wrong_selected_count",
            metrics.get("wrong_selected_count"),
            quality["max_wrong_selected_count"],
        )
    _evaluate_cleanup(
        failures,
        lifecycle_evidence,
        config["cleanup"],
        expected_providers=set(report["provider_ids"]),
    )
    eligible = not failures
    decision = {
        "contract_version": GATE_DECISION_CONTRACT,
        "benchmark_ref": deepcopy(report["benchmark_ref"]),
        "score_report_ref": {
            "id": f"score-report/{report['partition']}",
            "content_sha256": report["content_sha256"],
        },
        "gate_config_sha256": config["config_sha256"],
        "eligible": eligible,
        "decision": "PROMOTION_ELIGIBLE" if eligible else "KEEP_EXPERIMENTAL",
        "blocking_failures": failures,
        "public_evidence": {
            "visibility": "public_aggregate",
            "release_arm": arm_id,
            "split": split,
            "quality_metrics": deepcopy(metrics) if isinstance(metrics, Mapping) else None,
            "cleanup_gate_status": "passed" if not any(
                item["gate_id"].startswith("cleanup.") for item in failures
            ) else "failed",
        },
        "private_evidence_ref": deepcopy(report["private_evidence_ref"]),
        **_NON_AUTHORIZING,
    }
    decision["content_sha256"] = content_sha256(decision)
    return decision


def _selection_is_correct(selection: Mapping[str, Any], gold: Mapping[str, Any]) -> bool:
    if selection["selected"] is not True:
        return False
    if selection["candidate_id"] in gold["acceptable_candidate_ids"]:
        return True
    point = selection["point"]
    return any(
        region[0] <= point[0] <= region[2] and region[1] <= point[1] <= region[3]
        for region in gold["acceptable_regions"]
    )


def _selection_metrics(results: list[Mapping[str, Any]]) -> dict[str, Any]:
    selected = [item for item in results if item["selected"]]
    correct = [item for item in selected if item["correct"]]
    wrong = len(selected) - len(correct)
    case_count = len(results)
    return {
        "case_count": case_count,
        "selected_count": len(selected),
        "correct_selected_count": len(correct),
        "wrong_selected_count": wrong,
        "unselected_count": case_count - len(selected),
        "selection_precision": round(len(correct) / len(selected), 6) if selected else None,
        "target_recall": round(len(correct) / case_count, 6) if case_count else None,
    }


def _vista_metrics(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    statuses = Counter(record["vista"]["status"] for record in records)
    attempted = sum(count for status, count in statuses.items() if status != "not_requested")
    review_required = sum(
        statuses[status]
        for status in ("review_required", "failed", "out_of_bounds", "transform_invalid")
    )
    return {
        "case_count": len(records),
        "attempted_count": attempted,
        "succeeded_count": statuses["succeeded"],
        "review_required_count": review_required,
        "failed_count": attempted - statuses["succeeded"],
        "status_counts": dict(sorted(statuses.items())),
    }


def _validate_score_report(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("score_report must be an object")
    report = deepcopy(dict(value))
    required = {
        "contract_version",
        "benchmark_ref",
        "partition",
        "provider_ids",
        "arms",
        "public_evidence",
        "private_evidence_ref",
        "private_evidence",
        "artifact_is_authorization",
        "execute_binding_enabled",
        "content_sha256",
    }
    if set(report) != required:
        raise ValueError("score_report schema mismatch")
    if report["contract_version"] != SCORER_CONTRACT:
        raise ValueError("score_report contract_version mismatch")
    if report["artifact_is_authorization"] is not False or report["execute_binding_enabled"] is not False:
        raise ValueError("score_report violates non-authorizing boundary")
    if report["content_sha256"] != content_sha256(report):
        raise ValueError("score_report content_sha256 mismatch")
    if report["public_evidence"].get("visibility") != "public_aggregate":
        raise ValueError("public evidence visibility mismatch")
    if report["private_evidence"].get("visibility") != "private_gold_evaluation":
        raise ValueError("private evidence visibility mismatch")
    expected_private_sha = hashlib.sha256(
        canonical_json_bytes(report["private_evidence"])
    ).hexdigest()
    if report["private_evidence_ref"].get("content_sha256") != expected_private_sha:
        raise ValueError("private evidence reference mismatch")
    return report


def _validate_gate_config(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("gate_config must be an object")
    config = deepcopy(dict(value))
    if set(config) != {
        "contract_version",
        "config_id",
        "quality",
        "cleanup",
        "evidence_policy",
        "config_sha256",
    }:
        raise ValueError("gate_config schema mismatch")
    if config["contract_version"] != GATE_CONFIG_CONTRACT:
        raise ValueError("gate_config contract_version mismatch")
    declared = config.pop("config_sha256")
    actual = hashlib.sha256(canonical_json_bytes(config)).hexdigest()
    if declared != actual:
        raise ValueError("gate_config config_sha256 mismatch")
    config["config_sha256"] = declared
    quality = config["quality"]
    if not isinstance(quality, Mapping) or set(quality) != {
        "release_arm",
        "split",
        "min_selected_count",
        "min_selection_precision",
        "min_target_recall",
        "max_wrong_selected_count",
    }:
        raise ValueError("gate_config quality schema mismatch")
    if quality["release_arm"] not in ARM_IDS or quality["split"] not in {"pre_review", "post_review"}:
        raise ValueError("gate_config quality target mismatch")
    cleanup = config["cleanup"]
    if not isinstance(cleanup, Mapping) or set(cleanup) != {
        "max_simultaneous_gpu_owners",
        "required_cleanup_status",
        "max_orphan_provider_pids",
        "max_orphan_helper_pids",
        "max_lease_files_remaining",
        "vram_release_tolerance_mb",
        "require_cancel_timeout_compute_termination",
    }:
        raise ValueError("gate_config cleanup schema mismatch")
    if config["evidence_policy"] != {
        "public": "aggregate_only",
        "private": "sealed_case_evidence",
    }:
        raise ValueError("gate_config evidence policy mismatch")
    return config


def _evaluate_cleanup(
    failures: list[dict[str, Any]],
    evidence: Mapping[str, Any] | None,
    thresholds: Mapping[str, Any],
    *,
    expected_providers: set[str],
) -> None:
    lifecycle = dict(evidence) if isinstance(evidence, Mapping) else {}
    _at_most(
        failures,
        "cleanup.max_simultaneous_gpu_owners",
        lifecycle.get("max_simultaneous_gpu_owners"),
        thresholds["max_simultaneous_gpu_owners"],
    )
    _at_most(
        failures,
        "cleanup.orphan_provider_pids",
        lifecycle.get("orphan_provider_pids"),
        thresholds["max_orphan_provider_pids"],
    )
    _at_most(
        failures,
        "cleanup.orphan_helper_pids",
        lifecycle.get("orphan_helper_pids"),
        thresholds["max_orphan_helper_pids"],
    )
    _at_most(
        failures,
        "cleanup.lease_files_remaining",
        lifecycle.get("lease_files_remaining"),
        thresholds["max_lease_files_remaining"],
    )
    providers = lifecycle.get("providers")
    seen: set[str] = set()
    if not isinstance(providers, list):
        _failure(failures, "cleanup.provider_status", "provider cleanup evidence is missing", "list", providers)
        providers = []
    for provider in providers:
        if not isinstance(provider, Mapping):
            _failure(failures, "cleanup.provider_status", "provider cleanup evidence is indeterminate", "object", provider)
            continue
        provider_id = provider.get("provider_id")
        if isinstance(provider_id, str):
            seen.add(provider_id)
        if provider.get("cleanup_status") != thresholds["required_cleanup_status"]:
            _failure(
                failures,
                "cleanup.provider_status",
                f"cleanup status is not verified for {provider_id}",
                thresholds["required_cleanup_status"],
                provider.get("cleanup_status"),
            )
        _at_most(
            failures,
            "cleanup.vram_release",
            provider.get("vram_release_delta_mb"),
            thresholds["vram_release_tolerance_mb"],
        )
    if seen != expected_providers:
        _failure(
            failures,
            "cleanup.provider_status",
            "cleanup evidence does not cover every sealed provider",
            sorted(expected_providers),
            sorted(seen),
        )
    if thresholds["require_cancel_timeout_compute_termination"] is True and lifecycle.get(
        "cancel_timeout_compute_termination"
    ) != "verified":
        _failure(
            failures,
            "cleanup.cancel_timeout_termination",
            "compute termination after cancellation or timeout is not verified",
            "verified",
            lifecycle.get("cancel_timeout_compute_termination"),
        )


def _at_least(
    failures: list[dict[str, Any]], gate_id: str, actual: Any, expected: int | float
) -> None:
    if isinstance(actual, bool) or not isinstance(actual, (int, float)) or actual < expected:
        _failure(failures, gate_id, "value is missing, indeterminate, or below threshold", expected, actual)


def _at_most(
    failures: list[dict[str, Any]], gate_id: str, actual: Any, expected: int | float
) -> None:
    if isinstance(actual, bool) or not isinstance(actual, (int, float)) or actual > expected:
        _failure(failures, gate_id, "value is missing, indeterminate, or above threshold", expected, actual)


def _failure(
    failures: list[dict[str, Any]],
    gate_id: str,
    reason: str,
    expected: Any,
    actual: Any,
) -> None:
    failures.append(
        {"gate_id": gate_id, "reason": reason, "expected": expected, "actual": actual}
    )


__all__ = [
    "SCORER_SCHEMA_V1",
    "evaluate_release_gate",
    "score_benchmark_predictions",
]
