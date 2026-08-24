from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from threading import Event

import pytest

from app.learn.recognition.uei.canonical import seal_immutable
from app.learn.recognition.uei.contracts import UEIOuterBoundaryError
from app.learn.recognition.uei.provider_adapters import (
    NormalizedProviderItem,
    NormalizedScreenParseOutput,
)
from app.learn.recognition.uei.store import UEIObjectStore
from tests.test_learn_hybrid_capture import _context, _identity, _window


PROVIDER_ID = "local.runtime/omniparser"
PROFILE_ID = "local.runtime/omniparser/shadow-v2"
PROVIDER_VERSION = "v2.0.1"


class _RecordedAdapter:
    provider_id = PROVIDER_ID
    profile_id = PROFILE_ID
    provider_version = PROVIDER_VERSION

    def __init__(self) -> None:
        self.calls = 0
        self.cancellation_events: list[object] = []

    def invoke(self, *, capture, budget, invocation_id, cancellation_event=None):
        del capture, budget, invocation_id
        self.calls += 1
        self.cancellation_events.append(cancellation_event)
        return NormalizedScreenParseOutput(
            items=(
                NormalizedProviderItem(
                    source_item_id="omni/first",
                    kind="element",
                    safe_text="Quick Apply",
                    safe_role="button",
                    safe_states=(),
                    source_bbox=(40, 20, 120, 52),
                    source_coordinate_space="capture_pixel_xyxy",
                    provider_confidence=0.91,
                ),
                NormalizedProviderItem(
                    source_item_id="omni/disabled",
                    kind="icon",
                    safe_text=None,
                    safe_role=None,
                    safe_states=("disabled",),
                    source_bbox=(4, 5, 18, 19),
                    source_coordinate_space="capture_pixel_xyxy",
                    provider_confidence=0.03,
                ),
            ),
            duration_ms=9,
            resource_units=2,
        )


def _put(store: UEIObjectStore, value: dict[str, object]) -> dict[str, str]:
    return store.put(seal_immutable(value))


def _facts(tmp_path: Path) -> dict[str, object]:
    from app.learn.hybrid.capture import seal_hybrid_capture_bundle

    image, identity = _identity(
        tmp_path,
        run_id="run-omni",
        revision=7,
        name="omni.png",
        size=(160, 90),
    )
    bundle = seal_hybrid_capture_bundle(
        project_root=tmp_path,
        image_path=image,
        run_id="run-omni",
        workflow_revision=7,
        window_binding=_window(),
        ocr_uia_context=_context(
            tmp_path,
            identity,
            run_id="run-omni",
            revision=7,
        ),
        capture_envelope=identity.capture_envelope,
    )
    store = UEIObjectStore(root=tmp_path / "artifacts" / "uei-shadow-store")
    request_ref = _put(
        store,
        {
            "contract_version": "screen_parse_request_v1",
            "request_id": "request/hybrid-omni",
            "capture_lineage_ref": deepcopy(bundle["capture_lineage_ref"]),
            "requested_profiles": [
                {
                    "provider_id": PROVIDER_ID,
                    "profile_id": PROFILE_ID,
                    "mode": "Shadow",
                }
            ],
            "privacy_policy": "restricted",
            "requester_id": "server",
        },
    )
    registration_ref = _put(
        store,
        {
            "contract_version": "trusted_provider_registration_v1",
            "registration_id": "registration/hybrid-omni",
            "provider_id": PROVIDER_ID,
            "profile_ids": [PROFILE_ID],
            "enabled": True,
            "allowed_modes": ["Shadow"],
            "allowed_privacy_policies": ["restricted"],
            "egress_policy": "local_only",
            "wire_payload_policy": "restricted_store_only",
            "safe_payload_limits": {
                "max_json_bytes": 4096,
                "max_depth": 8,
                "max_array_items": 16,
                "max_object_properties": 32,
                "max_string_chars": 256,
                "allowed_json_types": [
                    "object",
                    "array",
                    "string",
                    "number",
                    "boolean",
                    "null",
                ],
            },
            "required_conformance_suite": "uei-v1-static-projection",
        },
    )
    manifest_ref = _put(
        store,
        {
            "contract_version": "provider_manifest_v1",
            "manifest_id": "manifest/hybrid-omni",
            "provider_id": PROVIDER_ID,
            "provider_version": PROVIDER_VERSION,
            "profiles": [
                {
                    "profile_id": PROFILE_ID,
                    "operation": "screen_parse",
                    "input_contract": "screen_parse_request_v1",
                    "output_contract": "provider_safe_result_v1",
                    "declared_output_kinds": ["element", "icon"],
                    "supported_coordinate_spaces": ["capture_pixel_xyxy"],
                    "supports_capture_artifact": True,
                    "privacy_capabilities": ["restricted"],
                    "mode_allowlist": ["Shadow"],
                }
            ],
        },
    )
    payload = {
        "project_root": str(tmp_path),
        "run_id": "run-omni",
        "workflow_revision": 7,
        "hybrid_capture_bundle_ref": deepcopy(bundle["bundle_ref"]),
        "request_ref": request_ref,
        "registration_ref": registration_ref,
        "manifest_ref": manifest_ref,
        "capture_image_path": image.relative_to(tmp_path).as_posix(),
    }
    return {"image": image, "bundle": bundle, "store": store, "payload": payload}


def test_managed_discovery_preserves_order_bbox_and_inactive_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import omni_discovery

    facts = _facts(tmp_path)
    adapter = _RecordedAdapter()
    monkeypatch.setattr(omni_discovery, "OmniParserShadowAdapter", lambda: adapter)
    cancellation_event = Event()

    result = omni_discovery.run_hybrid_omni_discovery(
        deepcopy(facts["payload"]),
        cancellation_event=cancellation_event,
    )

    inventory = result["inventory"]
    assert result["outcome"] == "completed"
    assert inventory["contract_version"] == "hybrid_omni_inventory_v1"
    assert [item["source_item_id"] for item in inventory["candidates"]] == [
        "omni/first",
        "omni/disabled",
    ]
    assert inventory["candidates"][0]["bbox_original"] == [40, 20, 120, 52]
    assert inventory["candidates"][1]["bbox_original"] == [4, 5, 18, 19]
    assert inventory["candidates"][1]["active"] is False
    assert inventory["candidates"][1]["inactive_reason"]
    assert len(inventory["candidates"]) == 2
    assert result["provider_result_ref"] == inventory["provider_result_ref"]
    assert result["provider_receipt_ref"]["id"].startswith("receipt/")
    assert result["duration_ms"] == 9
    assert result["cleanup_status"] == "clean"
    assert result["omni_candidate_ledger"]["contract_version"] == "hybrid_omni_candidate_ledger_v1"
    assert adapter.calls == 1
    assert adapter.cancellation_events == [cancellation_event]


def test_discovery_rejects_exact_capture_mismatch_before_adapter_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from PIL import Image
    from app.learn.hybrid import omni_discovery

    facts = _facts(tmp_path)
    adapter = _RecordedAdapter()
    monkeypatch.setattr(omni_discovery, "OmniParserShadowAdapter", lambda: adapter)
    mismatch = tmp_path / "mismatch.png"
    Image.new("RGB", (160, 90), color=(99, 1, 2)).save(mismatch)
    payload = deepcopy(facts["payload"])
    payload["capture_image_path"] = mismatch.relative_to(tmp_path).as_posix()

    with pytest.raises(UEIOuterBoundaryError):
        omni_discovery.run_hybrid_omni_discovery(payload)

    assert adapter.calls == 0


def test_discovery_recovers_completed_provider_claim_without_rerun(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import omni_discovery

    facts = _facts(tmp_path)
    adapter = _RecordedAdapter()
    monkeypatch.setattr(omni_discovery, "OmniParserShadowAdapter", lambda: adapter)

    first = omni_discovery.run_hybrid_omni_discovery(deepcopy(facts["payload"]))
    second = omni_discovery.run_hybrid_omni_discovery(deepcopy(facts["payload"]))

    assert second == first
    assert adapter.calls == 1


def test_non_shadow_rejection_reports_claim_not_created(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import omni_discovery

    facts = _facts(tmp_path)
    store = facts["store"]
    payload = deepcopy(facts["payload"])
    request = store.get(
        payload["request_ref"],
        contract_version="screen_parse_request_v1",
    )
    request.pop("content_sha256")
    request["requested_profiles"][0]["mode"] = "Primary"
    payload["request_ref"] = _put(store, request)
    adapter = _RecordedAdapter()
    monkeypatch.setattr(omni_discovery, "OmniParserShadowAdapter", lambda: adapter)

    result = omni_discovery.run_hybrid_omni_discovery(payload)

    assert result["outcome"] == "failed"
    assert result["provider_claim_status"] == "not_created"
    assert adapter.calls == 0
    claim_root = store.root / ".shadow-runtime-claims"
    assert not claim_root.exists() or list(claim_root.glob("*.json")) == []


def test_adapter_manifest_mismatch_reports_claim_not_created(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import omni_discovery

    facts = _facts(tmp_path)
    store = facts["store"]
    payload = deepcopy(facts["payload"])
    manifest = store.get(
        payload["manifest_ref"],
        contract_version="provider_manifest_v1",
    )
    manifest.pop("content_sha256")
    manifest["provider_version"] = "v9.9.9"
    payload["manifest_ref"] = _put(store, manifest)
    adapter = _RecordedAdapter()
    monkeypatch.setattr(omni_discovery, "OmniParserShadowAdapter", lambda: adapter)

    result = omni_discovery.run_hybrid_omni_discovery(payload)

    assert result["outcome"] == "failed"
    assert result["provider_claim_status"] == "not_created"
    assert adapter.calls == 0
    claim_root = store.root / ".shadow-runtime-claims"
    assert not claim_root.exists() or list(claim_root.glob("*.json")) == []


def test_adapter_bootstrap_failure_is_persisted_as_provider_safe_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import omni_discovery
    from app.learn import workflow_worker
    from app.learn.workflow_tasks import hybrid_omni
    from app.learn.recognition.uei.omniparser_shadow_adapter import (
        OmniParserShadowAdapterError,
    )

    facts = _facts(tmp_path)

    def unavailable_adapter():
        raise OmniParserShadowAdapterError("runtime_configuration_unavailable")

    monkeypatch.setattr(omni_discovery, "OmniParserShadowAdapter", unavailable_adapter)
    monkeypatch.setattr(hybrid_omni, "_PROJECT_ROOT", tmp_path)
    payload = deepcopy(facts["payload"])
    payload.pop("project_root")
    result = workflow_worker.execute_learning_stage_worker_task(
        "panel_learning_hybrid_omni_discovery",
        payload,
    )

    assert result["outcome"] == "failed"
    assert result["provider_result_ref"] is not None
    assert result["provider_error_ref"] is not None
    assert result["provider_reason_class"] == "runtime_provider_failed"
    assert result["failure_reason"] == "runtime_configuration_unavailable"
    assert result["cleanup_status"] == "not_required"
    assert result["provider_claim_status"] == "complete"
    stored = facts["store"].get(
        result["provider_result_ref"],
        contract_version="provider_safe_result_v1",
    )
    assert stored["status"] == "failed"
