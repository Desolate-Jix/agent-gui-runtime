"""Internal, dependency-free contracts for trusted Shadow screen-parse adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Protocol

from app.learn.recognition.uei.contracts import UEIValidationError, is_namespaced_provider_profile_id


class AdapterFailure(Exception):
    """不泄露 provider 细节的已分类 adapter 失败。"""

    def __init__(
        self, *, disposition: str, reason_class: str, retryable: bool,
        cleanup_status: str, duration_ms: int = 0, resource_units: int = 0,
        output_item_count: int = 0,
    ) -> None:
        if (disposition not in {"rejected", "failed"} or cleanup_status not in {"not_required", "clean", "failed"}
                or not all(isinstance(value, int) and value >= 0 for value in (duration_ms, resource_units, output_item_count))):
            raise UEIValidationError("runtime_invalid_adapter_failure")
        super().__init__(reason_class)
        self.disposition, self.reason_class, self.retryable = disposition, reason_class, retryable
        self.cleanup_status = cleanup_status
        self.duration_ms, self.resource_units, self.output_item_count = duration_ms, resource_units, output_item_count


@dataclass(frozen=True)
class ProviderRunBudget:
    timeout_ms: int
    max_output_bytes: int
    max_element_count: int
    max_string_length: int
    resource_group: str

    def __post_init__(self) -> None:
        if (not all(isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in (
                self.timeout_ms, self.max_output_bytes, self.max_element_count, self.max_string_length))
                or not isinstance(self.resource_group, str) or not self.resource_group or len(self.resource_group) > 128):
            raise UEIValidationError("runtime_invalid_budget")


@dataclass(frozen=True)
class RestrictedCaptureLease:
    request_ref: dict[str, str]
    capture_lineage_ref: dict[str, str]
    artifact_ref: dict[str, str]
    capture_id: str
    artifact_sha256: str
    image_size: dict[str, int]
    local_path: Path


@dataclass(frozen=True)
class NormalizedProviderItem:
    source_item_id: str | None
    kind: str
    safe_text: str | None
    source_bbox: tuple[int, int, int, int] | None
    source_coordinate_space: str
    safe_role: str | None = None
    safe_states: tuple[str, ...] = ()
    provider_confidence: float | None = None


@dataclass(frozen=True)
class NormalizedScreenParseOutput:
    items: tuple[NormalizedProviderItem, ...]
    duration_ms: int
    resource_units: int


class ScreenParseProviderAdapter(Protocol):
    provider_id: str
    profile_id: str
    provider_version: str

    def invoke(
        self, *, capture: RestrictedCaptureLease, budget: ProviderRunBudget,
        invocation_id: str, cancellation_event: Event | None = None,
    ) -> NormalizedScreenParseOutput: ...


class TrustedProviderAdapterRegistry:
    """Resolve only pre-registered, namespaced in-process adapter identities."""

    def __init__(self, adapters: list[ScreenParseProviderAdapter]) -> None:
        entries: dict[tuple[str, str], ScreenParseProviderAdapter] = {}
        for adapter in adapters:
            provider_id = getattr(adapter, "provider_id", None)
            profile_id = getattr(adapter, "profile_id", None)
            provider_version = getattr(adapter, "provider_version", None)
            if (not is_namespaced_provider_profile_id(provider_id)
                    or not is_namespaced_provider_profile_id(profile_id)
                    or not isinstance(provider_version, str) or not provider_version or len(provider_version) > 128):
                raise UEIValidationError("runtime_untrusted_adapter")
            key = (provider_id, profile_id)
            if key in entries:
                raise UEIValidationError("runtime_duplicate_adapter")
            entries[key] = adapter
        self._entries = entries

    def resolve(self, *, provider_id: str, profile_id: str) -> ScreenParseProviderAdapter | None:
        if not is_namespaced_provider_profile_id(provider_id) or not is_namespaced_provider_profile_id(profile_id):
            return None
        return self._entries.get((provider_id, profile_id))
