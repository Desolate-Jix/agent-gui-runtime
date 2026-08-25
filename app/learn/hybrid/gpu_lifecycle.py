"""Hybrid 专用的顺序 provider 清理门；不是通用 GPU 调度器。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any

from app.learn.recognition.uei.canonical import canonical_json_bytes, content_sha256, seal_immutable


_PROVIDERS = {"omni", "qwen", "vista"}
_NEXT_PROVIDER = {"omni": "qwen", "qwen": "vista", "vista": "review"}
_OBSERVER_CONTRACTS = {
    "omni": "hybrid_omni_cleanup_observer_v1",
    "qwen": "hybrid_qwen_cleanup_observer_v1",
    "vista": "hybrid_vista_cleanup_observer_v1",
}
_LINEAGE_FIELDS = {"run_id", "workflow_revision", "operation_id", "stage", "stage_execution_id"}
_INVENTORY_FIELDS = {
    "contract_version", "provider", "observer_contract", "release_status",
    "termination_reason", "lineage", "provider_lease_identity",
    "predecessor_sha256", "provider_result_sha256", "provider_processes_after",
    "helper_processes_after", "orphan_descendant_pids", "active_listeners_after",
    "lease_files_after", "source_cleanup_evidence",
}
_RECEIPT_FIELDS = {
    "contract_version", "provider", "observer_contract", "cleanup_status",
    "termination_reason", "lineage", "provider_lease_identity",
    "predecessor_sha256", "provider_result_sha256", "orphan_provider_pids",
    "orphan_helper_pids", "orphan_descendant_pids", "active_listeners",
    "lease_files_remaining", "source_cleanup_evidence", "content_sha256",
}


def release_hybrid_provider(
    provider: str,
    *,
    process_inventory: Callable[[str], Mapping[str, Any]],
) -> dict[str, Any]:
    """只接受服务端 provider observer，并收敛为绑定当前 lineage 的密封回执。"""
    normalized_provider = _provider(provider)
    if not callable(process_inventory):
        raise TypeError("Hybrid provider process inventory must be observed server-side")
    inventory = _closed_mapping(process_inventory(normalized_provider), _INVENTORY_FIELDS, "process inventory")
    if inventory.get("contract_version") != "hybrid_provider_process_inventory_v2":
        raise ValueError("Hybrid provider process inventory contract is invalid")
    if inventory.get("provider") != normalized_provider:
        raise ValueError("Hybrid provider process inventory provider mismatch")
    if inventory.get("observer_contract") != _OBSERVER_CONTRACTS[normalized_provider]:
        raise ValueError("Hybrid provider cleanup observer contract is invalid")
    if inventory.get("release_status") != "verified":
        raise RuntimeError("Hybrid provider cleanup is not verified")

    lineage = validate_hybrid_lineage(inventory.get("lineage"))
    identity = inventory.get("provider_lease_identity")
    if not isinstance(identity, Mapping) or not identity:
        raise RuntimeError("Hybrid provider cleanup identity is indeterminate")
    _validate_provider_identity(normalized_provider, identity)
    predecessor_sha256 = _sha256(inventory.get("predecessor_sha256"), "predecessor_sha256")
    provider_result_sha256 = _sha256(inventory.get("provider_result_sha256"), "provider_result_sha256")
    provider_processes = _list(inventory, "provider_processes_after")
    helper_processes = _list(inventory, "helper_processes_after")
    descendants = _pid_list(inventory, "orphan_descendant_pids")
    listeners = _list(inventory, "active_listeners_after")
    leases = _list(inventory, "lease_files_after")
    if provider_processes:
        raise RuntimeError("Hybrid provider process remains resident")
    if helper_processes:
        raise RuntimeError("Hybrid helper process remains resident")
    if descendants:
        raise RuntimeError("Hybrid orphan descendant remains resident")
    if listeners:
        raise RuntimeError("Hybrid provider listener remains active")
    if leases:
        raise RuntimeError("Hybrid provider lease file remains")
    evidence = inventory.get("source_cleanup_evidence")
    if not isinstance(evidence, Mapping) or evidence.get("status") != "verified":
        raise RuntimeError("Hybrid provider cleanup evidence is not verified")
    return seal_immutable({
        "contract_version": "hybrid_provider_cleanup_receipt_v2",
        "provider": normalized_provider,
        "observer_contract": _OBSERVER_CONTRACTS[normalized_provider],
        "cleanup_status": "verified",
        "termination_reason": _text(inventory.get("termination_reason"), "termination_reason"),
        "lineage": lineage,
        "provider_lease_identity": deepcopy(dict(identity)),
        "predecessor_sha256": predecessor_sha256,
        "provider_result_sha256": provider_result_sha256,
        "orphan_provider_pids": [], "orphan_helper_pids": [],
        "orphan_descendant_pids": [], "active_listeners": [],
        "lease_files_remaining": [],
        "source_cleanup_evidence": deepcopy(dict(evidence)),
    })


def assert_next_provider_safe_to_start(
    previous_cleanup_receipt: Mapping[str, Any],
    next_provider: str,
    *,
    expected_lineage: Mapping[str, Any] | None = None,
    expected_provider_result_sha256: str | None = None,
) -> None:
    """只允许当前 operation 的 Omni→Qwen→VISTA→Review 相邻转换。"""
    try:
        receipt = validate_hybrid_cleanup_receipt(previous_cleanup_receipt)
        previous_provider = _provider(str(receipt.get("provider") or ""))
    except (TypeError, ValueError):
        raise RuntimeError("previous provider cleanup is not verified") from None
    normalized_next = str(next_provider or "").strip().casefold()
    if _NEXT_PROVIDER[previous_provider] != normalized_next:
        raise RuntimeError("Hybrid provider transition is invalid")
    if expected_lineage is None:
        raise RuntimeError("active Hybrid lineage is required for provider transition")
    active_lineage = validate_hybrid_lineage(expected_lineage)
    if canonical_json_bytes(receipt["lineage"]) != canonical_json_bytes(active_lineage):
        raise RuntimeError("Hybrid cleanup receipt lineage mismatch")
    expected_digest = _sha256(expected_provider_result_sha256, "expected_provider_result_sha256")
    if receipt["provider_result_sha256"] != expected_digest:
        raise RuntimeError("Hybrid cleanup receipt predecessor result mismatch")


def validate_hybrid_cleanup_receipt(value: object) -> dict[str, Any]:
    receipt = _closed_mapping(value, _RECEIPT_FIELDS, "cleanup receipt")
    if receipt.get("content_sha256") != content_sha256(receipt):
        raise ValueError("cleanup receipt seal mismatch")
    provider = _provider(str(receipt.get("provider") or ""))
    if (
        receipt.get("contract_version") != "hybrid_provider_cleanup_receipt_v2"
        or receipt.get("observer_contract") != _OBSERVER_CONTRACTS[provider]
        or receipt.get("cleanup_status") != "verified"
        or any(receipt.get(field) for field in (
            "orphan_provider_pids", "orphan_helper_pids", "orphan_descendant_pids",
            "active_listeners", "lease_files_remaining",
        ))
    ):
        raise ValueError("cleanup receipt is not terminal")
    receipt["lineage"] = validate_hybrid_lineage(receipt.get("lineage"))
    if not isinstance(receipt.get("provider_lease_identity"), Mapping) or not receipt["provider_lease_identity"]:
        raise ValueError("cleanup receipt provider identity is invalid")
    _validate_provider_identity(provider, receipt["provider_lease_identity"])
    _sha256(receipt.get("predecessor_sha256"), "predecessor_sha256")
    _sha256(receipt.get("provider_result_sha256"), "provider_result_sha256")
    return receipt


def validate_hybrid_lineage(value: object) -> dict[str, Any]:
    lineage = _closed_mapping(value, _LINEAGE_FIELDS, "lineage")
    for field in ("run_id", "operation_id", "stage", "stage_execution_id"):
        _text(lineage.get(field), field)
    revision = lineage.get("workflow_revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("Hybrid lineage workflow_revision is invalid")
    return lineage


def _provider(value: str) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized not in _PROVIDERS:
        raise ValueError("Hybrid provider must be omni, qwen, or vista")
    return normalized


def _closed_mapping(value: Any, fields: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise ValueError(f"Hybrid {name} is not closed")
    return deepcopy(dict(value))


def _list(value: Mapping[str, Any], field: str) -> list[Any]:
    child = value.get(field)
    if not isinstance(child, list):
        raise ValueError(f"Hybrid process inventory {field} must be a list")
    return deepcopy(child)


def _pid_list(value: Mapping[str, Any], field: str) -> list[int]:
    result = _list(value, field)
    if any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in result):
        raise ValueError(f"Hybrid process inventory {field} contains invalid PID")
    return result


def _text(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"Hybrid {field} is required")
    return normalized


def _sha256(value: Any, field: str) -> str:
    normalized = _text(value, field)
    if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
        raise ValueError(f"Hybrid {field} must be lowercase SHA-256")
    return normalized


def _validate_provider_identity(provider: str, value: Mapping[str, Any]) -> None:
    if provider == "omni":
        if set(value) != {
            "provider_invocation_id", "provider_receipt_ref", "process_identity"
        } or not str(value.get("provider_invocation_id") or "").startswith(
            "invocation/"
        ) or not _immutable_ref(value.get("provider_receipt_ref")) or not _process_identity(
            value.get("process_identity")
        ):
            raise ValueError("Hybrid Omni cleanup identity is invalid")
        return
    if provider == "qwen":
        if set(value) != {
            "lease_id", "incarnation_id", "profile_id", "server_process_identity"
        } or any(
            not str(value.get(field) or "").strip()
            for field in ("lease_id", "incarnation_id", "profile_id")
        ) or not _process_identity(value.get("server_process_identity")):
            raise ValueError("Hybrid Qwen cleanup identity is invalid")
        return
    identities = value.get("process_identities")
    if set(value) != {"incarnation_id", "profile_id", "process_identities"} or any(
        not str(value.get(field) or "").strip()
        for field in ("incarnation_id", "profile_id")
    ) or not isinstance(identities, list) or not identities or any(
        not _process_identity(identity) for identity in identities
    ):
        raise ValueError("Hybrid VISTA cleanup identity is invalid")


def _process_identity(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == {"pid", "create_time_ns"}
        and isinstance(value.get("pid"), int)
        and not isinstance(value.get("pid"), bool)
        and int(value["pid"]) > 0
        and isinstance(value.get("create_time_ns"), int)
        and not isinstance(value.get("create_time_ns"), bool)
        and int(value["create_time_ns"]) > 0
    )


def _immutable_ref(value: object) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == {"id", "content_sha256"}
        and bool(str(value.get("id") or "").strip())
        and isinstance(value.get("content_sha256"), str)
        and len(value["content_sha256"]) == 64
        and all(character in "0123456789abcdef" for character in value["content_sha256"])
    )


__all__ = [
    "assert_next_provider_safe_to_start", "release_hybrid_provider",
    "validate_hybrid_cleanup_receipt", "validate_hybrid_lineage",
]
