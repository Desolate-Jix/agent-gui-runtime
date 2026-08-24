"""针对单个权威 Hybrid capture 执行受信任的 Omni discovery。"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from threading import Event
from typing import Any

from app.learn.hybrid.capture import load_and_verify_hybrid_capture_bundle
from app.learn.hybrid.omni_candidates import (
    build_omni_candidate_ledger,
    omni_inventory_from_ledger,
)
from app.learn.recognition.uei.omniparser_shadow_adapter import (
    OmniParserShadowAdapter,
    PROFILE_ID,
    PROVIDER_ID,
    PROVIDER_VERSION,
)
from app.learn.recognition.uei.provider_adapters import (
    AdapterFailure,
    NormalizedScreenParseOutput,
    ProviderRunBudget,
    RestrictedCaptureLease,
    TrustedProviderAdapterRegistry,
)
from app.learn.recognition.uei.provider_runtime import ShadowProviderRuntime
from app.learn.recognition.uei.store import UEIObjectStore


_STORE_RELATIVE_PATH = Path("artifacts") / "uei-shadow-store"
_PAYLOAD_FIELDS = {
    "project_root",
    "run_id",
    "workflow_revision",
    "hybrid_capture_bundle_ref",
    "request_ref",
    "registration_ref",
    "manifest_ref",
    "capture_image_path",
}


def run_hybrid_omni_discovery(
    payload: dict[str, Any],
    *,
    cancellation_event: Event | None = None,
) -> dict[str, Any]:
    """调用受信任 Shadow runtime，并仅返回重新验证的安全输出。"""
    request = _validated_payload(payload)
    root = Path(request["project_root"]).resolve()
    image_path = _capture_path(root, request["capture_image_path"])
    bundle = load_and_verify_hybrid_capture_bundle(
        project_root=root,
        bundle_ref=deepcopy(request["hybrid_capture_bundle_ref"]),
        expected_run_id=request["run_id"],
        expected_workflow_revision=request["workflow_revision"],
    )
    bundle_ref = deepcopy(request["hybrid_capture_bundle_ref"])
    identity = bundle["capture_identity"]
    store = UEIObjectStore(root=root / _STORE_RELATIVE_PATH)
    try:
        provider_adapter = OmniParserShadowAdapter()
    except AdapterFailure as failure:
        provider_adapter = _BootstrapFailureAdapter(failure)
    adapter = _FailureCapturingAdapter(provider_adapter)
    runtime = ShadowProviderRuntime(
        store=store,
        registry=TrustedProviderAdapterRegistry([adapter]),
        trusted_profiles={
            (PROVIDER_ID, PROFILE_ID): (
                deepcopy(request["registration_ref"]),
                deepcopy(request["manifest_ref"]),
            )
        },
        budget=ProviderRunBudget(
            timeout_ms=120_000,
            max_output_bytes=4 * 1024 * 1024,
            max_element_count=4096,
            max_string_length=4096,
            resource_group="hybrid_omniparser_v2",
        ),
    )
    reply = runtime.invoke(
        request_ref=deepcopy(request["request_ref"]),
        capture_lease=RestrictedCaptureLease(
            request_ref=deepcopy(request["request_ref"]),
            capture_lineage_ref=deepcopy(identity["capture_lineage_ref"]),
            artifact_ref=deepcopy(identity["artifact_ref"]),
            capture_id=identity["capture_id"],
            artifact_sha256=identity["artifact_sha256"],
            image_size=deepcopy(identity["image_size"]),
            local_path=image_path,
        ),
        cancellation_event=cancellation_event,
    )
    receipt_ref = _ref(reply.get("receipt_ref"), name="provider receipt ref")
    receipt = store.get(receipt_ref, contract_version="provider_runtime_receipt_v1")
    claim_status = reply.get("claim_status")
    if claim_status not in {"not_created", "complete"}:
        raise ValueError("provider claim status is invalid")
    metrics = receipt.get("metrics")
    duration_ms = metrics.get("duration_ms") if isinstance(metrics, dict) else 0
    result_ref_value = reply.get("result_ref")
    if result_ref_value is None or receipt.get("status") != "succeeded":
        result_ref = (
            _ref(result_ref_value, name="provider result ref")
            if result_ref_value is not None
            else None
        )
        if result_ref is not None:
            store.get(result_ref, contract_version="provider_safe_result_v1")
        error_ref_value = reply.get("error_ref")
        error_ref = (
            _ref(error_ref_value, name="provider error ref")
            if error_ref_value is not None
            else None
        )
        if error_ref is not None:
            store.get(error_ref, contract_version="provider_error_v1")
        return {
            "contract_version": "hybrid_omni_discovery_result_v1",
            "outcome": "failed",
            "hybrid_capture_bundle_ref": bundle_ref,
            "provider_result_ref": result_ref,
            "provider_error_ref": error_ref,
            "provider_receipt_ref": receipt_ref,
            "provider_invocation_id": reply["invocation_id"],
            "provider_claim_status": claim_status,
            "provider_status": receipt["status"],
            "provider_reason_class": receipt["reason_class"],
            "failure_reason": adapter.failure_code,
            "inventory": None,
            "omni_candidate_ledger": None,
            "duration_ms": duration_ms,
            "cleanup_status": receipt["cleanup_status"],
        }
    result_ref = _ref(result_ref_value, name="provider result ref")
    safe_result = store.get(result_ref, contract_version="provider_safe_result_v1")
    ledger = build_omni_candidate_ledger(
        safe_result=safe_result,
        capture_bundle={**bundle, "bundle_ref": bundle_ref},
    )
    inventory = omni_inventory_from_ledger(ledger)
    return {
        "contract_version": "hybrid_omni_discovery_result_v1",
        "outcome": "completed",
        "hybrid_capture_bundle_ref": bundle_ref,
        "provider_result_ref": result_ref,
        "provider_error_ref": None,
        "provider_receipt_ref": receipt_ref,
        "provider_invocation_id": reply["invocation_id"],
        "provider_claim_status": claim_status,
        "provider_status": receipt["status"],
        "provider_reason_class": receipt["reason_class"],
        "inventory": inventory,
        "omni_candidate_ledger": ledger,
        "duration_ms": duration_ms,
        "cleanup_status": receipt["cleanup_status"],
    }


def _validated_payload(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _PAYLOAD_FIELDS:
        raise ValueError("hybrid Omni discovery payload is not closed")
    payload = deepcopy(dict(value))
    if not isinstance(payload["project_root"], str) or not payload["project_root"].strip():
        raise ValueError("project_root is invalid")
    if not isinstance(payload["run_id"], str) or not payload["run_id"].strip():
        raise ValueError("run_id is invalid")
    revision = payload["workflow_revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("workflow_revision is invalid")
    for name in ("hybrid_capture_bundle_ref", "request_ref", "registration_ref", "manifest_ref"):
        payload[name] = _ref(payload[name], name=name)
    if not isinstance(payload["capture_image_path"], str) or not payload["capture_image_path"].strip():
        raise ValueError("capture_image_path is invalid")
    return payload


def _capture_path(root: Path, value: str) -> Path:
    candidate = Path(value)
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise ValueError("capture_image_path escapes project_root") from None
    if not resolved.is_file():
        raise ValueError("capture_image_path is not a file")
    return resolved


def _ref(value: object, *, name: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"id", "content_sha256"}:
        raise ValueError(f"{name} is invalid")
    identifier = value.get("id")
    digest = value.get("content_sha256")
    if (
        not isinstance(identifier, str)
        or not identifier
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ValueError(f"{name} is invalid")
    return {"id": identifier, "content_sha256": digest}


class _BootstrapFailureAdapter:
    provider_id = PROVIDER_ID
    profile_id = PROFILE_ID
    provider_version = PROVIDER_VERSION

    def __init__(self, failure: AdapterFailure) -> None:
        self._failure = failure

    def invoke(
        self,
        *,
        capture: RestrictedCaptureLease,
        budget: ProviderRunBudget,
        invocation_id: str,
        cancellation_event: Event | None = None,
    ) -> NormalizedScreenParseOutput:
        del capture, budget, invocation_id, cancellation_event
        raise self._failure


class _FailureCapturingAdapter:
    """保留适配器安全故障码，避免扩展公开 UEI 枚举。"""

    def __init__(self, adapter: object) -> None:
        self._adapter = adapter
        self.provider_id = getattr(adapter, "provider_id")
        self.profile_id = getattr(adapter, "profile_id")
        self.provider_version = getattr(adapter, "provider_version")
        self.failure_code: str | None = None

    def invoke(self, **kwargs: Any) -> NormalizedScreenParseOutput:
        try:
            return self._adapter.invoke(**kwargs)
        except AdapterFailure as failure:
            code = getattr(failure, "code", None)
            self.failure_code = code if isinstance(code, str) else failure.reason_class
            raise
