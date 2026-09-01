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


def validate_qwen_quality_safe_stop_omission(value: object) -> dict[str, Any]:
    """验证 Qwen 闭合 JSON 质量失败留下的非授权缺失标记。"""

    marker = closed_mapping(
        value,
        {
            "contract_version",
            "provider_group_ref",
            "omni_inventory_ref",
            "failure_result_ref",
            "failure_response_sha256",
            "diagnostics_ref",
            "model_request_ref",
            "capture_lineage_ref",
            "screenshot_sha256",
            "provider_dispatch_receipt_refs",
            "cleanup_refs",
            "failure_reason",
            "omitted_artifacts",
            "artifact_is_authorization",
            "execute_binding_enabled",
            "content_sha256",
        },
        "Qwen quality safe-stop omission",
    )
    if (
        marker["contract_version"]
        != "benchmark_v2_qwen_quality_safe_stop_omission_v1"
        or marker["failure_reason"]
        != "Qwen binding response is not a closed JSON object"
        or marker["omitted_artifacts"]
        != ["hybrid_qwen_bindings_v1", "hybrid_fusion_result_v1"]
        or marker["artifact_is_authorization"] is not False
        or marker["execute_binding_enabled"] is not False
    ):
        raise ValueError("Qwen quality safe-stop omission semantics differ")
    for field in ("provider_group_ref", "omni_inventory_ref"):
        ref = closed_mapping(marker[field], {"id", "content_sha256"}, field)
        if not isinstance(ref["id"], str) or not ref["id"]:
            raise ValueError(f"{field} identity is invalid")
        require_sha256(ref["content_sha256"], f"{field} content_sha256")
    result_ref = closed_mapping(
        marker["failure_result_ref"], {"content_sha256"}, "failure_result_ref"
    )
    require_sha256(result_ref["content_sha256"], "failure_result_ref content_sha256")
    diagnostics_ref = closed_mapping(
        marker["diagnostics_ref"], {"content_sha256"}, "diagnostics_ref"
    )
    require_sha256(diagnostics_ref["content_sha256"], "diagnostics_ref content_sha256")
    for field in ("model_request_ref", "capture_lineage_ref"):
        ref = closed_mapping(marker[field], {"id", "content_sha256"}, field)
        if not isinstance(ref["id"], str) or not ref["id"]:
            raise ValueError(f"{field} identity is invalid")
        require_sha256(ref["content_sha256"], f"{field} content_sha256")
    require_sha256(marker["screenshot_sha256"], "Qwen omission screenshot SHA")
    dispatch_refs = marker["provider_dispatch_receipt_refs"]
    if (
        not isinstance(dispatch_refs, list)
        or [item.get("provider") for item in dispatch_refs if isinstance(item, Mapping)]
        != ["omni", "qwen"]
    ):
        raise ValueError("Qwen omission dispatch lineage differs")
    for item in dispatch_refs:
        ref = closed_mapping(item, {"provider", "content_sha256"}, "dispatch ref")
        require_sha256(ref["content_sha256"], "dispatch ref content SHA")
    cleanup_refs = closed_mapping(
        marker["cleanup_refs"],
        {"worker_cleanup_ref", "provider_cleanup_ref"},
        "Qwen omission cleanup refs",
    )
    for item in cleanup_refs.values():
        ref = closed_mapping(item, {"content_sha256"}, "Qwen omission cleanup ref")
        require_sha256(ref["content_sha256"], "Qwen omission cleanup SHA")
    require_sha256(marker["failure_response_sha256"], "failure_response_sha256")
    require_sha256(marker["content_sha256"], "omission content_sha256")
    if marker["content_sha256"] != content_sha256(marker):
        raise ValueError("Qwen quality safe-stop omission seal differs")
    return marker


def validate_qwen_closed_json_quality_failure_response(
    value: object,
) -> dict[str, Any]:
    """验证唯一允许进入 denominator 的 Qwen 输出质量失败。"""

    response = closed_mapping(
        value,
        {
            "contract_version",
            "learning_pipeline_mode",
            "task_kind",
            "outcome",
            "result",
            "orchestration",
        },
        "Qwen closed-JSON quality failure response",
    )
    if (
        response["contract_version"] != "learning_hybrid_managed_stage_result_v1"
        or response["learning_pipeline_mode"] != "hybrid_v1_1"
        or response["task_kind"] != "panel_learning_hybrid_qwen_binding"
        or response["outcome"] != "failed"
        or not isinstance(response["orchestration"], Mapping)
    ):
        raise ValueError("Qwen closed-JSON quality failure response semantics differ")
    result = closed_mapping(
        response["result"],
        {
            "contract_version",
            "failure_reason",
            "error_type",
            "error_notes",
            "model_lifecycle",
            "diagnostics",
        },
        "Qwen closed-JSON quality failure result",
    )
    if (
        result["contract_version"] != "learning_hybrid_stage_failure_v1"
        or result["failure_reason"]
        != "Qwen binding response is not a closed JSON object"
        or result["error_type"] != "ValueError"
        or result["error_notes"] != []
        or not isinstance(result["model_lifecycle"], Mapping)
    ):
        raise ValueError("Qwen closed-JSON quality failure result semantics differ")
    diagnostics = closed_mapping(
        result["diagnostics"],
        {
            "contract_version",
            "artifact_is_authorization",
            "execute_binding_enabled",
            "evidence_use",
            "request_lineage",
            "http_response",
            "parse_error",
            "content_sha256",
        },
        "Qwen closed-JSON diagnostics",
    )
    if (
        diagnostics["contract_version"] != "qwen_binding_response_failure_trace_v1"
        or diagnostics["artifact_is_authorization"] is not False
        or diagnostics["execute_binding_enabled"] is not False
        or diagnostics["evidence_use"] != "benchmark_non_authorizing_diagnostic"
        or diagnostics["content_sha256"] != content_sha256(diagnostics)
    ):
        raise ValueError("Qwen closed-JSON diagnostics semantics differ")
    lineage = closed_mapping(
        diagnostics["request_lineage"],
        {
            "model_request_id",
            "request_content_sha256",
            "screenshot_sha256",
            "profile_id",
            "model_id",
        },
        "Qwen closed-JSON request lineage",
    )
    if (
        not isinstance(lineage["model_request_id"], str)
        or not lineage["model_request_id"]
        or not isinstance(lineage["profile_id"], str)
        or not lineage["profile_id"]
        or not isinstance(lineage["model_id"], str)
        or not lineage["model_id"]
    ):
        raise ValueError("Qwen closed-JSON request lineage identity is invalid")
    require_sha256(lineage["request_content_sha256"], "Qwen request content SHA")
    require_sha256(lineage["screenshot_sha256"], "Qwen screenshot SHA")
    http = closed_mapping(
        diagnostics["http_response"],
        {
            "response_body_bytes",
            "response_body_sha256",
            "raw_message_content",
            "raw_message_content_utf8_bytes",
            "raw_message_content_sha256",
            "finish_reason",
            "usage",
        },
        "Qwen closed-JSON HTTP response",
    )
    raw_content = http["raw_message_content"]
    raw_bytes = raw_content.encode("utf-8") if isinstance(raw_content, str) else b""
    if (
        isinstance(http["response_body_bytes"], bool)
        or not isinstance(http["response_body_bytes"], int)
        or http["response_body_bytes"] <= 0
        or http["finish_reason"] != "length"
        or not isinstance(http["usage"], Mapping)
        or isinstance(http["raw_message_content_utf8_bytes"], bool)
        or http["raw_message_content_utf8_bytes"] != len(raw_bytes)
        or http["raw_message_content_sha256"] != sha256_bytes(raw_bytes)
    ):
        raise ValueError("Qwen closed-JSON HTTP response evidence differs")
    require_sha256(http["response_body_sha256"], "Qwen response body SHA")
    parse_error = closed_mapping(
        diagnostics["parse_error"],
        {"type", "message", "line", "column", "position"},
        "Qwen closed-JSON parse error",
    )
    try:
        json.loads(raw_content)
    except json.JSONDecodeError as error:
        expected_parse_error = {
            "type": "JSONDecodeError",
            "message": str(error),
            "line": error.lineno,
            "column": error.colno,
            "position": error.pos,
        }
    else:
        raise ValueError("Qwen closed-JSON diagnostic content is valid JSON")
    if parse_error != expected_parse_error:
        raise ValueError("Qwen closed-JSON parse error evidence differs")
    response["result"] = result
    return response


def validate_qwen_quality_safe_stop_runtime_lineage(
    marker_value: object,
    *,
    dispatch_receipt_refs: object,
    cleanup_entry: object,
) -> dict[str, Any]:
    """把 omission 精确绑定到行 dispatch 与 Hybrid stable-zero cleanup。"""

    marker = validate_qwen_quality_safe_stop_omission(marker_value)
    if dispatch_receipt_refs != marker["provider_dispatch_receipt_refs"]:
        raise ValueError("Qwen omission row dispatch lineage differs")
    if not isinstance(cleanup_entry, Mapping):
        raise ValueError("Qwen omission Hybrid cleanup entry is missing")
    expected_cleanup: dict[str, dict[str, str]] = {}
    for name in ("worker_cleanup_ref", "provider_cleanup_ref"):
        ref = cleanup_entry.get(name)
        if not isinstance(ref, Mapping):
            raise ValueError("Qwen omission Hybrid cleanup entry is incomplete")
        digest = require_sha256(ref.get("content_sha256"), f"Hybrid {name} SHA")
        expected_cleanup[name] = {"content_sha256": digest}
    if marker["cleanup_refs"] != expected_cleanup:
        raise ValueError("Qwen omission stable-zero cleanup lineage differs")
    return marker


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
