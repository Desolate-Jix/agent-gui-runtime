"""Benchmark-v2 provider dispatch 的即时、非授权证明。"""

from __future__ import annotations

import json
import math
import os
import re
import stat
import time
from hashlib import sha256
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any, Literal

from app.learn.recognition.uei.canonical import canonical_json_bytes, content_sha256


_PROVIDERS = {"omni", "qwen", "vista"}
_CONTEXT_FIELDS = {
    "contract_version",
    "provider",
    "operation_ref",
    "window_binding",
    "receipt_journal_path",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "content_sha256",
}
_CONTEXT_REF_FIELDS = {
    "contract_version",
    "provider",
    "dispatch_context",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "content_sha256",
}
_OPERATION_FIELDS = {
    "run_id",
    "stage",
    "operation_id",
    "revision",
    "window_binding_ref",
    "capture_ref",
    "content_sha256",
}
_RUNTIME_IDENTITY_FIELDS = {
    "contract_version",
    "provider",
    "lease_identity",
    "profile_ref",
    "listener_owner",
    "process_identities",
    "process_scope",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "content_sha256",
}
_ACTIVE_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar(
    "benchmark_v2_dispatch_context", default=None
)
_ACTIVE_RECEIPTS: ContextVar[list[dict[str, str]] | None] = ContextVar(
    "benchmark_v2_dispatch_receipts", default=None
)
_JOURNAL_LOCK = RLock()
PROJECT_ROOT = Path(__file__).resolve().parents[3]
_MAX_EXACT_BINARY64_INTEGER = (1 << 53) - 1

_PROFILE_FIELDS = {"profile_id", "profile_sha256", "profile_payload_sha256"}
_OMNI_CONFIGURATION_FIELDS = {
    "contract_version",
    "profile_id",
    "interpreter_path",
    "worker_script_path",
    "code_path",
    "weights_path",
    "cache_path",
    "minimum_free_gpu_gib",
    "is_available",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "content_sha256",
}
_RUNTIME_PARENT_FIELDS = {
    "contract_version",
    "provider",
    "operation_ref",
    "dispatch_receipt_ref",
    "runtime_identity",
    "profile",
    "installed_configuration_snapshot",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "content_sha256",
}
_COMMIT_MARKER_FIELDS = {
    "contract_version",
    "provider",
    "operation_ref",
    "dispatch_receipt_ref",
    "runtime_parent_ref",
    "journal_prefix_sha256",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "content_sha256",
}


def compose_benchmark_dispatch_context(
    *,
    provider: Literal["omni", "qwen", "vista"],
    operation_ref: Mapping[str, object],
    window_binding: Mapping[str, object],
    receipt_journal_path: Path,
) -> dict[str, Any]:
    """由服务端父对象生成封闭、不可授权的 dispatch context。"""

    normalized_provider = _provider(provider)
    operation = _operation_ref(operation_ref)
    binding = _mapping(window_binding, "benchmark dispatch window binding")
    journal = Path(receipt_journal_path)
    if not journal.is_absolute() or journal != _lexical_absolute_path(journal):
        raise ValueError("benchmark dispatch receipt journal path is not canonical")
    if journal != _fixed_dispatch_journal_path(operation):
        raise ValueError("benchmark dispatch receipt journal path differs from fixed project root")
    body: dict[str, Any] = {
        "contract_version": "benchmark_v2_dispatch_context_v1",
        "provider": normalized_provider,
        "operation_ref": operation,
        "window_binding": binding,
        "receipt_journal_path": str(journal),
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    body["content_sha256"] = content_sha256(body)
    return validate_benchmark_dispatch_context(body)


def validate_benchmark_dispatch_context(value: object) -> dict[str, Any]:
    context = _closed(value, _CONTEXT_FIELDS, "benchmark dispatch context")
    if context["contract_version"] != "benchmark_v2_dispatch_context_v1":
        raise ValueError("benchmark dispatch context contract is invalid")
    context["provider"] = _provider(context["provider"])
    context["operation_ref"] = _operation_ref(context["operation_ref"])
    context["window_binding"] = _mapping(
        context["window_binding"], "benchmark dispatch window binding"
    )
    journal = Path(_text(context["receipt_journal_path"], "receipt journal path"))
    if not journal.is_absolute() or journal != _lexical_absolute_path(journal):
        raise ValueError("benchmark dispatch receipt journal path is not canonical")
    if journal != _fixed_dispatch_journal_path(context["operation_ref"]):
        raise ValueError("benchmark dispatch receipt journal path differs from fixed project root")
    if (
        context["artifact_is_authorization"] is not False
        or context["execute_binding_enabled"] is not False
    ):
        raise ValueError("benchmark dispatch context cannot authorize actions")
    _sha(context["content_sha256"], "benchmark dispatch context SHA")
    if context["content_sha256"] != content_sha256(context):
        raise ValueError("benchmark dispatch context content SHA mismatch")
    return context


def compose_benchmark_dispatch_context_ref(
    *, context: Mapping[str, object]
) -> dict[str, Any]:
    """固化服务端签发的完整 provider context，而不是后来推测 revision。"""

    validated = validate_benchmark_dispatch_context(context)
    body: dict[str, Any] = {
        "contract_version": "benchmark_v2_dispatch_context_ref_v1",
        "provider": validated["provider"],
        "dispatch_context": deepcopy(validated),
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    body["content_sha256"] = content_sha256(body)
    return validate_benchmark_dispatch_context_ref(body)


def validate_benchmark_dispatch_context_ref(value: object) -> dict[str, Any]:
    ref = _closed(value, _CONTEXT_REF_FIELDS, "benchmark dispatch context ref")
    if ref["contract_version"] != "benchmark_v2_dispatch_context_ref_v1":
        raise ValueError("benchmark dispatch context ref contract is invalid")
    ref["provider"] = _provider(ref["provider"])
    ref["dispatch_context"] = validate_benchmark_dispatch_context(
        ref["dispatch_context"]
    )
    if ref["dispatch_context"]["provider"] != ref["provider"]:
        raise ValueError("benchmark dispatch context ref provider differs")
    if (
        ref["artifact_is_authorization"] is not False
        or ref["execute_binding_enabled"] is not False
    ):
        raise ValueError("benchmark dispatch context ref cannot authorize actions")
    _sha(ref["content_sha256"], "benchmark dispatch context ref SHA")
    if ref["content_sha256"] != content_sha256(ref):
        raise ValueError("benchmark dispatch context ref content SHA mismatch")
    return ref


def compose_benchmark_provider_runtime_identity(
    *,
    provider: Literal["omni", "qwen", "vista"],
    lease_identity: Mapping[str, object] | None,
    profile_ref: Mapping[str, object] | None,
    listener_owner: Mapping[str, object] | None,
    process_identities: list[Mapping[str, object]],
    process_scope: Mapping[str, object],
) -> dict[str, Any]:
    """生成跨 dispatch/cleanup 共用的封闭、无路径、不可授权运行时身份。"""

    normalized_provider = _provider(provider)
    identities = [_process_identity(item) for item in process_identities]
    if not identities or len({(item["pid"], item["create_time_ns"]) for item in identities}) != len(
        identities
    ):
        raise ValueError("benchmark provider runtime process identities are invalid")
    scope = _closed(
        process_scope,
        {"scope_name", "member_pids", "process_identities"},
        "benchmark provider runtime process scope",
    )
    scope_name = _text(scope["scope_name"], "benchmark provider runtime scope name")
    member_pids = scope["member_pids"]
    if (
        not isinstance(member_pids, list)
        or not member_pids
        or any(isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0 for pid in member_pids)
        or len(set(member_pids)) != len(member_pids)
    ):
        raise ValueError("benchmark provider runtime Job members are invalid")
    scope_identities = [_process_identity(item) for item in scope["process_identities"]]
    if scope_identities != identities or any(item["pid"] not in member_pids for item in identities):
        raise ValueError("benchmark provider runtime Job membership differs")
    scope = {
        "scope_name": scope_name,
        # 绑定 exact provider incarnation 的 Job 成员；不把随后出现的 helper 当成身份。
        "member_pids": [item["pid"] for item in identities],
        "process_identities": scope_identities,
    }

    normalized_profile = None
    normalized_listener = None
    normalized_lease = None
    if normalized_provider == "omni":
        if lease_identity is not None or profile_ref is not None or listener_owner is not None:
            raise ValueError("benchmark Omni runtime identity has unexpected managed lease")
    else:
        normalized_profile = _content_ref(profile_ref, "benchmark provider profile ref")
        listener = _closed(
            listener_owner,
            {"host", "port", "process_identities"},
            "benchmark provider listener owner",
        )
        host = _text(listener["host"], "benchmark provider listener host")
        port = listener["port"]
        if isinstance(port, bool) or not isinstance(port, int) or port <= 0:
            raise ValueError("benchmark provider listener port is invalid")
        listener_identities = [
            _process_identity(item) for item in listener["process_identities"]
        ]
        if listener_identities != identities:
            raise ValueError("benchmark provider listener owner differs")
        normalized_listener = {
            "host": host,
            "port": port,
            "process_identities": listener_identities,
        }
        if normalized_provider == "qwen":
            normalized_lease = _closed(
                lease_identity,
                {"lease_id", "incarnation_id", "owner_request_id"},
                "benchmark Qwen lease identity",
            )
            for name in ("lease_id", "incarnation_id", "owner_request_id"):
                normalized_lease[name] = _text(
                    normalized_lease[name], f"benchmark Qwen {name}"
                )
        else:
            normalized_lease = _closed(
                lease_identity,
                {"incarnation_id", "lease_content_sha256"},
                "benchmark VISTA lease identity",
            )
            normalized_lease["incarnation_id"] = _text(
                normalized_lease["incarnation_id"],
                "benchmark VISTA incarnation id",
            )
            _sha(
                normalized_lease["lease_content_sha256"],
                "benchmark VISTA lease SHA",
            )

    body: dict[str, Any] = {
        "contract_version": "benchmark_v2_provider_runtime_identity_v1",
        "provider": normalized_provider,
        "lease_identity": normalized_lease,
        "profile_ref": normalized_profile,
        "listener_owner": normalized_listener,
        "process_identities": identities,
        "process_scope": scope,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    body["content_sha256"] = content_sha256(body)
    return body


def validate_benchmark_provider_runtime_identity(value: object) -> dict[str, Any]:
    identity = _closed(
        value, _RUNTIME_IDENTITY_FIELDS, "benchmark provider runtime identity"
    )
    if identity["contract_version"] != "benchmark_v2_provider_runtime_identity_v1":
        raise ValueError("benchmark provider runtime identity contract is invalid")
    if (
        identity["artifact_is_authorization"] is not False
        or identity["execute_binding_enabled"] is not False
    ):
        raise ValueError("benchmark provider runtime identity cannot authorize actions")
    _sha(identity["content_sha256"], "benchmark provider runtime identity SHA")
    # 复用 composer 的封闭字段验证，但避免递归 seal。
    unsigned = deepcopy(identity)
    declared = unsigned.pop("content_sha256")
    normalized = compose_benchmark_provider_runtime_identity(
        provider=unsigned["provider"],
        lease_identity=unsigned["lease_identity"],
        profile_ref=unsigned["profile_ref"],
        listener_owner=unsigned["listener_owner"],
        process_identities=unsigned["process_identities"],
        process_scope=unsigned["process_scope"],
    )
    if normalized["content_sha256"] != declared or normalized != identity:
        raise ValueError("benchmark provider runtime identity content SHA mismatch")
    return identity


@contextmanager
def install_benchmark_dispatch_attestor(
    *, dispatch_context: Mapping[str, object]
) -> Iterator[None]:
    """仅在当前 worker 上下文安装 server-owned attestor。"""

    context = validate_benchmark_dispatch_context(dispatch_context)
    if _ACTIVE_CONTEXT.get() is not None:
        raise RuntimeError("benchmark dispatch attestor is already installed")
    context_token = _ACTIVE_CONTEXT.set(context)
    receipt_token = _ACTIVE_RECEIPTS.set([])
    try:
        yield None
    finally:
        _ACTIVE_RECEIPTS.reset(receipt_token)
        _ACTIVE_CONTEXT.reset(context_token)


def current_benchmark_dispatch_context() -> dict[str, Any] | None:
    value = _ACTIVE_CONTEXT.get()
    return deepcopy(value) if isinstance(value, dict) else None


def current_benchmark_dispatch_receipt_refs() -> list[dict[str, str]]:
    refs = _ACTIVE_RECEIPTS.get()
    return deepcopy(refs) if isinstance(refs, list) else []


def attest_benchmark_provider_dispatch(
    *,
    provider: Literal["omni", "qwen", "vista"],
    operation_ref: Mapping[str, object],
    window_binding: Mapping[str, object],
    provider_runtime: Mapping[str, object],
) -> dict[str, Any]:
    """先重验全部父对象并 fsync receipt；成功返回后才可跨 provider 边界。"""

    context_value = _ACTIVE_CONTEXT.get()
    if context_value is None:
        raise RuntimeError("benchmark dispatch attestor is not installed")
    context = validate_benchmark_dispatch_context(context_value)
    normalized_provider = _provider(provider)
    operation = _operation_ref(operation_ref)
    binding = _mapping(window_binding, "benchmark dispatch window binding")
    runtime = _mapping(provider_runtime, "benchmark provider runtime")
    if normalized_provider != context["provider"]:
        raise ValueError("benchmark dispatch provider is stale")
    if operation != context["operation_ref"]:
        raise ValueError("benchmark dispatch operation ref is stale")
    if binding != context["window_binding"]:
        raise ValueError("benchmark dispatch window binding is stale")

    window_ref = _content_ref(
        _attest_exact_window(binding), "benchmark dispatch window attestation"
    )
    runtime_attestation = _validate_exact_provider_attestation(
        normalized_provider,
        _attest_exact_provider_runtime(normalized_provider, runtime),
    )
    runtime_ref = {
        "content_sha256": runtime_attestation["runtime_identity"]["content_sha256"]
    }
    refs = _ACTIVE_RECEIPTS.get()
    if refs is None:
        raise RuntimeError("benchmark dispatch receipt collector is unavailable")
    receipt: dict[str, Any] = {
        "contract_version": "benchmark_v2_provider_dispatch_receipt_v1",
        "provider": normalized_provider,
        "dispatch_index": len(refs) + 1,
        "operation_ref": deepcopy(operation),
        "window_attestation_ref": window_ref,
        "provider_runtime_attestation_ref": runtime_ref,
        "predecessor_content_sha256": (
            refs[-1]["content_sha256"] if refs else context["content_sha256"]
        ),
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    receipt["content_sha256"] = content_sha256(receipt)
    parent = _compose_dispatch_runtime_parent(
        provider=normalized_provider,
        operation_ref=operation,
        receipt=receipt,
        runtime_attestation=runtime_attestation,
    )
    receipt = _commit_dispatch_transaction(
        journal_path=Path(context["receipt_journal_path"]),
        receipt=receipt,
        runtime_parent=parent,
    )
    refs.append(
        {
            "provider": normalized_provider,
            "content_sha256": receipt["content_sha256"],
        }
    )
    return deepcopy(receipt)


def attest_managed_model_dispatch(
    *,
    model_lease: Mapping[str, object],
    dispatch_context: Mapping[str, object],
) -> dict[str, Any]:
    """重验 Qwen/VISTA lease，并通过当前 context 记录一次 dispatch。"""

    context = validate_benchmark_dispatch_context(dispatch_context)
    provider = context["provider"]
    if provider not in {"qwen", "vista"}:
        raise ValueError("managed model dispatch provider is invalid")
    return attest_benchmark_provider_dispatch(
        provider=provider,
        operation_ref=context["operation_ref"],
        window_binding=context["window_binding"],
        provider_runtime=model_lease,
    )


def validate_benchmark_dispatch_receipt_refs(
    *,
    receipt_journal_path: Path,
    receipt_refs: object,
    operation_identity: Mapping[str, object],
    expected_provider_counts: Mapping[str, int],
    expected_dispatch_contexts: Mapping[str, object],
) -> list[dict[str, str]]:
    """从 durable journal 重建并验证服务采用的 dispatch receipt 集合。"""

    path = Path(receipt_journal_path)
    if not path.is_absolute() or path != _lexical_absolute_path(path):
        raise ValueError("benchmark dispatch receipt journal is unavailable")
    if not isinstance(receipt_refs, list) or not receipt_refs:
        raise ValueError("benchmark dispatch receipt refs are missing")
    normalized_refs = [
        _receipt_ref(item, "benchmark dispatch receipt ref") for item in receipt_refs
    ]
    if len({item["content_sha256"] for item in normalized_refs}) != len(
        normalized_refs
    ):
        raise ValueError("benchmark dispatch receipt refs contain duplicates")
    identity = _mapping(operation_identity, "benchmark dispatch operation identity")
    required_identity = {
        "run_id",
        "stage",
        "operation_id",
        "window_binding_ref",
        "capture_ref",
    }
    if set(identity) != required_identity:
        raise ValueError("benchmark dispatch operation identity is not closed")
    for name in ("run_id", "stage", "operation_id"):
        identity[name] = _text(identity[name], f"dispatch identity {name}")
    identity["window_binding_ref"] = _identity_ref(
        identity["window_binding_ref"], "dispatch identity window binding ref"
    )
    identity["capture_ref"] = _identity_ref(
        identity["capture_ref"], "dispatch identity capture ref"
    )
    if path != _fixed_dispatch_journal_path(identity):
        raise ValueError("benchmark dispatch receipt journal differs from fixed project root")
    expected = dict(expected_provider_counts)
    if not expected or any(provider not in _PROVIDERS for provider in expected):
        raise ValueError("benchmark dispatch expected providers are invalid")
    if any(
        isinstance(count, bool) or not isinstance(count, int) or count < 1
        for count in expected.values()
    ):
        raise ValueError("benchmark dispatch expected counts are invalid")
    if not isinstance(expected_dispatch_contexts, Mapping) or set(
        expected_dispatch_contexts
    ) != set(expected):
        raise ValueError("benchmark dispatch expected contexts are invalid")
    contexts: dict[str, dict[str, Any]] = {}
    for provider in expected:
        context = validate_benchmark_dispatch_context(
            expected_dispatch_contexts[provider]
        )
        if context["provider"] != provider:
            raise ValueError("benchmark dispatch expected context provider differs")
        if Path(context["receipt_journal_path"]) != path:
            raise ValueError("benchmark dispatch expected context journal differs")
        operation = context["operation_ref"]
        if any(operation[name] != identity[name] for name in required_identity):
            raise ValueError("benchmark dispatch expected context lineage is stale")
        contexts[provider] = context

    records: dict[str, dict[str, Any]] = {}
    journal_order: dict[str, int] = {}
    for record in _read_committed_dispatch_records(path):
        digest = record["content_sha256"]
        journal_order[digest] = len(journal_order)
        records[digest] = record
    selected: list[dict[str, Any]] = []
    for ref in normalized_refs:
        record = records.get(ref["content_sha256"])
        if record is None:
            raise ValueError("benchmark dispatch receipt ref is not durable")
        if record["provider"] != ref["provider"]:
            raise ValueError("benchmark dispatch receipt ref provider is stale")
        selected.append(record)
    if [journal_order[item["content_sha256"]] for item in selected] != sorted(
        journal_order[item["content_sha256"]] for item in selected
    ):
        raise ValueError("benchmark dispatch receipt ref order differs from journal")
    expected_order = [
        provider
        for provider, count in expected.items()
        for _ in range(count)
    ]
    if [record["provider"] for record in selected] != expected_order:
        raise ValueError("benchmark dispatch receipt provider order differs")
    offset = 0
    for provider, expected_count in expected.items():
        context = contexts[provider]
        provider_records = selected[offset : offset + expected_count]
        offset += expected_count
        durable_context_records = [
            record
            for record in records.values()
            if record["provider"] == provider
            and record["operation_ref"] == context["operation_ref"]
        ]
        if [record["content_sha256"] for record in durable_context_records] != [
            record["content_sha256"] for record in provider_records
        ]:
            raise ValueError(
                "benchmark dispatch receipt context has missing or extra dispatches"
            )
        predecessor = context["content_sha256"]
        for expected_index, record in enumerate(provider_records, start=1):
            if record["operation_ref"] != context["operation_ref"]:
                raise ValueError(
                    "benchmark dispatch receipt operation revision or content SHA is stale"
                )
            if record["dispatch_index"] != expected_index:
                raise ValueError("benchmark dispatch receipt index is not contiguous")
            if record["predecessor_content_sha256"] != predecessor:
                raise ValueError("benchmark dispatch receipt predecessor chain differs")
            predecessor = record["content_sha256"]
    return deepcopy(normalized_refs)


def read_latest_benchmark_dispatch_receipt(
    *, dispatch_context: Mapping[str, object]
) -> dict[str, Any] | None:
    """只读返回 exact server-issued context 的最新 durable dispatch receipt。"""

    context = validate_benchmark_dispatch_context(dispatch_context)
    path = Path(context["receipt_journal_path"])
    records: list[dict[str, Any]] = []
    for receipt in _read_committed_dispatch_records(path):
        if receipt["provider"] == context["provider"]:
            if receipt["operation_ref"] != context["operation_ref"]:
                raise ValueError(
                    "benchmark dispatch receipt provider context is stale"
                )
            records.append(receipt)
    predecessor = context["content_sha256"]
    for index, receipt in enumerate(records, start=1):
        if (
            receipt["dispatch_index"] != index
            or receipt["predecessor_content_sha256"] != predecessor
        ):
            raise ValueError("benchmark dispatch receipt context chain differs")
        predecessor = receipt["content_sha256"]
    return deepcopy(records[-1]) if records else None


def project_authoritative_benchmark_provider_cleanup(
    *,
    provider: Literal["omni", "qwen", "vista"],
    record: Mapping[str, object],
    worker_termination: Mapping[str, object],
) -> dict[str, Any] | None:
    """只从 provider owner 的精确清理证据重建 dispatch 时的运行时身份。"""

    normalized = _provider(provider)
    if normalized == "qwen":
        projected = _authoritative_qwen_cleanup(record, worker_termination)
    elif normalized == "vista":
        projected = _authoritative_vista_cleanup(record, worker_termination)
    else:
        projected = _authoritative_omni_cleanup(record, worker_termination)
    if projected is None:
        return None
    identity = validate_benchmark_provider_runtime_identity(
        projected["runtime_identity"]
    )
    cleanup_ref = _content_ref(
        projected["authoritative_cleanup_ref"],
        "benchmark authoritative provider cleanup ref",
    )
    return {
        "runtime_identity": identity,
        "authoritative_cleanup_ref": cleanup_ref,
        "authoritative_cleanup_contract": _text(
            projected["authoritative_cleanup_contract"],
            "benchmark authoritative cleanup contract",
        ),
    }


def _authoritative_qwen_cleanup(
    record: Mapping[str, object], worker_termination: Mapping[str, object]
) -> dict[str, Any] | None:
    cancellation = worker_termination.get("model_request_cancellation")
    results = cancellation.get("provider_results") if isinstance(cancellation, Mapping) else None
    request_id = str(record.get("model_request_id") or "")
    if not isinstance(results, list):
        return None
    owner_receipts = [
        item.get("owner_receipt")
        for item in results
        if isinstance(item, Mapping) and isinstance(item.get("owner_receipt"), Mapping)
    ]
    owner = next(
        (
            deepcopy(dict(item))
            for item in owner_receipts
            if item.get("contract_version") == "qwen_model_request_owner_receipt_v1"
            and item.get("status") == "finalized"
            and item.get("owner_request_id") == request_id
        ),
        None,
    )
    if owner is None:
        from app.core.model_server import _find_qwen_owner_record

        try:
            owner_record = _find_qwen_owner_record(request_id)
        except (OSError, RuntimeError, ValueError):
            owner_record = None
        if (
            isinstance(owner_record, Mapping)
            and owner_record.get("kind") == "tombstone"
            and isinstance(owner_record.get("receipt"), Mapping)
        ):
            owner = deepcopy(dict(owner_record["receipt"]))
    if owner is None:
        return None
    release = owner.get("release_result")
    lease = release.get("lease") if isinstance(release, Mapping) else None
    if not isinstance(lease, dict):
        return None
    from app.core.model_server import (
        _validate_exact_qwen_cleanup_evidence,
        observe_qwen_model_request_cleanup,
    )

    try:
        exact_lease = _validate_exact_qwen_cleanup_evidence(release, lease)
        cleanup = observe_qwen_model_request_cleanup(request_id)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    fields = {
        "contract_version", "outcome", "model_request_id",
        "acquisition_intent_ref", "runtime_owner_ref", "lease_ref", "profile_ref",
        "server_process_identity", "socket_ref", "job_scope_ref", "finalization_token",
        "lease_state_ref", "owner_tombstone_ref", "release_reason",
        "termination_observation_ref", "scope_stable_zero_ref",
        "listener_stable_zero_ref", "no_active_lease_observation_ref",
        "no_owned_runtime_observation_ref", "content_sha256",
    }
    if (
        not isinstance(cleanup, Mapping)
        or set(cleanup) != fields
        or cleanup.get("contract_version") != "qwen_model_request_cleanup_receipt_v1"
        or cleanup.get("outcome") != "verified_exact_process_exited"
        or cleanup.get("model_request_id") != request_id
        or cleanup.get("content_sha256") != content_sha256(cleanup)
        or owner.get("lease_id") != exact_lease.get("lease_id")
        or owner.get("incarnation_id") != exact_lease.get("incarnation_id")
        or cleanup.get("lease_ref")
        != {"content_sha256": content_sha256(exact_lease)}
        or cleanup.get("profile_ref")
        != {"content_sha256": exact_lease.get("profile_sha256")}
        or cleanup.get("server_process_identity")
        != exact_lease.get("server_process_identity")
    ):
        return None
    from urllib.parse import urlsplit

    parsed = urlsplit(str(exact_lease.get("server_base_url") or ""))
    host = str(parsed.hostname or "")
    port = int(parsed.port or 0)
    process = _process_identity(exact_lease.get("server_process_identity"))
    scope = release.get("hybrid_process_scope_acquisition")
    if (
        not host
        or port <= 0
        or not isinstance(scope, Mapping)
        or scope.get("contract_version") != "hybrid_process_scope_acquisition_v1"
        or scope.get("server_process_identity") != process
        or cleanup.get("socket_ref")
        != {"content_sha256": content_sha256({"host": host, "port": port})}
        or cleanup.get("job_scope_ref")
        != {"content_sha256": content_sha256(scope)}
    ):
        return None
    identity = compose_benchmark_provider_runtime_identity(
        provider="qwen",
        lease_identity={
            "lease_id": exact_lease["lease_id"],
            "incarnation_id": exact_lease["incarnation_id"],
            "owner_request_id": exact_lease["owner_request_id"],
        },
        profile_ref=cleanup["profile_ref"],
        listener_owner={
            "host": host,
            "port": port,
            "process_identities": [process],
        },
        process_identities=[process],
        process_scope={
            "scope_name": scope["scope_name"],
            "member_pids": list(scope["member_pids"]),
            "process_identities": [process],
        },
    )
    return {
        "runtime_identity": identity,
        "authoritative_cleanup_ref": {"content_sha256": cleanup["content_sha256"]},
        "authoritative_cleanup_contract": cleanup["contract_version"],
    }


def _authoritative_vista_cleanup(
    record: Mapping[str, object], worker_termination: Mapping[str, object]
) -> dict[str, Any] | None:
    cooperative = worker_termination.get("cooperative_cleanup")
    receipt = cooperative.get("vista_cleanup_receipt") if isinstance(cooperative, Mapping) else None
    if not isinstance(receipt, Mapping):
        result_envelope = record.get("worker_result")
        response = (
            result_envelope.get("response")
            if isinstance(result_envelope, Mapping)
            else None
        )
        lifecycle = response.get("lifecycle_evidence") if isinstance(response, Mapping) else None
        receipt = lifecycle.get("vista_cleanup_receipt") if isinstance(lifecycle, Mapping) else None
        managed_result = response.get("result") if isinstance(response, Mapping) else None
        model_lifecycle = (
            managed_result.get("model_lifecycle")
            if isinstance(managed_result, Mapping)
            else None
        )
        if not isinstance(receipt, Mapping) and isinstance(model_lifecycle, Mapping):
            receipt = model_lifecycle.get("vista_cleanup_receipt")
    if not isinstance(receipt, Mapping):
        return None
    from app.learn.hybrid.gpu_lifecycle import validate_hybrid_cleanup_receipt

    try:
        exact_receipt = validate_hybrid_cleanup_receipt(receipt)
    except (TypeError, ValueError):
        return None
    evidence = exact_receipt.get("source_cleanup_evidence")
    lease = evidence.get("model_lease") if isinstance(evidence, Mapping) else None
    if exact_receipt.get("provider") != "vista" or not isinstance(lease, Mapping):
        return None
    identities = [_process_identity(item) for item in lease.get("process_identities", [])]
    profile = _mapping(lease.get("profile"), "VISTA cleanup profile")
    acquisition = _mapping(
        lease.get("process_scope_acquisition"), "VISTA cleanup scope acquisition"
    )
    port = profile.get("port")
    if (
        not identities
        or lease.get("contract_version") != "hybrid_vista_model_lease_v2"
        or lease.get("provider") != "vista"
        or exact_receipt.get("provider_lease_identity", {}).get("incarnation_id")
        != lease.get("incarnation_id")
        or exact_receipt.get("provider_lease_identity", {}).get("process_identities")
        != identities
        or acquisition.get("process_identities") != identities
        or isinstance(port, bool)
        or not isinstance(port, int)
        or port <= 0
    ):
        return None
    identity = compose_benchmark_provider_runtime_identity(
        provider="vista",
        lease_identity={
            "incarnation_id": lease["incarnation_id"],
            "lease_content_sha256": content_sha256(lease),
        },
        profile_ref={"content_sha256": content_sha256(profile)},
        listener_owner={
            "host": str(profile.get("host") or "127.0.0.1"),
            "port": port,
            "process_identities": identities,
        },
        process_identities=identities,
        process_scope={
            "scope_name": acquisition["scope_name"],
            "member_pids": list(acquisition["member_pids"]),
            "process_identities": identities,
        },
    )
    return {
        "runtime_identity": identity,
        "authoritative_cleanup_ref": {
            "content_sha256": exact_receipt["content_sha256"]
        },
        "authoritative_cleanup_contract": exact_receipt["contract_version"],
    }


def _authoritative_omni_cleanup(
    record: Mapping[str, object], worker_termination: Mapping[str, object]
) -> dict[str, Any] | None:
    cooperative = worker_termination.get("cooperative_cleanup")
    result = record.get("worker_result")
    response = result.get("response") if isinstance(result, Mapping) else None
    if not isinstance(response, Mapping):
        return None
    invocation_id = response.get("provider_invocation_id")
    if (
        not isinstance(invocation_id, str)
        or not invocation_id.startswith("invocation/")
    ):
        return None
    if isinstance(cooperative, Mapping) and (
        cooperative.get("contract_version") != "hybrid_omni_cooperative_cleanup_v1"
        or cooperative.get("cleanup_status") != "clean"
        or cooperative.get("provider_claim_status") != "complete"
        or cooperative.get("provider_invocation_id") != invocation_id
        or cooperative.get("provider_receipt_ref") != response.get("provider_receipt_ref")
    ):
        return None
    from app.learn.recognition.uei.omniparser_shadow_adapter import (
        load_omniparser_invocation_cleanup_observation,
    )

    try:
        observation = load_omniparser_invocation_cleanup_observation(invocation_id)
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    acquisition = observation.get("process_scope_acquisition")
    process = observation.get("process_identity")
    if (
        observation.get("cleanup_status") != "verified"
        or observation.get("inventory_observable") is not True
        or observation.get("provider_processes_after") != []
        or observation.get("orphan_descendant_identities") != []
        or observation.get("active_listeners_after") != []
        or observation.get("lease_files_after") != []
        or not isinstance(acquisition, Mapping)
        or acquisition.get("scope_name") != observation.get("process_scope_name")
        or not isinstance(process, Mapping)
        or process.get("pid") not in acquisition.get("member_pids", [])
        or observation.get("content_sha256") != content_sha256(observation)
    ):
        return None
    exact_process = _process_identity(process)
    identity = compose_benchmark_provider_runtime_identity(
        provider="omni",
        lease_identity=None,
        profile_ref=None,
        listener_owner=None,
        process_identities=[exact_process],
        process_scope={
            "scope_name": acquisition["scope_name"],
            "member_pids": list(acquisition["member_pids"]),
            "process_identities": [exact_process],
        },
    )
    return {
        "runtime_identity": identity,
        "authoritative_cleanup_ref": {
            "content_sha256": observation["content_sha256"]
        },
        "authoritative_cleanup_contract": observation["contract_version"],
    }


def _validate_dispatch_receipt(value: object) -> dict[str, Any]:
    fields = {
        "contract_version",
        "provider",
        "dispatch_index",
        "operation_ref",
        "window_attestation_ref",
        "provider_runtime_attestation_ref",
        "predecessor_content_sha256",
        "artifact_is_authorization",
        "execute_binding_enabled",
        "content_sha256",
    }
    receipt = _closed(value, fields, "benchmark dispatch receipt")
    if receipt["contract_version"] != "benchmark_v2_provider_dispatch_receipt_v1":
        raise ValueError("benchmark dispatch receipt contract is invalid")
    receipt["provider"] = _provider(receipt["provider"])
    index = receipt["dispatch_index"]
    if isinstance(index, bool) or not isinstance(index, int) or index < 1:
        raise ValueError("benchmark dispatch receipt index is invalid")
    receipt["operation_ref"] = _operation_ref(receipt["operation_ref"])
    for name in ("window_attestation_ref", "provider_runtime_attestation_ref"):
        receipt[name] = _content_ref(receipt[name], name)
    _sha(receipt["predecessor_content_sha256"], "dispatch predecessor SHA")
    if (
        receipt["artifact_is_authorization"] is not False
        or receipt["execute_binding_enabled"] is not False
    ):
        raise ValueError("benchmark dispatch receipt cannot authorize actions")
    _sha(receipt["content_sha256"], "benchmark dispatch receipt SHA")
    if receipt["content_sha256"] != content_sha256(receipt):
        raise ValueError("benchmark dispatch receipt content SHA mismatch")
    return receipt


def _attest_exact_window(value: Mapping[str, object]) -> dict[str, str]:
    from app.learn.hybrid.benchmark_v2_worker_binding import (
        _assert_owner_matches_serialized,
        _owner_from_journal,
        _validate_serialized,
    )

    serialized = _validate_serialized(value)
    owner = _owner_from_journal(serialized)
    attestation = _assert_owner_matches_serialized(
        serialized=serialized, owner=owner
    )
    return {"content_sha256": content_sha256(attestation)}


def _attest_exact_provider_runtime(
    provider: str, value: Mapping[str, object]
) -> dict[str, Any]:
    if provider == "qwen":
        return _attest_qwen_runtime(value)
    if provider == "vista":
        return _attest_vista_runtime(value)
    return _attest_scoped_process_runtime(value, expected_provider="omni")


def _attest_qwen_runtime(value: Mapping[str, object]) -> dict[str, Any]:
    lease = _mapping(value, "benchmark Qwen lease")
    from app.core.model_server import _profile_for_qwen_model_lease

    profile = _profile_for_qwen_model_lease(deepcopy(lease))
    required = {
        "contract_version",
        "lease_id",
        "owner_request_id",
        "profile_id",
        "incarnation_id",
        "server_base_url",
        "server_model_id",
        "profile_sha256",
        "server_process_identity",
    }
    if set(lease) != required or lease.get("contract_version") != "qwen_model_server_lease_v2":
        raise ValueError("exact Qwen model lease is required")
    from urllib.parse import urlsplit

    from app.core.model_server import (
        _current_process_identity,
        _find_qwen_owner_record,
        _listening_pids_for_port,
        _public_profile,
    )
    from app.learn.hybrid.windows_process_scope import WindowsProcessScope

    public_profile = _public_profile(profile)
    profile_payload_sha256 = content_sha256(public_profile)
    if profile_payload_sha256 != lease.get("profile_sha256"):
        raise ValueError("Qwen exact profile identity changed before dispatch")
    owner = _find_qwen_owner_record(str(lease.get("owner_request_id") or ""))
    if (
        not isinstance(owner, Mapping)
        or owner.get("kind") != "active"
        or owner.get("lease") != lease
        or not isinstance(owner.get("state"), Mapping)
    ):
        raise ValueError("Qwen exact ownership changed before dispatch")
    state = dict(owner["state"])
    acquisition = _mapping(
        state.get("process_scope_acquisition"),
        "Qwen process scope acquisition",
    )
    scope_name = _text(state.get("process_scope_name"), "Qwen process scope name")
    process = _process_identity(lease.get("server_process_identity"))
    if (
        acquisition.get("contract_version") != "hybrid_process_scope_acquisition_v1"
        or acquisition.get("scope_name") != scope_name
        or acquisition.get("server_process_identity") != process
        or not isinstance(acquisition.get("member_pids"), list)
        or process["pid"] not in acquisition["member_pids"]
        or _current_process_identity(process["pid"]) != process
    ):
        raise ValueError("Qwen exact Job ownership changed before dispatch")
    scope = WindowsProcessScope(scope_name, create=False)
    try:
        current_members = scope.pids()
    finally:
        scope.close()
    if process["pid"] not in current_members:
        raise ValueError("Qwen exact process is outside its Job before dispatch")
    parsed = urlsplit(_text(lease.get("server_base_url"), "Qwen server base URL"))
    port = int(parsed.port or 0)
    host = str(parsed.hostname or "")
    if not host or port <= 0 or process["pid"] not in _listening_pids_for_port(port):
        raise ValueError("Qwen exact listener ownership changed before dispatch")
    identity = compose_benchmark_provider_runtime_identity(
        provider="qwen",
        lease_identity={
            "lease_id": lease["lease_id"],
            "incarnation_id": lease["incarnation_id"],
            "owner_request_id": lease["owner_request_id"],
        },
        profile_ref={"content_sha256": lease["profile_sha256"]},
        listener_owner={
            "host": host,
            "port": port,
            "process_identities": [process],
        },
        process_identities=[process],
        process_scope={
            "scope_name": scope_name,
            "member_pids": list(acquisition["member_pids"]),
            "process_identities": [process],
        },
    )
    return {
        "runtime_identity": identity,
        "profile": {
            "profile_id": _text(lease["profile_id"], "Qwen profile id"),
            "profile_sha256": _sha(lease["profile_sha256"], "Qwen profile SHA"),
            "profile_payload_sha256": profile_payload_sha256,
        },
        "installed_configuration_snapshot": None,
    }


def _attest_scoped_process_runtime(
    value: Mapping[str, object], *, expected_provider: str
) -> dict[str, Any]:
    runtime = _mapping(value, "benchmark scoped provider runtime")
    if runtime.get("provider") != expected_provider:
        raise ValueError("benchmark scoped provider runtime provider mismatch")
    identity = _process_identity(runtime.get("process_identity"))
    scope_name = _text(runtime.get("scope_name"), "provider scope name")
    snapshot = _validate_omni_installed_configuration_snapshot(
        runtime.get("installed_configuration_snapshot")
    )
    from app.core.model_server import _current_process_identity
    from app.learn.hybrid.windows_process_scope import WindowsProcessScope

    if _current_process_identity(identity["pid"]) != identity:
        raise ValueError("benchmark provider process identity is stale")
    scope = WindowsProcessScope(scope_name, create=False)
    try:
        members = scope.pids()
    finally:
        scope.close()
    if identity["pid"] not in members:
        raise ValueError("benchmark provider process is outside its exact Job")
    exact = compose_benchmark_provider_runtime_identity(
        provider="omni",
        lease_identity=None,
        profile_ref=None,
        listener_owner=None,
        process_identities=[identity],
        process_scope={
            "scope_name": scope_name,
            "member_pids": members,
            "process_identities": [identity],
        },
    )
    return {
        "runtime_identity": exact,
        "profile": {
            "profile_id": snapshot["profile_id"],
            "profile_sha256": snapshot["content_sha256"],
            "profile_payload_sha256": snapshot["content_sha256"],
        },
        "installed_configuration_snapshot": snapshot,
    }


def _attest_vista_runtime(value: Mapping[str, object]) -> dict[str, Any]:
    lease = _mapping(value, "benchmark VISTA lease")
    if (
        lease.get("contract_version") != "hybrid_vista_model_lease_v2"
        or lease.get("provider") != "vista"
        or not isinstance(lease.get("process_identities"), list)
        or not lease["process_identities"]
    ):
        raise ValueError("exact Hybrid VISTA model lease is required")
    scope_name = _text(lease.get("process_scope_name"), "VISTA process scope")
    from app.core.model_server import _current_process_identity
    from app.learn.hybrid.windows_process_scope import WindowsProcessScope

    identities = [_process_identity(item) for item in lease["process_identities"]]
    profile = _mapping(lease.get("profile"), "VISTA profile")
    profile_id = _text(profile.get("profile_id"), "VISTA profile id")
    port = profile.get("port")
    if isinstance(port, bool) or not isinstance(port, int) or port <= 0:
        raise ValueError("VISTA profile listener port is invalid")
    expected_incarnation = content_sha256(
        {"profile_id": profile_id, "process_identities": identities}
    )
    if lease.get("incarnation_id") != expected_incarnation:
        raise ValueError("VISTA lease incarnation is stale")
    acquisition = _closed(
        lease.get("process_scope_acquisition"),
        {
            "contract_version",
            "scope_name",
            "member_pids",
            "process_identities",
        },
        "VISTA process scope acquisition",
    )
    if (
        acquisition["contract_version"] != "hybrid_process_scope_acquisition_v1"
        or acquisition["scope_name"] != scope_name
        or acquisition["process_identities"] != identities
        or not isinstance(acquisition["member_pids"], list)
        or any(
            isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0
            for pid in acquisition["member_pids"]
        )
        or any(item["pid"] not in acquisition["member_pids"] for item in identities)
    ):
        raise ValueError("VISTA process scope acquisition is stale")
    if any(_current_process_identity(item["pid"]) != item for item in identities):
        raise ValueError("VISTA process identity changed before dispatch")
    scope = WindowsProcessScope(scope_name, create=False)
    try:
        members = scope.pids()
    finally:
        scope.close()
    if any(item["pid"] not in members for item in identities):
        raise ValueError("VISTA process is outside its exact Job")
    from app.core.model_server import _listening_pids_for_port

    listener_pids = _listening_pids_for_port(port)
    expected_pids = {item["pid"] for item in identities}
    if not listener_pids or not set(listener_pids).issubset(expected_pids):
        raise ValueError("VISTA listener socket ownership changed before dispatch")
    profile_sha256 = content_sha256(profile)
    exact = compose_benchmark_provider_runtime_identity(
        provider="vista",
        lease_identity={
            "incarnation_id": lease["incarnation_id"],
            "lease_content_sha256": content_sha256(lease),
        },
        profile_ref={"content_sha256": profile_sha256},
        listener_owner={
            "host": str(profile.get("host") or "127.0.0.1"),
            "port": port,
            "process_identities": identities,
        },
        process_identities=identities,
        process_scope={
            "scope_name": scope_name,
            "member_pids": list(acquisition["member_pids"]),
            "process_identities": identities,
        },
    )
    return {
        "runtime_identity": exact,
        "profile": {
            "profile_id": profile_id,
            "profile_sha256": profile_sha256,
            "profile_payload_sha256": profile_sha256,
        },
        "installed_configuration_snapshot": None,
    }


def _lexical_absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _is_link_or_reparse(stat_result: os.stat_result) -> bool:
    attributes = int(getattr(stat_result, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(stat_result.st_mode) or bool(attributes & reparse_flag)


def _assert_secure_dispatch_path(path: Path, *, final_may_be_missing: bool) -> Path:
    root = _lexical_absolute_path(Path(PROJECT_ROOT))
    candidate = _lexical_absolute_path(Path(path))
    if not root.is_absolute() or candidate != Path(path):
        raise ValueError("benchmark dispatch path is not lexical canonical absolute")
    try:
        root_observation = os.lstat(root)
    except OSError as error:
        raise ValueError("benchmark dispatch fixed project root is unavailable") from error
    if _is_link_or_reparse(root_observation) or not stat.S_ISDIR(
        root_observation.st_mode
    ):
        raise ValueError("benchmark dispatch fixed project root is unsafe")
    try:
        relative = candidate.relative_to(root)
    except ValueError as error:
        raise ValueError("benchmark dispatch path escapes fixed project root") from error
    current = Path(root.anchor)
    components = [current]
    for part in root.parts[1:]:
        current = current / part
        components.append(current)
    for part in relative.parts:
        current = current / part
        components.append(current)
    for position, component in enumerate(components):
        is_final = position == len(components) - 1
        try:
            observed = os.lstat(component)
        except FileNotFoundError:
            if is_final and not final_may_be_missing:
                raise ValueError("benchmark dispatch final path is unavailable")
            continue
        except OSError as error:
            raise ValueError("benchmark dispatch path cannot be inspected") from error
        if _is_link_or_reparse(observed):
            raise ValueError("benchmark dispatch path contains a symlink or reparse point")
        if is_final:
            if stat.S_ISREG(observed.st_mode) and observed.st_nlink != 1:
                raise ValueError("benchmark dispatch final path is a hardlink")
        elif not stat.S_ISDIR(observed.st_mode):
            raise ValueError("benchmark dispatch ancestor is not a directory")
    return candidate


def _fixed_dispatch_journal_path(operation_ref: Mapping[str, object]) -> Path:
    key = content_sha256(
        {
            name: operation_ref[name]
            for name in ("run_id", "stage", "operation_id")
        }
    )
    root = _lexical_absolute_path(Path(PROJECT_ROOT))
    path = (
        root
        / "runtime_state"
        / "benchmark-v2-provider-dispatch"
        / f"{key}.jsonl"
    )
    return _assert_secure_dispatch_path(path, final_may_be_missing=True)


def _dispatch_artifact_path(
    operation_ref: Mapping[str, object], provider: str, dispatch_index: int, suffix: str
) -> Path:
    journal = _fixed_dispatch_journal_path(operation_ref)
    path = journal.parent / f"{journal.stem}.{provider}.{dispatch_index}.{suffix}.json"
    return _assert_secure_dispatch_path(path, final_may_be_missing=True)


@contextmanager
def _journal_process_lock(journal_path: Path) -> Iterator[None]:
    """以 crash-released OS primitive 串行同一 journal 的跨进程事务。"""

    journal = _assert_secure_dispatch_path(
        Path(journal_path), final_may_be_missing=True
    )
    lock_path = _assert_secure_dispatch_path(
        journal.with_name(journal.name + ".lock"), final_may_be_missing=True
    )
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    _assert_secure_dispatch_path(lock_path.parent, final_may_be_missing=False)
    if os.name == "nt":
        with _windows_exclusive_file_lock(lock_path):
            yield
        return

    import fcntl

    flags = os.O_RDWR | os.O_CREAT
    flags |= int(getattr(os, "O_NOFOLLOW", 0))
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        observed = os.fstat(descriptor)
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_nlink != 1
            or _is_link_or_reparse(observed)
        ):
            raise ValueError("benchmark dispatch process lock is unsafe")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        _assert_secure_dispatch_path(lock_path, final_may_be_missing=False)
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


@contextmanager
def _windows_exclusive_file_lock(lock_path: Path) -> Iterator[None]:
    import ctypes
    from ctypes import wintypes

    class _ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("dwFileAttributes", wintypes.DWORD),
            ("ftCreationTime", wintypes.FILETIME),
            ("ftLastAccessTime", wintypes.FILETIME),
            ("ftLastWriteTime", wintypes.FILETIME),
            ("dwVolumeSerialNumber", wintypes.DWORD),
            ("nFileSizeHigh", wintypes.DWORD),
            ("nFileSizeLow", wintypes.DWORD),
            ("nNumberOfLinks", wintypes.DWORD),
            ("nFileIndexHigh", wintypes.DWORD),
            ("nFileIndexLow", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    get_information = kernel32.GetFileInformationByHandle
    get_information.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ByHandleFileInformation),
    ]
    get_information.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    deadline = time.monotonic() + 30.0
    invalid_handle = wintypes.HANDLE(-1).value
    handle = None
    while handle is None:
        candidate = create_file(
            str(lock_path),
            0x80000000 | 0x40000000,
            0,
            None,
            4,
            0x00000080 | 0x00200000,
            None,
        )
        if candidate != invalid_handle:
            handle = candidate
            break
        error_code = ctypes.get_last_error()
        if error_code not in {32, 33} or time.monotonic() >= deadline:
            raise OSError(error_code, "benchmark dispatch process lock failed")
        time.sleep(0.01)
    try:
        information = _ByHandleFileInformation()
        if not get_information(handle, ctypes.byref(information)):
            error_code = ctypes.get_last_error()
            raise OSError(error_code, "benchmark dispatch process lock inspection failed")
        if (
            information.dwFileAttributes & 0x400
            or information.nNumberOfLinks != 1
        ):
            raise ValueError("benchmark dispatch process lock is unsafe")
        _assert_secure_dispatch_path(lock_path, final_may_be_missing=False)
        yield
    finally:
        close_handle(handle)


def _validate_profile_identity(value: object) -> dict[str, str]:
    profile = _closed(value, _PROFILE_FIELDS, "benchmark dispatch profile identity")
    profile["profile_id"] = _text(profile["profile_id"], "dispatch profile id")
    for name in ("profile_sha256", "profile_payload_sha256"):
        profile[name] = _sha(profile[name], f"dispatch {name}")
    if profile["profile_sha256"] != profile["profile_payload_sha256"]:
        raise ValueError("benchmark dispatch profile payload identity differs")
    return profile


def _validate_omni_installed_configuration_snapshot(value: object) -> dict[str, Any]:
    snapshot = _closed(
        value,
        _OMNI_CONFIGURATION_FIELDS,
        "Omni installed configuration snapshot",
    )
    if snapshot["contract_version"] != "omniparser_installed_configuration_snapshot_v1":
        raise ValueError("Omni installed configuration snapshot contract is invalid")
    snapshot["profile_id"] = _text(snapshot["profile_id"], "Omni profile id")
    for name in (
        "interpreter_path",
        "worker_script_path",
        "code_path",
        "weights_path",
        "cache_path",
    ):
        path = Path(_text(snapshot[name], f"Omni {name}"))
        if not path.is_absolute() or path != path.resolve():
            raise ValueError(f"Omni {name} is not canonical")
    minimum = snapshot["minimum_free_gpu_gib"]
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 0:
        raise ValueError("Omni minimum free GPU value is invalid")
    if not isinstance(snapshot["is_available"], bool):
        raise ValueError("Omni availability snapshot is invalid")
    if (
        snapshot["artifact_is_authorization"] is not False
        or snapshot["execute_binding_enabled"] is not False
    ):
        raise ValueError("Omni configuration snapshot cannot authorize actions")
    _sha(snapshot["content_sha256"], "Omni configuration snapshot SHA")
    if snapshot["content_sha256"] != content_sha256(snapshot):
        raise ValueError("Omni configuration snapshot seal is invalid")
    return snapshot


def _validate_exact_provider_attestation(
    provider: str, value: object
) -> dict[str, Any]:
    attestation = _closed(
        value,
        {"runtime_identity", "profile", "installed_configuration_snapshot"},
        "benchmark exact provider attestation",
    )
    identity = validate_benchmark_provider_runtime_identity(
        attestation["runtime_identity"]
    )
    if identity["provider"] != provider:
        raise ValueError("benchmark exact provider runtime differs")
    profile = _validate_profile_identity(attestation["profile"])
    snapshot = attestation["installed_configuration_snapshot"]
    if provider == "omni":
        snapshot = _validate_omni_installed_configuration_snapshot(snapshot)
        if (
            profile["profile_id"] != snapshot["profile_id"]
            or profile["profile_sha256"] != snapshot["content_sha256"]
            or profile["profile_payload_sha256"] != snapshot["content_sha256"]
        ):
            raise ValueError("Omni installed profile identity differs")
    elif snapshot is not None:
        raise ValueError("managed provider has unexpected Omni configuration snapshot")
    if identity["profile_ref"] is not None and identity["profile_ref"] != {
        "content_sha256": profile["profile_sha256"]
    }:
        raise ValueError("benchmark runtime and profile identity differ")
    return {
        "runtime_identity": identity,
        "profile": profile,
        "installed_configuration_snapshot": snapshot,
    }


def _compose_dispatch_runtime_parent(
    *,
    provider: str,
    operation_ref: Mapping[str, object],
    receipt: Mapping[str, object],
    runtime_attestation: Mapping[str, object],
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "contract_version": "benchmark_v2_dispatch_runtime_parent_v1",
        "provider": provider,
        "operation_ref": deepcopy(dict(operation_ref)),
        "dispatch_receipt_ref": {"content_sha256": receipt["content_sha256"]},
        "runtime_identity": deepcopy(runtime_attestation["runtime_identity"]),
        "profile": deepcopy(runtime_attestation["profile"]),
        "installed_configuration_snapshot": deepcopy(
            runtime_attestation["installed_configuration_snapshot"]
        ),
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    body["content_sha256"] = content_sha256(body)
    return _validate_dispatch_runtime_parent(body)


def _validate_dispatch_runtime_parent(value: object) -> dict[str, Any]:
    parent = _closed(value, _RUNTIME_PARENT_FIELDS, "benchmark dispatch runtime parent")
    if parent["contract_version"] != "benchmark_v2_dispatch_runtime_parent_v1":
        raise ValueError("benchmark dispatch runtime parent contract is invalid")
    parent["provider"] = _provider(parent["provider"])
    parent["operation_ref"] = _operation_ref(parent["operation_ref"])
    parent["dispatch_receipt_ref"] = _content_ref(
        parent["dispatch_receipt_ref"], "dispatch runtime parent receipt ref"
    )
    exact = _validate_exact_provider_attestation(
        parent["provider"],
        {
            "runtime_identity": parent["runtime_identity"],
            "profile": parent["profile"],
            "installed_configuration_snapshot": parent[
                "installed_configuration_snapshot"
            ],
        },
    )
    parent.update(exact)
    if (
        parent["artifact_is_authorization"] is not False
        or parent["execute_binding_enabled"] is not False
    ):
        raise ValueError("benchmark dispatch runtime parent cannot authorize actions")
    _sha(parent["content_sha256"], "dispatch runtime parent SHA")
    if parent["content_sha256"] != content_sha256(parent):
        raise ValueError("benchmark dispatch runtime parent content SHA mismatch")
    return parent


def _compose_dispatch_commit_marker(
    *,
    receipt: Mapping[str, object],
    runtime_parent: Mapping[str, object],
    journal_prefix: bytes,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "contract_version": "benchmark_v2_dispatch_commit_marker_v1",
        "provider": receipt["provider"],
        "operation_ref": deepcopy(receipt["operation_ref"]),
        "dispatch_receipt_ref": {"content_sha256": receipt["content_sha256"]},
        "runtime_parent_ref": {
            "content_sha256": runtime_parent["content_sha256"]
        },
        "journal_prefix_sha256": sha256(journal_prefix).hexdigest(),
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    body["content_sha256"] = content_sha256(body)
    return _validate_dispatch_commit_marker(body)


def _validate_dispatch_commit_marker(value: object) -> dict[str, Any]:
    marker = _closed(value, _COMMIT_MARKER_FIELDS, "benchmark dispatch commit marker")
    if marker["contract_version"] != "benchmark_v2_dispatch_commit_marker_v1":
        raise ValueError("benchmark dispatch commit marker contract is invalid")
    marker["provider"] = _provider(marker["provider"])
    marker["operation_ref"] = _operation_ref(marker["operation_ref"])
    for name in ("dispatch_receipt_ref", "runtime_parent_ref"):
        marker[name] = _content_ref(marker[name], f"dispatch commit marker {name}")
    _sha(marker["journal_prefix_sha256"], "dispatch journal prefix SHA")
    if (
        marker["artifact_is_authorization"] is not False
        or marker["execute_binding_enabled"] is not False
    ):
        raise ValueError("benchmark dispatch commit marker cannot authorize actions")
    _sha(marker["content_sha256"], "dispatch commit marker SHA")
    if marker["content_sha256"] != content_sha256(marker):
        raise ValueError("benchmark dispatch commit marker content SHA mismatch")
    return marker


def _read_canonical_artifact(
    path: Path, validator: Any, name: str
) -> dict[str, Any]:
    try:
        _assert_secure_dispatch_path(path, final_may_be_missing=False)
        raw = path.read_bytes()
        if not raw.endswith(b"\n") or raw.count(b"\n") != 1:
            raise ValueError(f"{name} is not canonical")
        decoded = json.loads(
            raw[:-1].decode("utf-8"),
            parse_int=_parse_canonical_integer,
        )
        if canonical_json_bytes(decoded) + b"\n" != raw:
            raise ValueError(f"{name} is not canonical")
        return validator(decoded)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        if isinstance(error, ValueError) and str(error).startswith(name):
            raise
        raise ValueError(f"{name} is corrupt") from error


def _parse_canonical_integer(raw: str) -> int:
    value = int(raw)
    if abs(value) <= _MAX_EXACT_BINARY64_INTEGER:
        return value
    as_float = float(raw)
    if not math.isfinite(as_float) or not as_float.is_integer():
        raise ValueError("canonical integer is not binary64")
    return int(as_float)


def _write_create_or_identical(path: Path, value: Mapping[str, object], name: str) -> None:
    raw = canonical_json_bytes(dict(value)) + b"\n"
    _assert_secure_dispatch_path(path, final_may_be_missing=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    _assert_secure_dispatch_path(path.parent, final_may_be_missing=False)
    try:
        with path.open("xb", buffering=0) as stream:
            written = stream.write(raw)
            if written != len(raw):
                raise OSError(f"{name} short write")
            stream.flush()
            os.fsync(stream.fileno())
        _assert_secure_dispatch_path(path, final_may_be_missing=False)
    except FileExistsError:
        _assert_secure_dispatch_path(path, final_may_be_missing=False)
        if path.read_bytes() != raw:
            raise ValueError(f"existing {name} is different")
        with path.open("ab", buffering=0) as stream:
            stream.flush()
            os.fsync(stream.fileno())


def _publish_commit_marker(
    path: Path, value: Mapping[str, object]
) -> None:
    name = "benchmark dispatch commit marker"
    raw = canonical_json_bytes(dict(value)) + b"\n"
    _assert_secure_dispatch_path(path, final_may_be_missing=True)
    if path.exists():
        existing = _read_canonical_artifact(
            path, _validate_dispatch_commit_marker, name
        )
        if existing != dict(value) or path.read_bytes() != raw:
            raise ValueError(f"existing {name} is different")
        return

    pending = path.with_name(path.name + ".pending")
    _assert_secure_dispatch_path(pending, final_may_be_missing=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    _assert_secure_dispatch_path(path.parent, final_may_be_missing=False)
    try:
        if pending.exists():
            _assert_secure_dispatch_path(pending, final_may_be_missing=False)
            if pending.read_bytes() != raw:
                raise ValueError(f"existing pending {name} is different")
            with pending.open("ab", buffering=0) as stream:
                stream.flush()
                os.fsync(stream.fileno())
        else:
            try:
                with pending.open("xb", buffering=0) as stream:
                    written = stream.write(raw)
                    if written != len(raw):
                        raise OSError(f"{name} short write")
                    stream.flush()
                    os.fsync(stream.fileno())
            except BaseException:
                try:
                    pending.unlink(missing_ok=True)
                except OSError:
                    pass
                raise
        _assert_secure_dispatch_path(pending, final_may_be_missing=False)
        try:
            os.link(pending, path, follow_symlinks=False)
        except FileExistsError as error:
            raise ValueError(f"existing {name} appeared during publish") from error
        try:
            pending.unlink()
        except OSError:
            try:
                path.unlink(missing_ok=True)
            finally:
                raise
        _assert_secure_dispatch_path(path, final_may_be_missing=False)
    finally:
        if not path.exists():
            try:
                pending.unlink(missing_ok=True)
            except OSError:
                pass


def _decode_journal(raw: bytes) -> tuple[list[dict[str, Any]], list[bytes]]:
    if not raw:
        return [], []
    if not raw.endswith(b"\n"):
        raise ValueError("benchmark dispatch receipt journal is incomplete")
    records: list[dict[str, Any]] = []
    lines = raw.splitlines(keepends=True)
    seen: set[str] = set()
    for line in lines:
        raw_line = line[:-1]
        try:
            decoded = json.loads(raw_line.decode("utf-8"))
            if canonical_json_bytes(decoded) != raw_line:
                raise ValueError("receipt row is not canonical")
            receipt = _validate_dispatch_receipt(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise ValueError("benchmark dispatch receipt journal is corrupt") from error
        digest = receipt["content_sha256"]
        if digest in seen:
            raise ValueError("benchmark dispatch receipt journal has duplicate rows")
        seen.add(digest)
        records.append(receipt)
    return records, lines


def _validate_committed_row(
    *, receipt: Mapping[str, object], prefix: bytes
) -> None:
    provider = str(receipt["provider"])
    index = int(receipt["dispatch_index"])
    operation = receipt["operation_ref"]
    parent_path = _dispatch_artifact_path(operation, provider, index, "runtime-parent")
    marker_path = _dispatch_artifact_path(operation, provider, index, "commit-marker")
    if not marker_path.is_file():
        raise ValueError("benchmark dispatch receipt row is uncommitted (commit marker missing)")
    parent = _read_canonical_artifact(
        parent_path, _validate_dispatch_runtime_parent, "benchmark dispatch runtime parent"
    )
    marker = _read_canonical_artifact(
        marker_path, _validate_dispatch_commit_marker, "benchmark dispatch commit marker"
    )
    if (
        parent["provider"] != provider
        or parent["operation_ref"] != operation
        or parent["dispatch_receipt_ref"]
        != {"content_sha256": receipt["content_sha256"]}
        or receipt["provider_runtime_attestation_ref"]
        != {"content_sha256": parent["runtime_identity"]["content_sha256"]}
        or marker["provider"] != provider
        or marker["operation_ref"] != operation
        or marker["dispatch_receipt_ref"] != parent["dispatch_receipt_ref"]
        or marker["runtime_parent_ref"]
        != {"content_sha256": parent["content_sha256"]}
        or marker["journal_prefix_sha256"] != sha256(prefix).hexdigest()
    ):
        raise ValueError("benchmark dispatch parent or commit marker join differs")


def _read_committed_dispatch_records_locked(path: Path) -> list[dict[str, Any]]:
    _assert_secure_dispatch_path(path, final_may_be_missing=False)
    records, lines = _decode_journal(path.read_bytes())
    prefix = b""
    provider_indexes: dict[str, int] = {}
    for receipt, line in zip(records, lines, strict=True):
        prefix += line
        provider = receipt["provider"]
        provider_indexes[provider] = provider_indexes.get(provider, 0) + 1
        if receipt["dispatch_index"] != provider_indexes[provider]:
            raise ValueError("benchmark dispatch receipt index is not contiguous")
        _validate_committed_row(receipt=receipt, prefix=prefix)
    return records


def _read_committed_dispatch_records(path: Path) -> list[dict[str, Any]]:
    with _JOURNAL_LOCK, _journal_process_lock(path):
        _assert_secure_dispatch_path(path, final_may_be_missing=True)
        if not path.is_file():
            return []
        return _read_committed_dispatch_records_locked(path)


def _append_receipt(path: Path, receipt: Mapping[str, object]) -> None:
    raw = canonical_json_bytes(dict(receipt)) + b"\n"
    _assert_secure_dispatch_path(path, final_may_be_missing=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    _assert_secure_dispatch_path(path.parent, final_may_be_missing=False)
    with path.open("ab", buffering=0) as stream:
        written = stream.write(raw)
        if written != len(raw):
            raise OSError("benchmark dispatch receipt short write")
        stream.flush()
        os.fsync(stream.fileno())
    _assert_secure_dispatch_path(path, final_may_be_missing=False)


def _commit_dispatch_transaction(
    *,
    journal_path: Path,
    receipt: Mapping[str, object],
    runtime_parent: Mapping[str, object],
) -> dict[str, Any]:
    exact_receipt = _validate_dispatch_receipt(receipt)
    exact_parent = _validate_dispatch_runtime_parent(runtime_parent)
    operation = exact_receipt["operation_ref"]
    provider = exact_receipt["provider"]
    index = exact_receipt["dispatch_index"]
    if journal_path != _fixed_dispatch_journal_path(operation):
        raise ValueError("benchmark dispatch journal differs from fixed project root")
    parent_path = _dispatch_artifact_path(operation, provider, index, "runtime-parent")
    marker_path = _dispatch_artifact_path(operation, provider, index, "commit-marker")
    with _JOURNAL_LOCK, _journal_process_lock(journal_path):
        _assert_secure_dispatch_path(journal_path, final_may_be_missing=True)
        raw = journal_path.read_bytes() if journal_path.is_file() else b""
        records, lines = _decode_journal(raw)
        slot_positions = [
            position
            for position, record in enumerate(records)
            if record["provider"] == provider
            and record["operation_ref"] == operation
            and record["dispatch_index"] == index
        ]
        if len(slot_positions) > 1:
            raise ValueError("benchmark dispatch journal has duplicate slot rows")
        if slot_positions and records[slot_positions[0]] != exact_receipt:
            raise ValueError("benchmark dispatch replay runtime or profile differs")

        if slot_positions:
            if not parent_path.is_file():
                raise ValueError(
                    "benchmark dispatch uncommitted row is missing its exact parent"
                )
            existing_parent = _read_canonical_artifact(
                parent_path,
                _validate_dispatch_runtime_parent,
                "benchmark dispatch runtime parent",
            )
            if existing_parent != exact_parent:
                raise ValueError("existing benchmark dispatch runtime parent is different")
            _write_create_or_identical(
                parent_path, exact_parent, "benchmark dispatch runtime parent"
            )
            position = slot_positions[0]
            prefix = b"".join(lines[: position + 1])
            if marker_path.is_file():
                _validate_committed_row(receipt=exact_receipt, prefix=prefix)
                return deepcopy(exact_receipt)
            if position != len(records) - 1:
                raise ValueError("benchmark dispatch uncommitted row is not the exact tail")
            for prior_position, prior in enumerate(records[:position]):
                _validate_committed_row(
                    receipt=prior, prefix=b"".join(lines[: prior_position + 1])
                )
            # 精确单行恢复：不重写 row，只重新 flush/fsync 后铸造 marker。
            with journal_path.open("ab", buffering=0) as stream:
                stream.flush()
                os.fsync(stream.fileno())
        else:
            if records:
                _read_committed_dispatch_records_locked(journal_path)
            # parent 必须先于 journal authority 持久化。
            _write_create_or_identical(
                parent_path, exact_parent, "benchmark dispatch runtime parent"
            )
            _append_receipt(journal_path, exact_receipt)
            prefix = raw + canonical_json_bytes(exact_receipt) + b"\n"

        marker = _compose_dispatch_commit_marker(
            receipt=exact_receipt,
            runtime_parent=exact_parent,
            journal_prefix=prefix,
        )
        _publish_commit_marker(marker_path, marker)
        return deepcopy(exact_receipt)


def _operation_ref(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("benchmark dispatch operation ref is invalid")
    candidate = deepcopy(dict(value))
    if "content_sha256" not in candidate:
        candidate["content_sha256"] = content_sha256(candidate)
    operation = _closed(candidate, _OPERATION_FIELDS, "benchmark dispatch operation ref")
    for name in ("run_id", "stage", "operation_id"):
        operation[name] = _text(operation[name], f"operation {name}")
    revision = operation["revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("benchmark dispatch operation revision is invalid")
    for name in ("window_binding_ref", "capture_ref"):
        operation[name] = _identity_ref(operation[name], name)
    _sha(operation["content_sha256"], "benchmark dispatch operation SHA")
    if operation["content_sha256"] != content_sha256(operation):
        raise ValueError("benchmark dispatch operation ref is stale (content SHA mismatch)")
    return operation


def _identity_ref(value: object, name: str) -> dict[str, str]:
    ref = _closed(value, {"id", "content_sha256"}, name)
    ref["id"] = _text(ref["id"], f"{name} id")
    _sha(ref["content_sha256"], f"{name} SHA")
    return ref


def _content_ref(value: object, name: str) -> dict[str, str]:
    ref = _closed(value, {"content_sha256"}, name)
    _sha(ref["content_sha256"], f"{name} SHA")
    return ref


def _receipt_ref(value: object, name: str) -> dict[str, str]:
    ref = _closed(value, {"provider", "content_sha256"}, name)
    ref["provider"] = _provider(ref["provider"])
    _sha(ref["content_sha256"], f"{name} SHA")
    return ref


def _process_identity(value: object) -> dict[str, int]:
    identity = _closed(value, {"pid", "create_time_ns"}, "process identity")
    if any(
        isinstance(item, bool) or not isinstance(item, int) or item <= 0
        for item in identity.values()
    ):
        raise ValueError("process identity is invalid")
    return {"pid": identity["pid"], "create_time_ns": identity["create_time_ns"]}


def _provider(value: object) -> str:
    if not isinstance(value, str) or value not in _PROVIDERS:
        raise ValueError("benchmark dispatch provider is invalid")
    return value


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an object")
    return deepcopy(dict(value))


def _closed(value: object, fields: set[str], name: str) -> dict[str, Any]:
    candidate = _mapping(value, name)
    if set(candidate) != fields:
        raise ValueError(f"{name} is not closed")
    return candidate


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{name} is invalid")
    return value


def _sha(value: object, name: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{name} is invalid")
    return value


__all__ = [
    "attest_benchmark_provider_dispatch",
    "attest_managed_model_dispatch",
    "compose_benchmark_dispatch_context",
    "compose_benchmark_provider_runtime_identity",
    "current_benchmark_dispatch_context",
    "current_benchmark_dispatch_receipt_refs",
    "install_benchmark_dispatch_attestor",
    "project_authoritative_benchmark_provider_cleanup",
    "read_latest_benchmark_dispatch_receipt",
    "validate_benchmark_dispatch_receipt_refs",
    "validate_benchmark_dispatch_context",
    "validate_benchmark_provider_runtime_identity",
]
