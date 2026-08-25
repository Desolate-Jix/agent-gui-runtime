from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from app.learn.hybrid.benchmark import (
    ARM_IDS,
    build_prediction_request,
    build_prediction_requests,
    contains_gold_fields,
    content_sha256,
    provider_manifest_projection,
    seal_benchmark_manifest,
    seal_prediction_run,
    validate_prediction_request,
    validate_prediction_record,
    verify_benchmark_manifest,
)
from app.learn.hybrid.benchmark_scorer_v1 import (
    evaluate_release_gate,
    score_benchmark_predictions,
    seal_lifecycle_evidence,
    validate_gate_config,
)


ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 64


def _write(path: Path, content: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def _arm(arm_id: str, phase: str, stages: list[str]) -> dict[str, object]:
    return {
        "arm_id": arm_id,
        "phase": phase,
        "producer_stages": stages,
        "budget": {
            "max_provider_calls_per_case": 3,
            "max_output_tokens_per_case": 2048,
            "max_wall_time_ms_per_case": 120000,
        },
        "context_policy": {
            "policy_version": "shared-uia-ocr-v1",
            "uia": "same_capture_optional",
            "ocr": "same_capture_optional",
        },
    }


def _manifest_template(tmp_path: Path) -> dict[str, object]:
    files = {
        "gate_config": "gate.json",
        "benchmark_producer": "benchmark.py",
        "benchmark_runner": "runner.py",
        "scorer": "scorer.py",
        "corpus_manifest": "corpus.json",
        "gold": "gold.json",
    }
    for name, relative in files.items():
        if name in {"gate_config", "corpus_manifest", "gold"}:
            continue
        _write(tmp_path / relative, f"{name}\n".encode("utf-8"))
    identity_a = hashlib.sha256(b"annotator-a").hexdigest()
    identity_b = hashlib.sha256(b"reviewer-b").hexdigest()
    identity_c = hashlib.sha256(b"image-reviewer-c").hexdigest()
    cases: list[dict[str, object]] = []
    for image_index in range(20):
        partition = "regression" if image_index < 10 else "holdout"
        image_path = f"images/image-{image_index:03d}.png"
        _write(tmp_path / image_path, f"synthetic-image-{image_index}\n".encode("utf-8"))
        for target_index in range(5):
            case_id = f"case-{image_index:03d}-{target_index:02d}"
            cases.append(
                {
                    "case_id": case_id,
                    "partition": partition,
                    "image_path": image_path,
                    "source_provenance": (
                        "existing_five_screen_regression"
                        if image_index < 5
                        else "public_synthetic_new"
                    ),
                    "image_review": {
                        "reviewer_identity_hash": identity_c,
                        "review_status": "approved",
                        "privacy_review_status": "approved",
                    },
                    "goal": f"Select important target {target_index}",
                    "gold": {
                        "acceptable_candidate_ids": [f"candidate/{case_id}"],
                        "acceptable_regions": [[10, 10, 30, 30]],
                        "annotator_identity_hash": identity_a,
                        "reviewer_identity_hash": identity_b,
                        "acceptable_region_disagreement": "resolved_by_independent_review",
                        "review_status": "approved",
                        "important_target": True,
                    },
                }
            )
    template = {
        "contract_version": "portfolio_hybrid_v1_1_benchmark_manifest_template_v1",
        "benchmark_id": "portfolio-hybrid-v1-1-test",
        "corpus_id": "synthetic-test-corpus",
        "artifact_paths": files,
        "provider_revisions": {
            "omni": "microsoft/OmniParser-v2@synthetic-revision",
            "qwen": "Qwen/Qwen2.5-VL@synthetic-revision",
            "vista": "portfolio-vista@future-revision",
        },
        "shared_budget": {
            "max_provider_calls_per_case": 3,
            "max_output_tokens_per_case": 2048,
            "max_wall_time_ms_per_case": 120000,
        },
        "shared_context_policy": {
            "policy_version": "shared-uia-ocr-v1",
            "uia": "same_capture_optional",
            "ocr": "same_capture_optional",
        },
        "arms": [
            _arm("qwen_only", "pre-vista", ["qwen"]),
            _arm("omni_only_discovery", "pre-vista", ["omni"]),
            _arm("omni_to_qwen", "pre-vista", ["omni", "qwen"]),
            _arm("omni_to_qwen_vista", "post-vista", ["omni", "qwen", "vista"]),
        ],
        "cases": cases,
        "evidence_policy": {
            "public": "aggregate_metrics_only",
            "private": "case_level_gold_and_predictions",
        },
    }
    _write_canonical_evidence(template, tmp_path)
    return template


def _write_canonical_evidence(template: dict[str, object], tmp_path: Path) -> None:
    cases = template["cases"]
    files = template["artifact_paths"]
    corpus_document = {
        "contract_version": "portfolio_hybrid_v1_1_corpus_records_v1",
        "cases": [
            {key: deepcopy(case[key]) for key in (
                "case_id", "partition", "image_path", "source_provenance",
                "image_review", "goal",
            )}
            for case in cases
        ],
    }
    gold_document = {
        "contract_version": "portfolio_hybrid_v1_1_gold_records_v1",
        "targets": [
            {"case_id": case["case_id"], "gold": deepcopy(case["gold"])}
            for case in cases
        ],
    }
    for relative, document in (
        (files["gate_config"], _gate_config()),
        (files["corpus_manifest"], corpus_document),
        (files["gold"], gold_document),
    ):
        _write(
            tmp_path / relative,
            (json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"),
        )


def _sealed(tmp_path: Path) -> dict[str, object]:
    return seal_benchmark_manifest(_manifest_template(tmp_path), root=tmp_path)


def _collapse_first_image(template: dict[str, object]) -> None:
    replacement = template["cases"][5]["image_path"]
    for case in template["cases"][:5]:
        case["image_path"] = replacement


def _drop_private_provider_evidence(report: dict[str, object]) -> None:
    prediction = report["private_evidence"]["prediction_records"][0]
    prediction["provider_evidence"] = []
    prediction["content_sha256"] = content_sha256(prediction)


def _diverge_case_from_prediction(report: dict[str, object]) -> None:
    report["private_evidence"]["case_results"][0]["candidate_id"] = "candidate/fabricated"


def _run(tmp_path: Path, sealed: dict[str, object], partition: str = "holdout") -> dict[str, object]:
    return seal_prediction_run(
        sealed,
        run_id=f"run/{partition}/001",
        partition=partition,
        root=tmp_path,
    )


def _requests(
    tmp_path: Path, sealed: dict[str, object], run: dict[str, object]
) -> list[dict[str, object]]:
    return build_prediction_requests(sealed, root=tmp_path, prediction_run=run)


def _lifecycle_template() -> dict[str, object]:
    return {
        "contract_version": "portfolio_hybrid_v1_1_lifecycle_evidence_template_v1",
        "max_simultaneous_gpu_owners": 1,
        "providers": [
            {
                "provider_id": provider_id,
                "cleanup_status": "verified",
                "vram_release_delta_mb": delta,
                "compute_termination_after_cancellation": "verified",
                "compute_termination_after_timeout": "verified",
            }
            for provider_id, delta in (("omni", 8), ("qwen", 16), ("vista", 32))
        ],
        "orphan_provider_pids": 0,
        "orphan_helper_pids": 0,
        "lease_files_remaining": 0,
    }


def _lifecycle(run: dict[str, object], requests: list[dict[str, object]]) -> dict[str, object]:
    return seal_lifecycle_evidence(_lifecycle_template(), run, requests)


def _selection(case_id: str, selected: bool = True) -> dict[str, object]:
    return {
        "selected": selected,
        "candidate_id": f"candidate/{case_id}" if selected else None,
        "point": [20, 20] if selected else None,
    }


def _prediction(
    request: dict[str, object], lifecycle: dict[str, object], *,
    selected: bool = True,
    review_status: str = "approved",
    vista_status: str | None = None,
) -> dict[str, object]:
    case_id = request["case"]["case_id"]
    selection = _selection(case_id, selected)
    is_vista = request["arm_id"] == "omni_to_qwen_vista"
    status = vista_status or ("succeeded" if is_vista else "not_requested")
    prediction = {
        "contract_version": "portfolio_hybrid_v1_1_prediction_v1",
        "benchmark_ref": deepcopy(request["benchmark_ref"]),
        "run_ref": deepcopy(request["run_ref"]),
        "request_ref": {"id": request["request_id"], "content_sha256": request["content_sha256"]},
        "arm_id": request["arm_id"],
        "statistical_identity_sha256": request["statistical_identity_sha256"],
        "case_id": case_id,
        "partition": request["case"]["partition"],
        "producer_artifact_ref": deepcopy(request["producer_artifact_ref"]),
        "provider_revisions_sha256": request["provider_revisions_sha256"],
        "budget_sha256": request["budget_sha256"],
        "context_policy_sha256": request["context_policy_sha256"],
        "pre_review": deepcopy(selection),
        "post_review": {"status": review_status, **deepcopy(selection)},
        "vista": {
            "requested": is_vista,
            "status": status,
            "candidate_id": f"candidate/{case_id}" if is_vista and status == "succeeded" else None,
            "candidate_bbox_ref": {"id": f"bbox/{case_id}", "content_sha256": SHA} if is_vista and status == "succeeded" else None,
            "roi_ref": {"id": f"roi/{case_id}", "content_sha256": SHA} if is_vista and status == "succeeded" else None,
            "affine_transform_ref": {"id": f"transform/{case_id}", "content_sha256": SHA} if is_vista and status == "succeeded" else None,
            "canonical_point": [20, 20] if is_vista and status == "succeeded" else None,
        },
        "provider_evidence": [
            {
                "provider_id": provider_id,
                "evidence_ref": {"id": f"evidence/{request['request_id']}/{provider_id}", "content_sha256": SHA},
            }
            for provider_id in request["required_provider_ids"]
        ],
        "cleanup_evidence_ref": {
            "id": lifecycle["evidence_id"],
            "content_sha256": lifecycle["content_sha256"],
        },
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    prediction["content_sha256"] = content_sha256(prediction)
    return prediction


def _predictions(requests: list[dict[str, object]], lifecycle: dict[str, object], **kwargs: object) -> list[dict[str, object]]:
    return [_prediction(request, lifecycle, **kwargs) for request in requests]


def _gate_config() -> dict[str, object]:
    config: dict[str, object] = {
        "contract_version": "portfolio_hybrid_v1_1_release_gate_v1",
        "config_id": "test-gate",
        "quality": {
            "release_arm": "omni_to_qwen_vista",
            "split": "post_review",
            "required_partition": "holdout",
            "min_selected_count": 1,
            "min_selection_precision": 1.0,
            "min_target_recall": 1.0,
            "max_wrong_selected_count": 0,
            "min_distinct_image_count": 20,
            "max_distinct_image_count": 30,
            "min_target_count": 100,
            "max_target_count": 200,
            "min_holdout_distinct_image_count": 10,
            "min_holdout_target_count": 50,
            "required_image_review_status": "approved",
            "required_target_review_status": "approved",
            "required_post_review_status": "approved",
            "require_vista_success": True,
        },
        "cleanup": {
            "max_simultaneous_gpu_owners": 1,
            "required_cleanup_status": "verified",
            "max_orphan_provider_pids": 0,
            "max_orphan_helper_pids": 0,
            "max_lease_files_remaining": 0,
            "vram_release_tolerance_mb": 64,
            "require_cancel_timeout_compute_termination": True,
        },
        "evidence_policy": {
            "public": "aggregate_only",
            "private": "sealed_case_evidence",
        },
    }
    config["config_sha256"] = hashlib.sha256(
        json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return config


def _score_bundle(tmp_path: Path, partition: str = "holdout", **prediction_kwargs: object) -> tuple[dict[str, object], ...]:
    sealed = _sealed(tmp_path)
    run = _run(tmp_path, sealed, partition)
    requests = _requests(tmp_path, sealed, run)
    lifecycle = _lifecycle(run, requests)
    predictions = _predictions(requests, lifecycle, **prediction_kwargs)
    report = score_benchmark_predictions(
        sealed, run, requests, predictions, lifecycle, root=tmp_path
    )
    return sealed, run, requests, lifecycle, predictions, report


def test_provider_projection_and_requests_never_contain_scorer_private_fields(tmp_path: Path) -> None:
    sealed = _sealed(tmp_path)
    run = _run(tmp_path, sealed)
    projection = provider_manifest_projection(sealed, run, root=tmp_path)
    request = build_prediction_request(
        sealed, "omni_to_qwen_vista", "case-010-00", root=tmp_path, prediction_run=run
    )
    forbidden = (
        "gold", "expected", "acceptable", "annotator", "reviewer",
        "scorer_only", "private_evidence", "ground_truth",
    )
    for artifact in (projection, request):
        encoded = json.dumps(artifact, sort_keys=True).casefold()
        assert not any(token in encoded for token in forbidden)
        assert contains_gold_fields(artifact) is False


@pytest.mark.parametrize(
    "private_key",
    [
        "gold_label", "expected_target", "acceptable_candidate_ids", "acceptable_regions",
        "annotator_hash", "reviewer_hash", "scorer_only_hint", "private_evidence",
        "ground_truth_target",
    ],
)
def test_gold_field_detector_rejects_adversarial_nested_private_keys(private_key: str) -> None:
    assert contains_gold_fields({"safe": [{"nested": {private_key: "secret"}}]}) is True


def test_seal_binds_release_corpus_cardinality_and_review_completeness(tmp_path: Path) -> None:
    sealed = _sealed(tmp_path)
    assert sealed["corpus_coverage"] == {
        "distinct_image_count": 20,
        "target_count": 100,
        "partition_image_counts": {"holdout": 10, "regression": 10},
        "partition_target_counts": {"holdout": 50, "regression": 50},
        "partitions_disjoint": True,
        "existing_five_screen_regression_image_count": 5,
        "image_review_complete": True,
        "target_review_complete": True,
    }
    assert verify_benchmark_manifest(sealed, root=tmp_path) == sealed


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda template: template["cases"].pop(), "100 to 200"),
        (_collapse_first_image, "20 to 30"),
        (lambda template: template["cases"][0]["image_review"].__setitem__("review_status", "pending"), "image review"),
        (lambda template: template["cases"][0]["gold"].__setitem__("review_status", "pending"), "target review"),
        (lambda template: template["cases"][0]["gold"].__setitem__("important_target", False), "important target"),
    ],
)
def test_seal_rejects_incomplete_release_corpus(tmp_path: Path, mutate: object, reason: str) -> None:
    template = _manifest_template(tmp_path)
    mutate(template)
    _write_canonical_evidence(template, tmp_path)
    with pytest.raises(ValueError, match=reason):
        seal_benchmark_manifest(template, root=tmp_path)


def test_seal_rejects_cross_partition_image_paths_and_hashes(tmp_path: Path) -> None:
    template = _manifest_template(tmp_path)
    regression_path = template["cases"][0]["image_path"]
    template["cases"][50]["image_path"] = regression_path
    _write_canonical_evidence(template, tmp_path)
    with pytest.raises(ValueError, match="partition image paths and hashes must be disjoint"):
        seal_benchmark_manifest(template, root=tmp_path)


def test_seal_requires_minimum_holdout_images_and_targets(tmp_path: Path) -> None:
    template = _manifest_template(tmp_path)
    for case in template["cases"][50:95]:
        case["partition"] = "regression"
    _write_canonical_evidence(template, tmp_path)
    with pytest.raises(ValueError, match="holdout must contain at least 10 distinct screenshots and 50 targets"):
        seal_benchmark_manifest(template, root=tmp_path)


def test_existing_five_screen_provenance_is_regression_only(tmp_path: Path) -> None:
    template = _manifest_template(tmp_path)
    template["cases"][0]["partition"] = "holdout"
    _write_canonical_evidence(template, tmp_path)
    with pytest.raises(ValueError, match="existing five-screen provenance is regression-only"):
        seal_benchmark_manifest(template, root=tmp_path)


def test_provider_projection_is_scoped_to_exact_run_partition(tmp_path: Path) -> None:
    sealed = _sealed(tmp_path)
    regression_run = _run(tmp_path, sealed, "regression")
    holdout_run = _run(tmp_path, sealed, "holdout")
    regression = provider_manifest_projection(sealed, regression_run, root=tmp_path)
    holdout = provider_manifest_projection(sealed, holdout_run, root=tmp_path)
    assert {case["partition"] for case in regression["cases"]} == {"regression"}
    assert {case["partition"] for case in holdout["cases"]} == {"holdout"}
    assert {case["case_id"] for case in regression["cases"]}.isdisjoint(
        case["case_id"] for case in holdout["cases"]
    )
    assert regression["run_ref"] == {"id": regression_run["run_id"], "content_sha256": regression_run["content_sha256"]}


def test_actual_request_path_rehashes_all_sealed_files(tmp_path: Path) -> None:
    sealed = _sealed(tmp_path)
    run = _run(tmp_path, sealed)
    (tmp_path / "scorer.py").write_text("mutated\n", encoding="utf-8")
    with pytest.raises(ValueError, match="artifact seal mismatch: scorer"):
        build_prediction_request(
            sealed, "qwen_only", "case-010-00", root=tmp_path, prediction_run=run
        )


def test_request_rehash_rejects_same_size_restored_mtime_mutation(tmp_path: Path) -> None:
    sealed = _sealed(tmp_path)
    run = _run(tmp_path, sealed)
    build_prediction_request(
        sealed, "qwen_only", "case-010-00", root=tmp_path, prediction_run=run
    )
    path = tmp_path / "scorer.py"
    stat = path.stat()
    assert len(path.read_bytes()) == len(b"SCORER\n")
    path.write_bytes(b"SCORER\n")
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    with pytest.raises(ValueError, match="artifact seal mismatch: scorer"):
        build_prediction_request(
            sealed, "qwen_only", "case-010-00", root=tmp_path, prediction_run=run
        )


def test_seal_rejects_unequal_context_budget_and_duplicate_arms(tmp_path: Path) -> None:
    for mutation, reason in (
        (lambda value: value["arms"][2]["context_policy"].__setitem__("ocr", "disabled"), "shared UIA/OCR"),
        (lambda value: value["arms"][1]["budget"].__setitem__("max_provider_calls_per_case", 2), "equal budgets"),
        (lambda value: value["arms"].append({**deepcopy(value["arms"][2]), "arm_id": "alias"}), "duplicate statistical arm"),
    ):
        template = _manifest_template(tmp_path)
        mutation(template)
        with pytest.raises(ValueError, match=reason):
            seal_benchmark_manifest(template, root=tmp_path)


def test_sealed_request_binds_exact_run_arm_budget_context_producer_and_revisions(tmp_path: Path) -> None:
    sealed = _sealed(tmp_path)
    run = _run(tmp_path, sealed)
    request = build_prediction_request(
        sealed, "omni_to_qwen_vista", "case-010-00", root=tmp_path, prediction_run=run
    )
    arm = next(item for item in sealed["arms"] if item["arm_id"] == "omni_to_qwen_vista")
    assert request["run_ref"] == {"id": run["run_id"], "content_sha256": run["content_sha256"]}
    assert request["statistical_identity_sha256"] == arm["statistical_identity_sha256"]
    assert request["producer_artifact_ref"] == sealed["artifact_seals"]["benchmark_producer"]
    assert request["provider_revisions_sha256"] == sealed["provider_revisions_sha256"]
    assert request["budget_sha256"] == sealed["shared_budget_sha256"]
    assert request["context_policy_sha256"] == sealed["shared_context_policy_sha256"]
    assert request["required_provider_ids"] == ["omni", "qwen", "vista"]
    assert request["vista_payload"]["enabled"] is True
    assert len(request["content_sha256"]) == 64


@pytest.mark.parametrize(
    "mutation",
    ["missing", "extra", "contract", "enabled", "candidate", "bbox", "roi", "transform", "point"],
)
def test_vista_request_payload_is_closed_exact_and_pre_execution_null(
    tmp_path: Path, mutation: str
) -> None:
    sealed = _sealed(tmp_path)
    run = _run(tmp_path, sealed)
    request = build_prediction_request(
        sealed, "omni_to_qwen_vista", "case-010-00", root=tmp_path, prediction_run=run
    )
    payload = request["vista_payload"]
    if mutation == "missing":
        payload.pop("roi_ref")
    elif mutation == "extra":
        payload["proposal"] = "unexpected"
    elif mutation == "contract":
        payload["proposal_contract_version"] = "hybrid_vista_proposals_v2"
    elif mutation == "enabled":
        payload["enabled"] = False
    elif mutation == "candidate":
        payload["candidate_id"] = "candidate/preexecuted"
    elif mutation == "bbox":
        payload["candidate_bbox_ref"] = {"id": "bbox/preexecuted", "content_sha256": SHA}
    elif mutation == "roi":
        payload["roi_ref"] = {"id": "roi/preexecuted", "content_sha256": SHA}
    elif mutation == "transform":
        payload["affine_transform_ref"] = {"id": "transform/preexecuted", "content_sha256": SHA}
    else:
        payload["canonical_point"] = [20, 20]
    request["content_sha256"] = content_sha256(request)
    with pytest.raises(ValueError, match="VISTA payload"):
        validate_prediction_request(request, sealed, run)


def test_canonical_corpus_and_gold_artifacts_must_equal_scored_records(tmp_path: Path) -> None:
    template = _manifest_template(tmp_path)
    corpus_path = tmp_path / template["artifact_paths"]["corpus_manifest"]
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    corpus["cases"][0]["goal"] = "divergent corpus goal"
    corpus_path.write_text(
        json.dumps(corpus, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="canonical corpus artifact does not match inline cases"):
        seal_benchmark_manifest(template, root=tmp_path)

    template = _manifest_template(tmp_path)
    gold_path = tmp_path / template["artifact_paths"]["gold"]
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    gold["targets"][0]["gold"]["acceptable_candidate_ids"] = ["candidate/divergent"]
    gold_path.write_text(
        json.dumps(gold, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="canonical Gold artifact does not match inline Gold"):
        seal_benchmark_manifest(template, root=tmp_path)


def test_sealed_cases_bind_corpus_and_gold_artifact_lineage(tmp_path: Path) -> None:
    sealed = _sealed(tmp_path)
    case = sealed["cases"][0]
    assert case["corpus_artifact_sha256"] == sealed["artifact_seals"]["corpus_manifest"]["sha256"]
    assert case["gold_artifact_sha256"] == sealed["artifact_seals"]["gold"]["sha256"]
    assert len(case["corpus_record_sha256"]) == 64
    assert len(case["gold_record_sha256"]) == 64


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda prediction: prediction.__setitem__("run_ref", {"id": "stale", "content_sha256": SHA}), "run_ref"),
        (lambda prediction: prediction.__setitem__("statistical_identity_sha256", SHA), "statistical identity"),
        (lambda prediction: prediction.__setitem__("provider_evidence", []), "provider evidence"),
        (lambda prediction: prediction.__setitem__("cleanup_evidence_ref", None), "cleanup_evidence_ref"),
        (lambda prediction: prediction["vista"].__setitem__("candidate_bbox_ref", None), "bounded VISTA evidence"),
    ],
)
def test_prediction_rejects_unbound_or_missing_execution_evidence(tmp_path: Path, mutate: object, reason: str) -> None:
    sealed = _sealed(tmp_path)
    run = _run(tmp_path, sealed)
    requests = _requests(tmp_path, sealed, run)
    request = requests[-1]
    lifecycle = _lifecycle(run, requests)
    prediction = _prediction(request, lifecycle)
    mutate(prediction)
    prediction["content_sha256"] = content_sha256(prediction)
    with pytest.raises(ValueError, match=reason):
        validate_prediction_record(prediction, sealed, run, request, lifecycle)


def test_regression_report_can_never_be_promotion_eligible(tmp_path: Path) -> None:
    sealed, run, requests, lifecycle, _, report = _score_bundle(tmp_path, "regression")
    decision = evaluate_release_gate(report, _gate_config(), lifecycle, sealed, run, requests, root=tmp_path)
    assert decision["eligible"] is False
    assert decision["decision"] == "KEEP_EXPERIMENTAL"
    assert "quality.required_partition" in {item["gate_id"] for item in decision["blocking_failures"]}


def test_holdout_release_requires_vista_success_and_approved_post_review(tmp_path: Path) -> None:
    for kwargs, gate_id in (
        ({"vista_status": "not_requested"}, "quality.vista_success"),
        ({"review_status": "not_reviewed"}, "quality.post_review_status"),
    ):
        sealed, run, requests, lifecycle, _, report = _score_bundle(tmp_path, "holdout", **kwargs)
        decision = evaluate_release_gate(report, _gate_config(), lifecycle, sealed, run, requests, root=tmp_path)
        assert decision["eligible"] is False
        assert gate_id in {item["gate_id"] for item in decision["blocking_failures"]}


def test_exact_holdout_run_and_verified_evidence_can_pass_gate(tmp_path: Path) -> None:
    sealed, run, requests, lifecycle, _, report = _score_bundle(tmp_path, "holdout")
    decision = evaluate_release_gate(report, _gate_config(), lifecycle, sealed, run, requests, root=tmp_path)
    assert decision["eligible"] is True
    assert decision["decision"] == "PROMOTION_ELIGIBLE"
    assert decision["blocking_failures"] == []


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("none", "lifecycle evidence must be an object"),
        ("missing_providers", "missing fields"),
        ("duplicate_provider", "duplicate lifecycle provider"),
        ("unexpected_provider", "unexpected lifecycle provider"),
        ("nan_owner", "finite non-negative"),
        ("negative_pid", "finite non-negative"),
        ("boolean_lease", "finite non-negative"),
        ("infinite_vram", "finite non-negative"),
        ("indeterminate_cleanup", "cleanup_status"),
        ("indeterminate_termination", "termination"),
    ],
)
def test_lifecycle_contract_rejects_missing_duplicate_unexpected_and_invalid_values(
    tmp_path: Path, mutation: str, reason: str
) -> None:
    sealed = _sealed(tmp_path)
    run = _run(tmp_path, sealed)
    requests = _requests(tmp_path, sealed, run)
    candidate: object = _lifecycle_template()
    if mutation == "none":
        candidate = None
    elif mutation == "missing_providers":
        candidate.pop("providers")
    elif mutation == "duplicate_provider":
        candidate["providers"].append(deepcopy(candidate["providers"][0]))
    elif mutation == "unexpected_provider":
        candidate["providers"].append({**deepcopy(candidate["providers"][0]), "provider_id": "unexpected"})
    elif mutation == "nan_owner":
        candidate["max_simultaneous_gpu_owners"] = float("nan")
    elif mutation == "negative_pid":
        candidate["orphan_provider_pids"] = -1
    elif mutation == "boolean_lease":
        candidate["lease_files_remaining"] = True
    elif mutation == "infinite_vram":
        candidate["providers"][0]["vram_release_delta_mb"] = float("inf")
    elif mutation == "indeterminate_cleanup":
        candidate["providers"][0]["cleanup_status"] = "indeterminate"
    elif mutation == "indeterminate_termination":
        candidate["providers"][0]["compute_termination_after_timeout"] = "indeterminate"
    with pytest.raises(ValueError, match=reason):
        seal_lifecycle_evidence(candidate, run, requests)


def test_gate_rejects_stale_lifecycle_and_prediction_cleanup_refs(tmp_path: Path) -> None:
    sealed, run, requests, lifecycle, predictions, report = _score_bundle(tmp_path, "holdout")
    stale = deepcopy(lifecycle)
    stale["run_ref"] = {"id": "run/stale", "content_sha256": SHA}
    stale["content_sha256"] = content_sha256(stale)
    with pytest.raises(ValueError, match="run_ref"):
        evaluate_release_gate(report, _gate_config(), stale, sealed, run, requests, root=tmp_path)
    prediction = deepcopy(predictions[0])
    prediction["cleanup_evidence_ref"] = {"id": "cleanup/stale", "content_sha256": SHA}
    prediction["content_sha256"] = content_sha256(prediction)
    predictions[0] = prediction
    with pytest.raises(ValueError, match="cleanup_evidence_ref"):
        score_benchmark_predictions(sealed, run, requests, predictions, lifecycle, root=tmp_path)


def test_score_and_gate_rehash_files_after_request_and_scoring(tmp_path: Path) -> None:
    sealed = _sealed(tmp_path)
    run = _run(tmp_path, sealed)
    requests = _requests(tmp_path, sealed, run)
    lifecycle = _lifecycle(run, requests)
    predictions = _predictions(requests, lifecycle)
    gold_path = tmp_path / "gold.json"
    original_gold = gold_path.read_bytes()
    gold_path.write_bytes(original_gold.replace(b"case-000-00", b"case-000-XX", 1))
    with pytest.raises(ValueError, match="artifact seal mismatch: gold"):
        score_benchmark_predictions(
            sealed, run, requests, predictions, lifecycle, root=tmp_path
        )
    gold_path.write_bytes(original_gold)
    report = score_benchmark_predictions(
        sealed, run, requests, predictions, lifecycle, root=tmp_path
    )
    producer_path = tmp_path / "benchmark.py"
    producer_path.write_bytes(b"BENCHMARK\n")
    with pytest.raises(ValueError, match="artifact seal mismatch: benchmark_producer"):
        evaluate_release_gate(
            report, _gate_config(), lifecycle, sealed, run, requests, root=tmp_path
        )


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda report: report["arms"]["omni_to_qwen_vista"]["post_review"].__setitem__("selected_count", 999), "metric arithmetic"),
        (lambda report: report.__setitem__("partition", "regression"), "partition lineage"),
        (lambda report: report.__setitem__("provider_ids", ["omni"]), "provider set"),
        (lambda report: report["public_evidence"].__setitem__("arms", {}), "public arms"),
        (lambda report: report["private_evidence"]["case_results"].pop(), "case coverage"),
        (lambda report: report["private_evidence"]["case_results"][0].__setitem__("selected", 1), "selection schema"),
        (_drop_private_provider_evidence, "provider evidence"),
        (_diverge_case_from_prediction, "prediction projection"),
    ],
)
def test_gate_fully_revalidates_score_report_not_just_its_hash(
    tmp_path: Path, mutate: object, reason: str
) -> None:
    sealed, run, requests, lifecycle, _, report = _score_bundle(tmp_path, "holdout")
    mutate(report)
    report["private_evidence_ref"]["content_sha256"] = hashlib.sha256(
        json.dumps(report["private_evidence"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    report["content_sha256"] = content_sha256(report)
    with pytest.raises(ValueError, match=reason):
        evaluate_release_gate(report, _gate_config(), lifecycle, sealed, run, requests, root=tmp_path)


@pytest.mark.parametrize(
    ("path", "value", "reason"),
    [
        (("quality", "min_selection_precision"), float("nan"), "finite"),
        (("quality", "min_target_recall"), True, "finite"),
        (("quality", "min_selected_count"), -1, "non-negative integer"),
        (("quality", "required_partition"), "regression", "holdout"),
        (("quality", "release_arm"), "qwen_only", "VISTA"),
        (("cleanup", "vram_release_tolerance_mb"), -1, "finite non-negative"),
        (("cleanup", "max_orphan_provider_pids"), True, "non-negative integer"),
        (("cleanup", "required_cleanup_status"), "indeterminate", "verified"),
        (("cleanup", "require_cancel_timeout_compute_termination"), 1, "boolean true"),
    ],
)
def test_gate_config_rejects_invalid_or_weakened_semantics(path: tuple[str, str], value: object, reason: str) -> None:
    config = _gate_config()
    config[path[0]][path[1]] = value
    config["config_sha256"] = hashlib.sha256(
        json.dumps({key: child for key, child in config.items() if key != "config_sha256"}, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=True).encode("utf-8")
    ).hexdigest()
    with pytest.raises(ValueError, match=reason):
        validate_gate_config(config)


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("quality", "min_selection_precision", 0.5),
        ("quality", "min_target_recall", 0.5),
        ("quality", "max_wrong_selected_count", 1),
        (None, "config_id", "rehashed-weakened-gate"),
        ("cleanup", "vram_release_tolerance_mb", 65),
    ],
)
def test_evaluation_rejects_finite_rehashed_gate_not_identical_to_sealed_artifact(
    tmp_path: Path, section: str | None, field: str, value: object
) -> None:
    sealed, run, requests, lifecycle, _, report = _score_bundle(tmp_path, "holdout")
    config = _gate_config()
    target = config if section is None else config[section]
    target[field] = value
    config["config_sha256"] = hashlib.sha256(
        json.dumps(
            {key: child for key, child in config.items() if key != "config_sha256"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    with pytest.raises(ValueError, match="sealed gate artifact"):
        evaluate_release_gate(
            report, config, lifecycle, sealed, run, requests, root=tmp_path
        )


def test_zero_selection_cannot_produce_false_gate_success(tmp_path: Path) -> None:
    sealed, run, requests, lifecycle, _, report = _score_bundle(tmp_path, "holdout", selected=False)
    metrics = report["arms"]["omni_to_qwen_vista"]["post_review"]
    assert metrics["selected_count"] == 0
    assert metrics["selection_precision"] is None
    decision = evaluate_release_gate(report, _gate_config(), lifecycle, sealed, run, requests, root=tmp_path)
    assert decision["eligible"] is False
    assert "quality.min_selected_count" in {item["gate_id"] for item in decision["blocking_failures"]}


def test_regression_pre_vista_dry_run_validates_all_frozen_interfaces(tmp_path: Path) -> None:
    outputs = [tmp_path / "one.json", tmp_path / "two.json"]
    command = [
        sys.executable,
        str(ROOT / "scripts/run_portfolio_hybrid_v1_1_benchmark.py"),
        "--partition", "regression", "--phase", "pre-vista", "--dry-run",
    ]
    completed = [subprocess.run(
        [*command, "--output", str(output)], cwd=ROOT, capture_output=True,
        text=True, encoding="utf-8", check=False,
    ) for output in outputs]
    assert all(item.returncode == 0 for item in completed), completed[-1].stderr
    first = json.loads(outputs[0].read_text(encoding="utf-8"))
    second = json.loads(outputs[1].read_text(encoding="utf-8"))
    assert first == second
    assert first["arms"] == ["qwen_only", "omni_only_discovery", "omni_to_qwen"]
    assert set(first["frozen_interfaces"]) == {
        "manifest_template", "gate_config", "benchmark_producer", "benchmark_runner", "scorer"
    }
    assert all(len(value["sha256"]) == 64 for value in first["frozen_interfaces"].values())
    assert first["gate_validation_status"] == "verified"
    assert {key: first[key] for key in (
        "provider_launch_count", "prediction_count", "holdout_prediction_count", "owned_process_count"
    )} == {key: 0 for key in (
        "provider_launch_count", "prediction_count", "holdout_prediction_count", "owned_process_count"
    )}


def test_dry_run_rejects_rehashed_malformed_gate(tmp_path: Path) -> None:
    gate = _gate_config()
    gate["quality"]["required_partition"] = "regression"
    gate["config_sha256"] = hashlib.sha256(
        json.dumps({key: value for key, value in gate.items() if key != "config_sha256"}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    gate_path = tmp_path / "gate.json"
    gate_path.write_text(json.dumps(gate), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts/run_portfolio_hybrid_v1_1_benchmark.py"),
         "--partition", "regression", "--phase", "pre-vista", "--dry-run",
         "--gate-config", str(gate_path), "--output", str(tmp_path / "out.json")],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert completed.returncode != 0
    assert "holdout" in completed.stderr


def test_runner_refuses_holdout_and_non_dry_run_before_vista(tmp_path: Path) -> None:
    script = str(ROOT / "scripts/run_portfolio_hybrid_v1_1_benchmark.py")
    for extra in (
        ["--partition", "holdout", "--phase", "pre-vista", "--dry-run"],
        ["--partition", "regression", "--phase", "pre-vista"],
    ):
        completed = subprocess.run(
            [sys.executable, script, *extra, "--output", str(tmp_path / "out.json")],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False,
        )
        assert completed.returncode != 0
        assert "regression-only dry-run" in completed.stderr
