"""Benchmark v2 provider-safe contracts and immutable identities."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


BENCHMARK_RELEASE_ID = "portfolio_hybrid_v1_1_benchmark_v2_release_1"
PROVIDER_CORPUS_CONTRACT = "portfolio_hybrid_v1_1_provider_corpus_v2"
PROVIDER_MANIFEST_CONTRACT = "portfolio_hybrid_v1_1_provider_manifest_v2_1"
PARENT_REF_CONTRACT = "portfolio_hybrid_v1_1_corpus_parent_ref_v1"
PARENT_ARTIFACT_ID = "portfolio-hybrid-v1-1-corpus-parent"
PARENT_FILE_SHA256 = "8503010496a426893456e903b9d768f2a281ef0509f11230d312b073c0760757"
PARENT_CONTENT_SHA256 = "bc06e007b4518bb716fdaff81ae7dd147227d09a10044d90a6b4577088ecba93"
ARM_ORDER = (
    "qwen_only",
    "omni_only_discovery",
    "omni_to_qwen",
    "omni_to_qwen_vista",
)
PROVIDER_CODE_REFS = (
    ("bootstrap", "app/learn/hybrid/benchmark_v2_provider_sandbox.py"),
    ("contracts", "app/learn/hybrid/benchmark_v2_contracts.py"),
    ("corpus_loader", "app/learn/hybrid/benchmark_v2_provider_corpus.py"),
)
EVALUATION_PROJECTION = {
    "provider_policy": {
        "provider_revisions": {
            "omni": "PINNED_OMNI_REVISION",
            "qwen": "PINNED_QWEN_REVISION",
            "vista": "PINNED_VISTA_REVISION",
        },
        "provider_revisions_sha256": "25ff2b06d0f5c3fa24809b9e3b046994f3a1d3a472fecffd252238aaa0a0e1c4",
        "shared_budget": {
            "max_provider_calls_per_case": 3,
            "max_output_tokens_per_case": 2048,
            "max_wall_time_ms_per_case": 120000,
        },
        "shared_budget_sha256": "ee15ff899063c6e6ce6de50d635886699b2bc4c3962ca441f3ea2cbf23028932",
        "shared_context_policy": {
            "policy_version": "portfolio-hybrid-shared-uia-ocr-v1",
            "uia": "same_capture_optional",
            "ocr": "same_capture_optional",
        },
        "shared_context_policy_sha256": "a02c7efbb9c639d1c45c8e621be5f24a474a85aa34205e46a5b654d84eb1d31e",
    },
    "estimand": {
        "file_sha256": "c123a09b48ae144b6869c2d1a0d6e87db81948f6212a8bb686ad863826ad4eeb",
        "contract_version": "portfolio_hybrid_v1_1_estimand_v2_1",
        "arms": {
            "arm_ids": list(ARM_ORDER),
            "release_arm": "omni_to_qwen_vista",
            "statistical_arm_count": 4,
        },
        "execution_units": {
            "hybrid_arms": [
                "omni_only_discovery",
                "omni_to_qwen",
                "omni_to_qwen_vista",
            ],
            "hybrid_invocation_unit": "screen_group",
            "hybrid_invocations_per_screen_group": 1,
            "incumbent_arm": "qwen_only",
            "incumbent_invocation_unit": "target",
            "targets_per_screen_group": 5,
            "call_count_reports": [
                "unique_invocation_count",
                "amortized_per_target_count",
            ],
        },
        "point_metric": {
            "denominator": "submitted_count",
            "gain_numerator": "sum(refined_hit-baseline_hit)",
            "gain": "gain_numerator/submitted_count",
            "comparison_arithmetic": "exact_rational_no_rounding",
            "min_vista_submitted_count": 1,
            "required_gain_numerator": ">0",
        },
    },
    "gate": {
        "file_sha256": "677a5bb7f8f97468b811332bf0811333c793790b4098e2b21fc7068aa7136861",
        "contract_version": "portfolio_hybrid_v1_1_automatic_gate_v2",
        "automatic_split": "pre_review",
        "holdout_role": "automatic_gate",
        "regression_role": "precondition_only",
        "thresholds": {
            "min_coverage": "1/5",
            "min_important_target_correct_coverage_delta": "1/20",
            "min_semantic_precision_delta": "0/1",
            "min_vista_submitted_count": 1,
            "required_vista_gain_numerator": ">0",
            "wrong_target_count": 0,
        },
    },
}
SAFETY = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
    "display_only": True,
}
PARENT_REF = {
    "contract_version": PARENT_REF_CONTRACT,
    "artifact_id": PARENT_ARTIFACT_ID,
    "file_sha256": PARENT_FILE_SHA256,
    "content_sha256": PARENT_CONTENT_SHA256,
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def canonical_json_bytes(value: object, *, pretty: bool = False) -> bytes:
    if pretty:
        return (
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def content_sha256(value: Mapping[str, object]) -> str:
    unhashed = {key: item for key, item in value.items() if key != "content_sha256"}
    return sha256_bytes(canonical_json_bytes(unhashed))


def closed_mapping(
    value: object,
    fields: set[str],
    name: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"{name} must contain exactly {sorted(fields)}")
    return deepcopy(dict(value))


def require_sha256(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256")
    return value


def require_relative_posix_path(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError(f"{name} must be a non-empty POSIX relative path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ValueError(f"{name} must remain inside its declared root")
    return value


def validate_parent_ref(value: object) -> dict[str, Any]:
    parent = closed_mapping(
        value,
        {"contract_version", "artifact_id", "file_sha256", "content_sha256"},
        "source_parent_ref",
    )
    if parent != PARENT_REF:
        raise ValueError("source parent lineage does not match the frozen corpus parent")
    return parent
