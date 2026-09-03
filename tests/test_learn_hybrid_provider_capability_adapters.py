from __future__ import annotations

from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from threading import Event

import pytest

from app.learn.recognition.uei.contracts import UEIValidationError
from app.learn.recognition.uei.canonical import seal_immutable
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
    GroundingRefinementRequestV1,
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


def test_qwen_compatibility_adapter_uses_exact_managed_envelope_and_current_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid.provider_capability_adapters import (
        QwenSemanticBindingCompatibilityAdapter,
        project_semantic_result_to_hybrid_qwen_v1,
    )
    from app.learn.recognition.uei.provider_capabilities import (
        SemanticBindingRequestV1,
        invoke_with_capability_envelope,
    )
    from tests.test_learn_hybrid_qwen_binding import _qwen_facts

    facts = _qwen_facts(tmp_path, monkeypatch)
    capture_path = Path(facts["qwen_payload"]["capture_image_path"])
    if not capture_path.is_absolute():
        capture_path = tmp_path / capture_path
    screenshot_bytes = capture_path.read_bytes()
    inputs = {
        "capture_bundle": facts["bundle"],
        "omni_inventory": {key: value for key, value in facts["inventory"].items() if key != "content_sha256"},
        "context_ref": facts["bundle"]["context_ref"],
        "screenshot_bytes": screenshot_bytes,
        "screenshot_media_type": "image/png",
        "screenshot_sha256": facts["bundle"]["capture_identity"]["screenshot_sha256"],
    }
    ordered_candidate_ids = tuple(
        candidate["candidate_id"] for candidate in inputs["omni_inventory"]["candidates"]
    )
    descriptor = seal_provider_bundle_descriptor_v1({
        "contract_version": "provider_bundle_descriptor_v1",
        "bundle_id": "bundle/local.qwen-semantic-contract",
        "bundle_revision": "test-v1",
        "capability": "semantic_binding",
        "provider_id": "provider/local.qwen3",
        "profile_id": "profile/local.qwen3",
        "model_id": "model/qwen3",
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
        "resource_budget": ProviderRunBudget(100, 4_096, 8, 128, "gpu_vision").__dict__,
        "resource_lease_policy": "exact_managed",
    })
    bundle_ref = provider_bundle_ref(descriptor)
    lease = {
        "contract_version": "managed_qwen_model_lease_v1",
        "lease_id": "lease/qwen",
        "owner_request_id": "owner/qwen",
        "profile_id": "profile/local.qwen3",
        "incarnation_id": "incarnation/qwen",
        "server_base_url": "http://127.0.0.1:18080",
        "server_model_id": "model/qwen3",
        "profile_sha256": "9" * 64,
        "server_process_identity": {"pid": 1, "create_time_ns": 1},
    }
    calls: list[dict[str, object]] = []

    def runner(**kwargs: object) -> dict[str, object]:
        calls.append(dict(kwargs))
        return {
            "bindings": [
                {
                    "candidate_id": candidate_id,
                    "role": "site-specific-quick-apply-control",
                    "label": f"candidate {index}",
                    "binding_status": "BOUND",
                    "confidence": 0.9,
                }
                for index, candidate_id in enumerate(ordered_candidate_ids)
            ]
        }

    monkeypatch.setattr(
        "app.core.model_server._profile_for_qwen_model_lease",
        lambda value: {"profile_id": value["profile_id"]},
    )
    monkeypatch.setattr(
        "app.core.model_server.qwen_model_lease_is_active", lambda value: False,
    )
    adapter = QwenSemanticBindingCompatibilityAdapter(
        bundle_ref=bundle_ref, model_runner=runner,
    )
    request = SemanticBindingRequestV1(
        envelope=ProviderInvocationEnvelopeV1(
            bundle_ref=bundle_ref,
            capability="semantic_binding",
            invocation_id="invocation/qwen-compat",
            capture_lineage_ref=inputs["capture_bundle"]["capture_identity"]["capture_lineage_ref"],
            budget=ProviderRunBudget(1_000, 4_096, 16, 256, "gpu_vision"),
            resource_lease=lease,
        ),
        ordered_candidate_ids=ordered_candidate_ids,
        **inputs,
    )
    registry = TrustedProviderBundleRegistry([(descriptor, adapter)])
    outcome = invoke_with_capability_envelope(
        request=request, registry=registry, adapter=adapter, invoke=adapter.invoke,
        validate_result=lambda result, _: request.validate_result(result),
        cleanup=lambda: {
            "status": "released", "lease": lease,
            "shared_server_retained": True,
            "server_termination": "not_required_shared",
            "reason": "test-shared-server",
        },
        validate_cleanup=adapter.validate_cleanup,
    )

    assert outcome.promoted is True
    assert outcome.failure is None
    assert calls[0]["model_lease"] == lease
    assert calls[0]["cancellation_event"] is request.envelope.cancellation_event
    assert calls[0]["timeout_seconds"] == 0.1
    legacy = project_semantic_result_to_hybrid_qwen_v1(
        result=outcome.result, inventory=seal_immutable(dict(request.omni_inventory)), context_ref=request.context_ref,
    )
    assert legacy["contract_version"] == "hybrid_qwen_bindings_v1"
    assert legacy["artifact_is_authorization"] is False
    assert "binding_status" not in legacy["bindings"][0]

    valid_bindings = runner()["bindings"]
    legacy_bindings = [{
        "candidate_id": binding["candidate_id"], "role": binding["role"],
        "label": binding["label"], "description": "legacy", "semantic_confidence": 0.9,
        "task_relevance": 0.8, "relation": "candidate_binding", "ambiguity": None,
    } for binding in valid_bindings]
    raw_cases = [
        {"bindings": valid_bindings, "padding": "x" * 5_000},
        {"bindings": [{**valid_bindings[0], "candidate_id": "candidate/unknown"}, valid_bindings[1]]},
        {"bindings": valid_bindings[:-1]},
        {"bindings": [valid_bindings[0], {**valid_bindings[1], "candidate_id": valid_bindings[0]["candidate_id"]}]},
        {"bindings": legacy_bindings, "ambiguity_sets": [{
            "contract_version": "hybrid_semantic_ambiguity_set_v1",
            "candidate_ids": [candidate["candidate_id"] for candidate in facts["inventory"]["candidates"]],
        }, {
            "contract_version": "hybrid_semantic_ambiguity_set_v1",
            "candidate_ids": [candidate["candidate_id"] for candidate in facts["inventory"]["candidates"]],
        }], "orphan_semantics": []},
        {"bindings": legacy_bindings, "ambiguity_sets": [], "orphan_semantics": [{
            "semantic_id": "candidate/unknown", "role": "text", "label": "orphan",
            "description": "invalid", "reason": "ORPHAN_SEMANTIC",
        }]},
    ]
    for raw in raw_cases:
        adapter._model_runner = lambda **_: raw
        rejected = invoke_with_capability_envelope(
            request=request, registry=registry, adapter=adapter, invoke=adapter.invoke,
            validate_result=lambda result, _: request.validate_result(result),
            cleanup=lambda: {
                "status": "released", "lease": lease, "shared_server_retained": True,
                "server_termination": "not_required_shared", "reason": "test-shared-server",
            },
            validate_cleanup=adapter.validate_cleanup,
        )
        assert rejected.promoted is False
        assert rejected.failure is not None and rejected.failure.stage == "invocation"


def test_qwen_compatibility_adapter_rejects_stale_profile_or_incarnation_before_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid.provider_capability_adapters import QwenSemanticBindingCompatibilityAdapter

    adapter = QwenSemanticBindingCompatibilityAdapter(
        bundle_ref={"id": "bundle/local.qwen", "content_sha256": "a" * 64},
        model_runner=lambda **_: pytest.fail("stale lease reached Qwen runner"),
    )
    monkeypatch.setattr(
        "app.core.model_server._profile_for_qwen_model_lease",
        lambda _: {"profile_id": "profile/unexpected"},
    )
    with pytest.raises(UEIValidationError, match="resource_lease_mismatch"):
        adapter.validate_resource_lease(
            lease={"profile_id": "profile/local.qwen3", "incarnation_id": "stale"},
            descriptor={"profile_id": "profile/local.qwen3"},
            bundle_ref={"id": "bundle/local.qwen", "content_sha256": "a" * 64},
        )


def test_qwen_cleanup_requires_terminal_receipt_and_inactive_exact_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid.provider_capability_adapters import QwenSemanticBindingCompatibilityAdapter

    lease = {
        "contract_version": "managed_qwen_model_lease_v1",
        "lease_id": "lease/qwen",
        "owner_request_id": "owner/qwen",
        "profile_id": "profile/local.qwen3",
        "incarnation_id": "incarnation/qwen",
        "server_base_url": "http://127.0.0.1:18080",
        "server_model_id": "model/qwen3",
        "profile_sha256": "9" * 64,
        "server_process_identity": {"pid": 1, "create_time_ns": 1},
    }
    adapter = QwenSemanticBindingCompatibilityAdapter(
        bundle_ref={"id": "bundle/local.qwen", "content_sha256": "a" * 64},
        model_runner=lambda **_: pytest.fail("cleanup must not run a model"),
    )
    shared = {
        "status": "released",
        "lease": lease,
        "shared_server_retained": True,
        "server_termination": "not_required_shared",
        "reason": "completed",
    }
    monkeypatch.setattr("app.core.model_server.qwen_model_lease_is_active", lambda _: True)
    assert adapter.validate_cleanup(
        receipt=shared, lease=lease, bundle_ref=adapter.bundle_ref, invocation_id="invocation/qwen",
    ).status == "indeterminate"

    monkeypatch.setattr("app.core.model_server.qwen_model_lease_is_active", lambda _: False)
    assert adapter.validate_cleanup(
        receipt=shared, lease=lease, bundle_ref=adapter.bundle_ref, invocation_id="invocation/qwen",
    ).status == "clean"
    assert adapter.validate_cleanup(
        receipt={"status": "released", "lease": lease},
        lease=lease, bundle_ref=adapter.bundle_ref, invocation_id="invocation/qwen",
    ).status == "indeterminate"

    external = {**shared, "server_termination": "not_owned", "reason": "external"}
    assert adapter.validate_cleanup(
        receipt=external, lease=lease, bundle_ref=adapter.bundle_ref, invocation_id="invocation/qwen",
    ).status == "clean"
    owned = {
        "status": "released", "lease": lease, "shared_server_retained": False,
        "server_termination": "verified_exact_process_exited",
        "release": {"status": "proven_absent", "identity": None, "reason": "no_such_process"},
        "after": {"status": "stopped"},
        "process_identity": lease["server_process_identity"],
        "hybrid_descendant_cleanup": {"status": "verified"},
        "hybrid_process_scope_name": "scope/qwen",
        "hybrid_process_scope_acquisition": {"contract_version": "hybrid_process_scope_acquisition_v1"},
        "hybrid_process_scope_cleanup": {"cleanup_status": "verified"},
    }
    assert adapter.validate_cleanup(
        receipt=owned, lease=lease, bundle_ref=adapter.bundle_ref, invocation_id="invocation/qwen",
    ).status == "clean"
    retry_owned = {
        key: value for key, value in owned.items()
        if key not in {
            "hybrid_process_scope_name", "hybrid_process_scope_acquisition",
            "hybrid_process_scope_cleanup",
        }
    }
    retry_owned["server_termination"] = "verified_exact_process_proven_absent_on_retry"
    assert adapter.validate_cleanup(
        receipt=retry_owned, lease=lease, bundle_ref=adapter.bundle_ref, invocation_id="invocation/qwen",
    ).status == "clean"
    for invalid in (
        {**shared, "status": "pending"},
        {**shared, "shared_server_retained": False},
        {**owned, "process_identity": {"pid": 2, "create_time_ns": 1}},
    ):
        assert adapter.validate_cleanup(
            receipt=invalid, lease=lease, bundle_ref=adapter.bundle_ref, invocation_id="invocation/qwen",
        ).status == "indeterminate"
    monkeypatch.setattr(
        "app.core.model_server.qwen_model_lease_is_active",
        lambda _: (_ for _ in ()).throw(RuntimeError("lease observer failed")),
    )
    assert adapter.validate_cleanup(
        receipt=shared, lease=lease, bundle_ref=adapter.bundle_ref, invocation_id="invocation/qwen",
    ).status == "indeterminate"



def _vista_lease() -> dict[str, object]:
    identities = [{"pid": 123, "create_time_ns": 456}]
    return {
        "contract_version": "hybrid_vista_model_lease_v2", "provider": "vista",
        "incarnation_id": "vista-incarnation",
        "profile": {"profile_id": "profile/local.vista", "host": "127.0.0.1", "port": 18081},
        "process_identities": identities, "process_scope_name": "scope/vista",
        "process_scope_acquisition": {
            "contract_version": "hybrid_process_scope_acquisition_v1",
            "scope_name": "scope/vista", "member_pids": [123],
            "process_identities": identities,
        },
    }

def _sealed_grounding_descriptor(*, bundle_ref: dict[str, str]) -> dict[str, object]:
    return seal_provider_bundle_descriptor_v1({
        "contract_version": "provider_bundle_descriptor_v1",
        "bundle_id": bundle_ref["id"],
        "bundle_revision": "test-v1",
        "capability": "grounding_refinement",
        "provider_id": "provider/local.vista",
        "profile_id": "profile/local.vista",
        "model_id": "model/vista",
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
        "resource_budget": ProviderRunBudget(1_000, 4_096, 8, 128, "vista-test").__dict__,
        "resource_lease_policy": "exact_managed",
    })


def test_vista_compatibility_adapter_projects_exact_bound_request_without_authority(
    tmp_path,
) -> None:
    from app.learn.hybrid.provider_capability_adapters import (
        VistaGroundingRefinementCompatibilityAdapter,
    )
    from app.learn.hybrid.vista_refinement import (
        normalize_vista_grounding_result,
        project_grounding_result_to_hybrid_vista_refinement_v1,
    )
    from tests.test_learn_hybrid_vista_refinement import (
        _raw_result,
        _stored_authoritative_inputs,
    )
    from app.learn.hybrid.vista_refinement import build_vista_requests

    fusion, bundle, inventory, bindings, receipt, context = _stored_authoritative_inputs(tmp_path)
    legacy_request = build_vista_requests(
        fusion, bundle, omni_inventory=inventory, qwen_bindings=bindings,
        qwen_cleanup_receipt=receipt, expected_workflow_revision=bundle["workflow_revision"],
    )[0]
    bundle_ref = {"id": "bundle/local.vista-grounding", "content_sha256": "a" * 64}
    descriptor = _sealed_grounding_descriptor(bundle_ref=bundle_ref)
    bundle_ref = provider_bundle_ref(descriptor)
    raw = _raw_result(legacy_request)
    calls: list[dict[str, object]] = []

    def runner(**kwargs: object) -> dict[str, object]:
        calls.append(dict(kwargs))
        return raw

    lease = _vista_lease()
    request = GroundingRefinementRequestV1(
        envelope=ProviderInvocationEnvelopeV1(
            bundle_ref=bundle_ref, capability="grounding_refinement",
            invocation_id="invocation/vista-adapter",
            capture_lineage_ref=legacy_request["capture_lineage_ref"],
            budget=ProviderRunBudget(2_000, 8_192, 16, 256, "vista-test"),
            resource_lease=lease,
        ),
        candidate_id=legacy_request["candidate_id"],
        candidate_bbox=tuple(legacy_request["candidate_bbox_ref"]["xyxy"]),
        permitted_roi=tuple(legacy_request["roi_ref"]["xyxy"]),
        provider_request={"state": "BOUND", "vista_request": legacy_request},
    )
    adapter = VistaGroundingRefinementCompatibilityAdapter(
        bundle_ref=bundle_ref, provider_runner=runner,
        authoritative_context_resolver=lambda _: context,
    )

    result = adapter.invoke(request)

    assert result.status == "PROPOSED"
    assert result.point == tuple(raw["point"])
    assert calls == [{
        "request": legacy_request, "timeout_seconds": 2.0,
        "cancellation_event": request.envelope.cancellation_event, "model_lease": lease,
    }]
    assert project_grounding_result_to_hybrid_vista_refinement_v1(
        request=legacy_request, raw_result=raw, result=result,
    ) == project_grounding_result_to_hybrid_vista_refinement_v1(
        request=legacy_request, raw_result=raw,
        result=normalize_vista_grounding_result(
            request=legacy_request, raw_result=raw, bundle_ref=bundle_ref,
            invocation_id=request.envelope.invocation_id,
            authoritative_context=context,
        ),
    )


def test_vista_compatibility_adapter_rejects_non_bound_or_authority_raw_before_projection(
    tmp_path,
) -> None:
    from app.learn.hybrid.provider_capability_adapters import (
        VistaGroundingRefinementCompatibilityAdapter,
    )
    from tests.test_learn_hybrid_vista_refinement import (
        _raw_result,
        _stored_authoritative_inputs,
    )
    from app.learn.hybrid.vista_refinement import build_vista_requests

    fusion, bundle, inventory, bindings, receipt, context = _stored_authoritative_inputs(tmp_path)
    legacy_request = build_vista_requests(
        fusion, bundle, omni_inventory=inventory, qwen_bindings=bindings,
        qwen_cleanup_receipt=receipt, expected_workflow_revision=bundle["workflow_revision"],
    )[0]
    bundle_ref = {"id": "bundle/local.vista-grounding", "content_sha256": "a" * 64}
    request = GroundingRefinementRequestV1(
        envelope=ProviderInvocationEnvelopeV1(
            bundle_ref=bundle_ref, capability="grounding_refinement",
            invocation_id="invocation/vista-adapter-reject",
            capture_lineage_ref=legacy_request["capture_lineage_ref"],
            budget=ProviderRunBudget(1_000, 4_096, 8, 128, "vista-test"),
            resource_lease=_vista_lease(),
        ),
        candidate_id=legacy_request["candidate_id"],
        candidate_bbox=tuple(legacy_request["candidate_bbox_ref"]["xyxy"]),
        permitted_roi=tuple(legacy_request["roi_ref"]["xyxy"]),
        provider_request={"state": "BOUND", "vista_request": legacy_request},
    )
    raw = _raw_result(legacy_request)
    raw["provenance"]["nested"] = {"execute": True}
    adapter = VistaGroundingRefinementCompatibilityAdapter(
        bundle_ref=bundle_ref, provider_runner=lambda **_: raw,
        authoritative_context_resolver=lambda _: context,
    )
    with pytest.raises(ValueError, match="non_authorizing"):
        adapter.invoke(request)


def _production_vista_profile(tmp_path: Path) -> dict[str, object]:
    return {
        "profile_id": "profile/local.vista",
        "host": "127.0.0.1",
        "port": 18081,
        "pid_file": str(tmp_path / "vista.pid"),
    }


def _production_vista_lease(
    tmp_path: Path,
    *,
    identity: dict[str, int] | None = None,
    scope_name: str | None = None,
) -> dict[str, object]:
    from app.learn.recognition.uei.canonical import content_sha256
    from app.learn.hybrid.windows_process_scope import process_scope_name

    process_identity = identity or {"pid": 123, "create_time_ns": 456}
    identities = [process_identity]
    profile = _production_vista_profile(tmp_path)
    scope = scope_name or process_scope_name({
        "run_id": "run/vista-cleanup",
        "workflow_revision": 1,
        "operation_id": "operation/vista-cleanup",
        "stage": "vista",
        "stage_execution_id": "stage/vista-cleanup",
    }, "vista")
    return {
        "contract_version": "hybrid_vista_model_lease_v2",
        "provider": "vista",
        "incarnation_id": content_sha256({
            "profile_id": profile["profile_id"],
            "process_identities": identities,
        }),
        "profile": profile,
        "process_identities": identities,
        "process_scope_name": scope,
        "process_scope_acquisition": {
            "contract_version": "hybrid_process_scope_acquisition_v1",
            "scope_name": scope,
            "member_pids": [process_identity["pid"]],
            "process_identities": identities,
        },
    }


class _FakeVistaScope:
    def __init__(self, name: str, *, create: bool, pids: list[int]) -> None:
        assert create is False
        self.name = name
        self._pids = pids

    def pids(self) -> list[int]:
        return list(self._pids)

    def close(self) -> None:
        pass


def _install_live_vista_observation(
    monkeypatch,
    *,
    lease: dict[str, object],
    process_status: str = "exact_live",
    scope_pids: list[int] | None = None,
    listener_pids: list[int] | None = None,
) -> None:
    from app.core import model_server
    from app.learn.hybrid import windows_process_scope

    identities = lease["process_identities"]
    expected_pids = [item["pid"] for item in identities]
    monkeypatch.setattr(model_server, "load_model_profiles", lambda: [dict(lease["profile"])])
    monkeypatch.setattr(
        model_server,
        "_probe_exact_qwen_process",
        lambda identity: {
            "status": process_status,
            "identity": dict(identity) if process_status == "exact_live" else None,
            **({} if process_status == "exact_live" else {"reason": "test"}),
        },
    )
    monkeypatch.setattr(
        windows_process_scope,
        "WindowsProcessScope",
        lambda name, create: _FakeVistaScope(
            name,
            create=create,
            pids=list(expected_pids if scope_pids is None else scope_pids),
        ),
    )
    monkeypatch.setattr(
        model_server,
        "_listening_pids_for_port",
        lambda port: list(expected_pids if listener_pids is None else listener_pids),
    )


def test_live_vista_lease_validator_attests_exact_profile_process_scope_and_listener(
    tmp_path,
    monkeypatch,
) -> None:
    from app.core.model_server import validate_live_hybrid_vista_model_lease

    lease = _production_vista_lease(tmp_path)
    _install_live_vista_observation(monkeypatch, lease=lease)

    assert validate_live_hybrid_vista_model_lease(
        lease,
        expected_profile_id="profile/local.vista",
    ) == lease["profile"]


@pytest.mark.parametrize(
    "failure",
    ["fabricated", "extra_field", "dead", "unobservable", "wrong_scope", "wrong_listener"],
)
def test_live_vista_lease_validator_fails_closed_on_unproved_runtime_identity(
    tmp_path,
    monkeypatch,
    failure: str,
) -> None:
    from app.core.model_server import validate_live_hybrid_vista_model_lease

    lease = _production_vista_lease(tmp_path)
    if failure == "fabricated":
        lease["incarnation_id"] = "f" * 64
    elif failure == "extra_field":
        lease["forged"] = True
    _install_live_vista_observation(
        monkeypatch,
        lease=lease,
        process_status=(
            "proven_absent" if failure == "dead"
            else "unobservable" if failure == "unobservable"
            else "exact_live"
        ),
        scope_pids=[] if failure == "wrong_scope" else None,
        listener_pids=[999] if failure == "wrong_listener" else None,
    )

    with pytest.raises((RuntimeError, ValueError)):
        validate_live_hybrid_vista_model_lease(
            lease,
            expected_profile_id="profile/local.vista",
        )


def _vista_cleanup_receipt(
    lease: dict[str, object],
    *,
    identity: dict[str, object] | None = None,
    evidence_lease: dict[str, object] | None = None,
) -> dict[str, object]:
    from app.learn.hybrid.gpu_lifecycle import release_hybrid_provider

    lineage = {
        "run_id": "run/vista-cleanup",
        "workflow_revision": 1,
        "operation_id": "operation/vista-cleanup",
        "stage": "vista",
        "stage_execution_id": "stage/vista-cleanup",
    }
    scope_name = lease["process_scope_name"]
    identities = lease["process_identities"]
    scope_cleanup = {
        "contract_version": "hybrid_windows_process_scope_v1",
        "scope_name": scope_name,
        "authority": "windows_job_object",
        "scope_absent_after_owner_close": False,
        "cleanup_status": "verified",
        "observed_member_pids_before": [item["pid"] for item in identities],
        "observed_member_identities_before": identities,
        "member_pids_after": [],
        "member_identities_after": [],
        "active_listeners_after": [],
        "pid_file_after": None,
        "stable_zero_observations": 3,
        "samples": [
            {"pids": [], "process_identities": [], "listeners": []},
            {"pids": [], "process_identities": [], "listeners": []},
            {"pids": [], "process_identities": [], "listeners": []},
        ],
    }
    provider_identity = identity or {
        "incarnation_id": lease["incarnation_id"],
        "profile_id": lease["profile"]["profile_id"],
        "process_identities": identities,
        "process_scope_name": scope_name,
    }
    inventory = {
        "contract_version": "hybrid_provider_process_inventory_v2",
        "provider": "vista",
        "observer_contract": "hybrid_vista_cleanup_observer_v1",
        "release_status": "verified",
        "termination_reason": "completed",
        "lineage": lineage,
        "provider_lease_identity": provider_identity,
        "predecessor_sha256": "a" * 64,
        "provider_result_sha256": "b" * 64,
        "provider_processes_after": [],
        "helper_processes_after": [],
        "orphan_descendant_pids": [],
        "active_listeners_after": [],
        "lease_files_after": [],
        "source_cleanup_evidence": {
            "contract_version": "hybrid_vista_cleanup_evidence_v2",
            "status": "verified",
            "model_lease": evidence_lease or lease,
            "stop_result": {"stopped": True},
            "inventory_observable": True,
            "process_scope_cleanup": scope_cleanup,
            "provider_probes": [
                {"status": "proven_absent", "identity": None, "reason": "no_such_process"}
                for _ in identities
            ],
        },
    }
    return release_hybrid_provider("vista", process_inventory=lambda _: inventory)


def test_vista_cleanup_validator_binds_exact_lease_and_reattests_live_absence(
    tmp_path,
    monkeypatch,
) -> None:
    from app.core import model_server

    lease = _production_vista_lease(tmp_path)
    receipt = _vista_cleanup_receipt(lease)
    monkeypatch.setattr(
        model_server,
        "_probe_exact_qwen_process",
        lambda _: {"status": "proven_absent", "identity": None, "reason": "no_such_process"},
    )
    monkeypatch.setattr(model_server, "_listening_pids_for_port", lambda _: [])

    assert model_server.validate_hybrid_vista_cleanup_receipt(
        receipt,
        model_lease=lease,
    ) == receipt


@pytest.mark.parametrize("mismatch", ["profile", "pid", "scope"])
def test_vista_cleanup_validator_rejects_cross_lease_identity(
    tmp_path,
    monkeypatch,
    mismatch: str,
) -> None:
    from app.core import model_server

    lease = _production_vista_lease(tmp_path)
    identity = {
        "incarnation_id": lease["incarnation_id"],
        "profile_id": lease["profile"]["profile_id"],
        "process_identities": lease["process_identities"],
        "process_scope_name": lease["process_scope_name"],
    }
    if mismatch == "profile":
        identity["profile_id"] = "profile/different"
    elif mismatch == "pid":
        identity["process_identities"] = [{"pid": 999, "create_time_ns": 456}]
    else:
        identity["process_scope_name"] = "Local\\AgentGuiHybrid-vista-" + "2" * 64
    receipt = _vista_cleanup_receipt(lease, identity=identity)
    monkeypatch.setattr(
        model_server,
        "_probe_exact_qwen_process",
        lambda _: {"status": "proven_absent", "identity": None, "reason": "no_such_process"},
    )
    monkeypatch.setattr(model_server, "_listening_pids_for_port", lambda _: [])

    with pytest.raises((RuntimeError, ValueError)):
        model_server.validate_hybrid_vista_cleanup_receipt(receipt, model_lease=lease)


@pytest.mark.parametrize("residue", ["exact_live", "unobservable", "listener"])
def test_vista_cleanup_validator_fails_closed_on_live_residue(
    tmp_path,
    monkeypatch,
    residue: str,
) -> None:
    from app.core import model_server

    lease = _production_vista_lease(tmp_path)
    receipt = _vista_cleanup_receipt(lease)
    monkeypatch.setattr(
        model_server,
        "_probe_exact_qwen_process",
        lambda identity: (
            {"status": "exact_live", "identity": identity}
            if residue == "exact_live"
            else {"status": "unobservable", "identity": None, "reason": "AccessDenied"}
            if residue == "unobservable"
            else {"status": "proven_absent", "identity": None, "reason": "no_such_process"}
        ),
    )
    monkeypatch.setattr(
        model_server,
        "_listening_pids_for_port",
        lambda _: [lease["process_identities"][0]["pid"]] if residue == "listener" else [],
    )

    with pytest.raises((RuntimeError, ValueError)):
        model_server.validate_hybrid_vista_cleanup_receipt(receipt, model_lease=lease)


@pytest.mark.parametrize("mutation", ["evidence_lease", "evidence_status", "scope_shape"])
def test_vista_cleanup_validator_rejects_unbound_or_malformed_source_evidence(
    tmp_path,
    monkeypatch,
    mutation: str,
) -> None:
    from app.core import model_server
    from app.learn.recognition.uei.canonical import seal_immutable

    lease = _production_vista_lease(tmp_path)
    receipt = _vista_cleanup_receipt(lease)
    mutated = {key: value for key, value in receipt.items() if key != "content_sha256"}
    evidence = dict(mutated["source_cleanup_evidence"])
    if mutation == "evidence_lease":
        evidence["model_lease"] = {**lease, "incarnation_id": "f" * 64}
    elif mutation == "evidence_status":
        evidence["status"] = "failed"
    else:
        evidence["process_scope_cleanup"] = {
            **evidence["process_scope_cleanup"],
            "forged": True,
        }
    mutated["source_cleanup_evidence"] = evidence
    receipt = seal_immutable(mutated)
    monkeypatch.setattr(
        model_server,
        "_probe_exact_qwen_process",
        lambda _: {"status": "proven_absent", "identity": None, "reason": "no_such_process"},
    )
    monkeypatch.setattr(model_server, "_listening_pids_for_port", lambda _: [])

    with pytest.raises((RuntimeError, ValueError)):
        model_server.validate_hybrid_vista_cleanup_receipt(receipt, model_lease=lease)


@pytest.mark.parametrize("scenario", ["success", "cancel_before", "cancel_after", "failure", "timeout"])
def test_registered_vista_capability_cleans_exactly_once_on_every_terminal_path(
    tmp_path,
    monkeypatch,
    scenario: str,
) -> None:
    from app.core import model_server
    from app.learn.hybrid.provider_capability_adapters import (
        VistaGroundingRefinementCompatibilityAdapter,
    )
    from app.learn.hybrid.vista_refinement import build_vista_requests
    from tests.test_learn_hybrid_vista_refinement import (
        _raw_result,
        _stored_authoritative_inputs,
    )

    fusion, bundle, inventory, bindings, qwen_receipt, context = _stored_authoritative_inputs(tmp_path)
    legacy_request = build_vista_requests(
        fusion,
        bundle,
        omni_inventory=inventory,
        qwen_bindings=bindings,
        qwen_cleanup_receipt=qwen_receipt,
        expected_workflow_revision=bundle["workflow_revision"],
    )[0]
    lease = _production_vista_lease(tmp_path)
    descriptor_seed = _sealed_grounding_descriptor(
        bundle_ref={"id": "bundle/local.vista-grounding", "content_sha256": "a" * 64},
    )
    bundle_ref = provider_bundle_ref(descriptor_seed)
    event = Event()
    if scenario == "cancel_before":
        event.set()
    cleaned = False
    cleanup_calls = 0
    runner_calls = 0

    from app.learn.hybrid import windows_process_scope

    monkeypatch.setattr(model_server, "load_model_profiles", lambda: [dict(lease["profile"])])
    monkeypatch.setattr(
        windows_process_scope,
        "WindowsProcessScope",
        lambda name, create: _FakeVistaScope(
            name,
            create=create,
            pids=[] if cleaned else [lease["process_identities"][0]["pid"]],
        ),
    )
    monkeypatch.setattr(
        model_server,
        "_probe_exact_qwen_process",
        lambda identity: (
            {"status": "proven_absent", "identity": None, "reason": "no_such_process"}
            if cleaned
            else {"status": "exact_live", "identity": dict(identity)}
        ),
    )
    monkeypatch.setattr(
        model_server,
        "_listening_pids_for_port",
        lambda _: [] if cleaned else [lease["process_identities"][0]["pid"]],
    )

    def runner(**_: object) -> dict[str, object]:
        nonlocal runner_calls
        runner_calls += 1
        if scenario == "cancel_after":
            event.set()
        if scenario == "failure":
            raise RuntimeError("provider failed")
        if scenario == "timeout":
            raise TimeoutError("provider timed out")
        return _raw_result(legacy_request)

    def cleanup() -> dict[str, object]:
        nonlocal cleaned, cleanup_calls
        cleanup_calls += 1
        cleaned = True
        return _vista_cleanup_receipt(lease)

    request = GroundingRefinementRequestV1(
        envelope=ProviderInvocationEnvelopeV1(
            bundle_ref=bundle_ref,
            capability="grounding_refinement",
            invocation_id=f"invocation/vista-{scenario}",
            capture_lineage_ref=legacy_request["capture_lineage_ref"],
            budget=ProviderRunBudget(1_000, 4_096, 8, 128, "vista-test"),
            resource_lease=lease,
            cancellation_event=event,
        ),
        candidate_id=legacy_request["candidate_id"],
        candidate_bbox=tuple(legacy_request["candidate_bbox_ref"]["xyxy"]),
        permitted_roi=tuple(legacy_request["roi_ref"]["xyxy"]),
        provider_request={"state": "BOUND", "vista_request": legacy_request},
    )
    adapter = VistaGroundingRefinementCompatibilityAdapter(
        bundle_ref=bundle_ref,
        provider_runner=runner,
        authoritative_context_resolver=lambda _: context,
    )
    registry = TrustedProviderBundleRegistry([(descriptor_seed, adapter)])

    outcome = invoke_with_capability_envelope(
        request=request,
        registry=registry,
        adapter=adapter,
        invoke=adapter.invoke,
        validate_result=lambda result, _: request.validate_result(result),
        cleanup=cleanup,
        validate_cleanup=lambda receipt: adapter.validate_cleanup(
            receipt=receipt,
            lease=lease,
            bundle_ref=bundle_ref,
            invocation_id=request.envelope.invocation_id,
        ),
    )

    assert cleanup_calls == 1
    assert outcome.cleanup.status == "clean"
    assert outcome.promoted is (scenario == "success")
    assert runner_calls == (0 if scenario == "cancel_before" else 1)
