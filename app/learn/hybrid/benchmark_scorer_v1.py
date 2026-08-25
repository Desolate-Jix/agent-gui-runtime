"""Frozen scorer, lifecycle evidence and release gate for Portfolio Hybrid v1.1."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from copy import deepcopy
import hashlib
import math
from pathlib import Path
import re
from typing import Any

from app.learn.hybrid.benchmark import (
    ARM_IDS,
    canonical_json_bytes,
    content_sha256,
    validate_prediction_record,
    validate_prediction_request,
    verify_benchmark_manifest,
    verify_prediction_run,
)


SCORER_CONTRACT = "portfolio_hybrid_v1_1_scorer_report_v1"
LIFECYCLE_TEMPLATE_CONTRACT = "portfolio_hybrid_v1_1_lifecycle_evidence_template_v1"
LIFECYCLE_CONTRACT = "portfolio_hybrid_v1_1_lifecycle_evidence_v1"
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
        "approved_count",
        "selection_precision",
        "target_recall",
    ],
    "vista_metric_fields": [
        "case_count",
        "attempted_count",
        "succeeded_count",
        "refinement_complete_count",
        "review_required_count",
        "failed_count",
        "status_counts",
    ],
    "evidence_splits": ["public_evidence", "private_evidence"],
    "lineage_refs": ["benchmark_ref", "run_ref", "request_refs", "prediction_refs", "lifecycle_ref"],
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_NON_AUTHORIZING = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
}


def seal_lifecycle_evidence(
    evidence: Mapping[str, Any],
    prediction_run: Mapping[str, Any],
    prediction_requests: list[Mapping[str, Any]],
) -> dict[str, Any]:
    if not isinstance(evidence, Mapping):
        raise ValueError("lifecycle evidence must be an object")
    run = _run_shape(prediction_run)
    requests = _request_set_shape(prediction_requests, run)
    template = _closed(
        evidence,
        "lifecycle evidence template",
        {
            "contract_version",
            "max_simultaneous_gpu_owners",
            "providers",
            "orphan_provider_pids",
            "orphan_helper_pids",
            "lease_files_remaining",
        },
    )
    if template["contract_version"] != LIFECYCLE_TEMPLATE_CONTRACT:
        raise ValueError("lifecycle evidence template contract_version mismatch")
    for field in (
        "max_simultaneous_gpu_owners",
        "orphan_provider_pids",
        "orphan_helper_pids",
        "lease_files_remaining",
    ):
        template[field] = _non_negative_number(template[field], field, integer=True)
    expected_providers = sorted(
        {provider_id for request in requests for provider_id in request["required_provider_ids"]}
    )
    providers = template["providers"]
    if not isinstance(providers, list):
        raise ValueError("lifecycle providers must be a list")
    provider_records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(providers):
        provider = _closed(
            item,
            f"lifecycle providers[{index}]",
            {
                "provider_id",
                "cleanup_status",
                "vram_release_delta_mb",
                "compute_termination_after_cancellation",
                "compute_termination_after_timeout",
            },
        )
        provider_id = _string(provider["provider_id"], "lifecycle provider_id")
        if provider_id in seen:
            raise ValueError(f"duplicate lifecycle provider: {provider_id}")
        seen.add(provider_id)
        if provider_id not in expected_providers:
            raise ValueError(f"unexpected lifecycle provider: {provider_id}")
        if provider["cleanup_status"] != "verified":
            raise ValueError(f"lifecycle provider cleanup_status must be verified: {provider_id}")
        provider["vram_release_delta_mb"] = _non_negative_number(
            provider["vram_release_delta_mb"], "vram_release_delta_mb"
        )
        if (
            provider["compute_termination_after_cancellation"] != "verified"
            or provider["compute_termination_after_timeout"] != "verified"
        ):
            raise ValueError(f"lifecycle provider compute termination must be verified: {provider_id}")
        provider_records.append(provider)
    if seen != set(expected_providers):
        raise ValueError("lifecycle provider set is incomplete")
    request_refs = _request_refs(requests)
    run_ref = _run_ref(run)
    evidence_identity = {
        "run_ref": run_ref,
        "request_refs": request_refs,
        "provider_ids": expected_providers,
    }
    sealed = {
        "contract_version": LIFECYCLE_CONTRACT,
        "evidence_id": "lifecycle/" + hashlib.sha256(canonical_json_bytes(evidence_identity)).hexdigest(),
        "benchmark_ref": deepcopy(run["benchmark_ref"]),
        "run_ref": run_ref,
        "request_refs": request_refs,
        "max_simultaneous_gpu_owners": template["max_simultaneous_gpu_owners"],
        "providers": sorted(provider_records, key=lambda item: item["provider_id"]),
        "orphan_provider_pids": template["orphan_provider_pids"],
        "orphan_helper_pids": template["orphan_helper_pids"],
        "lease_files_remaining": template["lease_files_remaining"],
        **_NON_AUTHORIZING,
    }
    sealed["content_sha256"] = content_sha256(sealed)
    return validate_lifecycle_evidence(sealed, run, requests)


def validate_lifecycle_evidence(
    value: Mapping[str, Any],
    prediction_run: Mapping[str, Any],
    prediction_requests: list[Mapping[str, Any]],
) -> dict[str, Any]:
    run = _run_shape(prediction_run)
    requests = _request_set_shape(prediction_requests, run)
    lifecycle = _closed(
        value,
        "lifecycle evidence",
        {
            "contract_version",
            "evidence_id",
            "benchmark_ref",
            "run_ref",
            "request_refs",
            "max_simultaneous_gpu_owners",
            "providers",
            "orphan_provider_pids",
            "orphan_helper_pids",
            "lease_files_remaining",
            "artifact_is_authorization",
            "execute_binding_enabled",
            "content_sha256",
        },
    )
    if lifecycle["contract_version"] != LIFECYCLE_CONTRACT:
        raise ValueError("lifecycle evidence contract_version mismatch")
    _non_authorizing(lifecycle, "lifecycle evidence")
    if _sha(lifecycle["content_sha256"], "lifecycle content_sha256") != content_sha256(lifecycle):
        raise ValueError("lifecycle evidence content_sha256 mismatch")
    if lifecycle["benchmark_ref"] != run["benchmark_ref"]:
        raise ValueError("lifecycle evidence benchmark_ref mismatch")
    if lifecycle["run_ref"] != _run_ref(run):
        raise ValueError("lifecycle evidence run_ref mismatch")
    if lifecycle["request_refs"] != _request_refs(requests):
        raise ValueError("lifecycle evidence request refs mismatch")
    expected_providers = sorted(
        {provider_id for request in requests for provider_id in request["required_provider_ids"]}
    )
    identity = {
        "run_ref": _run_ref(run),
        "request_refs": _request_refs(requests),
        "provider_ids": expected_providers,
    }
    expected_id = "lifecycle/" + hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
    if lifecycle["evidence_id"] != expected_id:
        raise ValueError("lifecycle evidence_id mismatch")
    for field in (
        "max_simultaneous_gpu_owners",
        "orphan_provider_pids",
        "orphan_helper_pids",
        "lease_files_remaining",
    ):
        lifecycle[field] = _non_negative_number(lifecycle[field], field, integer=True)
    providers = lifecycle["providers"]
    if not isinstance(providers, list):
        raise ValueError("lifecycle providers must be a list")
    seen: set[str] = set()
    for item in providers:
        provider = _closed(
            item,
            "lifecycle provider",
            {
                "provider_id",
                "cleanup_status",
                "vram_release_delta_mb",
                "compute_termination_after_cancellation",
                "compute_termination_after_timeout",
            },
        )
        provider_id = _string(provider["provider_id"], "provider_id")
        if provider_id in seen:
            raise ValueError(f"duplicate lifecycle provider: {provider_id}")
        seen.add(provider_id)
        if provider_id not in expected_providers:
            raise ValueError(f"unexpected lifecycle provider: {provider_id}")
        if provider["cleanup_status"] != "verified":
            raise ValueError("lifecycle provider cleanup_status must be verified")
        _non_negative_number(provider["vram_release_delta_mb"], "vram_release_delta_mb")
        if (
            provider["compute_termination_after_cancellation"] != "verified"
            or provider["compute_termination_after_timeout"] != "verified"
        ):
            raise ValueError("lifecycle provider compute termination must be verified")
    if seen != set(expected_providers):
        raise ValueError("lifecycle provider set is incomplete")
    return lifecycle


def score_benchmark_predictions(
    sealed_manifest: Mapping[str, Any],
    prediction_run: Mapping[str, Any],
    prediction_requests: list[Mapping[str, Any]],
    predictions: list[Mapping[str, Any]],
    lifecycle_evidence: Mapping[str, Any],
    *,
    root: str | Path,
) -> dict[str, Any]:
    manifest = verify_benchmark_manifest(sealed_manifest, root=root)
    run = verify_prediction_run(prediction_run, manifest)
    requests = _validated_requests(prediction_requests, manifest, run)
    lifecycle = validate_lifecycle_evidence(lifecycle_evidence, run, requests)
    if not isinstance(predictions, list):
        raise ValueError("predictions must be a list")
    request_by_ref = {
        (request["request_id"], request["content_sha256"]): request for request in requests
    }
    records: list[dict[str, Any]] = []
    seen_requests: set[tuple[str, str]] = set()
    for prediction in predictions:
        if not isinstance(prediction, Mapping):
            raise ValueError("prediction must be an object")
        raw_ref = prediction.get("request_ref")
        key = (
            raw_ref.get("id") if isinstance(raw_ref, Mapping) else None,
            raw_ref.get("content_sha256") if isinstance(raw_ref, Mapping) else None,
        )
        request = request_by_ref.get(key)
        if request is None:
            raise ValueError("prediction request_ref is not in sealed run")
        if key in seen_requests:
            raise ValueError("duplicate prediction request_ref")
        seen_requests.add(key)
        records.append(validate_prediction_record(prediction, manifest, run, request, lifecycle))
    if seen_requests != set(request_by_ref):
        raise ValueError("prediction matrix must cover every sealed request exactly once")
    case_by_id = {
        case["case_id"]: case
        for case in manifest["cases"]
        if case["partition"] == run["partition"]
    }
    case_results: list[dict[str, Any]] = []
    vista_results: list[dict[str, Any]] = []
    arms: dict[str, dict[str, Any]] = {}
    lifecycle_ref = _lifecycle_ref(lifecycle)
    for arm_id in ARM_IDS:
        arm_records = sorted(
            (record for record in records if record["arm_id"] == arm_id),
            key=lambda item: item["case_id"],
        )
        split_results: dict[str, list[dict[str, Any]]] = {"pre_review": [], "post_review": []}
        for record in arm_records:
            gold = case_by_id[record["case_id"]]["gold"]
            prediction_ref = _prediction_ref(record)
            for split in ("pre_review", "post_review"):
                selection = record[split]
                result = {
                    "arm_id": arm_id,
                    "case_id": record["case_id"],
                    "partition": run["partition"],
                    "split": split,
                    "request_ref": deepcopy(record["request_ref"]),
                    "prediction_ref": prediction_ref,
                    "cleanup_evidence_ref": lifecycle_ref,
                    "selected": selection["selected"],
                    "candidate_id": selection["candidate_id"],
                    "point": selection["point"],
                    "correct": _correct(selection, gold),
                    "review_status": record["post_review"]["status"] if split == "post_review" else "not_applicable",
                }
                split_results[split].append(result)
                case_results.append(result)
            vista = record["vista"]
            vista_results.append(
                {
                    "arm_id": arm_id,
                    "case_id": record["case_id"],
                    "request_ref": deepcopy(record["request_ref"]),
                    "prediction_ref": prediction_ref,
                    "requested": vista["requested"],
                    "status": vista["status"],
                    "refinement_complete": vista["status"] == "succeeded"
                    and all(
                        vista[field] is not None
                        for field in ("candidate_bbox_ref", "roi_ref", "affine_transform_ref", "canonical_point")
                    ),
                }
            )
        arms[arm_id] = {
            "pre_review": _selection_metrics(split_results["pre_review"]),
            "post_review": _selection_metrics(split_results["post_review"]),
            "vista": _vista_metrics([item for item in vista_results if item["arm_id"] == arm_id]),
        }
    public = {
        "visibility": "public_aggregate",
        "partition": run["partition"],
        "case_count": len(case_by_id),
        "corpus_coverage": deepcopy(manifest["corpus_coverage"]),
        "arms": deepcopy(arms),
    }
    private = {
        "visibility": "private_gold_evaluation",
        "partition": run["partition"],
        "prediction_records": deepcopy(records),
        "case_results": case_results,
        "vista_results": vista_results,
    }
    private_ref = {
        "id": f"private-evidence/{run['run_id']}",
        "content_sha256": hashlib.sha256(canonical_json_bytes(private)).hexdigest(),
    }
    report = {
        "contract_version": SCORER_CONTRACT,
        "benchmark_ref": deepcopy(run["benchmark_ref"]),
        "run_ref": _run_ref(run),
        "partition": run["partition"],
        "artifact_seals": deepcopy(run["artifact_seals"]),
        "gate_config_identity": deepcopy(run["gate_config_identity"]),
        "provider_ids": sorted(run["provider_revisions"]),
        "provider_revisions_sha256": run["provider_revisions_sha256"],
        "budget_sha256": run["budget_sha256"],
        "context_policy_sha256": run["context_policy_sha256"],
        "request_refs": _request_refs(requests),
        "prediction_refs": sorted((_prediction_ref(record) for record in records), key=lambda item: item["id"]),
        "lifecycle_ref": lifecycle_ref,
        "corpus_coverage": deepcopy(manifest["corpus_coverage"]),
        "arms": arms,
        "public_evidence": public,
        "private_evidence_ref": private_ref,
        "private_evidence": private,
        **_NON_AUTHORIZING,
    }
    report["content_sha256"] = content_sha256(report)
    return _validate_score_report(report, manifest, run, requests, lifecycle)


def evaluate_release_gate(
    score_report: Mapping[str, Any],
    gate_config: Mapping[str, Any],
    lifecycle_evidence: Mapping[str, Any],
    sealed_manifest: Mapping[str, Any],
    prediction_run: Mapping[str, Any],
    prediction_requests: list[Mapping[str, Any]],
    *,
    root: str | Path,
) -> dict[str, Any]:
    manifest = verify_benchmark_manifest(sealed_manifest, root=root)
    run = verify_prediction_run(prediction_run, manifest)
    config = validate_gate_config(gate_config)
    evaluated_gate_identity = {
        "artifact_sha256": manifest["artifact_seals"]["gate_config"]["sha256"],
        "config_id": config["config_id"],
        "config_sha256": config["config_sha256"],
    }
    if (
        evaluated_gate_identity != manifest["gate_config_identity"]
        or evaluated_gate_identity != run["gate_config_identity"]
    ):
        raise ValueError("evaluated gate config does not match sealed gate artifact")
    requests = _validated_requests(prediction_requests, manifest, run)
    lifecycle = validate_lifecycle_evidence(lifecycle_evidence, run, requests)
    report = _validate_score_report(score_report, manifest, run, requests, lifecycle)
    failures: list[dict[str, Any]] = []
    quality = config["quality"]
    metrics = report["arms"][quality["release_arm"]][quality["split"]]
    _equal(failures, "quality.required_partition", report["partition"], quality["required_partition"])
    _at_least(failures, "quality.min_selected_count", metrics["selected_count"], quality["min_selected_count"])
    _at_least(failures, "quality.min_selection_precision", metrics["selection_precision"], quality["min_selection_precision"])
    _at_least(failures, "quality.min_target_recall", metrics["target_recall"], quality["min_target_recall"])
    _at_most(failures, "quality.max_wrong_selected_count", metrics["wrong_selected_count"], quality["max_wrong_selected_count"])
    _equal(failures, "quality.post_review_status", metrics["approved_count"], metrics["case_count"])
    coverage = report["corpus_coverage"]
    _at_least(failures, "quality.min_distinct_image_count", coverage["distinct_image_count"], quality["min_distinct_image_count"])
    _at_most(failures, "quality.max_distinct_image_count", coverage["distinct_image_count"], quality["max_distinct_image_count"])
    _at_least(failures, "quality.min_target_count", coverage["target_count"], quality["min_target_count"])
    _at_most(failures, "quality.max_target_count", coverage["target_count"], quality["max_target_count"])
    _at_least(
        failures,
        "quality.min_holdout_distinct_image_count",
        coverage["partition_image_counts"]["holdout"],
        quality["min_holdout_distinct_image_count"],
    )
    _at_least(
        failures,
        "quality.min_holdout_target_count",
        coverage["partition_target_counts"]["holdout"],
        quality["min_holdout_target_count"],
    )
    _equal(failures, "quality.image_review_complete", coverage["image_review_complete"], True)
    _equal(failures, "quality.target_review_complete", coverage["target_review_complete"], True)
    vista = report["arms"][quality["release_arm"]]["vista"]
    if quality["require_vista_success"]:
        vista_ok = (
            vista["attempted_count"] == vista["case_count"]
            and vista["succeeded_count"] == vista["case_count"]
            and vista["refinement_complete_count"] == vista["case_count"]
            and vista["failed_count"] == 0
        )
        _equal(failures, "quality.vista_success", vista_ok, True)
    cleanup = config["cleanup"]
    _at_most(failures, "cleanup.max_simultaneous_gpu_owners", lifecycle["max_simultaneous_gpu_owners"], cleanup["max_simultaneous_gpu_owners"])
    _at_most(failures, "cleanup.orphan_provider_pids", lifecycle["orphan_provider_pids"], cleanup["max_orphan_provider_pids"])
    _at_most(failures, "cleanup.orphan_helper_pids", lifecycle["orphan_helper_pids"], cleanup["max_orphan_helper_pids"])
    _at_most(failures, "cleanup.lease_files_remaining", lifecycle["lease_files_remaining"], cleanup["max_lease_files_remaining"])
    for provider in lifecycle["providers"]:
        _equal(failures, "cleanup.provider_status", provider["cleanup_status"], cleanup["required_cleanup_status"])
        _at_most(failures, "cleanup.vram_release", provider["vram_release_delta_mb"], cleanup["vram_release_tolerance_mb"])
        if cleanup["require_cancel_timeout_compute_termination"]:
            _equal(failures, "cleanup.cancel_termination", provider["compute_termination_after_cancellation"], "verified")
            _equal(failures, "cleanup.timeout_termination", provider["compute_termination_after_timeout"], "verified")
    eligible = not failures
    decision = {
        "contract_version": GATE_DECISION_CONTRACT,
        "benchmark_ref": deepcopy(report["benchmark_ref"]),
        "run_ref": deepcopy(report["run_ref"]),
        "score_report_ref": {"id": f"score-report/{run['run_id']}", "content_sha256": report["content_sha256"]},
        "lifecycle_ref": _lifecycle_ref(lifecycle),
        "gate_config_sha256": config["config_sha256"],
        "gate_config_identity": deepcopy(evaluated_gate_identity),
        "eligible": eligible,
        "decision": "PROMOTION_ELIGIBLE" if eligible else "KEEP_EXPERIMENTAL",
        "blocking_failures": failures,
        "public_evidence": {
            "visibility": "public_aggregate",
            "release_arm": quality["release_arm"],
            "split": quality["split"],
            "partition": report["partition"],
            "quality_metrics": deepcopy(metrics),
            "cleanup_gate_status": "passed" if not any(item["gate_id"].startswith("cleanup.") for item in failures) else "failed",
        },
        "private_evidence_ref": deepcopy(report["private_evidence_ref"]),
        **_NON_AUTHORIZING,
    }
    decision["content_sha256"] = content_sha256(decision)
    return decision


def validate_gate_config(value: Mapping[str, Any]) -> dict[str, Any]:
    config = _closed(
        value,
        "gate config",
        {"contract_version", "config_id", "quality", "cleanup", "evidence_policy", "config_sha256"},
    )
    if config["contract_version"] != GATE_CONFIG_CONTRACT:
        raise ValueError("gate config contract_version mismatch")
    _string(config["config_id"], "gate config_id")
    quality = _closed(
        config["quality"],
        "gate quality",
        {
            "release_arm",
            "split",
            "required_partition",
            "min_selected_count",
            "min_selection_precision",
            "min_target_recall",
            "max_wrong_selected_count",
            "min_distinct_image_count",
            "max_distinct_image_count",
            "min_target_count",
            "max_target_count",
            "min_holdout_distinct_image_count",
            "min_holdout_target_count",
            "required_image_review_status",
            "required_target_review_status",
            "required_post_review_status",
            "require_vista_success",
        },
    )
    if quality["release_arm"] != "omni_to_qwen_vista":
        raise ValueError("release arm must be the VISTA arm")
    if quality["split"] != "post_review":
        raise ValueError("release split must be post_review")
    if quality["required_partition"] != "holdout":
        raise ValueError("release partition must be holdout")
    for field in ("min_selection_precision", "min_target_recall"):
        child = _finite(quality[field], f"quality.{field}")
        if child < 0 or child > 1:
            raise ValueError(f"quality.{field} must be between 0 and 1")
    for field in (
        "min_selected_count",
        "max_wrong_selected_count",
        "min_distinct_image_count",
        "max_distinct_image_count",
        "min_target_count",
        "max_target_count",
        "min_holdout_distinct_image_count",
        "min_holdout_target_count",
    ):
        quality[field] = _non_negative_number(quality[field], f"quality.{field}", integer=True)
    if quality["min_selected_count"] < 1:
        raise ValueError("quality.min_selected_count must be at least one")
    if (
        quality["min_distinct_image_count"] != 20
        or quality["max_distinct_image_count"] != 30
        or quality["min_target_count"] != 100
        or quality["max_target_count"] != 200
    ):
        raise ValueError("gate corpus bounds must remain 20-30 images and 100-200 targets")
    if (
        quality["min_holdout_distinct_image_count"] != 10
        or quality["min_holdout_target_count"] != 50
    ):
        raise ValueError("gate holdout bounds must remain at least 10 images and 50 targets")
    for field in ("required_image_review_status", "required_target_review_status", "required_post_review_status"):
        if quality[field] != "approved":
            raise ValueError(f"quality.{field} must be approved")
    if quality["require_vista_success"] is not True:
        raise ValueError("quality.require_vista_success must be boolean true")
    cleanup = _closed(
        config["cleanup"],
        "gate cleanup",
        {
            "max_simultaneous_gpu_owners",
            "required_cleanup_status",
            "max_orphan_provider_pids",
            "max_orphan_helper_pids",
            "max_lease_files_remaining",
            "vram_release_tolerance_mb",
            "require_cancel_timeout_compute_termination",
        },
    )
    for field in (
        "max_simultaneous_gpu_owners",
        "max_orphan_provider_pids",
        "max_orphan_helper_pids",
        "max_lease_files_remaining",
    ):
        cleanup[field] = _non_negative_number(cleanup[field], f"cleanup.{field}", integer=True)
    if cleanup["max_simultaneous_gpu_owners"] > 1:
        raise ValueError("cleanup.max_simultaneous_gpu_owners cannot exceed one")
    if any(cleanup[field] != 0 for field in ("max_orphan_provider_pids", "max_orphan_helper_pids", "max_lease_files_remaining")):
        raise ValueError("cleanup orphan and lease thresholds must remain zero")
    cleanup["vram_release_tolerance_mb"] = _non_negative_number(
        cleanup["vram_release_tolerance_mb"], "cleanup.vram_release_tolerance_mb"
    )
    if cleanup["required_cleanup_status"] != "verified":
        raise ValueError("cleanup.required_cleanup_status must be verified")
    if cleanup["require_cancel_timeout_compute_termination"] is not True:
        raise ValueError("cleanup.require_cancel_timeout_compute_termination must be boolean true")
    if config["evidence_policy"] != {"public": "aggregate_only", "private": "sealed_case_evidence"}:
        raise ValueError("gate evidence policy mismatch")
    declared = _sha(config["config_sha256"], "gate config_sha256")
    unhashed = deepcopy(config)
    unhashed.pop("config_sha256")
    try:
        actual = hashlib.sha256(canonical_json_bytes(unhashed)).hexdigest()
    except ValueError as error:
        raise ValueError("gate config numeric thresholds must be finite") from error
    if declared != actual:
        raise ValueError("gate config config_sha256 mismatch")
    return config


def _validate_score_report(
    value: Mapping[str, Any],
    manifest: Mapping[str, Any],
    run: Mapping[str, Any],
    requests: list[Mapping[str, Any]],
    lifecycle: Mapping[str, Any],
) -> dict[str, Any]:
    report = _closed(
        value,
        "score report",
        {
            "contract_version",
            "benchmark_ref",
            "run_ref",
            "partition",
            "artifact_seals",
            "gate_config_identity",
            "provider_ids",
            "provider_revisions_sha256",
            "budget_sha256",
            "context_policy_sha256",
            "request_refs",
            "prediction_refs",
            "lifecycle_ref",
            "corpus_coverage",
            "arms",
            "public_evidence",
            "private_evidence_ref",
            "private_evidence",
            "artifact_is_authorization",
            "execute_binding_enabled",
            "content_sha256",
        },
    )
    if report["contract_version"] != SCORER_CONTRACT:
        raise ValueError("score report contract_version mismatch")
    _non_authorizing(report, "score report")
    if _sha(report["content_sha256"], "score report content_sha256") != content_sha256(report):
        raise ValueError("score report content_sha256 mismatch")
    if report["benchmark_ref"] != run["benchmark_ref"] or report["run_ref"] != _run_ref(run):
        raise ValueError("score report benchmark/run provenance mismatch")
    if report["partition"] != run["partition"]:
        raise ValueError("score report partition lineage mismatch")
    if report["artifact_seals"] != manifest["artifact_seals"]:
        raise ValueError("score report sealed artifact identity mismatch")
    if report["gate_config_identity"] != manifest["gate_config_identity"]:
        raise ValueError("score report gate config identity mismatch")
    if report["provider_ids"] != sorted(manifest["provider_revisions"]):
        raise ValueError("score report provider set mismatch")
    for field, expected in (
        ("provider_revisions_sha256", manifest["provider_revisions_sha256"]),
        ("budget_sha256", manifest["shared_budget_sha256"]),
        ("context_policy_sha256", manifest["shared_context_policy_sha256"]),
    ):
        if report[field] != expected:
            raise ValueError(f"score report {field} mismatch")
    if report["request_refs"] != _request_refs(requests):
        raise ValueError("score report request refs mismatch")
    if report["lifecycle_ref"] != _lifecycle_ref(lifecycle):
        raise ValueError("score report lifecycle ref mismatch")
    if report["corpus_coverage"] != manifest["corpus_coverage"]:
        raise ValueError("score report corpus coverage mismatch")
    private = _closed(
        report["private_evidence"],
        "private evidence",
        {"visibility", "partition", "prediction_records", "case_results", "vista_results"},
    )
    if private["visibility"] != "private_gold_evaluation" or private["partition"] != run["partition"]:
        raise ValueError("private evidence partition/visibility mismatch")
    private_sha = hashlib.sha256(canonical_json_bytes(private)).hexdigest()
    if report["private_evidence_ref"] != {"id": f"private-evidence/{run['run_id']}", "content_sha256": private_sha}:
        raise ValueError("private evidence reference mismatch")
    case_by_id = {
        case["case_id"]: case
        for case in manifest["cases"]
        if case["partition"] == run["partition"]
    }
    request_by_identity = {(item["arm_id"], item["case"]["case_id"]): item for item in requests}
    request_by_ref = {
        (item["request_id"], item["content_sha256"]): item for item in requests
    }
    prediction_ref_by_identity: dict[tuple[str, str], dict[str, str]] = {}
    prediction_by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    raw_prediction_records = private["prediction_records"]
    if not isinstance(raw_prediction_records, list):
        raise ValueError("score report prediction records must be a list")
    seen_prediction_requests: set[tuple[str, str]] = set()
    for prediction in raw_prediction_records:
        raw_ref = prediction.get("request_ref") if isinstance(prediction, Mapping) else None
        ref_key = (
            raw_ref.get("id") if isinstance(raw_ref, Mapping) else None,
            raw_ref.get("content_sha256") if isinstance(raw_ref, Mapping) else None,
        )
        request = request_by_ref.get(ref_key)
        if request is None or ref_key in seen_prediction_requests:
            raise ValueError("score report prediction record request coverage mismatch")
        seen_prediction_requests.add(ref_key)
        validated_prediction = validate_prediction_record(
            prediction, manifest, run, request, lifecycle
        )
        prediction_identity = (validated_prediction["arm_id"], validated_prediction["case_id"])
        prediction_ref_by_identity[prediction_identity] = _prediction_ref(validated_prediction)
        prediction_by_identity[prediction_identity] = validated_prediction
    if seen_prediction_requests != set(request_by_ref):
        raise ValueError("score report prediction record coverage mismatch")
    expected_case_keys = {
        (arm_id, case_id, split)
        for arm_id in ARM_IDS
        for case_id in case_by_id
        for split in ("pre_review", "post_review")
    }
    actual_case_keys: set[tuple[str, str, str]] = set()
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in private["case_results"] if isinstance(private["case_results"], list) else []:
        result = _closed(
            item,
            "private case result",
            {
                "arm_id", "case_id", "partition", "split", "request_ref", "prediction_ref",
                "cleanup_evidence_ref", "selected", "candidate_id", "point", "correct", "review_status",
            },
        )
        key = (result["arm_id"], result["case_id"], result["split"])
        if key in actual_case_keys:
            raise ValueError("score report duplicate private case result")
        actual_case_keys.add(key)
        request = request_by_identity.get((result["arm_id"], result["case_id"]))
        if request is None or result["request_ref"] != _request_ref(request):
            raise ValueError("score report private request lineage mismatch")
        if result["partition"] != run["partition"] or result["cleanup_evidence_ref"] != _lifecycle_ref(lifecycle):
            raise ValueError("score report private lifecycle/partition mismatch")
        selection = _case_selection(result)
        source_prediction = prediction_by_identity[(result["arm_id"], result["case_id"])]
        source_selection = source_prediction[result["split"]]
        expected_review_status = (
            source_prediction["post_review"]["status"]
            if result["split"] == "post_review"
            else "not_applicable"
        )
        if selection != {
            "selected": source_selection["selected"],
            "candidate_id": source_selection["candidate_id"],
            "point": source_selection["point"],
        } or result["review_status"] != expected_review_status:
            raise ValueError("score report case result does not match prediction projection")
        expected_correct = _correct(selection, case_by_id[result["case_id"]]["gold"])
        if not isinstance(result["correct"], bool) or result["correct"] is not expected_correct:
            raise ValueError("score report private correctness mismatch")
        if result["split"] == "pre_review" and result["review_status"] != "not_applicable":
            raise ValueError("score report pre-review status mismatch")
        grouped.setdefault((result["arm_id"], result["split"]), []).append(result)
        expected_prediction_ref = prediction_ref_by_identity[(result["arm_id"], result["case_id"])]
        if result["prediction_ref"] != expected_prediction_ref:
            raise ValueError("score report prediction_ref lineage mismatch")
    if actual_case_keys != expected_case_keys:
        raise ValueError("score report private case coverage mismatch")
    expected_vista_keys = {(arm_id, case_id) for arm_id in ARM_IDS for case_id in case_by_id}
    actual_vista_keys: set[tuple[str, str]] = set()
    vista_grouped: dict[str, list[dict[str, Any]]] = {}
    for item in private["vista_results"] if isinstance(private["vista_results"], list) else []:
        vista = _closed(
            item,
            "private vista result",
            {"arm_id", "case_id", "request_ref", "prediction_ref", "requested", "status", "refinement_complete"},
        )
        key = (vista["arm_id"], vista["case_id"])
        if key in actual_vista_keys:
            raise ValueError("score report duplicate VISTA result")
        actual_vista_keys.add(key)
        request = request_by_identity.get(key)
        if request is None or vista["request_ref"] != _request_ref(request):
            raise ValueError("score report VISTA request lineage mismatch")
        if vista["prediction_ref"] != prediction_ref_by_identity[key]:
            raise ValueError("score report VISTA prediction lineage mismatch")
        source_vista = prediction_by_identity[key]["vista"]
        expected_refinement = source_vista["status"] == "succeeded" and all(
            source_vista[field] is not None
            for field in ("candidate_bbox_ref", "roi_ref", "affine_transform_ref", "canonical_point")
        )
        if (
            vista["requested"] is not source_vista["requested"]
            or vista["status"] != source_vista["status"]
            or vista["refinement_complete"] is not expected_refinement
        ):
            raise ValueError("score report VISTA result does not match prediction projection")
        if not isinstance(vista["requested"], bool) or not isinstance(vista["refinement_complete"], bool):
            raise ValueError("score report VISTA booleans are invalid")
        if vista["arm_id"] != "omni_to_qwen_vista" and vista["requested"] is not False:
            raise ValueError("score report pre-VISTA request mismatch")
        if vista["status"] == "succeeded" and vista["refinement_complete"] is not True:
            raise ValueError("score report VISTA refinement mismatch")
        vista_grouped.setdefault(vista["arm_id"], []).append(vista)
    if actual_vista_keys != expected_vista_keys:
        raise ValueError("score report private VISTA coverage mismatch")
    derived_arms = {
        arm_id: {
            "pre_review": _selection_metrics(grouped[(arm_id, "pre_review")]),
            "post_review": _selection_metrics(grouped[(arm_id, "post_review")]),
            "vista": _vista_metrics(vista_grouped[arm_id]),
        }
        for arm_id in ARM_IDS
    }
    if report["arms"] != derived_arms:
        raise ValueError("score report metric arithmetic mismatch")
    expected_prediction_refs = sorted(prediction_ref_by_identity.values(), key=lambda item: item["id"])
    if report["prediction_refs"] != expected_prediction_refs:
        raise ValueError("score report prediction refs mismatch")
    public = report["public_evidence"]
    expected_public = {
        "visibility": "public_aggregate",
        "partition": run["partition"],
        "case_count": len(case_by_id),
        "corpus_coverage": manifest["corpus_coverage"],
        "arms": derived_arms,
    }
    if public != expected_public:
        raise ValueError("score report public arms or aggregate mismatch")
    return report


def _correct(selection: Mapping[str, Any], gold: Mapping[str, Any]) -> bool:
    if selection["selected"] is not True:
        return False
    if selection["candidate_id"] in gold["acceptable_candidate_ids"]:
        return True
    point = selection["point"]
    return any(
        box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]
        for box in gold["acceptable_regions"]
    )


def _case_selection(result: Mapping[str, Any]) -> dict[str, Any]:
    selected = result["selected"]
    candidate_id = result["candidate_id"]
    point = result["point"]
    if not isinstance(selected, bool):
        raise ValueError("score report private selection schema is invalid")
    if selected:
        if not isinstance(candidate_id, str) or not candidate_id:
            raise ValueError("score report private selection schema is invalid")
        if (
            not isinstance(point, list)
            or len(point) != 2
            or any(isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item) for item in point)
        ):
            raise ValueError("score report private selection schema is invalid")
    elif candidate_id is not None or point is not None:
        raise ValueError("score report private selection schema is invalid")
    return {"selected": selected, "candidate_id": candidate_id, "point": point}


def _selection_metrics(results: list[Mapping[str, Any]]) -> dict[str, Any]:
    selected = [item for item in results if item["selected"]]
    correct = [item for item in selected if item["correct"]]
    case_count = len(results)
    return {
        "case_count": case_count,
        "selected_count": len(selected),
        "correct_selected_count": len(correct),
        "wrong_selected_count": len(selected) - len(correct),
        "unselected_count": case_count - len(selected),
        "approved_count": sum(item["review_status"] == "approved" for item in results),
        "selection_precision": round(len(correct) / len(selected), 6) if selected else None,
        "target_recall": round(len(correct) / case_count, 6) if case_count else None,
    }


def _vista_metrics(results: list[Mapping[str, Any]]) -> dict[str, Any]:
    statuses = Counter(item["status"] for item in results)
    attempted = sum(item["requested"] for item in results)
    succeeded = statuses["succeeded"]
    review_required = sum(
        statuses[status] for status in ("review_required", "failed", "out_of_bounds", "transform_invalid")
    )
    return {
        "case_count": len(results),
        "attempted_count": attempted,
        "succeeded_count": succeeded,
        "refinement_complete_count": sum(item["refinement_complete"] for item in results),
        "review_required_count": review_required,
        "failed_count": attempted - succeeded,
        "status_counts": dict(sorted(statuses.items())),
    }


def _validated_requests(
    values: list[Mapping[str, Any]], manifest: Mapping[str, Any], run: Mapping[str, Any]
) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        raise ValueError("prediction requests must be a list")
    requests = [validate_prediction_request(item, manifest, run) for item in values]
    expected = {(arm_id, case_id) for arm_id in ARM_IDS for case_id in run["case_ids"]}
    actual = {(item["arm_id"], item["case"]["case_id"]) for item in requests}
    if actual != expected or len(requests) != len(expected):
        raise ValueError("prediction request matrix must cover the sealed run exactly once")
    return sorted(requests, key=lambda item: item["request_id"])


def _run_shape(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("prediction run must be an object")
    run = deepcopy(dict(value))
    if run.get("content_sha256") != content_sha256(run):
        raise ValueError("prediction run content_sha256 mismatch")
    required = {"run_id", "benchmark_ref", "partition", "arm_identities", "case_ids", "provider_revisions", "content_sha256"}
    if not required <= set(run):
        raise ValueError("prediction run is missing sealed lineage")
    return run


def _request_set_shape(values: list[Mapping[str, Any]], run: Mapping[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        raise ValueError("prediction requests must be a list")
    requests: list[dict[str, Any]] = []
    identities: set[tuple[str, str]] = set()
    for value in values:
        if not isinstance(value, Mapping):
            raise ValueError("prediction request must be an object")
        request = deepcopy(dict(value))
        if request.get("content_sha256") != content_sha256(request):
            raise ValueError("prediction request content_sha256 mismatch")
        if request.get("run_ref") != _run_ref(run):
            raise ValueError("prediction request run_ref mismatch")
        identity = (request.get("arm_id"), request.get("case", {}).get("case_id"))
        if identity in identities:
            raise ValueError("duplicate prediction request")
        identities.add(identity)
        requests.append(request)
    expected = {(arm_id, case_id) for arm_id in ARM_IDS for case_id in run["case_ids"]}
    if identities != expected:
        raise ValueError("prediction requests do not cover sealed run")
    return sorted(requests, key=lambda item: item["request_id"])


def _request_refs(requests: list[Mapping[str, Any]]) -> list[dict[str, str]]:
    return sorted((_request_ref(item) for item in requests), key=lambda item: item["id"])


def _request_ref(request: Mapping[str, Any]) -> dict[str, str]:
    return {"id": request["request_id"], "content_sha256": request["content_sha256"]}


def _prediction_ref(prediction: Mapping[str, Any]) -> dict[str, str]:
    return {
        "id": f"prediction/{prediction['request_ref']['id']}",
        "content_sha256": prediction["content_sha256"],
    }


def _run_ref(run: Mapping[str, Any]) -> dict[str, str]:
    return {"id": run["run_id"], "content_sha256": run["content_sha256"]}


def _lifecycle_ref(lifecycle: Mapping[str, Any]) -> dict[str, str]:
    return {"id": lifecycle["evidence_id"], "content_sha256": lifecycle["content_sha256"]}


def _closed(value: Any, name: str, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    result = dict(value)
    actual = set(result)
    if actual != fields:
        missing = sorted(fields - actual)
        unknown = sorted(actual - fields)
        parts = []
        if missing:
            parts.append(f"missing fields: {', '.join(missing)}")
        if unknown:
            parts.append(f"unknown fields: {', '.join(unknown)}")
        raise ValueError(f"{name} is not closed ({'; '.join(parts)})")
    return result


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256")
    return value


def _finite(value: Any, name: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def _non_negative_number(value: Any, name: str, *, integer: bool = False) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        suffix = " integer" if integer else ""
        raise ValueError(f"{name} must be a finite non-negative{suffix}")
    child = value
    if child < 0 or (integer and not isinstance(child, int)):
        suffix = " integer" if integer else ""
        raise ValueError(f"{name} must be a finite non-negative{suffix}")
    return child


def _non_authorizing(value: Mapping[str, Any], name: str) -> None:
    for field, expected in _NON_AUTHORIZING.items():
        if value.get(field) is not expected:
            raise ValueError(f"{name} violates non-authorizing invariant: {field}")


def _equal(failures: list[dict[str, Any]], gate_id: str, actual: Any, expected: Any) -> None:
    if actual != expected or type(actual) is not type(expected):
        failures.append({"gate_id": gate_id, "reason": "value mismatch", "expected": expected, "actual": actual})


def _at_least(failures: list[dict[str, Any]], gate_id: str, actual: Any, expected: int | float) -> None:
    if isinstance(actual, bool) or not isinstance(actual, (int, float)) or not math.isfinite(actual) or actual < expected:
        failures.append({"gate_id": gate_id, "reason": "missing, invalid, or below threshold", "expected": expected, "actual": actual})


def _at_most(failures: list[dict[str, Any]], gate_id: str, actual: Any, expected: int | float) -> None:
    if isinstance(actual, bool) or not isinstance(actual, (int, float)) or not math.isfinite(actual) or actual < 0 or actual > expected:
        failures.append({"gate_id": gate_id, "reason": "missing, invalid, or above threshold", "expected": expected, "actual": actual})


__all__ = [
    "SCORER_SCHEMA_V1",
    "evaluate_release_gate",
    "score_benchmark_predictions",
    "seal_lifecycle_evidence",
    "validate_gate_config",
    "validate_lifecycle_evidence",
]
