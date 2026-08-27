"""Benchmark-v2 provider dispatch 的即时、非授权证明。"""

from __future__ import annotations

import json
import os
import re
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
_ACTIVE_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar(
    "benchmark_v2_dispatch_context", default=None
)
_ACTIVE_RECEIPTS: ContextVar[list[dict[str, str]] | None] = ContextVar(
    "benchmark_v2_dispatch_receipts", default=None
)
_JOURNAL_LOCK = RLock()


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
    if not journal.is_absolute() or journal != journal.resolve():
        raise ValueError("benchmark dispatch receipt journal path is not canonical")
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
    if not journal.is_absolute() or journal != journal.resolve():
        raise ValueError("benchmark dispatch receipt journal path is not canonical")
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
    runtime_ref = _content_ref(
        _attest_exact_provider_runtime(normalized_provider, runtime),
        "benchmark dispatch provider attestation",
    )
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
    _append_receipt(Path(context["receipt_journal_path"]), receipt)
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
    if not path.is_absolute() or path != path.resolve() or not path.is_file():
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
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = _validate_dispatch_receipt(json.loads(line))
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            raise ValueError("benchmark dispatch receipt journal is corrupt") from error
        digest = record["content_sha256"]
        if digest in records:
            raise ValueError("benchmark dispatch receipt journal has duplicate rows")
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
) -> dict[str, str]:
    if provider == "qwen":
        from app.core.model_server import _profile_for_qwen_model_lease

        profile = _profile_for_qwen_model_lease(deepcopy(dict(value)))
        return {"content_sha256": content_sha256(profile)}
    if provider == "vista":
        return _attest_vista_runtime(value)
    return _attest_scoped_process_runtime(value, expected_provider="omni")


def _attest_scoped_process_runtime(
    value: Mapping[str, object], *, expected_provider: str
) -> dict[str, str]:
    runtime = _mapping(value, "benchmark scoped provider runtime")
    if runtime.get("provider") != expected_provider:
        raise ValueError("benchmark scoped provider runtime provider mismatch")
    identity = _process_identity(runtime.get("process_identity"))
    scope_name = _text(runtime.get("scope_name"), "provider scope name")
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
    return {
        "content_sha256": content_sha256(
            {"provider": expected_provider, "process_identity": identity, "members": members}
        )
    }


def _attest_vista_runtime(value: Mapping[str, object]) -> dict[str, str]:
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
    return {
        "content_sha256": content_sha256(
            {
                "incarnation_id": lease.get("incarnation_id"),
                "profile": profile,
                "process_identities": identities,
                "members": members,
                "listener_pids": listener_pids,
            }
        )
    }


def _append_receipt(path: Path, receipt: Mapping[str, object]) -> None:
    raw = canonical_json_bytes(receipt) + b"\n"
    with _JOURNAL_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("ab", buffering=0) as stream:
            written = stream.write(raw)
            if written != len(raw):
                raise OSError("benchmark dispatch receipt short write")
            os.fsync(stream.fileno())


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
    "current_benchmark_dispatch_context",
    "current_benchmark_dispatch_receipt_refs",
    "install_benchmark_dispatch_attestor",
    "validate_benchmark_dispatch_receipt_refs",
    "validate_benchmark_dispatch_context",
]
