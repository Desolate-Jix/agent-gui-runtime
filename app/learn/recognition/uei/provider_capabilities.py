"""Transient, non-authorizing provider capability contracts."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import math
import re
from threading import Event
from typing import Callable, Generic, Protocol, TypeVar

from app.learn.hybrid.contracts import validate_capture_identity, validate_omni_inventory
from app.learn.recognition.uei.canonical import canonical_json_bytes, content_sha256
from app.learn.recognition.uei.contracts import UEIValidationError
from app.learn.recognition.uei.provider_adapters import (
    AdapterFailure,
    ProviderRunBudget,
    RestrictedCaptureLease,
)
from app.learn.recognition.uei.provider_bundles import PROVIDER_CAPABILITIES


AUTHORITY_SHAPED_KEYS = frozenset({
    "approved_to_click", "execute", "final_submit", "send", "confirm", "payment",
})

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CAPTURE_COORDINATE_SPACE = "capture_pixel_xyxy"
_BINDING_STATUSES = frozenset({"BOUND", "UNBOUND", "AMBIGUOUS", "CONFLICT"})
_MAX_ID_LENGTH = 512
_MAX_ITEM_TEXT_LENGTH = 4_096
_MAX_ROLE_LENGTH = 64
_MAX_LABEL_LENGTH = 256
_MAX_STATE_COUNT = 64
_TERMINAL_CLEANUP_STATUSES = frozenset({"clean", "not_required"})

TRequest = TypeVar("TRequest")
TResult = TypeVar("TResult")


def _non_empty_string(value: object, *, name: str, maximum: int = _MAX_ID_LENGTH) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise UEIValidationError(f"provider_capability_invalid_{name}")
    return value


def _sha256_string(value: object, *, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise UEIValidationError(f"provider_capability_invalid_{name}")
    return value


def _ref(value: object, *, name: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"id", "content_sha256"}:
        raise UEIValidationError(f"provider_capability_invalid_{name}_ref")
    identifier = _non_empty_string(value["id"], name=f"{name}_id")
    digest = _sha256_string(value["content_sha256"], name=f"{name}_content_sha256")
    return {"id": identifier, "content_sha256": digest}


def _same_ref(left: dict[str, str], right: dict[str, str], *, name: str) -> None:
    if left != right:
        raise UEIValidationError(f"provider_capability_{name}_mismatch")


class _FrozenDict(dict[object, object]):
    """保持 dict/JSON 兼容性、但不允许就地修改的防御性副本。"""

    __slots__ = ()

    def __init__(self, value: Mapping[object, object]) -> None:
        dict.__init__(self, value)

    @staticmethod
    def _immutable(*args: object, **kwargs: object) -> None:
        raise TypeError("provider capability evidence is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable

    def copy(self) -> dict[object, object]:
        return dict(self)

    def __deepcopy__(self, memo: dict[int, object]) -> dict[object, object]:
        return deepcopy(dict(self), memo)


class _FrozenList(list[object]):
    """保持 list/JSON 兼容性的不可变证据序列。"""

    __slots__ = ()

    def __init__(self, value: list[object] | tuple[object, ...]) -> None:
        list.__init__(self, value)

    @staticmethod
    def _immutable(*args: object, **kwargs: object) -> None:
        raise TypeError("provider capability evidence is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable

    def copy(self) -> list[object]:
        return list(self)

    def __deepcopy__(self, memo: dict[int, object]) -> list[object]:
        return deepcopy(list(self), memo)


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return _FrozenDict({key: _freeze(child) for key, child in value.items()})
    if isinstance(value, list):
        return _FrozenList([_freeze(child) for child in value])
    if isinstance(value, tuple):
        return tuple(_freeze(child) for child in value)
    return value


def _finite_confidence(value: object, *, name: str, optional: bool = False) -> float | int | None:
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise UEIValidationError(f"provider_capability_invalid_{name}")
    return value


def _xyxy(value: object, *, name: str) -> tuple[int, int, int, int]:
    if not isinstance(value, tuple) or len(value) != 4 or any(
        isinstance(edge, bool) or not isinstance(edge, int) or edge < 0 for edge in value
    ):
        raise UEIValidationError(f"provider_capability_invalid_{name}")
    x1, y1, x2, y2 = value
    if not x1 < x2 or not y1 < y2:
        raise UEIValidationError(f"provider_capability_invalid_{name}")
    return value


def _point(value: object, *, name: str) -> tuple[float, float]:
    if not isinstance(value, tuple) or len(value) != 2 or any(
        isinstance(axis, bool) or not isinstance(axis, (int, float)) or not math.isfinite(axis)
        for axis in value
    ):
        raise UEIValidationError(f"provider_capability_invalid_{name}")
    return value


def _non_negative_int(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise UEIValidationError(f"provider_capability_invalid_{name}")
    return value


def _semantic_capture_identity(value: object, *, name: str) -> tuple[dict[str, str], str, dict[str, int]]:
    if not isinstance(value, dict):
        raise UEIValidationError(f"provider_capability_invalid_{name}")
    try:
        identity = validate_capture_identity(value)
    except (TypeError, ValueError) as error:
        raise UEIValidationError(f"provider_capability_invalid_{name}") from error
    return (
        _ref(identity["capture_lineage_ref"], name="capture_lineage"),
        _sha256_string(identity["screenshot_sha256"], name="screenshot_sha256"),
        identity["image_size"],
    )


def _sealed_context_ref(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise UEIValidationError("provider_capability_invalid_context")
    context_id = _non_empty_string(value.get("context_id"), name="context_id")
    declared_sha256 = _sha256_string(
        value.get("content_sha256"), name="context_content_sha256"
    )
    try:
        actual_sha256 = content_sha256(value)
    except ValueError as error:
        raise UEIValidationError("provider_capability_invalid_context") from error
    if actual_sha256 != declared_sha256:
        raise UEIValidationError("provider_capability_invalid_context")
    return {"id": context_id, "content_sha256": declared_sha256}


def _candidate_ids_from_inventory(
    value: object, *, capture_identity: tuple[dict[str, str], str, dict[str, int]]
) -> tuple[tuple[str, ...], dict[str, object]]:
    if not isinstance(value, dict):
        raise UEIValidationError("provider_capability_invalid_omni_inventory")
    try:
        inventory = validate_omni_inventory(value)
    except (TypeError, ValueError) as error:
        raise UEIValidationError("provider_capability_invalid_omni_inventory") from error
    inventory_identity = _semantic_capture_identity(
        inventory.get("capture_identity"), name="omni_inventory"
    )
    for actual, expected in zip(inventory_identity, capture_identity):
        if actual != expected:
            raise UEIValidationError("provider_capability_lineage_mismatch")
    return tuple(candidate["candidate_id"] for candidate in inventory["candidates"]), inventory


def reject_authority_shaped_payload(value: object) -> None:
    """Reject nested provider data that attempts to carry execution authority."""
    if isinstance(value, Mapping):
        forbidden = sorted(set(value) & AUTHORITY_SHAPED_KEYS)
        if forbidden:
            raise UEIValidationError(
                f"provider_capability_non_authorizing_{forbidden[0]}"
            )
        for child in value.values():
            reject_authority_shaped_payload(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            reject_authority_shaped_payload(child)


def effective_provider_budget(
    caller: ProviderRunBudget, bundle: ProviderRunBudget
) -> ProviderRunBudget:
    """Return the strictest compatible caller and sealed-bundle resource budget."""
    if not isinstance(caller, ProviderRunBudget) or not isinstance(bundle, ProviderRunBudget):
        raise UEIValidationError("provider_capability_invalid_budget")
    if caller.resource_group != bundle.resource_group:
        raise UEIValidationError("provider_capability_resource_group_mismatch")
    return ProviderRunBudget(
        min(caller.timeout_ms, bundle.timeout_ms),
        min(caller.max_output_bytes, bundle.max_output_bytes),
        min(caller.max_element_count, bundle.max_element_count),
        min(caller.max_string_length, bundle.max_string_length),
        caller.resource_group,
    )


def deterministic_neutral_source_item_id(
    *, bundle_ref: dict[str, str], source_index: int, native_fingerprint: str
) -> str:
    """Derive a provider-neutral stable source identity without native payload retention."""
    reference = _ref(bundle_ref, name="bundle")
    if isinstance(source_index, bool) or not isinstance(source_index, int) or source_index < 0:
        raise UEIValidationError("provider_capability_invalid_source_index")
    fingerprint = _sha256_string(native_fingerprint, name="native_fingerprint")
    payload = {
        "bundle_ref": reference,
        "native_fingerprint": fingerprint,
        "source_index": source_index,
    }
    return "source/" + sha256(canonical_json_bytes(payload)).hexdigest()


@dataclass(frozen=True)
class ProviderInvocationEnvelopeV1:
    bundle_ref: dict[str, str]
    capability: str
    invocation_id: str
    capture_lineage_ref: dict[str, str]
    budget: ProviderRunBudget
    resource_lease: dict[str, object] | None = None
    cancellation_event: Event | None = None

    def __post_init__(self) -> None:
        _ref(self.bundle_ref, name="bundle")
        if self.capability not in PROVIDER_CAPABILITIES:
            raise UEIValidationError("provider_capability_invalid_capability")
        _non_empty_string(self.invocation_id, name="invocation_id")
        _ref(self.capture_lineage_ref, name="capture_lineage")
        if not isinstance(self.budget, ProviderRunBudget):
            raise UEIValidationError("provider_capability_invalid_budget")
        if self.resource_lease is not None and not isinstance(self.resource_lease, dict):
            raise UEIValidationError("provider_capability_invalid_resource_lease")
        if self.cancellation_event is not None and not isinstance(self.cancellation_event, Event):
            raise UEIValidationError("provider_capability_invalid_cancellation_event")
        object.__setattr__(self, "bundle_ref", _freeze(self.bundle_ref))
        object.__setattr__(self, "capture_lineage_ref", _freeze(self.capture_lineage_ref))
        if self.resource_lease is not None:
            object.__setattr__(self, "resource_lease", _freeze(self.resource_lease))


@dataclass(frozen=True)
class CapabilityCleanupOutcomeV1:
    status: str
    receipt: dict[str, object] | None


@dataclass(frozen=True)
class CapabilityInvocationFailure:
    stage: str
    reason: str
    retryable: bool
    cleanup_status: str


@dataclass(frozen=True)
class CapabilityInvocationOutcome(Generic[TResult]):
    result: TResult | None
    failure: CapabilityInvocationFailure | None
    cleanup: CapabilityCleanupOutcomeV1
    promoted: bool


def _invocation_envelope_failure(
    *, request: object, adapter: object, cleanup: Callable[[], dict[str, object]] | None
) -> str | None:
    envelope = getattr(request, "envelope", None)
    if not isinstance(envelope, ProviderInvocationEnvelopeV1):
        return "invalid_envelope"
    if not isinstance(envelope.budget, ProviderRunBudget):
        return "invalid_budget"
    adapter_bundle_ref = getattr(adapter, "bundle_ref", None)
    if not isinstance(adapter_bundle_ref, Mapping) or dict(adapter_bundle_ref) != dict(envelope.bundle_ref):
        return "unknown_bundle"
    adapter_capability = getattr(adapter, "capability", None)
    descriptor = getattr(adapter, "descriptor", None)
    if adapter_capability is None and isinstance(descriptor, Mapping):
        adapter_capability = descriptor.get("capability")
    if adapter_capability is not None and adapter_capability != envelope.capability:
        return "capability_mismatch"
    if envelope.resource_lease is not None and cleanup is None:
        return "resource_cleanup_required"
    if not bool(getattr(adapter, "requires_managed_resource", False)):
        return None
    lease = envelope.resource_lease
    if not isinstance(lease, Mapping):
        return "resource_lease_required"
    if not isinstance(descriptor, Mapping):
        return "managed_descriptor_invalid"
    descriptor_bundle_ref = descriptor.get("bundle_ref")
    if descriptor_bundle_ref is None and {
        "bundle_id", "content_sha256"
    }.issubset(descriptor):
        descriptor_bundle_ref = {
            "id": descriptor["bundle_id"],
            "content_sha256": descriptor["content_sha256"],
        }
    if (
        not isinstance(descriptor_bundle_ref, Mapping)
        or dict(descriptor_bundle_ref) != dict(envelope.bundle_ref)
    ):
        return "unknown_bundle"
    profile_id = descriptor.get("profile_id")
    if not isinstance(profile_id, str) or lease.get("profile_id") != profile_id:
        return "resource_lease_profile_mismatch"
    expected_incarnation = getattr(adapter, "incarnation_id", None)
    if expected_incarnation is None:
        expected_incarnation = descriptor.get("incarnation_id")
    if (
        not isinstance(expected_incarnation, str)
        or not expected_incarnation
        or lease.get("incarnation_id") != expected_incarnation
    ):
        return "resource_lease_stale"
    return None


def _cleanup_outcome(
    *, cleanup: Callable[[], dict[str, object]] | None,
    acquired: bool,
    validate_cleanup: Callable[[dict[str, object]], CapabilityCleanupOutcomeV1],
) -> CapabilityCleanupOutcomeV1:
    if not acquired or cleanup is None:
        return CapabilityCleanupOutcomeV1("not_required", None)
    try:
        receipt = cleanup()
        validated = validate_cleanup(receipt)
    except Exception:
        return CapabilityCleanupOutcomeV1("indeterminate", None)
    if not isinstance(validated, CapabilityCleanupOutcomeV1):
        return CapabilityCleanupOutcomeV1("indeterminate", receipt)
    return CapabilityCleanupOutcomeV1(validated.status, receipt)


def invoke_with_capability_envelope(
    *,
    request: TRequest,
    adapter: object,
    invoke: Callable[[TRequest], TResult],
    validate_result: Callable[[TResult, ProviderRunBudget], TResult],
    cleanup: Callable[[], dict[str, object]] | None,
    validate_cleanup: Callable[[dict[str, object]], CapabilityCleanupOutcomeV1],
) -> CapabilityInvocationOutcome[TResult]:
    """执行一次受限 provider 调用；不持久化、不重试、不授予权限。"""
    failure: CapabilityInvocationFailure | None = None
    result: TResult | None = None
    promoted = False
    acquired = False
    terminal_cleanup = CapabilityCleanupOutcomeV1("not_required", None)
    try:
        envelope = getattr(request, "envelope", None)
        validation_failure = _invocation_envelope_failure(
            request=request, adapter=adapter, cleanup=cleanup
        )
        if validation_failure is not None:
            failure = CapabilityInvocationFailure(
                "validation", validation_failure, False, "not_required"
            )
        elif envelope.cancellation_event is not None and envelope.cancellation_event.is_set():
            failure = CapabilityInvocationFailure("cancellation", "cancelled", False, "not_required")
        else:
            try:
                acquired = True
                raw_result = invoke(request)
            except AdapterFailure as error:
                failure = CapabilityInvocationFailure(
                    "invocation", error.reason_class, error.retryable, "not_required"
                )
            except Exception:
                failure = CapabilityInvocationFailure(
                    "invocation", "provider_failed", False, "not_required"
                )
            else:
                if envelope.cancellation_event is not None and envelope.cancellation_event.is_set():
                    failure = CapabilityInvocationFailure(
                        "cancellation", "cancelled", False, "not_required"
                    )
                else:
                    try:
                        validated_result = validate_result(raw_result, envelope.budget)
                    except Exception:
                        failure = CapabilityInvocationFailure(
                            "validation", "result_validation_failed", False, "not_required"
                        )
                    else:
                        if envelope.cancellation_event is not None and envelope.cancellation_event.is_set():
                            failure = CapabilityInvocationFailure(
                                "cancellation", "cancelled", False, "not_required"
                            )
                        else:
                            result = validated_result
                            promoted = True
    finally:
        terminal_cleanup = _cleanup_outcome(
            cleanup=cleanup, acquired=acquired, validate_cleanup=validate_cleanup
        )
    if terminal_cleanup.status not in _TERMINAL_CLEANUP_STATUSES:
        return CapabilityInvocationOutcome(
            result=None,
            failure=CapabilityInvocationFailure(
                "cleanup", "cleanup_ambiguous", False, terminal_cleanup.status
            ),
            cleanup=terminal_cleanup,
            promoted=False,
        )
    if failure is not None:
        failure = CapabilityInvocationFailure(
            failure.stage, failure.reason, failure.retryable, terminal_cleanup.status
        )
    return CapabilityInvocationOutcome(
        result=result, failure=failure, cleanup=terminal_cleanup, promoted=promoted
    )


@dataclass(frozen=True)
class CandidateDiscoveryRequestV1:
    envelope: ProviderInvocationEnvelopeV1
    capture: RestrictedCaptureLease

    def __post_init__(self) -> None:
        if not isinstance(self.envelope, ProviderInvocationEnvelopeV1):
            raise UEIValidationError("provider_capability_invalid_envelope")
        if self.envelope.capability != "candidate_discovery":
            raise UEIValidationError("provider_capability_capability_mismatch")
        if not isinstance(self.capture, RestrictedCaptureLease):
            raise UEIValidationError("provider_capability_invalid_capture")
        capture_lineage = _ref(self.capture.capture_lineage_ref, name="capture_lineage")
        _same_ref(self.envelope.capture_lineage_ref, capture_lineage, name="lineage")
        _ref(self.capture.artifact_ref, name="artifact")
        _sha256_string(self.capture.artifact_sha256, name="artifact_sha256")
        _non_empty_string(self.capture.capture_id, name="capture_id")
        if (
            not isinstance(self.capture.image_size, dict)
            or set(self.capture.image_size) != {"width", "height"}
            or any(isinstance(edge, bool) or not isinstance(edge, int) or edge <= 0 for edge in self.capture.image_size.values())
        ):
            raise UEIValidationError("provider_capability_invalid_capture")
        object.__setattr__(
            self,
            "capture",
            RestrictedCaptureLease(
                request_ref=_freeze(self.capture.request_ref),
                capture_lineage_ref=_freeze(self.capture.capture_lineage_ref),
                artifact_ref=_freeze(self.capture.artifact_ref),
                capture_id=self.capture.capture_id,
                artifact_sha256=self.capture.artifact_sha256,
                image_size=_freeze(self.capture.image_size),
                local_path=self.capture.local_path,
            ),
        )

    def validate_result(self, result: CandidateDiscoveryResultV1) -> CandidateDiscoveryResultV1:
        """Bind discovery evidence to this exact invocation and immutable capture."""
        if not isinstance(result, CandidateDiscoveryResultV1):
            raise UEIValidationError("provider_capability_invalid_discovery_result")
        _same_ref(self.envelope.bundle_ref, result.bundle_ref, name="bundle")
        _same_ref(self.envelope.capture_lineage_ref, result.capture_lineage_ref, name="lineage")
        if self.envelope.invocation_id != result.invocation_id:
            raise UEIValidationError("provider_capability_invocation_mismatch")
        return result


@dataclass(frozen=True)
class CandidateDiscoveryItemV1:
    source_item_id: str
    kind: str
    source_bbox: tuple[int, int, int, int] | None
    source_coordinate_space: str
    safe_text: str | None = None
    safe_role: str | None = None
    safe_states: tuple[str, ...] = ()
    confidence: float | None = None

    def __post_init__(self) -> None:
        _non_empty_string(self.source_item_id, name="source_item_id")
        _non_empty_string(self.kind, name="kind")
        if self.source_bbox is not None:
            _xyxy(self.source_bbox, name="source_bbox")
        _non_empty_string(self.source_coordinate_space, name="source_coordinate_space", maximum=128)
        for name, value, maximum in (
            ("safe_text", self.safe_text, _MAX_ITEM_TEXT_LENGTH),
            ("safe_role", self.safe_role, _MAX_ROLE_LENGTH),
        ):
            if value is not None:
                _non_empty_string(value, name=name, maximum=maximum)
        if not isinstance(self.safe_states, tuple) or len(self.safe_states) > _MAX_STATE_COUNT:
            raise UEIValidationError("provider_capability_invalid_safe_states")
        if len(set(self.safe_states)) != len(self.safe_states):
            raise UEIValidationError("provider_capability_invalid_safe_states")
        for state in self.safe_states:
            _non_empty_string(state, name="safe_state", maximum=_MAX_ROLE_LENGTH)
        _finite_confidence(self.confidence, name="confidence", optional=True)


@dataclass(frozen=True)
class CandidateDiscoveryResultV1:
    bundle_ref: dict[str, str]
    invocation_id: str
    capture_lineage_ref: dict[str, str]
    items: tuple[CandidateDiscoveryItemV1, ...]
    duration_ms: int
    resource_units: int

    def __post_init__(self) -> None:
        _ref(self.bundle_ref, name="bundle")
        _non_empty_string(self.invocation_id, name="invocation_id")
        _ref(self.capture_lineage_ref, name="capture_lineage")
        if not isinstance(self.items, tuple) or any(not isinstance(item, CandidateDiscoveryItemV1) for item in self.items):
            raise UEIValidationError("provider_capability_invalid_discovery_items")
        ids = [item.source_item_id for item in self.items]
        if len(set(ids)) != len(ids):
            raise UEIValidationError("provider_capability_candidate_duplicate")
        _non_negative_int(self.duration_ms, name="duration_ms")
        _non_negative_int(self.resource_units, name="resource_units")
        object.__setattr__(self, "bundle_ref", _freeze(self.bundle_ref))
        object.__setattr__(self, "capture_lineage_ref", _freeze(self.capture_lineage_ref))


@dataclass(frozen=True)
class SemanticBindingRequestV1:
    envelope: ProviderInvocationEnvelopeV1
    ordered_candidate_ids: tuple[str, ...]
    capture_bundle: dict[str, object]
    omni_inventory: dict[str, object]
    context_ref: dict[str, str]
    screenshot_bytes: bytes
    screenshot_media_type: str
    screenshot_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.envelope, ProviderInvocationEnvelopeV1):
            raise UEIValidationError("provider_capability_invalid_envelope")
        if self.envelope.capability != "semantic_binding":
            raise UEIValidationError("provider_capability_capability_mismatch")
        if not isinstance(self.ordered_candidate_ids, tuple):
            raise UEIValidationError("provider_capability_invalid_candidate_order")
        supplied_ids = tuple(_non_empty_string(item, name="candidate_id") for item in self.ordered_candidate_ids)
        if len(set(supplied_ids)) != len(supplied_ids):
            raise UEIValidationError("provider_capability_candidate_duplicate")
        if not isinstance(self.capture_bundle, dict) or not isinstance(self.omni_inventory, dict):
            raise UEIValidationError("provider_capability_invalid_semantic_input")
        capture_lineage = _ref(
            self.capture_bundle.get("capture_lineage_ref"), name="capture_lineage"
        )
        _same_ref(self.envelope.capture_lineage_ref, capture_lineage, name="lineage")
        capture_identity = _semantic_capture_identity(
            self.capture_bundle.get("capture_identity"), name="capture_bundle"
        )
        _same_ref(self.envelope.capture_lineage_ref, capture_identity[0], name="lineage")
        bundle_context_ref = _ref(self.capture_bundle.get("context_ref"), name="context")
        _same_ref(bundle_context_ref, _ref(self.context_ref, name="context"), name="context")
        context = self.capture_bundle.get("context")
        _same_ref(bundle_context_ref, _sealed_context_ref(context), name="context")
        if not isinstance(context, dict):
            raise UEIValidationError("provider_capability_invalid_context")
        _same_ref(
            self.envelope.capture_lineage_ref,
            _ref(context.get("capture_lineage_ref"), name="capture_lineage"),
            name="lineage",
        )
        expected_ids, validated_inventory = _candidate_ids_from_inventory(
            self.omni_inventory, capture_identity=capture_identity
        )
        if supplied_ids != expected_ids:
            raise UEIValidationError("provider_capability_candidate_order_mismatch")
        if not isinstance(self.screenshot_bytes, bytes) or not self.screenshot_bytes:
            raise UEIValidationError("provider_capability_invalid_screenshot")
        _non_empty_string(self.screenshot_media_type, name="screenshot_media_type", maximum=128)
        declared_sha256 = _sha256_string(self.screenshot_sha256, name="screenshot_sha256")
        if sha256(self.screenshot_bytes).hexdigest() != declared_sha256:
            raise UEIValidationError("provider_capability_screenshot_sha256_mismatch")
        if declared_sha256 != capture_identity[1]:
            raise UEIValidationError("provider_capability_screenshot_sha256_mismatch")
        object.__setattr__(self, "capture_bundle", _freeze(self.capture_bundle))
        object.__setattr__(self, "omni_inventory", _freeze(validated_inventory))
        object.__setattr__(self, "context_ref", _freeze(self.context_ref))

    def validate_result(self, result: SemanticBindingResultV1) -> SemanticBindingResultV1:
        """Bind semantic output to the request's immutable closed candidate order."""
        if not isinstance(result, SemanticBindingResultV1):
            raise UEIValidationError("provider_capability_invalid_semantic_result")
        _same_ref(self.envelope.bundle_ref, result.bundle_ref, name="bundle")
        _same_ref(self.envelope.capture_lineage_ref, result.capture_lineage_ref, name="lineage")
        if self.envelope.invocation_id != result.invocation_id:
            raise UEIValidationError("provider_capability_invocation_mismatch")
        actual_ids = tuple(binding.candidate_id for binding in result.bindings)
        if actual_ids != self.ordered_candidate_ids:
            raise UEIValidationError("provider_capability_candidate_order_mismatch")
        return result


@dataclass(frozen=True)
class SemanticBindingItemV1:
    candidate_id: str
    role: str
    label: str
    binding_status: str
    confidence: float

    def __post_init__(self) -> None:
        _non_empty_string(self.candidate_id, name="candidate_id")
        _non_empty_string(self.role, name="role", maximum=_MAX_ROLE_LENGTH)
        _non_empty_string(self.label, name="label", maximum=_MAX_LABEL_LENGTH)
        if self.binding_status not in _BINDING_STATUSES:
            raise UEIValidationError("provider_capability_invalid_binding_status")
        _finite_confidence(self.confidence, name="confidence")


@dataclass(frozen=True)
class SemanticBindingResultV1:
    bundle_ref: dict[str, str]
    invocation_id: str
    capture_lineage_ref: dict[str, str]
    bindings: tuple[SemanticBindingItemV1, ...]
    duration_ms: int
    resource_units: int

    def __post_init__(self) -> None:
        _ref(self.bundle_ref, name="bundle")
        _non_empty_string(self.invocation_id, name="invocation_id")
        _ref(self.capture_lineage_ref, name="capture_lineage")
        if not isinstance(self.bindings, tuple) or any(not isinstance(item, SemanticBindingItemV1) for item in self.bindings):
            raise UEIValidationError("provider_capability_invalid_bindings")
        candidate_ids = [item.candidate_id for item in self.bindings]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise UEIValidationError("provider_capability_candidate_duplicate")
        _non_negative_int(self.duration_ms, name="duration_ms")
        _non_negative_int(self.resource_units, name="resource_units")
        object.__setattr__(self, "bundle_ref", _freeze(self.bundle_ref))
        object.__setattr__(self, "capture_lineage_ref", _freeze(self.capture_lineage_ref))


@dataclass(frozen=True)
class GroundingRefinementRequestV1:
    envelope: ProviderInvocationEnvelopeV1
    candidate_id: str
    candidate_bbox: tuple[int, int, int, int]
    permitted_roi: tuple[int, int, int, int]
    provider_request: dict[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.envelope, ProviderInvocationEnvelopeV1):
            raise UEIValidationError("provider_capability_invalid_envelope")
        if self.envelope.capability != "grounding_refinement":
            raise UEIValidationError("provider_capability_capability_mismatch")
        _non_empty_string(self.candidate_id, name="candidate_id")
        _xyxy(self.candidate_bbox, name="candidate_bbox")
        _xyxy(self.permitted_roi, name="permitted_roi")
        if not isinstance(self.provider_request, dict) or self.provider_request.get("state") != "BOUND":
            raise UEIValidationError("provider_capability_grounding_requires_bound")
        reject_authority_shaped_payload(self.provider_request)
        object.__setattr__(self, "provider_request", _freeze(self.provider_request))

    def validate_result(self, result: GroundingRefinementResultV1) -> GroundingRefinementResultV1:
        """Bind a grounding result to this exact request and strict interior geometry."""
        if not isinstance(result, GroundingRefinementResultV1):
            raise UEIValidationError("provider_capability_invalid_grounding_result")
        _same_ref(self.envelope.bundle_ref, result.bundle_ref, name="bundle")
        _same_ref(self.envelope.capture_lineage_ref, result.capture_lineage_ref, name="lineage")
        if self.envelope.invocation_id != result.invocation_id:
            raise UEIValidationError("provider_capability_invocation_mismatch")
        if self.candidate_id != result.candidate_id:
            raise UEIValidationError("provider_capability_candidate_mismatch")
        if result.point is not None:
            if result.coordinate_space != _CAPTURE_COORDINATE_SPACE:
                raise UEIValidationError("provider_capability_coordinate_space_mismatch")
            x, y = result.point
            for bbox in (self.candidate_bbox, self.permitted_roi):
                x1, y1, x2, y2 = bbox
                if not (x1 < x < x2 and y1 < y < y2):
                    raise UEIValidationError("provider_capability_strict_interior_required")
        return result


@dataclass(frozen=True)
class GroundingRefinementResultV1:
    bundle_ref: dict[str, str]
    invocation_id: str
    capture_lineage_ref: dict[str, str]
    candidate_id: str
    status: str
    point: tuple[float, float] | None
    coordinate_space: str
    confidence: float | None
    evidence_refs: tuple[dict[str, str], ...]
    duration_ms: int
    resource_units: int

    def __post_init__(self) -> None:
        _ref(self.bundle_ref, name="bundle")
        _non_empty_string(self.invocation_id, name="invocation_id")
        _ref(self.capture_lineage_ref, name="capture_lineage")
        _non_empty_string(self.candidate_id, name="candidate_id")
        _non_empty_string(self.status, name="status", maximum=128)
        if self.point is not None:
            _point(self.point, name="point")
        _non_empty_string(self.coordinate_space, name="coordinate_space", maximum=128)
        _finite_confidence(self.confidence, name="confidence", optional=True)
        if not isinstance(self.evidence_refs, tuple):
            raise UEIValidationError("provider_capability_invalid_evidence_refs")
        for evidence_ref in self.evidence_refs:
            _ref(evidence_ref, name="evidence")
        _non_negative_int(self.duration_ms, name="duration_ms")
        _non_negative_int(self.resource_units, name="resource_units")
        object.__setattr__(self, "bundle_ref", _freeze(self.bundle_ref))
        object.__setattr__(self, "capture_lineage_ref", _freeze(self.capture_lineage_ref))
        object.__setattr__(self, "evidence_refs", _freeze(self.evidence_refs))


class CandidateDiscoveryProvider(Protocol):
    bundle_ref: dict[str, str]

    def invoke(self, request: CandidateDiscoveryRequestV1) -> CandidateDiscoveryResultV1: ...


class SemanticBindingProvider(Protocol):
    bundle_ref: dict[str, str]

    def invoke(self, request: SemanticBindingRequestV1) -> SemanticBindingResultV1: ...


class GroundingRefinementProvider(Protocol):
    bundle_ref: dict[str, str]

    def invoke(self, request: GroundingRefinementRequestV1) -> GroundingRefinementResultV1: ...
