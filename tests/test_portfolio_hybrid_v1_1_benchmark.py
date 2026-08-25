from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from app.learn.hybrid.benchmark import (
    ARM_IDS,
    build_prediction_request,
    contains_gold_fields,
    provider_manifest_projection,
    seal_benchmark_manifest,
    verify_benchmark_manifest,
)
from app.learn.hybrid.benchmark_scorer_v1 import (
    evaluate_release_gate,
    score_benchmark_predictions,
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
        _write(tmp_path / relative, f"{name}\n".encode("utf-8"))
    _write(tmp_path / "images/case-001.png", b"synthetic-image")
    identity_a = hashlib.sha256(b"annotator-a").hexdigest()
    identity_b = hashlib.sha256(b"reviewer-b").hexdigest()
    shared_budget = {
        "max_provider_calls_per_case": 3,
        "max_output_tokens_per_case": 2048,
        "max_wall_time_ms_per_case": 120000,
    }
    shared_context = {
        "policy_version": "shared-uia-ocr-v1",
        "uia": "same_capture_optional",
        "ocr": "same_capture_optional",
    }
    return {
        "contract_version": "portfolio_hybrid_v1_1_benchmark_manifest_template_v1",
        "benchmark_id": "portfolio-hybrid-v1-1-test",
        "corpus_id": "synthetic-test-corpus",
        "artifact_paths": files,
        "provider_revisions": {
            "omni": "microsoft/OmniParser-v2@synthetic-revision",
            "qwen": "Qwen/Qwen2.5-VL@synthetic-revision",
            "vista": "portfolio-vista@future-revision",
        },
        "shared_budget": shared_budget,
        "shared_context_policy": shared_context,
        "arms": [
            _arm("qwen_only", "pre-vista", ["qwen"]),
            _arm("omni_only_discovery", "pre-vista", ["omni"]),
            _arm("omni_to_qwen", "pre-vista", ["omni", "qwen"]),
            _arm("omni_to_qwen_vista", "post-vista", ["omni", "qwen", "vista"]),
        ],
        "cases": [
            {
                "case_id": "case-001",
                "partition": "regression",
                "image_path": "images/case-001.png",
                "goal": "Open the application flow",
                "gold": {
                    "acceptable_candidate_ids": ["candidate/expected"],
                    "acceptable_regions": [[10, 10, 30, 30]],
                    "annotator_identity_hash": identity_a,
                    "reviewer_identity_hash": identity_b,
                    "acceptable_region_disagreement": "resolved_by_independent_review",
                },
            }
        ],
        "evidence_policy": {
            "public": "aggregate_metrics_only",
            "private": "case_level_gold_and_predictions",
        },
    }


def _sealed(tmp_path: Path) -> dict[str, object]:
    return seal_benchmark_manifest(_manifest_template(tmp_path), root=tmp_path)


def _selection(selected: bool, *, candidate_id: str | None = None) -> dict[str, object]:
    return {
        "selected": selected,
        "candidate_id": candidate_id,
        "point": [20, 20] if selected else None,
    }


def _prediction(
    sealed: dict[str, object],
    arm_id: str,
    *,
    selected: bool = True,
    candidate_id: str | None = "candidate/expected",
) -> dict[str, object]:
    selection = _selection(selected, candidate_id=candidate_id if selected else None)
    return {
        "contract_version": "portfolio_hybrid_v1_1_prediction_v1",
        "benchmark_ref": {
            "id": sealed["benchmark_id"],
            "content_sha256": sealed["content_sha256"],
        },
        "arm_id": arm_id,
        "case_id": "case-001",
        "partition": "regression",
        "producer_revision_sha256": SHA,
        "pre_review": deepcopy(selection),
        "post_review": {"status": "reviewed", **deepcopy(selection)},
        "vista": {
            "status": "not_requested" if "vista" not in arm_id else "succeeded",
            "candidate_id": candidate_id if "vista" in arm_id else None,
            "candidate_bbox_ref": None,
            "roi_ref": None,
            "affine_transform_ref": None,
            "canonical_point": [20, 20] if "vista" in arm_id else None,
        },
        "provider_evidence_refs": [],
        "cleanup_evidence_ref": None,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _gate_config() -> dict[str, object]:
    config: dict[str, object] = {
        "contract_version": "portfolio_hybrid_v1_1_release_gate_v1",
        "config_id": "test-gate",
        "quality": {
            "release_arm": "omni_to_qwen_vista",
            "split": "post_review",
            "min_selected_count": 1,
            "min_selection_precision": 1.0,
            "min_target_recall": 1.0,
            "max_wrong_selected_count": 0,
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
    encoded = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    config["config_sha256"] = hashlib.sha256(encoded).hexdigest()
    return config


def _verified_cleanup() -> dict[str, object]:
    return {
        "max_simultaneous_gpu_owners": 1,
        "providers": [
            {
                "provider_id": "omni",
                "cleanup_status": "verified",
                "vram_release_delta_mb": 8,
            },
            {
                "provider_id": "qwen",
                "cleanup_status": "verified",
                "vram_release_delta_mb": 16,
            },
            {
                "provider_id": "vista",
                "cleanup_status": "verified",
                "vram_release_delta_mb": 32,
            },
        ],
        "orphan_provider_pids": 0,
        "orphan_helper_pids": 0,
        "lease_files_remaining": 0,
        "cancel_timeout_compute_termination": "verified",
    }


def test_provider_projection_never_contains_gold_or_expected_target(tmp_path: Path) -> None:
    projection = provider_manifest_projection(_sealed(tmp_path))
    encoded = json.dumps(projection, sort_keys=True)

    assert contains_gold_fields(projection) is False
    assert "gold" not in encoded.casefold()
    assert "expected_candidate" not in encoded.casefold()
    assert "acceptable_bbox" not in encoded.casefold()
    assert "acceptable_region" not in encoded.casefold()
    assert "annotator" not in encoded.casefold()
    assert "reviewer" not in encoded.casefold()


def test_seal_binds_every_file_revision_budget_and_context_before_prediction(tmp_path: Path) -> None:
    sealed = _sealed(tmp_path)

    assert set(sealed["artifact_seals"]) == {
        "gate_config",
        "benchmark_producer",
        "benchmark_runner",
        "scorer",
        "corpus_manifest",
        "gold",
    }
    assert all(len(item["sha256"]) == 64 for item in sealed["artifact_seals"].values())
    assert len(sealed["cases"][0]["image_sha256"]) == 64
    assert len(sealed["cases"][0]["gold_sha256"]) == 64
    assert len(sealed["provider_revisions_sha256"]) == 64
    assert len(sealed["shared_budget_sha256"]) == 64
    assert len(sealed["shared_context_policy_sha256"]) == 64
    assert verify_benchmark_manifest(sealed, root=tmp_path) == sealed


def test_post_seal_manifest_or_file_mutation_is_rejected(tmp_path: Path) -> None:
    sealed = _sealed(tmp_path)
    mutated = deepcopy(sealed)
    mutated["cases"][0]["goal"] = "A changed goal"

    with pytest.raises(ValueError, match="content_sha256 mismatch"):
        provider_manifest_projection(mutated)

    (tmp_path / "scorer.py").write_text("mutated\n", encoding="utf-8")
    with pytest.raises(ValueError, match="artifact seal mismatch: scorer"):
        verify_benchmark_manifest(sealed, root=tmp_path)


def test_seal_rejects_unequal_non_omni_context(tmp_path: Path) -> None:
    template = _manifest_template(tmp_path)
    template["arms"][2]["context_policy"]["ocr"] = "disabled"

    with pytest.raises(ValueError, match="shared UIA/OCR context policy"):
        seal_benchmark_manifest(template, root=tmp_path)


def test_seal_rejects_unequal_budgets(tmp_path: Path) -> None:
    template = _manifest_template(tmp_path)
    template["arms"][1]["budget"]["max_provider_calls_per_case"] = 2

    with pytest.raises(ValueError, match="equal budgets"):
        seal_benchmark_manifest(template, root=tmp_path)


def test_seal_rejects_duplicate_statistical_arms(tmp_path: Path) -> None:
    template = _manifest_template(tmp_path)
    duplicate = deepcopy(template["arms"][2])
    duplicate["arm_id"] = "duplicate_alias"
    template["arms"].append(duplicate)

    with pytest.raises(ValueError, match="duplicate statistical arm"):
        seal_benchmark_manifest(template, root=tmp_path)


def test_generic_prediction_requests_cover_every_arm_and_future_vista_fields(tmp_path: Path) -> None:
    sealed = _sealed(tmp_path)

    requests = [build_prediction_request(sealed, arm_id, "case-001") for arm_id in ARM_IDS]

    assert [item["arm_id"] for item in requests] == list(ARM_IDS)
    assert all(set(item["vista_payload"]) == {
        "enabled",
        "proposal_contract_version",
        "candidate_id",
        "candidate_bbox_ref",
        "roi_ref",
        "affine_transform_ref",
        "canonical_point",
    } for item in requests)
    assert requests[-1]["vista_payload"]["enabled"] is True
    assert all(contains_gold_fields(item) is False for item in requests)


def test_scorer_keeps_public_aggregate_separate_from_private_case_evidence(tmp_path: Path) -> None:
    sealed = _sealed(tmp_path)
    report = score_benchmark_predictions(
        sealed,
        [_prediction(sealed, arm_id) for arm_id in ARM_IDS],
    )

    public = json.dumps(report["public_evidence"], sort_keys=True)
    private = report["private_evidence"]
    assert "case-001" not in public
    assert "gold" not in public.casefold()
    assert "acceptable" not in public.casefold()
    assert private["visibility"] == "private_gold_evaluation"
    assert private["case_results"][0]["case_id"] == "case-001"
    assert set(report["arms"]["omni_to_qwen_vista"]) >= {"pre_review", "post_review", "vista"}


def test_zero_selection_cannot_produce_false_gate_success(tmp_path: Path) -> None:
    sealed = _sealed(tmp_path)
    report = score_benchmark_predictions(
        sealed,
        [_prediction(sealed, arm_id, selected=False, candidate_id=None) for arm_id in ARM_IDS],
    )

    metrics = report["arms"]["omni_to_qwen_vista"]["post_review"]
    assert metrics["selected_count"] == 0
    assert metrics["selection_precision"] is None
    decision = evaluate_release_gate(report, _gate_config(), _verified_cleanup())
    assert decision["eligible"] is False
    assert decision["decision"] == "KEEP_EXPERIMENTAL"
    assert "quality.min_selected_count" in {item["gate_id"] for item in decision["blocking_failures"]}


@pytest.mark.parametrize(
    ("mutate", "gate_id"),
    [
        (lambda evidence: evidence.pop("orphan_provider_pids"), "cleanup.orphan_provider_pids"),
        (lambda evidence: evidence.__setitem__("orphan_helper_pids", None), "cleanup.orphan_helper_pids"),
        (lambda evidence: evidence["providers"][0].__setitem__("cleanup_status", "indeterminate"), "cleanup.provider_status"),
        (lambda evidence: evidence.__setitem__("lease_files_remaining", 1), "cleanup.lease_files_remaining"),
        (lambda evidence: evidence.__setitem__("max_simultaneous_gpu_owners", 2), "cleanup.max_simultaneous_gpu_owners"),
        (lambda evidence: evidence["providers"][1].__setitem__("vram_release_delta_mb", 65), "cleanup.vram_release"),
        (lambda evidence: evidence.__setitem__("cancel_timeout_compute_termination", "indeterminate"), "cleanup.cancel_timeout_termination"),
    ],
)
def test_release_gate_fails_closed_on_missing_or_indeterminate_cleanup(
    tmp_path: Path, mutate: object, gate_id: str
) -> None:
    sealed = _sealed(tmp_path)
    report = score_benchmark_predictions(
        sealed,
        [_prediction(sealed, arm_id) for arm_id in ARM_IDS],
    )
    cleanup = _verified_cleanup()
    mutate(cleanup)

    decision = evaluate_release_gate(report, _gate_config(), cleanup)

    assert decision["eligible"] is False
    assert gate_id in {item["gate_id"] for item in decision["blocking_failures"]}


def test_verified_cleanup_and_nonzero_quality_can_pass_gate(tmp_path: Path) -> None:
    sealed = _sealed(tmp_path)
    report = score_benchmark_predictions(
        sealed,
        [_prediction(sealed, arm_id) for arm_id in ARM_IDS],
    )

    decision = evaluate_release_gate(report, _gate_config(), _verified_cleanup())

    assert decision["eligible"] is True
    assert decision["decision"] == "PROMOTION_ELIGIBLE"
    assert decision["blocking_failures"] == []


def test_regression_pre_vista_dry_run_is_deterministic_and_never_predicts_holdout(tmp_path: Path) -> None:
    outputs = [tmp_path / "one.json", tmp_path / "two.json"]
    command = [
        sys.executable,
        str(ROOT / "scripts/run_portfolio_hybrid_v1_1_benchmark.py"),
        "--partition",
        "regression",
        "--phase",
        "pre-vista",
        "--dry-run",
    ]
    completed = []
    for output in outputs:
        completed.append(subprocess.run(
            [*command, "--output", str(output)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        ))

    assert all(item.returncode == 0 for item in completed), completed[-1].stderr
    first = json.loads(outputs[0].read_text(encoding="utf-8"))
    second = json.loads(outputs[1].read_text(encoding="utf-8"))
    assert first == second
    assert first["partition"] == "regression"
    assert first["phase"] == "pre-vista"
    assert first["arms"] == ["qwen_only", "omni_only_discovery", "omni_to_qwen"]
    assert first["provider_launch_count"] == 0
    assert first["prediction_count"] == 0
    assert first["holdout_prediction_count"] == 0
    assert first["owned_process_count"] == 0


def test_runner_refuses_holdout_and_non_dry_run_before_vista(tmp_path: Path) -> None:
    script = str(ROOT / "scripts/run_portfolio_hybrid_v1_1_benchmark.py")
    for extra in (
        ["--partition", "holdout", "--phase", "pre-vista", "--dry-run"],
        ["--partition", "regression", "--phase", "pre-vista"],
    ):
        completed = subprocess.run(
            [sys.executable, script, *extra, "--output", str(tmp_path / "out.json")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        assert completed.returncode != 0
        assert "regression-only dry-run" in completed.stderr
