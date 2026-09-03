from copy import deepcopy

import pytest

from app.learn.recognition.uei.contracts import UEIValidationError
from app.learn.recognition.uei.canonical import content_sha256
from app.learn.recognition.uei.provider_bundles import (
    TrustedProviderBundleRegistry,
    provider_bundle_ref,
    seal_provider_bundle_descriptor_v1,
    validate_provider_bundle_descriptor_v1,
)


def descriptor_fixture(*, capability: str = "semantic_binding") -> dict[str, object]:
    return {
        "contract_version": "provider_bundle_descriptor_v1",
        "bundle_id": "bundle/local.qwen3.semantic-binding",
        "bundle_revision": "compat-v1",
        "capability": capability,
        "provider_id": "provider/local.qwen3",
        "profile_id": "profile/local.qwen3-vl-8b",
        "model_id": "Qwen3-VL-8B-Instruct",
        "model_revision": "q4-k-m",
        "prompt_spec_sha256": "1" * 64,
        "prompt_renderer_sha256": "2" * 64,
        "native_parser_sha256": "3" * 64,
        "adapter_sha256": "4" * 64,
        "preprocessing_sha256": "5" * 64,
        "transport_sha256": "6" * 64,
        "coordinate_convention": "capture_pixel_xyxy",
        "decoding_config_sha256": "7" * 64,
        "artifact_sha256s": ["8" * 64, "9" * 64],
        "resource_budget": {
            "timeout_ms": 30_000,
            "max_output_bytes": 65_536,
            "max_element_count": 256,
            "max_string_length": 4_096,
            "resource_group": "gpu_vision",
        },
    }


def test_bundle_descriptor_is_closed_jcs_sealed_and_ref_resolves():
    sealed = seal_provider_bundle_descriptor_v1(descriptor_fixture())
    assert sealed["content_sha256"] == content_sha256(sealed)
    assert provider_bundle_ref(sealed) == {
        "id": sealed["bundle_id"],
        "content_sha256": sealed["content_sha256"],
    }


@pytest.mark.parametrize("field", [
    "prompt_spec_sha256", "native_parser_sha256", "adapter_sha256",
    "coordinate_convention", "decoding_config_sha256",
])
def test_each_load_bearing_mutation_changes_or_invalidates_bundle_identity(field):
    sealed = seal_provider_bundle_descriptor_v1(descriptor_fixture())
    mutated = deepcopy(sealed)
    mutated[field] = "f" * 64 if field.endswith("sha256") else "image_normalized_xyxy"
    with pytest.raises(UEIValidationError):
        validate_provider_bundle_descriptor_v1(mutated)


def test_registry_rejects_duplicate_key_and_wrong_capability_or_ref():
    sealed = seal_provider_bundle_descriptor_v1(descriptor_fixture())
    adapter = object()
    with pytest.raises(UEIValidationError, match="duplicate"):
        TrustedProviderBundleRegistry([(sealed, adapter), (sealed, adapter)])
    registry = TrustedProviderBundleRegistry([(sealed, adapter)])
    with pytest.raises(UEIValidationError, match="capability"):
        registry.resolve(
            capability="candidate_discovery",
            bundle_ref=provider_bundle_ref(sealed),
        )
    bad_ref = {**provider_bundle_ref(sealed), "content_sha256": "0" * 64}
    with pytest.raises(UEIValidationError, match="bundle"):
        registry.resolve(capability="semantic_binding", bundle_ref=bad_ref)
