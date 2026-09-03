"""Omni discovery compatibility adapter for the transient capability boundary."""

from __future__ import annotations

from hashlib import sha256

from app.learn.recognition.uei.canonical import canonical_json_bytes
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
    deterministic_neutral_source_item_id,
    reject_authority_shaped_payload,
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
