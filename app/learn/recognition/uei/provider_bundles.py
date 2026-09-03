"""Provider 能力 Bundle 的闭合描述符与可信解析注册表。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re

from app.learn.recognition.uei.canonical import (
    canonical_json_bytes,
    content_sha256,
    immutable_ref,
    seal_immutable,
)
from app.learn.recognition.uei.contracts import UEIValidationError
from app.learn.recognition.uei.provider_adapters import ProviderRunBudget


PROVIDER_CAPABILITIES = frozenset({
    "candidate_discovery",
    "semantic_binding",
    "grounding_refinement",
})

_DESCRIPTOR_KEYS = frozenset({
    "contract_version",
    "bundle_id",
    "bundle_revision",
    "capability",
    "provider_id",
    "profile_id",
    "model_id",
    "model_revision",
    "prompt_spec_sha256",
    "prompt_renderer_sha256",
    "native_parser_sha256",
    "adapter_sha256",
    "preprocessing_sha256",
    "transport_sha256",
    "coordinate_convention",
    "decoding_config_sha256",
    "artifact_sha256s",
    "resource_budget",
})
_SEALED_DESCRIPTOR_KEYS = _DESCRIPTOR_KEYS | {"content_sha256"}
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_HASH_FIELDS = (
    "prompt_spec_sha256",
    "prompt_renderer_sha256",
    "native_parser_sha256",
    "adapter_sha256",
    "preprocessing_sha256",
    "transport_sha256",
    "decoding_config_sha256",
)
_TEXT_FIELDS = (
    "bundle_id",
    "bundle_revision",
    "provider_id",
    "profile_id",
    "model_id",
    "model_revision",
)


def _require_sha256(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise UEIValidationError(f"provider_bundle_invalid_{field}")
    return value


def _validate_descriptor_shape(value: object, *, sealed: bool) -> dict[str, object]:
    if not isinstance(value, dict):
        raise UEIValidationError("provider_bundle_descriptor_not_object")
    expected_keys = _SEALED_DESCRIPTOR_KEYS if sealed else _DESCRIPTOR_KEYS
    if set(value) != expected_keys:
        raise UEIValidationError("provider_bundle_descriptor_keys")
    if value["contract_version"] != "provider_bundle_descriptor_v1":
        raise UEIValidationError("provider_bundle_contract_version")
    for field in _TEXT_FIELDS:
        field_value = value[field]
        if not isinstance(field_value, str) or not field_value:
            raise UEIValidationError(f"provider_bundle_invalid_{field}")
    capability = value["capability"]
    if capability not in PROVIDER_CAPABILITIES:
        raise UEIValidationError("provider_bundle_capability_invalid")
    for field in _HASH_FIELDS:
        _require_sha256(value[field], field)
    coordinate_convention = value["coordinate_convention"]
    if coordinate_convention != "capture_pixel_xyxy":
        raise UEIValidationError("provider_bundle_coordinate_convention")
    artifacts = value["artifact_sha256s"]
    if not isinstance(artifacts, list) or any(
        _SHA256_PATTERN.fullmatch(item) is None for item in artifacts
        if isinstance(item, str)
    ):
        raise UEIValidationError("provider_bundle_artifacts")
    if not all(isinstance(item, str) for item in artifacts):
        raise UEIValidationError("provider_bundle_artifacts")
    if artifacts != sorted(set(artifacts)):
        raise UEIValidationError("provider_bundle_artifacts")
    budget = value["resource_budget"]
    if not isinstance(budget, dict):
        raise UEIValidationError("provider_bundle_resource_budget")
    try:
        ProviderRunBudget(**budget)
    except (TypeError, UEIValidationError) as error:
        raise UEIValidationError("provider_bundle_resource_budget") from error
    if sealed:
        _require_sha256(value["content_sha256"], "content_sha256")
        if value["content_sha256"] != content_sha256(value):
            raise UEIValidationError("provider_bundle_content_sha256")
    canonical_json_bytes(value)
    return value


def validate_provider_bundle_descriptor_v1(value: object) -> dict[str, object]:
    """返回闭合、已封存且可机器验证的 Provider Bundle。"""
    return _validate_descriptor_shape(value, sealed=True)


def seal_provider_bundle_descriptor_v1(value: object) -> dict[str, object]:
    """验证未封存描述符并使用 JCS content hash 封存。"""
    descriptor = _validate_descriptor_shape(value, sealed=False)
    return validate_provider_bundle_descriptor_v1(seal_immutable(descriptor))


def provider_bundle_ref(value: object) -> dict[str, str]:
    """只返回 bundle_id 与已验证 content_sha256。"""
    descriptor = validate_provider_bundle_descriptor_v1(value)
    return immutable_ref(descriptor, id_field="bundle_id")


@dataclass(frozen=True)
class ResolvedProviderBundle:
    descriptor: dict[str, object]
    adapter: object


class TrustedProviderBundleRegistry:
    def __init__(self, entries: list[tuple[dict[str, object], object]]) -> None:
        self._entries: dict[tuple[str, str], ResolvedProviderBundle] = {}
        for descriptor, adapter in entries:
            validated = validate_provider_bundle_descriptor_v1(descriptor)
            key = (validated["capability"], validated["bundle_id"])
            if key in self._entries:
                raise UEIValidationError("provider_bundle_duplicate")
            self._entries[key] = ResolvedProviderBundle(deepcopy(validated), adapter)

    def resolve(
        self, *, capability: str, bundle_ref: dict[str, str]
    ) -> ResolvedProviderBundle:
        if capability not in PROVIDER_CAPABILITIES:
            raise UEIValidationError("provider_bundle_capability_invalid")
        if not isinstance(bundle_ref, dict) or set(bundle_ref) != {"id", "content_sha256"}:
            raise UEIValidationError("provider_bundle_unresolved")
        bundle_id = bundle_ref.get("id")
        declared_hash = bundle_ref.get("content_sha256")
        if not isinstance(bundle_id, str) or not bundle_id:
            raise UEIValidationError("provider_bundle_unresolved")
        if not isinstance(declared_hash, str) or _SHA256_PATTERN.fullmatch(declared_hash) is None:
            raise UEIValidationError("provider_bundle_unresolved")
        key = (capability, bundle_id)
        resolved = self._entries.get(key)
        if resolved is None:
            if any(existing_id == bundle_id for _, existing_id in self._entries):
                raise UEIValidationError("provider_bundle_capability_mismatch")
            raise UEIValidationError("provider_bundle_unresolved")
        if provider_bundle_ref(resolved.descriptor) != bundle_ref:
            raise UEIValidationError("provider_bundle_unresolved")
        return ResolvedProviderBundle(deepcopy(resolved.descriptor), resolved.adapter)
