from __future__ import annotations

from copy import deepcopy
import json
from hashlib import sha256
from pathlib import Path

import pytest

from app.learn.hybrid.contracts import stable_candidate_id, validate_omni_inventory
from app.learn.recognition.uei.canonical import seal_immutable
from app.learn.recognition.uei.contracts import UEIValidationError
from app.learn.recognition.uei.provider_adapters import (
    ProviderRunBudget,
    RestrictedCaptureLease,
)
from app.learn.recognition.uei.provider_capabilities import (
    AUTHORITY_SHAPED_KEYS,
    CandidateDiscoveryItemV1,
    CandidateDiscoveryRequestV1,
    CandidateDiscoveryResultV1,
    GroundingRefinementRequestV1,
    GroundingRefinementResultV1,
    ProviderInvocationEnvelopeV1,
    SemanticBindingItemV1,
    SemanticBindingRequestV1,
    SemanticBindingResultV1,
    deterministic_neutral_source_item_id,
    effective_provider_budget,
    reject_authority_shaped_payload,
)


BUNDLE_REF = {"id": "bundle/local.omni", "content_sha256": "1" * 64}
LINEAGE_REF = {"id": "capture/test", "content_sha256": "2" * 64}
ARTIFACT_REF = {"id": "artifact/capture", "content_sha256": "3" * 64}


def budget() -> ProviderRunBudget:
    return ProviderRunBudget(30_000, 65_536, 256, 4_096, "gpu_vision")


def envelope(capability: str) -> ProviderInvocationEnvelopeV1:
    return ProviderInvocationEnvelopeV1(
        bundle_ref=dict(BUNDLE_REF),
        capability=capability,
        invocation_id="invocation/test",
        capture_lineage_ref=dict(LINEAGE_REF),
        budget=budget(),
    )


def capture() -> RestrictedCaptureLease:
    return RestrictedCaptureLease(
        request_ref={"id": "request/test", "content_sha256": "4" * 64},
        capture_lineage_ref=dict(LINEAGE_REF),
        artifact_ref=dict(ARTIFACT_REF),
        capture_id="capture/test",
        artifact_sha256="3" * 64,
        image_size={"width": 100, "height": 100},
        local_path=Path("capture.png"),
    )


def discovery_result_fixture() -> dict[str, object]:
    return {
        "bundle_ref": dict(BUNDLE_REF),
        "invocation_id": "invocation/test",
        "capture_lineage_ref": dict(LINEAGE_REF),
        "items": [],
    }


def semantic_result_fixture() -> dict[str, object]:
    return {
        "bundle_ref": dict(BUNDLE_REF),
        "invocation_id": "invocation/test",
        "capture_lineage_ref": dict(LINEAGE_REF),
        "bindings": [],
    }


def grounding_result_fixture() -> dict[str, object]:
    return {
        "bundle_ref": dict(BUNDLE_REF),
        "invocation_id": "invocation/test",
        "capture_lineage_ref": dict(LINEAGE_REF),
        "candidate_id": "candidate/one",
    }


@pytest.mark.parametrize("factory", [
    discovery_result_fixture,
    semantic_result_fixture,
    grounding_result_fixture,
])
@pytest.mark.parametrize("key", sorted(AUTHORITY_SHAPED_KEYS))
def test_capability_results_recursively_reject_authority_shaped_keys(factory, key):
    value = factory()
    value["provider_payload"] = {"nested": [{key: True}]}
    with pytest.raises(UEIValidationError, match="non_authorizing"):
        reject_authority_shaped_payload(value)


def test_budget_intersection_uses_the_strictest_limit_and_exact_resource_group():
    caller = ProviderRunBudget(30_000, 65_536, 256, 4_096, "gpu_vision")
    bundle = ProviderRunBudget(20_000, 32_768, 128, 2_048, "gpu_vision")
    assert effective_provider_budget(caller, bundle) == ProviderRunBudget(
        20_000, 32_768, 128, 2_048, "gpu_vision"
    )


def test_budget_intersection_rejects_resource_group_mismatch():
    with pytest.raises(UEIValidationError, match="resource_group"):
        effective_provider_budget(
            ProviderRunBudget(30_000, 65_536, 256, 4_096, "gpu_vision"),
            ProviderRunBudget(30_000, 65_536, 256, 4_096, "cpu_vision"),
        )


def test_neutral_source_id_is_stable_but_changes_on_bundle_item_or_fingerprint():
    first = deterministic_neutral_source_item_id(
        bundle_ref={"id": "bundle/local.omni", "content_sha256": "1" * 64},
        source_index=3,
        native_fingerprint="2" * 64,
    )
    assert first == deterministic_neutral_source_item_id(
        bundle_ref={"id": "bundle/local.omni", "content_sha256": "1" * 64},
        source_index=3,
        native_fingerprint="2" * 64,
    )
    assert first != deterministic_neutral_source_item_id(
        bundle_ref={"id": "bundle/local.omni", "content_sha256": "1" * 64},
        source_index=4,
        native_fingerprint="2" * 64,
    )
    assert first != deterministic_neutral_source_item_id(
        bundle_ref={"id": "bundle/local.omni-v2", "content_sha256": "1" * 64},
        source_index=3,
        native_fingerprint="2" * 64,
    )
    assert first != deterministic_neutral_source_item_id(
        bundle_ref={"id": "bundle/local.omni", "content_sha256": "1" * 64},
        source_index=3,
        native_fingerprint="3" * 64,
    )


def test_semantic_request_rejects_non_closed_candidate_coverage_or_order():
    expected = _bound_semantic_request().ordered_candidate_ids
    for ordered_candidate_ids in (
        expected[:1],
        (expected[0], expected[0]),
        (expected[0], "candidate/unknown"),
        tuple(reversed(expected)),
    ):
        with pytest.raises(UEIValidationError, match="candidate"):
            _bound_semantic_request(ordered_candidate_ids=ordered_candidate_ids)



def _semantic_request() -> SemanticBindingRequestV1:
    return _bound_semantic_request()


def _semantic_result(
    candidate_ids: tuple[str, ...], *, capture_lineage_ref: dict[str, str]
) -> SemanticBindingResultV1:
    return SemanticBindingResultV1(
        bundle_ref=dict(BUNDLE_REF),
        invocation_id="invocation/test",
        capture_lineage_ref=dict(capture_lineage_ref),
        bindings=tuple(
            SemanticBindingItemV1(
                candidate_id=candidate_id,
                role="site-specific-quick-apply-control",
                label="Quick Apply",
                binding_status="BOUND",
                confidence=0.9,
            )
            for candidate_id in candidate_ids
        ),
        duration_ms=1,
        resource_units=1,
    )


def test_semantic_result_rejects_missing_duplicate_unknown_or_reordered_candidate_ids():
    request = _semantic_request()
    expected = request.ordered_candidate_ids
    for candidate_ids in (
        expected[:1],
        (expected[0], expected[0]),
        (expected[0], "candidate/unknown"),
        tuple(reversed(expected)),
    ):
        with pytest.raises(UEIValidationError, match="candidate"):
            request.validate_result(
                _semantic_result(
                    candidate_ids,
                    capture_lineage_ref=request.envelope.capture_lineage_ref,
                )
            )


def test_semantic_item_keeps_open_non_empty_role_strings():
    binding = SemanticBindingItemV1(
        candidate_id=_bound_semantic_request().ordered_candidate_ids[0],
        role="site-specific-quick-apply-control",
        label="Quick Apply",
        binding_status="BOUND",
        confidence=0.9,
    )
    assert binding.role == "site-specific-quick-apply-control"


def _grounding_request(*, candidate_bbox=(10, 10, 20, 20), permitted_roi=(10, 10, 20, 20)):
    return GroundingRefinementRequestV1(
        envelope=envelope("grounding_refinement"),
        candidate_id="candidate/one",
        candidate_bbox=candidate_bbox,
        permitted_roi=permitted_roi,
        provider_request={"state": "BOUND"},
    )


def _grounding_result(point: tuple[float, float]) -> GroundingRefinementResultV1:
    return GroundingRefinementResultV1(
        bundle_ref=dict(BUNDLE_REF),
        invocation_id="invocation/test",
        capture_lineage_ref=dict(LINEAGE_REF),
        candidate_id="candidate/one",
        status="REFINED",
        point=point,
        coordinate_space="capture_pixel_xyxy",
        confidence=0.9,
        evidence_refs=(),
        duration_ms=1,
        resource_units=1,
    )


@pytest.mark.parametrize("point", [
    (10, 15), (20, 15), (15, 10), (15, 20),
    (10, 10), (10, 20), (20, 10), (20, 20),
])
def test_grounding_rejects_candidate_bbox_edges_and_corners(point):
    with pytest.raises(UEIValidationError, match="strict_interior"):
        _grounding_request(permitted_roi=(0, 0, 30, 30)).validate_result(
            _grounding_result(point)
        )


@pytest.mark.parametrize("point", [
    (12, 15), (18, 15), (15, 12), (15, 18),
    (12, 12), (12, 18), (18, 12), (18, 18),
])
def test_grounding_rejects_permitted_roi_edges_and_corners(point):
    with pytest.raises(UEIValidationError, match="strict_interior"):
        _grounding_request(permitted_roi=(12, 12, 18, 18)).validate_result(
            _grounding_result(point)
        )


def test_requests_and_results_bind_exact_capability_refs_and_lineage():
    with pytest.raises(UEIValidationError, match="capability"):
        CandidateDiscoveryRequestV1(envelope=envelope("semantic_binding"), capture=capture())
    with pytest.raises(UEIValidationError, match="lineage"):
        CandidateDiscoveryRequestV1(
            envelope=envelope("candidate_discovery"),
            capture=RestrictedCaptureLease(
                **{**capture().__dict__, "capture_lineage_ref": {"id": "capture/other", "content_sha256": "2" * 64}}
            ),
        )
    with pytest.raises(UEIValidationError, match="bundle"):
        CandidateDiscoveryResultV1(
            bundle_ref={"id": "bundle/other", "content_sha256": "1" * 64, "unexpected": True},
            invocation_id="invocation/test",
            capture_lineage_ref=dict(LINEAGE_REF),
            items=(),
            duration_ms=1,
            resource_units=1,
        )


def _discovery_request() -> CandidateDiscoveryRequestV1:
    return CandidateDiscoveryRequestV1(
        envelope=envelope("candidate_discovery"),
        capture=capture(),
    )


def _discovery_result(**overrides: object) -> CandidateDiscoveryResultV1:
    values: dict[str, object] = {
        "bundle_ref": dict(BUNDLE_REF),
        "invocation_id": "invocation/test",
        "capture_lineage_ref": dict(LINEAGE_REF),
        "items": (),
        "duration_ms": 1,
        "resource_units": 1,
    }
    values.update(overrides)
    return CandidateDiscoveryResultV1(**values)


@pytest.mark.parametrize("overrides", [
    {"bundle_ref": {"id": "bundle/other", "content_sha256": "1" * 64}},
    {"invocation_id": "invocation/other"},
    {"capture_lineage_ref": {"id": "capture/other", "content_sha256": "2" * 64}},
])
def test_discovery_result_requires_exact_request_bundle_invocation_and_lineage(overrides):
    with pytest.raises(UEIValidationError, match="mismatch"):
        _discovery_request().validate_result(_discovery_result(**overrides))


def _semantic_capture_identity(screenshot_bytes: bytes) -> dict[str, object]:
    screenshot_sha256 = sha256(screenshot_bytes).hexdigest()
    artifact = seal_immutable({
        "contract_version": "artifact_ref_v1",
        "artifact_id": "artifact/semantic-screenshot",
        "artifact_sha256": screenshot_sha256,
        "media_type": "image/png",
        "byte_length": len(screenshot_bytes),
        "restricted": True,
    })
    artifact_ref = {"id": artifact["artifact_id"], "content_sha256": artifact["content_sha256"]}
    lineage = seal_immutable({
        "contract_version": "capture_lineage_v1",
        "capture_id": "capture/semantic-test",
        "artifact_ref": artifact_ref,
        "artifact_sha256": screenshot_sha256,
        "image_size": {"width": 100, "height": 100},
        "capture_coordinate_space": "capture_pixel_xyxy",
        "captured_at": "2026-09-03T00:00:00Z",
    })
    return {
        "contract_version": "hybrid_capture_identity_v1",
        "capture_id": "capture/semantic-test",
        "capture_lineage_ref": {"id": lineage["capture_id"], "content_sha256": lineage["content_sha256"]},
        "capture_lineage": lineage,
        "artifact_ref": artifact_ref,
        "artifact": artifact,
        "artifact_sha256": screenshot_sha256,
        "screenshot_sha256": screenshot_sha256,
        "image_size": {"width": 100, "height": 100},
        "capture_coordinate_space": "capture_pixel_xyxy",
        "captured_at": "2026-09-03T00:00:00Z",
        "workflow_revision": "1",
    }


def _semantic_bound_inputs(*, screenshot_bytes: bytes = b"bound-screenshot") -> dict[str, object]:
    capture_identity = _semantic_capture_identity(screenshot_bytes)
    capture_lineage_ref = deepcopy(capture_identity["capture_lineage_ref"])
    context = seal_immutable({
        "context_id": "context/test",
        "capture_lineage_ref": deepcopy(capture_lineage_ref),
    })
    context_ref = {"id": context["context_id"], "content_sha256": context["content_sha256"]}
    provider_id = "provider/local.omni"
    profile_id = "profile/local.omni"
    generic_ref = {"id": "synthetic/ref", "content_sha256": "1" * 64}
    provider_items = []
    for index, bbox in enumerate(([10, 10, 20, 20], [30, 30, 40, 40])):
        provider_items.append({
            "source_item_id": f"source/{index}",
            "source_id_origin": "provider",
            "kind": "element",
            "safe_text": f"candidate {index}",
            "safe_role": "button",
            "safe_states": [],
            "source_bbox": list(bbox),
            "capture_bbox": list(bbox),
            "source_coordinate_space": "capture_pixel_xyxy",
            "coordinate_transform_ref": None,
            "opaque_attributes": {},
            "provider_confidence": 0.9,
        })
    provider_result = seal_immutable({
        "contract_version": "provider_safe_result_v1",
        "result_id": "result/semantic-discovery",
        "request_ref": generic_ref,
        "requested_provider_id": provider_id,
        "requested_profile_id": profile_id,
        "registration_resolution": "resolved",
        "manifest_resolution": "resolved",
        "registration_ref": generic_ref,
        "manifest_ref": generic_ref,
        "provider_id": provider_id,
        "profile_id": profile_id,
        "provider_version": "test-v1",
        "capture_lineage_ref": deepcopy(capture_lineage_ref),
        "status": "success",
        "review_only": True,
        "items": provider_items,
        "redaction_summary": {
            "redacted_item_count": 0,
            "redacted_field_count": 0,
            "secret_detected": False,
            "sensitive_categories": [],
        },
    })
    provider_result_ref = {
        "id": provider_result["result_id"],
        "content_sha256": provider_result["content_sha256"],
    }
    candidates = []
    for item in provider_items:
        source_item_id = item["source_item_id"]
        candidate_id = stable_candidate_id(
            provider_result_ref=provider_result_ref,
            source_item_id=source_item_id,
        )
        candidates.append({
            "candidate_id": candidate_id,
            "provider_result_ref": provider_result_ref,
            "source_item_id": source_item_id,
            "bbox_original": deepcopy(item["capture_bbox"]),
            "coordinate_space": "capture_pixel_xyxy",
            "confidence": item["provider_confidence"],
            "active": True,
            "inactive_reason": None,
            "provenance": seal_immutable({
                "contract_version": "hybrid_candidate_provenance_v1",
                "provider_result_ref": provider_result_ref,
                "source_item_id": source_item_id,
            }),
        })
    return {
        "capture_bundle": {
            "capture_lineage_ref": capture_lineage_ref,
            "context_ref": context_ref,
            "capture_identity": deepcopy(capture_identity),
            "context": context,
        },
        "omni_inventory": {
            "contract_version": "hybrid_omni_inventory_v1",
            "capture_identity": deepcopy(capture_identity),
            "provider_result_ref": provider_result_ref,
            "provider_result": provider_result,
            "provider_id": provider_id,
            "provider_revision": "test-v1",
            "candidates": candidates,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "final_submit_forbidden": True,
            "real_action_requires_gate": True,
            "authorization_scope": "display_and_review_only",
        },
        "context_ref": context_ref,
        "screenshot_bytes": screenshot_bytes,
        "screenshot_media_type": "image/png",
        "screenshot_sha256": capture_identity["screenshot_sha256"],
    }


def _bound_semantic_request(**overrides: object) -> SemanticBindingRequestV1:
    values: dict[str, object] = _semantic_bound_inputs()
    values["ordered_candidate_ids"] = tuple(
        candidate["candidate_id"] for candidate in values["omni_inventory"]["candidates"]
    )
    capture_lineage_ref = values["capture_bundle"]["capture_lineage_ref"]
    values["envelope"] = ProviderInvocationEnvelopeV1(
        bundle_ref=dict(BUNDLE_REF),
        capability="semantic_binding",
        invocation_id="invocation/test",
        capture_lineage_ref=dict(capture_lineage_ref),
        budget=budget(),
    )
    values.update(overrides)
    if "ordered_candidate_ids" not in overrides:
        values["ordered_candidate_ids"] = tuple(
            candidate["candidate_id"] for candidate in values["omni_inventory"]["candidates"]
        )
    return SemanticBindingRequestV1(**values)


@pytest.mark.parametrize("mutate", [
    lambda values: values["capture_bundle"].pop("capture_lineage_ref"),
    lambda values: values["omni_inventory"]["capture_identity"].update({"screenshot_sha256": "f" * 64}),
    lambda values: values["omni_inventory"]["candidates"][0].update({"bbox_original": [10, 10, 10, 20]}),
    lambda values: values["omni_inventory"]["candidates"][0].update({"coordinate_space": "image_normalized_xyxy"}),
])
def test_semantic_request_requires_same_capture_and_immutable_candidate_geometry(mutate):
    values = _semantic_bound_inputs()
    mutate(values)
    with pytest.raises(UEIValidationError):
        _bound_semantic_request(**values)


def test_semantic_screenshot_input_is_not_limited_by_output_budget():
    screenshot_bytes = b"input-bytes-not-output"
    values = _semantic_bound_inputs(screenshot_bytes=screenshot_bytes)
    request = _bound_semantic_request(
        envelope=ProviderInvocationEnvelopeV1(
            bundle_ref=dict(BUNDLE_REF),
            capability="semantic_binding",
            invocation_id="invocation/input-budget",
            capture_lineage_ref=deepcopy(values["capture_bundle"]["capture_lineage_ref"]),
            budget=ProviderRunBudget(30_000, 1, 256, 4_096, "gpu_vision"),
        ),
        **values,
    )
    assert request.screenshot_bytes == screenshot_bytes


@pytest.mark.parametrize("provider_request", [
    {"state": "UNBOUND"},
    {},
    {"state": "BOUND", "nested": {"execute": True}},
])
def test_grounding_request_requires_bound_non_authorizing_input(provider_request):
    with pytest.raises(UEIValidationError):
        GroundingRefinementRequestV1(
            envelope=envelope("grounding_refinement"),
            candidate_id="candidate/one",
            candidate_bbox=(10, 10, 20, 20),
            permitted_roi=(10, 10, 20, 20),
            provider_request=provider_request,
        )



@pytest.mark.parametrize("mutate", [
    lambda values: values["omni_inventory"]["candidates"][0].update(
        {"bbox_original": [11, 11, 21, 21]}
    ),
    lambda values: values["omni_inventory"]["candidates"][0].update(
        {"bbox": [10, 10, 20, 20]}
    ),
    lambda values: values["omni_inventory"]["candidates"][0].update(
        {"execute": True}
    ),
])
def test_semantic_inventory_rejects_substituted_geometry_and_unknown_candidate_fields(mutate):
    values = _semantic_bound_inputs()
    mutate(values)
    with pytest.raises(UEIValidationError):
        _bound_semantic_request(**values)


def test_semantic_inventory_rejects_candidate_not_proven_by_discovery():
    values = _semantic_bound_inputs()
    values["omni_inventory"]["candidates"].append({
        "candidate_id": "candidate/unknown",
        "bbox_original": [50, 50, 60, 60],
        "coordinate_space": "capture_pixel_xyxy",
    })
    expected = tuple(candidate["candidate_id"] for candidate in values["omni_inventory"]["candidates"])
    with pytest.raises(UEIValidationError):
        _bound_semantic_request(ordered_candidate_ids=expected, **values)


def test_discovery_ref_values_are_copied_before_external_mutation():
    shared_bundle_ref = dict(BUNDLE_REF)
    shared_lineage_ref = dict(LINEAGE_REF)
    request = CandidateDiscoveryRequestV1(
        envelope=ProviderInvocationEnvelopeV1(
            bundle_ref=shared_bundle_ref,
            capability="candidate_discovery",
            invocation_id="invocation/frozen-discovery",
            capture_lineage_ref=shared_lineage_ref,
            budget=budget(),
        ),
        capture=capture(),
    )
    result = CandidateDiscoveryResultV1(
        bundle_ref=shared_bundle_ref,
        invocation_id="invocation/frozen-discovery",
        capture_lineage_ref=shared_lineage_ref,
        items=(),
        duration_ms=1,
        resource_units=1,
    )
    shared_bundle_ref["id"] = "bundle/mutated"
    shared_lineage_ref["id"] = "capture/mutated"
    assert request.envelope.bundle_ref["id"] == BUNDLE_REF["id"]
    assert result.capture_lineage_ref["id"] == LINEAGE_REF["id"]
    request.validate_result(result)


def test_semantic_evidence_is_copied_before_geometry_or_order_mutation():
    values = _semantic_bound_inputs()
    request = _bound_semantic_request(**values)
    values["omni_inventory"]["candidates"][0]["bbox_original"][0] = 11
    values["omni_inventory"]["candidates"].reverse()
    assert request.omni_inventory["candidates"][0]["bbox_original"] == [10, 10, 20, 20]
    assert request.ordered_candidate_ids == tuple(
        candidate["candidate_id"] for candidate in request.omni_inventory["candidates"]
    )


def test_grounding_request_is_copied_before_state_or_authority_mutation():
    provider_request = {"state": "BOUND", "nested": {"evidence": "safe"}}
    request = GroundingRefinementRequestV1(
        envelope=envelope("grounding_refinement"),
        candidate_id="candidate/one",
        candidate_bbox=(10, 10, 20, 20),
        permitted_roi=(10, 10, 20, 20),
        provider_request=provider_request,
    )
    provider_request["state"] = "UNBOUND"
    provider_request["nested"]["execute"] = True
    assert request.provider_request["state"] == "BOUND"
    reject_authority_shaped_payload(request.provider_request)



def test_frozen_discovery_capture_keeps_existing_omni_delegate_json_contract():
    request = _discovery_request()
    assert isinstance(request.capture.image_size, dict)
    payload = json.dumps({
        "input_path": str(request.capture.local_path),
        "image_size": request.capture.image_size,
    })
    assert json.loads(payload)["image_size"] == {"width": 100, "height": 100}


def test_frozen_semantic_and_grounding_evidence_support_deepcopy_materialization():
    semantic_request = _bound_semantic_request()
    inventory = deepcopy(semantic_request.omni_inventory)
    assert isinstance(inventory, dict)
    assert isinstance(inventory["candidates"], list)
    assert validate_omni_inventory(inventory)["candidates"]

    grounding_request = GroundingRefinementRequestV1(
        envelope=envelope("grounding_refinement"),
        candidate_id="candidate/one",
        candidate_bbox=(10, 10, 20, 20),
        permitted_roi=(10, 10, 20, 20),
        provider_request={"state": "BOUND", "nested": {"evidence": "safe"}},
    )
    provider_request = deepcopy(grounding_request.provider_request)
    assert isinstance(provider_request, dict)
    assert provider_request == {"state": "BOUND", "nested": {"evidence": "safe"}}
