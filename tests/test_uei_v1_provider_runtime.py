from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from threading import Barrier, Event, Thread

import pytest
from PIL import Image

from app.learn.recognition.uei.canonical import seal_immutable
from app.learn.recognition.uei.contracts import UEIOuterBoundaryError, UEIValidationError, validate_contract
from app.learn.recognition.uei.store import UEIObjectStore


PROVIDER_ID = "local.test/provider"
PROFILE_ID = "local.test/provider/shadow"
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360f8cfc0000003010100c9fe92ef0000000049454e44ae426082"
)


class FakeAdapter:
    provider_id = PROVIDER_ID
    profile_id = PROFILE_ID
    provider_version = "test-1"

    def __init__(self, *, fail: bool = False, started: Event | None = None, release: Event | None = None,
                 output=None, provider_version: str = "test-1") -> None:
        self.provider_version = provider_version
        self.calls = 0
        self.last_budget = None
        self.fail = fail
        self.started = started
        self.release = release
        self.output = output

    def invoke(self, *, capture, budget, invocation_id, cancellation_event=None):
        from app.learn.recognition.uei.provider_adapters import (
            NormalizedProviderItem,
            NormalizedScreenParseOutput,
        )

        self.calls += 1
        self.last_budget = budget
        self.last_cancellation_event = cancellation_event
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            assert self.release.wait(timeout=3)
        if self.fail:
            raise RuntimeError("not persisted")
        if self.output is not None:
            return self.output
        return NormalizedScreenParseOutput(
            items=(NormalizedProviderItem(
                source_item_id="provider-item-1", kind="text", safe_text="visible label",
                source_bbox=(1, 2, 3, 4), source_coordinate_space="capture_pixel_xyxy",
                provider_confidence=0.9,
            ),),
            duration_ms=7,
            resource_units=1,
        )


def _put(store: UEIObjectStore, value: dict[str, object]) -> dict[str, str]:
    return store.put(seal_immutable(value))


def _context(tmp_path: Path, *, mode: str = "Shadow", enabled: bool = True,
             egress_policy: str = "local_only", safe_payload_limits: dict[str, object] | None = None,
             provider_version: str = "test-1", identity_suffix: str = "test") -> tuple[UEIObjectStore, dict[str, str], object]:
    from app.learn.recognition.uei.provider_adapters import RestrictedCaptureLease

    store = UEIObjectStore(root=tmp_path / "objects")
    image = tmp_path / "private.png"
    Image.new("RGB", (1, 1), color=(1, 2, 3)).save(image)
    image_bytes = image.read_bytes()
    artifact_sha = sha256(image_bytes).hexdigest()
    artifact_ref = _put(store, {
        "contract_version": "artifact_ref_v1", "artifact_id": "artifact/test", "artifact_sha256": artifact_sha,
        "media_type": "image/png", "byte_length": len(image_bytes), "restricted": True,
    })
    lineage_ref = _put(store, {
        "contract_version": "capture_lineage_v1", "capture_id": "capture/test", "artifact_ref": artifact_ref,
        "artifact_sha256": artifact_sha, "image_size": {"width": 1, "height": 1},
        "capture_coordinate_space": "capture_pixel_xyxy", "captured_at": "2026-08-21T00:00:00Z",
    })
    request_ref = _put(store, {
        "contract_version": "screen_parse_request_v1", "request_id": "request/test",
        "capture_lineage_ref": lineage_ref,
        "requested_profiles": [{"provider_id": PROVIDER_ID, "profile_id": PROFILE_ID, "mode": mode}],
        "privacy_policy": "restricted", "requester_id": "server",
    })
    registration_ref = _put(store, {
        "contract_version": "trusted_provider_registration_v1", "registration_id": f"registration/{identity_suffix}",
        "provider_id": PROVIDER_ID, "profile_ids": [PROFILE_ID], "enabled": enabled,
        "allowed_modes": ["Shadow"], "allowed_privacy_policies": ["restricted"],
        "egress_policy": egress_policy, "wire_payload_policy": "restricted_store_only",
        "safe_payload_limits": safe_payload_limits or {"max_json_bytes": 1024, "max_depth": 4, "max_array_items": 10,
                                "max_object_properties": 10, "max_string_chars": 128,
                                "allowed_json_types": ["object", "array", "string", "number", "boolean", "null"]},
        "required_conformance_suite": "uei-v1-static-projection",
    })
    manifest_ref = _put(store, {
        "contract_version": "provider_manifest_v1", "manifest_id": f"manifest/{identity_suffix}", "provider_id": PROVIDER_ID,
        "provider_version": provider_version, "profiles": [{"profile_id": PROFILE_ID, "operation": "screen_parse",
            "input_contract": "screen_parse_request_v1", "output_contract": "provider_safe_result_v1",
            "declared_output_kinds": ["text"], "supported_coordinate_spaces": ["capture_pixel_xyxy"],
            "supports_capture_artifact": True, "privacy_capabilities": ["restricted"], "mode_allowlist": ["Shadow"]}],
    })
    lease = RestrictedCaptureLease(
        request_ref=request_ref, capture_lineage_ref=lineage_ref, artifact_ref=artifact_ref, capture_id="capture/test",
        artifact_sha256=artifact_sha, image_size={"width": 1, "height": 1}, local_path=image,
    )
    return store, request_ref, (registration_ref, manifest_ref, lease)


def _runtime(store: UEIObjectStore, registration_ref: dict[str, str], manifest_ref: dict[str, str], adapter: FakeAdapter,
             budget=None):
    from app.learn.recognition.uei.provider_adapters import ProviderRunBudget, TrustedProviderAdapterRegistry
    from app.learn.recognition.uei.provider_runtime import ShadowProviderRuntime

    return ShadowProviderRuntime(
        store=store, registry=TrustedProviderAdapterRegistry([adapter]),
        trusted_profiles={(PROVIDER_ID, PROFILE_ID): (registration_ref, manifest_ref)},
        budget=budget or ProviderRunBudget(timeout_ms=100, max_output_bytes=1024, max_element_count=10,
                                          max_string_length=128, resource_group="test"),
    )


def test_receipt_is_closed_jcs_sealed_and_private(tmp_path: Path):
    store, request_ref, (registration_ref, manifest_ref, lease) = _context(tmp_path)
    reply = _runtime(store, registration_ref, manifest_ref, FakeAdapter()).invoke(
        request_ref=request_ref, capture_lease=lease,
    )

    receipt = store.get(reply["receipt_ref"], contract_version="provider_runtime_receipt_v1")
    validate_contract(receipt, "provider_runtime_receipt_v1")
    assert receipt["status"] == "succeeded" and receipt["mode"] == "Shadow"
    assert set(receipt) == {"contract_version", "receipt_id", "request_ref", "capture_lineage_ref", "artifact_ref",
                            "provider_id", "profile_id", "mode", "status", "reason_class", "retryable",
                            "metrics", "result_ref", "cleanup_status", "content_sha256"}
    assert "private.png" not in str(receipt)


def test_only_server_trusted_shadow_local_profile_can_invoke(tmp_path: Path):
    store, request_ref, (registration_ref, manifest_ref, lease) = _context(tmp_path, mode="Primary")
    adapter = FakeAdapter()
    reply = _runtime(store, registration_ref, manifest_ref, adapter).invoke(request_ref=request_ref, capture_lease=lease)
    receipt = store.get(reply["receipt_ref"], contract_version="provider_runtime_receipt_v1")
    assert receipt["status"] == "rejected" and receipt["reason_class"] == "policy_rejected"
    assert adapter.calls == 0


@pytest.mark.parametrize("mutation", [
    lambda lease: replace(lease, artifact_sha256="b" * 64),
    lambda lease: replace(lease, image_size={"width": 1, "height": 30}),
    lambda lease: replace(lease, capture_id="capture/other"),
])
def test_capture_lease_identity_mismatch_rejects_before_adapter(tmp_path: Path, mutation):
    store, request_ref, (registration_ref, manifest_ref, lease) = _context(tmp_path)
    adapter = FakeAdapter()
    with pytest.raises(UEIOuterBoundaryError):
        _runtime(store, registration_ref, manifest_ref, adapter).invoke(
            request_ref=request_ref, capture_lease=mutation(lease),
        )
    assert adapter.calls == 0



def test_runtime_propagates_internal_cancellation_event_without_result_contract_change(
    tmp_path: Path,
):
    store, request_ref, (registration_ref, manifest_ref, lease) = _context(tmp_path)
    adapter = FakeAdapter()
    cancellation_event = Event()

    reply = _runtime(store, registration_ref, manifest_ref, adapter).invoke(
        request_ref=request_ref,
        capture_lease=lease,
        cancellation_event=cancellation_event,
    )

    assert adapter.last_cancellation_event is cancellation_event
    result = store.get(reply["result_ref"], contract_version="provider_safe_result_v1")
    assert result["contract_version"] == "provider_safe_result_v1"
    assert "cancellation_event" not in result

def test_success_persists_review_only_result_and_is_idempotent(tmp_path: Path):
    store, request_ref, (registration_ref, manifest_ref, lease) = _context(tmp_path)
    adapter = FakeAdapter()
    runtime = _runtime(store, registration_ref, manifest_ref, adapter)
    first = runtime.invoke(request_ref=request_ref, capture_lease=lease)
    second = runtime.invoke(request_ref=request_ref, capture_lease=lease)

    result = store.get(first["result_ref"], contract_version="provider_safe_result_v1")
    assert first == second and adapter.calls == 1
    assert result["status"] == "success" and result["review_only"] is True
    assert set(result["items"][0]) == {"source_item_id", "source_id_origin", "kind", "safe_text", "safe_role",
                                          "safe_states", "source_bbox", "capture_bbox", "source_coordinate_space",
                                          "coordinate_transform_ref", "opaque_attributes", "provider_confidence"}


def test_second_runtime_recovers_completed_claim_without_adapter_dispatch(tmp_path: Path):
    store, request_ref, (registration_ref, manifest_ref, lease) = _context(tmp_path)
    first_adapter, second_adapter = FakeAdapter(), FakeAdapter()
    first = _runtime(store, registration_ref, manifest_ref, first_adapter).invoke(
        request_ref=request_ref, capture_lease=lease,
    )
    recovered = _runtime(store, registration_ref, manifest_ref, second_adapter).invoke(
        request_ref=request_ref, capture_lease=lease,
    )

    assert recovered == first
    assert first_adapter.calls == 1 and second_adapter.calls == 0


def test_benchmark_request_recovers_sealed_reply_without_second_adapter_call(tmp_path: Path):
    version = "test-1+benchmark-cold1-warm3"
    store, request_ref, (registration_ref, manifest_ref, lease) = _context(tmp_path, provider_version=version)
    first_adapter, second_adapter = FakeAdapter(provider_version=version), FakeAdapter(provider_version=version)
    first = _runtime(store, registration_ref, manifest_ref, first_adapter).invoke(request_ref=request_ref, capture_lease=lease)
    recovered = _runtime(store, registration_ref, manifest_ref, second_adapter).invoke(request_ref=request_ref, capture_lease=lease)
    assert recovered == first and first_adapter.calls == 1 and second_adapter.calls == 0


def test_changed_provider_version_has_distinct_durable_invocation_identity(tmp_path: Path):
    first_version = "test-1"
    second_version = "test-1+benchmark-cold1-warm3"
    store, request_ref, (registration_ref, first_manifest_ref, lease) = _context(
        tmp_path, provider_version=first_version, identity_suffix="normal",
    )
    first_adapter = FakeAdapter(provider_version=first_version)
    first = _runtime(store, registration_ref, first_manifest_ref, first_adapter).invoke(
        request_ref=request_ref, capture_lease=lease,
    )

    second_manifest_ref = _put(store, {
        "contract_version": "provider_manifest_v1", "manifest_id": "manifest/benchmark",
        "provider_id": PROVIDER_ID, "provider_version": second_version,
        "profiles": [{"profile_id": PROFILE_ID, "operation": "screen_parse",
            "input_contract": "screen_parse_request_v1", "output_contract": "provider_safe_result_v1",
            "declared_output_kinds": ["text"], "supported_coordinate_spaces": ["capture_pixel_xyxy"],
            "supports_capture_artifact": True, "privacy_capabilities": ["restricted"],
            "mode_allowlist": ["Shadow"]}],
    })
    second_adapter = FakeAdapter(provider_version=second_version)
    second = _runtime(store, registration_ref, second_manifest_ref, second_adapter).invoke(
        request_ref=request_ref, capture_lease=lease,
    )

    assert first["invocation_id"] != second["invocation_id"]
    assert first_adapter.calls == 1 and second_adapter.calls == 1


def test_manifest_provider_version_mismatch_rejects_before_adapter_dispatch(tmp_path: Path):
    store, request_ref, (registration_ref, manifest_ref, lease) = _context(
        tmp_path, provider_version="test-2",
    )
    adapter = FakeAdapter(provider_version="test-1")

    reply = _runtime(store, registration_ref, manifest_ref, adapter).invoke(
        request_ref=request_ref, capture_lease=lease,
    )

    receipt = store.get(reply["receipt_ref"], contract_version="provider_runtime_receipt_v1")
    assert receipt["status"] == "rejected" and receipt["reason_class"] == "policy_rejected"
    assert adapter.calls == 0


def test_two_runtime_instances_claim_once_and_orphan_claim_fails_closed(tmp_path: Path):
    store, request_ref, (registration_ref, manifest_ref, lease) = _context(tmp_path)
    started, release = Event(), Event()
    first_adapter, second_adapter = FakeAdapter(started=started, release=release), FakeAdapter()
    first_runtime = _runtime(store, registration_ref, manifest_ref, first_adapter)
    second_runtime = _runtime(store, registration_ref, manifest_ref, second_adapter)
    errors: list[BaseException] = []

    thread = Thread(target=lambda: first_runtime.invoke(request_ref=request_ref, capture_lease=lease))
    thread.start()
    assert started.wait(timeout=3)
    try:
        with pytest.raises(UEIOuterBoundaryError):
            second_runtime.invoke(request_ref=request_ref, capture_lease=lease)
    finally:
        release.set()
        thread.join(timeout=3)
    assert not errors and first_adapter.calls == 1 and second_adapter.calls == 0

    claim_root = store.root / ".shadow-runtime-claims"
    for claim in claim_root.glob("*.json"):
        claim.write_text('{"state":"in_progress"}', encoding="utf-8")
    with pytest.raises(UEIOuterBoundaryError):
        _runtime(store, registration_ref, manifest_ref, FakeAdapter()).invoke(request_ref=request_ref, capture_lease=lease)


def test_post_precondition_failure_persists_error_result_then_receipt(tmp_path: Path):
    store, request_ref, (registration_ref, manifest_ref, lease) = _context(tmp_path)
    reply = _runtime(store, registration_ref, manifest_ref, FakeAdapter(fail=True)).invoke(
        request_ref=request_ref, capture_lease=lease,
    )

    assert store.write_order[-3:] == ("provider_error_v1", "provider_safe_result_v1", "provider_runtime_receipt_v1")
    assert reply["error_ref"] is not None
    result = store.get(reply["result_ref"], contract_version="provider_safe_result_v1")
    assert result["status"] == "failed" and result["review_only"] is True and result["items"] == []


def test_runtime_centrally_redacts_generic_credential_text_and_typed_rejects(tmp_path: Path):
    from app.learn.recognition.uei.provider_adapters import AdapterFailure, NormalizedProviderItem, NormalizedScreenParseOutput

    store, request_ref, (registration_ref, manifest_ref, lease) = _context(tmp_path)
    output = NormalizedScreenParseOutput(items=(NormalizedProviderItem(
        source_item_id="item/secret", kind="text", safe_text="Authorization: Bearer private-value",
        source_bbox=(0, 0, 1, 1), source_coordinate_space="capture_pixel_xyxy",
    ),), duration_ms=3, resource_units=1)
    reply = _runtime(store, registration_ref, manifest_ref, FakeAdapter(output=output)).invoke(
        request_ref=request_ref, capture_lease=lease,
    )
    result = store.get(reply["result_ref"], contract_version="provider_safe_result_v1")
    assert result["items"][0]["safe_text"] == "[redacted]"
    assert result["redaction_summary"] == {"redacted_item_count": 1, "redacted_field_count": 1,
                                           "secret_detected": True, "sensitive_categories": ["credential"]}

    class RejectingAdapter(FakeAdapter):
        def invoke(self, **kwargs):
            raise AdapterFailure(disposition="rejected", reason_class="resource_rejected", retryable=True,
                                 cleanup_status="not_required")

    store, request_ref, (registration_ref, manifest_ref, lease) = _context(tmp_path / "rejected")
    reply = _runtime(store, registration_ref, manifest_ref, RejectingAdapter()).invoke(
        request_ref=request_ref, capture_lease=lease,
    )
    receipt = store.get(reply["receipt_ref"], contract_version="provider_runtime_receipt_v1")
    assert reply["result_ref"] is None and receipt["reason_class"] == "resource_rejected" and receipt["retryable"] is True


@pytest.mark.parametrize("secret", [
    r"C:\Users\Alice\secret.txt",
    "alice@example.com",
    "AKIAIOSFODNN7EXAMPLE",
    "eyJhbGciOiJIUzI1NiJ9.payload.signature",
    "-----BEGIN PRIVATE KEY-----",
])
def test_runtime_redacts_common_private_path_and_credential_shapes(tmp_path: Path, secret: str):
    from app.learn.recognition.uei.provider_adapters import NormalizedProviderItem, NormalizedScreenParseOutput

    store, request_ref, (registration_ref, manifest_ref, lease) = _context(tmp_path)
    output = NormalizedScreenParseOutput(items=(NormalizedProviderItem(
        source_item_id="item/secret", kind="text", safe_text=secret,
        source_bbox=(0, 0, 1, 1), source_coordinate_space="capture_pixel_xyxy",
    ),), duration_ms=1, resource_units=0)

    reply = _runtime(store, registration_ref, manifest_ref, FakeAdapter(output=output)).invoke(
        request_ref=request_ref, capture_lease=lease,
    )
    result = store.get(reply["result_ref"], contract_version="provider_safe_result_v1")

    assert result["items"][0]["safe_text"] == "[redacted]"
    assert secret not in json.dumps(result)


def test_concurrent_same_invocation_fails_closed_without_second_adapter_call(tmp_path: Path):
    store, request_ref, (registration_ref, manifest_ref, lease) = _context(tmp_path)
    started, release = Event(), Event()
    adapter = FakeAdapter(started=started, release=release)
    runtime = _runtime(store, registration_ref, manifest_ref, adapter)
    errors: list[BaseException] = []

    def invoke_once() -> None:
        try:
            runtime.invoke(request_ref=request_ref, capture_lease=lease)
        except BaseException as error:
            errors.append(error)

    thread = Thread(target=invoke_once)
    thread.start()
    assert started.wait(timeout=3)
    try:
        with pytest.raises(UEIOuterBoundaryError):
            runtime.invoke(request_ref=request_ref, capture_lease=lease)
    finally:
        release.set()
        thread.join(timeout=3)
    assert not errors and adapter.calls == 1


def test_clean_public_package_import_does_not_load_runtime_modules():
    import subprocess
    import sys

    process = subprocess.run([
        sys.executable, "-c",
        "import sys; import app.learn.recognition.uei; "
        "assert not any(name.endswith('provider_runtime') or name.endswith('provider_adapters') for name in sys.modules)",
    ], check=False, capture_output=True, text=True)
    assert process.returncode == 0, process.stderr


def test_runtime_intersects_constructor_budget_with_registration_limits(tmp_path: Path):
    from app.learn.recognition.uei.provider_adapters import ProviderRunBudget

    limits = {"max_json_bytes": 9, "max_depth": 4, "max_array_items": 2, "max_object_properties": 10,
              "max_string_chars": 7, "allowed_json_types": ["object", "array", "string", "number", "boolean", "null"]}
    store, request_ref, (registration_ref, manifest_ref, lease) = _context(tmp_path, safe_payload_limits=limits)
    adapter = FakeAdapter()
    runtime = _runtime(store, registration_ref, manifest_ref, adapter, ProviderRunBudget(
        timeout_ms=100, max_output_bytes=100, max_element_count=10, max_string_length=100, resource_group="test",
    ))

    runtime.invoke(request_ref=request_ref, capture_lease=lease)

    assert adapter.last_budget is not None
    assert (adapter.last_budget.max_output_bytes, adapter.last_budget.max_element_count,
            adapter.last_budget.max_string_length) == (9, 2, 7)
