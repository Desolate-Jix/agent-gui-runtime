from __future__ import annotations

from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from threading import Event

import pytest

from app.learn.recognition.uei.contracts import UEIValidationError
from app.learn.recognition.uei.provider_adapters import (
    NormalizedProviderItem,
    NormalizedScreenParseOutput,
    ProviderRunBudget,
    RestrictedCaptureLease,
)
from app.learn.recognition.uei.provider_bundles import (
    TrustedProviderBundleRegistry,
    provider_bundle_ref,
    seal_provider_bundle_descriptor_v1,
)
from app.learn.recognition.uei.provider_capabilities import (
    CandidateDiscoveryItemV1,
    CandidateDiscoveryRequestV1,
    CandidateDiscoveryResultV1,
    CapabilityCleanupOutcomeV1,
    ProviderInvocationEnvelopeV1,
    deterministic_neutral_source_item_id,
    invoke_with_capability_envelope,
)
from app.learn.hybrid.provider_capability_adapters import (
    OmniDiscoveryCompatibilityAdapter,
    project_discovery_to_screen_parse_v1,
)


BUNDLE_REF = {"id": "bundle/local.omni-discovery", "content_sha256": "a" * 64}
LINEAGE_REF = {"id": "capture/omni-adapter", "content_sha256": "b" * 64}
ARTIFACT_REF = {"id": "artifact/omni-adapter", "content_sha256": "c" * 64}


class RecordedScreenParseAdapter:
    provider_id = "local.runtime/omniparser"
    profile_id = "local.runtime/omniparser/shadow-v2"
    provider_version = "test-v1"

    def __init__(self, output: NormalizedScreenParseOutput) -> None:
        self.output = output
        self.calls: list[dict[str, object]] = []

    def invoke(self, *, capture, budget, invocation_id, cancellation_event=None):
        self.calls.append({
            "capture": capture,
            "budget": budget,
            "invocation_id": invocation_id,
            "cancellation_event": cancellation_event,
        })
        return self.output


def current_screen_parse_output_fixture(*, first_id: str | None = "provider/first") -> NormalizedScreenParseOutput:
    return NormalizedScreenParseOutput(
        items=(
            NormalizedProviderItem(
                source_item_id=first_id,
                kind="element",
                safe_text="Open role",
                safe_role="button",
                safe_states=("enabled",),
                source_bbox=(10, 20, 30, 40),
                source_coordinate_space="capture_pixel_xyxy",
                provider_confidence=0.9,
            ),
            NormalizedProviderItem(
                source_item_id="provider/second",
                kind="text",
                safe_text="Details",
                source_bbox=(50, 60, 70, 80),
                source_coordinate_space="capture_pixel_xyxy",
                provider_confidence=0.7,
            ),
        ),
        duration_ms=17,
        resource_units=2,
    )


def discovery_request_fixture(
    *,
    cancellation_event: Event | None = None,
    bundle_ref: dict[str, str] | None = None,
    budget: ProviderRunBudget | None = None,
) -> CandidateDiscoveryRequestV1:
    budget = budget or ProviderRunBudget(3_000, 32_768, 32, 256, "omni-test")
    capture = RestrictedCaptureLease(
        request_ref={"id": "request/omni-adapter", "content_sha256": "d" * 64},
        capture_lineage_ref=dict(LINEAGE_REF),
        artifact_ref=dict(ARTIFACT_REF),
        capture_id="capture/omni-adapter",
        artifact_sha256="e" * 64,
        image_size={"width": 100, "height": 100},
        local_path=Path("capture.png"),
    )
    return CandidateDiscoveryRequestV1(
        envelope=ProviderInvocationEnvelopeV1(
            bundle_ref=dict(BUNDLE_REF if bundle_ref is None else bundle_ref),
            capability="candidate_discovery",
            invocation_id="invocation/omni-adapter",
            capture_lineage_ref=dict(LINEAGE_REF),
            budget=budget,
            cancellation_event=cancellation_event,
        ),
        capture=capture,
    )


def _sealed_discovery_descriptor(*, budget: ProviderRunBudget) -> dict[str, object]:
    return seal_provider_bundle_descriptor_v1({
        "contract_version": "provider_bundle_descriptor_v1",
        "bundle_id": "bundle/local.omni-discovery-contract",
        "bundle_revision": "test-v1",
        "capability": "candidate_discovery",
        "provider_id": "provider/local.omni",
        "profile_id": "profile/local.omni",
        "model_id": "model/omni",
        "model_revision": "test-v1",
        "prompt_spec_sha256": "1" * 64,
        "prompt_renderer_sha256": "2" * 64,
        "native_parser_sha256": "3" * 64,
        "adapter_sha256": "4" * 64,
        "preprocessing_sha256": "5" * 64,
        "transport_sha256": "6" * 64,
        "coordinate_convention": "capture_pixel_xyxy",
        "decoding_config_sha256": "7" * 64,
        "artifact_sha256s": ["8" * 64],
        "resource_budget": budget.__dict__,
        "resource_lease_policy": "none",
    })



def _native_fingerprint(item: NormalizedProviderItem) -> str:
    from app.learn.recognition.uei.canonical import canonical_json_bytes

    return sha256(canonical_json_bytes({
        "kind": item.kind,
        "safe_text": item.safe_text,
        "safe_role": item.safe_role,
        "safe_states": list(item.safe_states),
        "source_bbox": list(item.source_bbox) if item.source_bbox is not None else None,
        "source_coordinate_space": item.source_coordinate_space,
        "provider_confidence": item.provider_confidence,
    })).hexdigest()


def test_omni_compatibility_projection_is_field_equivalent_to_current_output():
    current = current_screen_parse_output_fixture()
    adapter = OmniDiscoveryCompatibilityAdapter(
        bundle_ref=dict(BUNDLE_REF),
        delegate=RecordedScreenParseAdapter(current),
    )

    neutral = adapter.invoke(discovery_request_fixture())

    assert project_discovery_to_screen_parse_v1(neutral) == current


def test_provider_supplied_ids_remain_unchanged_in_neutral_result():
    current = current_screen_parse_output_fixture()
    neutral = OmniDiscoveryCompatibilityAdapter(
        bundle_ref=dict(BUNDLE_REF),
        delegate=RecordedScreenParseAdapter(current),
    ).invoke(discovery_request_fixture())

    assert tuple(item.source_item_id for item in neutral.items) == (
        "provider/first", "provider/second",
    )


def test_missing_provider_id_receives_deterministic_transient_neutral_id():
    current = current_screen_parse_output_fixture(first_id=None)
    request = discovery_request_fixture()
    adapter = OmniDiscoveryCompatibilityAdapter(
        bundle_ref=dict(BUNDLE_REF),
        delegate=RecordedScreenParseAdapter(current),
    )

    first = adapter.invoke(request)
    second = adapter.invoke(request)

    expected = deterministic_neutral_source_item_id(
        bundle_ref=dict(BUNDLE_REF),
        source_index=0,
        native_fingerprint=_native_fingerprint(current.items[0]),
    )
    assert first.items[0].source_item_id == expected
    assert second.items[0].source_item_id == expected
    assert first.items[0].source_item_id


def test_missing_id_projection_survives_declared_neutral_reconstruction_and_replace():
    current = current_screen_parse_output_fixture(first_id=None)
    neutral = OmniDiscoveryCompatibilityAdapter(
        bundle_ref=dict(BUNDLE_REF),
        delegate=RecordedScreenParseAdapter(current),
    ).invoke(discovery_request_fixture())
    serialized = asdict(neutral)
    reconstructed = CandidateDiscoveryResultV1(
        **{
            **serialized,
            "items": tuple(
                CandidateDiscoveryItemV1(**item) for item in serialized["items"]
            ),
        }
    )

    assert neutral.items[0].provider_source_item_id is None
    assert project_discovery_to_screen_parse_v1(reconstructed) == current
    assert project_discovery_to_screen_parse_v1(replace(neutral)) == current


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "made-up"),
        ("source_coordinate_space", "unsupported_space"),
        ("source_bbox", (0, 0, 101, 100)),
    ],
)
def test_omni_neutral_validation_rejects_invalid_current_geometry_or_kind(field, value):
    current = current_screen_parse_output_fixture()
    invalid = replace(
        current,
        items=(replace(current.items[0], **{field: value}), current.items[1]),
    )

    with pytest.raises(UEIValidationError, match="omni"):
        OmniDiscoveryCompatibilityAdapter(
            bundle_ref=dict(BUNDLE_REF),
            delegate=RecordedScreenParseAdapter(invalid),
        ).invoke(discovery_request_fixture())



def test_duplicate_provider_ids_fail_closed_before_neutral_result():
    current = current_screen_parse_output_fixture()
    duplicate = NormalizedScreenParseOutput(
        items=(current.items[0], current.items[0]),
        duration_ms=current.duration_ms,
        resource_units=current.resource_units,
    )

    with pytest.raises(UEIValidationError, match="duplicate"):
        OmniDiscoveryCompatibilityAdapter(
            bundle_ref=dict(BUNDLE_REF),
            delegate=RecordedScreenParseAdapter(duplicate),
        ).invoke(discovery_request_fixture())


def test_reordered_neutral_items_cannot_project_to_the_recorded_legacy_output():
    current = current_screen_parse_output_fixture()
    neutral = OmniDiscoveryCompatibilityAdapter(
        bundle_ref=dict(BUNDLE_REF),
        delegate=RecordedScreenParseAdapter(current),
    ).invoke(discovery_request_fixture())
    object.__setattr__(neutral, "items", tuple(reversed(neutral.items)))

    with pytest.raises(UEIValidationError, match="order"):
        project_discovery_to_screen_parse_v1(neutral)


def test_nested_authority_shaped_payload_is_rejected_before_neutral_item_creation():
    current = current_screen_parse_output_fixture()
    object.__setattr__(current.items[0], "provider_payload", {"nested": [{"execute": True}]})

    with pytest.raises(UEIValidationError, match="non_authorizing"):
        OmniDiscoveryCompatibilityAdapter(
            bundle_ref=dict(BUNDLE_REF),
            delegate=RecordedScreenParseAdapter(current),
        ).invoke(discovery_request_fixture())


def test_authority_shaped_payload_added_to_neutral_result_cannot_project():
    current = current_screen_parse_output_fixture()
    neutral = OmniDiscoveryCompatibilityAdapter(
        bundle_ref=dict(BUNDLE_REF),
        delegate=RecordedScreenParseAdapter(current),
    ).invoke(discovery_request_fixture())
    object.__setattr__(neutral.items[0], "provider_payload", {"nested": {"final_submit": True}})

    with pytest.raises(UEIValidationError, match="non_authorizing"):
        project_discovery_to_screen_parse_v1(neutral)



def test_delegate_receives_the_existing_intersected_budget_and_cancellation_unchanged():
    current = current_screen_parse_output_fixture()
    delegate = RecordedScreenParseAdapter(current)
    cancellation_event = Event()
    request = discovery_request_fixture(cancellation_event=cancellation_event)

    OmniDiscoveryCompatibilityAdapter(
        bundle_ref=dict(BUNDLE_REF), delegate=delegate,
    ).invoke(request)

    assert delegate.calls == [{
        "capture": request.capture,
        "budget": request.envelope.budget,
        "invocation_id": request.envelope.invocation_id,
        "cancellation_event": cancellation_event,
    }]


def test_task3_dispatches_the_sealed_effective_budget_to_omni_delegate():
    current = current_screen_parse_output_fixture()
    delegate = RecordedScreenParseAdapter(current)
    sealed_budget = ProviderRunBudget(100, 20_000, 16, 128, "omni-test")
    caller_budget = ProviderRunBudget(1_000, 30_000, 32, 256, "omni-test")
    descriptor = _sealed_discovery_descriptor(budget=sealed_budget)
    bundle_ref = provider_bundle_ref(descriptor)
    adapter = OmniDiscoveryCompatibilityAdapter(bundle_ref=bundle_ref, delegate=delegate)
    registry = TrustedProviderBundleRegistry([(descriptor, adapter)])
    cancellation_event = Event()
    request = discovery_request_fixture(
        bundle_ref=bundle_ref,
        budget=caller_budget,
        cancellation_event=cancellation_event,
    )

    outcome = invoke_with_capability_envelope(
        request=request,
        registry=registry,
        adapter=adapter,
        invoke=adapter.invoke,
        validate_result=lambda result, _: request.validate_result(result),
        cleanup=None,
        validate_cleanup=lambda _: CapabilityCleanupOutcomeV1("not_required", None),
    )

    assert outcome.promoted is True
    assert delegate.calls == [{
        "capture": request.capture,
        "budget": sealed_budget,
        "invocation_id": request.envelope.invocation_id,
        "cancellation_event": cancellation_event,
    }]
    assert delegate.calls[0]["capture"] is request.capture
    assert delegate.calls[0]["cancellation_event"] is cancellation_event
