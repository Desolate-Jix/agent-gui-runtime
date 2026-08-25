"""Hybrid 专用的顺序 provider 清理门；不是通用 GPU 调度器。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable, Mapping

from app.learn.recognition.uei.canonical import content_sha256, seal_immutable


_PROVIDERS = {"omni", "qwen", "vista"}
_NEXT_PROVIDER = {"omni": "qwen", "qwen": "vista", "vista": "review"}
_INVENTORY_FIELDS = {
    "contract_version",
    "provider",
    "release_status",
    "termination_reason",
    "provider_processes_after",
    "helper_processes_after",
    "orphan_descendant_pids",
    "active_listeners_after",
    "lease_files_after",
    "source_cleanup_evidence",
}
_RECEIPT_FIELDS = {
    "contract_version",
    "provider",
    "cleanup_status",
    "termination_reason",
    "orphan_provider_pids",
    "orphan_helper_pids",
    "orphan_descendant_pids",
    "active_listeners",
    "lease_files_remaining",
    "source_cleanup_evidence",
    "content_sha256",
}


def release_hybrid_provider(
    provider: str,
    *,
    process_inventory: Mapping[str, Any] | Callable[[str], Mapping[str, Any]],
) -> dict[str, Any]:
    """把既有 provider 停止/租约证据收敛为可供下一阶段使用的密封回执。"""

    normalized_provider = _provider(provider)
    observed = (
        process_inventory(normalized_provider)
        if callable(process_inventory)
        else process_inventory
    )
    inventory = _closed_mapping(observed, _INVENTORY_FIELDS, "process inventory")
    if inventory.get("contract_version") != "hybrid_provider_process_inventory_v1":
        raise ValueError("Hybrid provider process inventory contract is invalid")
    if inventory.get("provider") != normalized_provider:
        raise ValueError("Hybrid provider process inventory provider mismatch")
    if inventory.get("release_status") != "verified":
        raise RuntimeError("Hybrid provider cleanup is not verified")

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
    return seal_immutable(
        {
            "contract_version": "hybrid_provider_cleanup_receipt_v1",
            "provider": normalized_provider,
            "cleanup_status": "verified",
            "termination_reason": _text(
                inventory.get("termination_reason"), "termination_reason"
            ),
            "orphan_provider_pids": [],
            "orphan_helper_pids": [],
            "orphan_descendant_pids": [],
            "active_listeners": [],
            "lease_files_remaining": [],
            "source_cleanup_evidence": deepcopy(dict(evidence)),
        }
    )


def assert_next_provider_safe_to_start(
    previous_cleanup_receipt: Mapping[str, Any],
    next_provider: str,
) -> None:
    """只允许 Omni→Qwen→VISTA→Review 的相邻转换。"""

    try:
        receipt = _closed_mapping(
            previous_cleanup_receipt, _RECEIPT_FIELDS, "cleanup receipt"
        )
        declared = receipt.get("content_sha256")
        if not isinstance(declared, str) or declared != content_sha256(receipt):
            raise ValueError("cleanup receipt seal mismatch")
        if (
            receipt.get("contract_version") != "hybrid_provider_cleanup_receipt_v1"
            or receipt.get("cleanup_status") != "verified"
            or any(
                receipt.get(field)
                for field in (
                    "orphan_provider_pids",
                    "orphan_helper_pids",
                    "orphan_descendant_pids",
                    "active_listeners",
                    "lease_files_remaining",
                )
            )
        ):
            raise ValueError("cleanup receipt is not terminal")
        previous_provider = _provider(str(receipt.get("provider") or ""))
    except (TypeError, ValueError):
        raise RuntimeError("previous provider cleanup is not verified") from None

    normalized_next = str(next_provider or "").strip().casefold()
    if _NEXT_PROVIDER[previous_provider] != normalized_next:
        raise RuntimeError("Hybrid provider transition is invalid")


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
        raise ValueError(f"Hybrid process inventory {field} is required")
    return normalized


__all__ = ["assert_next_provider_safe_to_start", "release_hybrid_provider"]
