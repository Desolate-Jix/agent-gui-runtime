"""Omni discovery compatibility adapter for the transient capability boundary."""

from __future__ import annotations

from hashlib import sha256
from typing import Any, Callable

from app.learn.recognition.uei.canonical import canonical_json_bytes, seal_immutable
from app.learn.recognition.uei.contracts import UEIValidationError
from app.learn.recognition.uei.provider_adapters import (
    NormalizedProviderItem,
    NormalizedScreenParseOutput,
    ScreenParseProviderAdapter,
)
from app.learn.recognition.uei.provider_capabilities import (
    CandidateDiscoveryItemV1,
    CandidateDiscoveryRequestV1,
    CandidateDiscoveryResultV1,
    CapabilityCleanupOutcomeV1,
    GroundingRefinementRequestV1,
    GroundingRefinementResultV1,
    SemanticBindingRequestV1,
    SemanticBindingResultV1,
    deterministic_neutral_source_item_id,
    enforce_provider_native_output_budget,
    reject_authority_shaped_payload,
)
from app.learn.hybrid.vista_refinement import (
    _validated_request,
    normalize_vista_grounding_result,
    validate_vista_request_pre_acquisition,
)
from app.learn.hybrid.qwen_binding import (
    QwenBindingCancelled,
    QwenBindingTimeout,
    build_qwen_binding_request,
    normalize_qwen_semantic_result,
    project_semantic_result_to_hybrid_qwen_v1,
)


class OmniDiscoveryCompatibilityAdapter:
    capability = "candidate_discovery"

    def __init__(
        self,
        *,
        bundle_ref: dict[str, str],
        delegate: ScreenParseProviderAdapter,
    ) -> None:
        self.bundle_ref = dict(bundle_ref)
        self._delegate = delegate

    def invoke(self, request: CandidateDiscoveryRequestV1) -> CandidateDiscoveryResultV1:
        if not isinstance(request, CandidateDiscoveryRequestV1):
            raise UEIValidationError("provider_capability_invalid_discovery_request")
        if self.bundle_ref != dict(request.envelope.bundle_ref):
            raise UEIValidationError("provider_capability_bundle_mismatch")
        output = self._delegate.invoke(
            capture=request.capture,
            budget=request.envelope.budget,
            invocation_id=request.envelope.invocation_id,
            cancellation_event=request.envelope.cancellation_event,
        )
        return normalize_current_screen_parse_output(request=request, output=output)


def normalize_current_screen_parse_output(
    *,
    request: CandidateDiscoveryRequestV1,
    output: NormalizedScreenParseOutput,
) -> CandidateDiscoveryResultV1:
    """将现有 screen-parse 输出转换为瞬态、非授权的 discovery 结果。"""
    if not isinstance(request, CandidateDiscoveryRequestV1):
        raise UEIValidationError("provider_capability_invalid_discovery_request")
    _validate_screen_parse_output(request=request, output=output)
    items = tuple(
        _neutral_item(
            item=item,
            bundle_ref=dict(request.envelope.bundle_ref),
            source_index=index,
        )
        for index, item in enumerate(output.items)
    )
    result = CandidateDiscoveryResultV1(
        bundle_ref=dict(request.envelope.bundle_ref),
        invocation_id=request.envelope.invocation_id,
        capture_lineage_ref=dict(request.envelope.capture_lineage_ref),
        items=items,
        duration_ms=output.duration_ms,
        resource_units=output.resource_units,
    )
    request.validate_result(result)
    return result


def project_discovery_to_screen_parse_v1(
    result: CandidateDiscoveryResultV1,
) -> NormalizedScreenParseOutput:
    """投影回现有 UEI runtime 输入，不持久化 bundle 字段。"""
    if not isinstance(result, CandidateDiscoveryResultV1):
        raise UEIValidationError("provider_capability_invalid_discovery_result")
    reject_authority_shaped_payload(vars(result))
    if result.source_item_order != tuple(item.source_item_id for item in result.items):
        raise UEIValidationError("provider_capability_discovery_projection_order_mismatch")
    for item in result.items:
        reject_authority_shaped_payload(vars(item))
    return NormalizedScreenParseOutput(
        items=tuple(_screen_parse_item(item) for item in result.items),
        duration_ms=result.duration_ms,
        resource_units=result.resource_units,
    )


def _validate_screen_parse_output(
    *, request: CandidateDiscoveryRequestV1, output: object,
) -> None:
    if not isinstance(output, NormalizedScreenParseOutput):
        raise UEIValidationError("provider_capability_invalid_screen_parse_output")
    reject_authority_shaped_payload(vars(output))
    if not isinstance(output.items, tuple):
        raise UEIValidationError("provider_capability_invalid_screen_parse_items")
    width = request.capture.image_size["width"]
    height = request.capture.image_size["height"]
    for item in output.items:
        if not isinstance(item, NormalizedProviderItem):
            raise UEIValidationError("provider_capability_invalid_screen_parse_item")
        reject_authority_shaped_payload(vars(item))
        if item.kind not in {"element", "text", "role", "state", "icon", "structure"}:
            raise UEIValidationError("provider_capability_invalid_omni_kind")
        if item.source_coordinate_space != "capture_pixel_xyxy":
            raise UEIValidationError("provider_capability_invalid_omni_coordinate_space")
        bbox = item.source_bbox
        if (
            not isinstance(bbox, tuple) or len(bbox) != 4
            or any(isinstance(edge, bool) or not isinstance(edge, int) for edge in bbox)
            or not (0 <= bbox[0] < bbox[2] <= width and 0 <= bbox[1] < bbox[3] <= height)
        ):
            raise UEIValidationError("provider_capability_invalid_omni_bbox")


def _neutral_item(
    *,
    item: NormalizedProviderItem,
    bundle_ref: dict[str, str],
    source_index: int,
) -> CandidateDiscoveryItemV1:
    provider_source_item_id = item.source_item_id
    source_item_id = provider_source_item_id
    source_id_origin = "provider"
    if source_item_id is None:
        source_item_id = deterministic_neutral_source_item_id(
            bundle_ref=bundle_ref,
            source_index=source_index,
            native_fingerprint=_native_item_fingerprint(item),
        )
        source_id_origin = "synthesized"
    return CandidateDiscoveryItemV1(
        source_item_id=source_item_id,
        kind=item.kind,
        source_bbox=item.source_bbox,
        source_coordinate_space=item.source_coordinate_space,
        safe_text=item.safe_text,
        safe_role=item.safe_role,
        safe_states=item.safe_states,
        confidence=item.provider_confidence,
        provider_source_item_id=provider_source_item_id,
        source_id_origin=source_id_origin,
    )


def _native_item_fingerprint(item: NormalizedProviderItem) -> str:
    payload = {
        "kind": item.kind,
        "safe_text": item.safe_text,
        "safe_role": item.safe_role,
        "safe_states": list(item.safe_states),
        "source_bbox": list(item.source_bbox) if item.source_bbox is not None else None,
        "source_coordinate_space": item.source_coordinate_space,
        "provider_confidence": item.provider_confidence,
    }
    return sha256(canonical_json_bytes(payload)).hexdigest()


def _screen_parse_item(item: CandidateDiscoveryItemV1) -> NormalizedProviderItem:
    return NormalizedProviderItem(
        source_item_id=item.provider_source_item_id,
        kind=item.kind,
        safe_text=item.safe_text,
        source_bbox=item.source_bbox,
        source_coordinate_space=item.source_coordinate_space,
        safe_role=item.safe_role,
        safe_states=item.safe_states,
        provider_confidence=item.confidence,
    )


class QwenSemanticBindingCompatibilityAdapter:
    """将现有 Qwen wire/parser 约束投影到 transient semantic capability。"""

    capability = "semantic_binding"

    def __init__(
        self,
        *,
        bundle_ref: dict[str, str],
        model_runner: Callable[..., object],
    ) -> None:
        self.bundle_ref = dict(bundle_ref)
        self._model_runner = model_runner

    def validate_resource_lease(
        self,
        *,
        lease: dict[str, object],
        descriptor: dict[str, object],
        bundle_ref: dict[str, str],
    ) -> None:
        """要求活动 Qwen lease 与已封存 profile/incarnation 精确一致。"""
        if self.bundle_ref != dict(bundle_ref):
            raise UEIValidationError("provider_capability_resource_lease_mismatch")
        expected_profile_id = descriptor.get("profile_id")
        if (
            not isinstance(expected_profile_id, str)
            or not expected_profile_id
            or not isinstance(lease.get("profile_id"), str)
            or lease.get("profile_id") != expected_profile_id
            or not isinstance(lease.get("incarnation_id"), str)
            or not lease.get("incarnation_id")
        ):
            raise UEIValidationError("provider_capability_resource_lease_mismatch")
        from app.core.model_server import _profile_for_qwen_model_lease

        try:
            active_profile = _profile_for_qwen_model_lease(lease)
        except (RuntimeError, ValueError, TypeError) as error:
            raise UEIValidationError("provider_capability_resource_lease_mismatch") from error
        if active_profile.get("profile_id") != expected_profile_id:
            raise UEIValidationError("provider_capability_resource_lease_mismatch")

    def validate_cleanup(
        self,
        *,
        receipt: dict[str, object],
        lease: dict[str, object],
        bundle_ref: dict[str, str],
        invocation_id: str,
    ) -> CapabilityCleanupOutcomeV1:
        """只接受真实 managed Qwen release 的终态，并重新证明 owner lease 已失效。"""
        if self.bundle_ref != dict(bundle_ref) or not invocation_id:
            return CapabilityCleanupOutcomeV1("indeterminate", None)
        try:
            valid_terminal = _validate_qwen_release_terminal_receipt(receipt, lease)
            from app.core.model_server import qwen_model_lease_is_active

            if qwen_model_lease_is_active(lease):
                return CapabilityCleanupOutcomeV1("indeterminate", None)
        except (RuntimeError, TypeError, ValueError):
            return CapabilityCleanupOutcomeV1("indeterminate", None)
        return CapabilityCleanupOutcomeV1("clean", valid_terminal)

    def invoke(self, request: SemanticBindingRequestV1) -> SemanticBindingResultV1:
        if not isinstance(request, SemanticBindingRequestV1):
            raise UEIValidationError("provider_capability_invalid_semantic_request")
        if self.bundle_ref != dict(request.envelope.bundle_ref):
            raise UEIValidationError("provider_capability_bundle_mismatch")
        if not isinstance(request.envelope.resource_lease, dict):
            raise UEIValidationError("provider_capability_resource_lease_required")
        if (
            request.envelope.cancellation_event is not None
            and request.envelope.cancellation_event.is_set()
        ):
            raise QwenBindingCancelled("Qwen candidate binding cancelled")
        sealed_inventory = seal_immutable(dict(request.omni_inventory))
        native_request = build_qwen_binding_request(
            request.capture_bundle, sealed_inventory,
        )
        try:
            raw = self._model_runner(
                request=native_request,
                screenshot_bytes=request.screenshot_bytes,
                screenshot_media_type=request.screenshot_media_type,
                screenshot_sha256=request.screenshot_sha256,
                cancellation_event=request.envelope.cancellation_event,
                model_lease=request.envelope.resource_lease,
                timeout_seconds=request.envelope.budget.timeout_ms / 1000.0,
            )
        except TimeoutError as error:
            raise QwenBindingTimeout("Qwen model timeout") from error
        except RuntimeError as error:
            if (
                request.envelope.cancellation_event is not None
                and request.envelope.cancellation_event.is_set()
            ):
                raise QwenBindingCancelled("Qwen candidate binding cancelled") from error
            raise
        if (
            request.envelope.cancellation_event is not None
            and request.envelope.cancellation_event.is_set()
        ):
            raise QwenBindingCancelled("Qwen candidate binding cancelled")
        enforce_provider_native_output_budget(raw, request.envelope.budget)
        result = normalize_qwen_semantic_result(
            raw=raw,
            inventory=sealed_inventory,
            bundle_ref=dict(request.envelope.bundle_ref),
            invocation_id=request.envelope.invocation_id,
            context_ref=request.context_ref,
        )
        return request.validate_result(result)


def _validate_qwen_release_terminal_receipt(
    receipt: object, lease: dict[str, object],
) -> dict[str, object]:
    if not isinstance(receipt, dict) or receipt.get("lease") != lease:
        raise ValueError("Qwen release receipt lease mismatch")
    shared_fields = {
        "status", "lease", "shared_server_retained", "server_termination", "reason",
    }
    if set(receipt) == shared_fields:
        if (
            receipt.get("status") != "released"
            or receipt.get("shared_server_retained") is not True
            or receipt.get("server_termination")
            not in {"not_required_shared", "not_owned"}
            or not isinstance(receipt.get("reason"), str)
            or not receipt["reason"]
        ):
            raise ValueError("Qwen shared release receipt is not terminal")
        return dict(receipt)
    owned_fields = {
        "status", "lease", "shared_server_retained", "server_termination", "release",
        "after", "process_identity", "hybrid_descendant_cleanup",
        "hybrid_process_scope_name", "hybrid_process_scope_acquisition",
        "hybrid_process_scope_cleanup",
    }
    retry_owned_fields = {
        "status", "lease", "shared_server_retained", "server_termination", "release",
        "after", "process_identity", "hybrid_descendant_cleanup",
    }
    terminal = receipt.get("server_termination")
    if terminal == "verified_exact_process_exited":
        expected_fields = owned_fields
    elif terminal == "verified_exact_process_proven_absent_on_retry":
        expected_fields = retry_owned_fields
    else:
        raise ValueError("Qwen release receipt shape is invalid")
    release = receipt.get("release")
    if (
        set(receipt) != expected_fields
        or receipt.get("status") != "released"
        or receipt.get("shared_server_retained") is not False
        or receipt.get("process_identity") != lease.get("server_process_identity")
        or not isinstance(release, dict)
        or set(release) != {"status", "identity", "reason"}
        or release.get("status") != "proven_absent"
        or release.get("identity") is not None
        or release.get("reason") not in {"no_such_process", "not_running"}
        or not isinstance(receipt.get("after"), dict)
        or not isinstance(receipt.get("hybrid_descendant_cleanup"), dict)
        or receipt["hybrid_descendant_cleanup"].get("status") != "verified"
    ):
        raise ValueError("Qwen owned release receipt is not terminal")
    if terminal == "verified_exact_process_exited" and (
        not isinstance(receipt.get("hybrid_process_scope_name"), str)
        or not receipt["hybrid_process_scope_name"]
        or not isinstance(receipt.get("hybrid_process_scope_acquisition"), dict)
        or not isinstance(receipt.get("hybrid_process_scope_cleanup"), dict)
        or receipt["hybrid_process_scope_cleanup"].get("cleanup_status") != "verified"
    ):
        raise ValueError("Qwen owned release receipt is not terminal")
    return dict(receipt)


class VistaGroundingRefinementCompatibilityAdapter:
    """将现有 VISTA 调用投影为受限的 grounding capability。"""

    capability = "grounding_refinement"

    def __init__(
        self,
        *,
        bundle_ref: dict[str, str],
        provider_runner: Callable[..., object],
        authoritative_context_resolver: Callable[
            [GroundingRefinementRequestV1], dict[str, object]
        ],
    ) -> None:
        self.bundle_ref = dict(bundle_ref)
        self._provider_runner = provider_runner
        if not callable(authoritative_context_resolver):
            raise TypeError("VISTA authoritative context resolver is required")
        self._authoritative_context_resolver = authoritative_context_resolver

    def validate_resource_lease(
        self, *, lease: dict[str, object], descriptor: dict[str, object], bundle_ref: dict[str, str],
    ) -> None:
        """验证 VISTA v2 精确 lease 的 profile、进程 scope 与 listener 所有权。"""
        if self.bundle_ref != dict(bundle_ref):
            raise UEIValidationError("provider_capability_resource_lease_mismatch")
        from app.core.model_server import validate_live_hybrid_vista_model_lease

        try:
            validate_live_hybrid_vista_model_lease(
                lease,
                expected_profile_id=descriptor.get("profile_id"),
            )
        except (RuntimeError, TypeError, ValueError) as error:
            raise UEIValidationError("provider_capability_resource_lease_mismatch")

    def validate_cleanup(
        self, *, receipt: dict[str, object], lease: dict[str, object], bundle_ref: dict[str, str], invocation_id: str,
    ) -> CapabilityCleanupOutcomeV1:
        if self.bundle_ref != dict(bundle_ref) or not invocation_id:
            return CapabilityCleanupOutcomeV1("indeterminate", None)
        try:
            from app.core.model_server import validate_hybrid_vista_cleanup_receipt

            validated = validate_hybrid_vista_cleanup_receipt(
                receipt,
                model_lease=lease,
            )
        except (RuntimeError, TypeError, ValueError):
            return CapabilityCleanupOutcomeV1("indeterminate", None)
        return CapabilityCleanupOutcomeV1("clean", validated)

    def invoke(
        self, request: GroundingRefinementRequestV1,
    ) -> GroundingRefinementResultV1:
        if not isinstance(request, GroundingRefinementRequestV1):
            raise UEIValidationError("provider_capability_invalid_grounding_request")
        if self.bundle_ref != dict(request.envelope.bundle_ref):
            raise UEIValidationError("provider_capability_bundle_mismatch")
        if not isinstance(request.envelope.resource_lease, dict):
            raise UEIValidationError("provider_capability_resource_lease_required")
        if (
            request.envelope.cancellation_event is not None
            and request.envelope.cancellation_event.is_set()
        ):
            raise UEIValidationError("provider_capability_cancelled")
        provider_request = dict(request.provider_request)
        legacy_request = provider_request.get("vista_request")
        if not isinstance(legacy_request, dict):
            raise UEIValidationError("provider_capability_invalid_vista_request")
        authoritative_context = self._authoritative_context_resolver(request)
        validated_request = validate_vista_request_pre_acquisition(
            request=legacy_request,
            authoritative_context=authoritative_context,
        )
        _validate_vista_grounding_request(request=request, legacy_request=validated_request)
        raw = self._provider_runner(
            request=validated_request,
            timeout_seconds=request.envelope.budget.timeout_ms / 1000.0,
            cancellation_event=request.envelope.cancellation_event,
            model_lease=request.envelope.resource_lease,
        )
        if (
            request.envelope.cancellation_event is not None
            and request.envelope.cancellation_event.is_set()
        ):
            raise UEIValidationError("provider_capability_cancelled")
        enforce_provider_native_output_budget(raw, request.envelope.budget)
        if not isinstance(raw, dict):
            raise UEIValidationError("provider_capability_invalid_vista_result")
        result = normalize_vista_grounding_result(
            request=validated_request, raw_result=raw,
            bundle_ref=dict(request.envelope.bundle_ref),
            invocation_id=request.envelope.invocation_id,
            authoritative_context=authoritative_context,
        )
        return request.validate_result(result)


def _validate_vista_grounding_request(
    *, request: GroundingRefinementRequestV1, legacy_request: dict[str, object],
) -> None:
    """确保 compatibility runner 只能细化同一个已绑定候选。"""
    validated = _validated_request(legacy_request)
    if (
        validated.get("candidate_id") != request.candidate_id
        or tuple(validated.get("candidate_bbox_ref", {}).get("xyxy", ()))
        != request.candidate_bbox
        or tuple(validated.get("roi_ref", {}).get("xyxy", ()))
        != request.permitted_roi
        or validated.get("capture_lineage_ref") != dict(request.envelope.capture_lineage_ref)
    ):
        raise UEIValidationError("provider_capability_grounding_request_mismatch")
