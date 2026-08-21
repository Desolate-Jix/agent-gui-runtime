from copy import deepcopy

import pytest

from tests.uei_v1_helpers import SHA, minimal_provider_safe_result


def minimal_contract_values() -> dict[str, dict[str, object]]:
    ref = {"id": "ref/1", "content_sha256": SHA}
    profile = {"profile_id": "profile/1", "operation": "screen_parse", "input_contract": "screen_parse_request_v1", "output_contract": "provider_safe_result_v1", "declared_output_kinds": ["text"], "supported_coordinate_spaces": ["capture_pixel_xyxy"], "supports_capture_artifact": True, "privacy_capabilities": ["minimal"], "mode_allowlist": ["Shadow"]}
    common = {"content_sha256": SHA}
    return {
        "trusted_provider_registration_v1": {"contract_version": "trusted_provider_registration_v1", "registration_id": "registration/1", "provider_id": "provider/1", "profile_ids": ["profile/1"], "enabled": True, "allowed_modes": ["Shadow"], "allowed_privacy_policies": ["minimal"], "egress_policy": "local_only", "wire_payload_policy": "restricted_store_only", "safe_payload_limits": {"max_json_bytes": 1, "max_depth": 1, "max_array_items": 1, "max_object_properties": 1, "max_string_chars": 1, "allowed_json_types": ["null"]}, "required_conformance_suite": "suite", **common},
        "artifact_ref_v1": {"contract_version": "artifact_ref_v1", "artifact_id": "artifact/1", "artifact_sha256": SHA, "media_type": "image/png", "byte_length": 1, "restricted": False, **common},
        "capture_lineage_v1": {"contract_version": "capture_lineage_v1", "capture_id": "capture/1", "artifact_ref": ref, "artifact_sha256": SHA, "image_size": {"width": 1, "height": 1}, "capture_coordinate_space": "capture_pixel_xyxy", "captured_at": "2026-01-01T00:00:00Z", **common},
        "affine_coordinate_transform_v1": {"contract_version": "affine_coordinate_transform_v1", "source_space": "image_pixel_xyxy", "target_space": "capture_pixel_xyxy", "source_size": {"width": 1, "height": 1}, "target_size": {"width": 1, "height": 1}, "scale": {"x": 1, "y": 1}, "offset": {"x": 0, "y": 0}, "rounding": "none", "clipping": "reject_if_outside", "source_capture_artifact_sha256": SHA, "target_capture_artifact_sha256": SHA, **common},
        "provider_manifest_v1": {"contract_version": "provider_manifest_v1", "manifest_id": "manifest/1", "provider_id": "provider/1", "provider_version": "1", "profiles": [profile], **common},
        "screen_parse_request_v1": {"contract_version": "screen_parse_request_v1", "request_id": "request/1", "capture_lineage_ref": ref, "requested_profiles": [{"provider_id": "provider/1", "profile_id": "profile/1", "mode": "Shadow"}], "privacy_policy": "minimal", "requester_id": "requester/1", **common},
        "provider_safe_result_v1": minimal_provider_safe_result(),
        "provider_error_v1": {"contract_version": "provider_error_v1", "error_id": "error/1", "request_ref": ref, "requested_provider_id": "provider/1", "requested_profile_id": "profile/1", "registration_resolution": "not_found", "manifest_resolution": "not_reached", "provider_id": "provider/1", "profile_id": "profile/1", "stage": "registration", "code": "provider_unregistered", "retryable": False, "message": "synthetic", "safe_details": {"reason_class": "policy"}, "capture_lineage_ref": ref, **common},
    }


def test_all_eight_uei_schemas_load_and_reject_unknown_nested_fields():
    from app.learn.recognition.uei.contracts import (UEI_CONTRACTS, UEIValidationError,
                                                      load_contract_schema, validate_contract)
    assert set(load_contract_schema(name)["title"] for name in UEI_CONTRACTS) == set(UEI_CONTRACTS)
    value = minimal_provider_safe_result()
    value["items"][0]["x_extension"] = True
    with pytest.raises(UEIValidationError, match="additionalProperties"):
        validate_contract(value, contract_version="provider_safe_result_v1")


@pytest.mark.parametrize("contract,value", minimal_contract_values().items())
def test_all_contract_legal_minima_validate(contract, value):
    from app.learn.recognition.uei.contracts import validate_contract
    validate_contract(value, contract_version=contract)


@pytest.mark.parametrize("contract", [
    "trusted_provider_registration_v1", "artifact_ref_v1", "capture_lineage_v1",
    "affine_coordinate_transform_v1", "provider_manifest_v1", "screen_parse_request_v1",
    "provider_safe_result_v1", "provider_error_v1",
])
def test_schema_has_closed_top_level_and_version(contract):
    from app.learn.recognition.uei.contracts import load_contract_schema
    schema = load_contract_schema(contract)
    assert schema["additionalProperties"] is False
    assert schema["properties"]["contract_version"]["const"] == contract
    assert {"opaque_scalar", "opaque_value"} <= set(schema["$defs"])


@pytest.mark.parametrize("mutator", [
    lambda v: v.__setitem__("contract_version", "provider_safe_result_v0"),
    lambda v: v["items"][0].__setitem__("kind", "click"),
    lambda v: v["items"][0].__setitem__("source_item_id", None),
    lambda v: v["items"][0].__setitem__("source_bbox", [0, 0, 0, 1]),
    lambda v: v.__setitem__("content_sha256", "A" * 64),
    lambda v: v.__setitem__("content_sha256", "g" * 64),
    lambda v: v.__setitem__("content_sha256", "a" * 63),
])
def test_safe_result_rejects_wrong_version_enum_null_bbox_and_bad_sha(mutator):
    from app.learn.recognition.uei.contracts import UEIValidationError, validate_contract
    value = minimal_provider_safe_result()
    mutator(value)
    with pytest.raises(UEIValidationError):
        validate_contract(value, contract_version="provider_safe_result_v1")
    value = minimal_provider_safe_result()
    value["items"][0]["source_bbox"] = [0.1, 0.2, 0.8, 0.9]
    with pytest.raises(UEIValidationError):
        validate_contract(value, contract_version="provider_safe_result_v1")


def test_capture_lineage_requires_rfc3339_utc_z_and_real_date():
    from app.learn.recognition.uei.contracts import UEIValidationError, validate_contract
    value = {"contract_version": "capture_lineage_v1", "capture_id": "capture/1",
             "artifact_ref": {"id": "artifact/1", "content_sha256": SHA},
             "artifact_sha256": SHA, "image_size": {"width": 1, "height": 1},
             "capture_coordinate_space": "capture_pixel_xyxy", "captured_at": "2026-08-21T03:14:15Z",
             "content_sha256": SHA}
    validate_contract(value, contract_version="capture_lineage_v1")
    for timestamp in ("2026-08-21T03:14:15+00:00", "2026-02-30T03:14:15Z", "not-a-dateZ"):
        invalid = deepcopy(value); invalid["captured_at"] = timestamp
        with pytest.raises(UEIValidationError):
            validate_contract(invalid, contract_version="capture_lineage_v1")


def test_normalized_source_bbox_is_accepted_only_in_normalized_space():
    from app.learn.recognition.uei.contracts import UEIValidationError, validate_contract
    value = minimal_provider_safe_result()
    item = value["items"][0]
    item["source_coordinate_space"] = "image_normalized_xyxy"
    item["source_bbox"] = [0.1, 0.2, 0.8, 0.9]
    item["capture_bbox"] = None
    validate_contract(value, contract_version="provider_safe_result_v1")
    item["source_bbox"] = [0.1, 0.2, 0.8, 1.1]
    with pytest.raises(UEIValidationError):
        validate_contract(value, contract_version="provider_safe_result_v1")


@pytest.mark.parametrize("mutation", [
    lambda value: value["items"][0]["opaque_attributes"].__setitem__("bad", float("nan")),
    lambda value: value["items"][0]["opaque_attributes"].__setitem__(1, "bad key"),
])
def test_rejects_non_json_numbers_and_object_keys(mutation):
    from app.learn.recognition.uei.contracts import UEIValidationError, validate_contract
    value = minimal_provider_safe_result()
    mutation(value)
    with pytest.raises(UEIValidationError):
        validate_contract(value, contract_version="provider_safe_result_v1")


def test_duplicate_profile_tuples_and_nested_manifest_ids_are_rejected():
    from app.learn.recognition.uei.contracts import UEIValidationError, validate_contract
    request = {"contract_version": "screen_parse_request_v1", "request_id": "request/1",
               "capture_lineage_ref": {"id": "capture/1", "content_sha256": SHA},
               "requested_profiles": [{"provider_id": "provider/1", "profile_id": "profile/1", "mode": "Shadow"},
                                      {"provider_id": "provider/1", "profile_id": "profile/1", "mode": "Assist"}],
               "privacy_policy": "minimal", "requester_id": "synthetic", "content_sha256": SHA}
    with pytest.raises(UEIValidationError, match="duplicate"):
        validate_contract(request, contract_version="screen_parse_request_v1")


def test_duplicate_manifest_profile_ids_are_rejected():
    from app.learn.recognition.uei.contracts import UEIValidationError, validate_contract
    profile = {"profile_id": "profile/1", "operation": "screen_parse",
               "input_contract": "screen_parse_request_v1", "output_contract": "provider_safe_result_v1",
               "declared_output_kinds": ["text"], "supported_coordinate_spaces": ["capture_pixel_xyxy"],
               "supports_capture_artifact": True, "privacy_capabilities": ["minimal"],
               "mode_allowlist": ["Shadow"]}
    duplicate_id_with_different_shape = deepcopy(profile)
    duplicate_id_with_different_shape["mode_allowlist"] = ["Assist"]
    manifest = {"contract_version": "provider_manifest_v1", "manifest_id": "manifest/1",
                "provider_id": "provider/1", "provider_version": "1", "profiles": [profile, duplicate_id_with_different_shape],
                "content_sha256": SHA}
    with pytest.raises(UEIValidationError, match="duplicate"):
        validate_contract(manifest, contract_version="provider_manifest_v1")



@pytest.mark.parametrize("identifier", ["x/y", "local.runtime/windows-uia", "local.runtime/windows-uia/static"])
def test_namespaced_provider_and_profile_ids_accept_valid_examples(identifier):
    from app.learn.recognition.uei.contracts import is_namespaced_provider_profile_id
    assert is_namespaced_provider_profile_id(identifier)


@pytest.mark.parametrize("identifier", ["x", "windows_uia", "omniparser", "X/y", "x//y", "x/y/", "/x/y"])
def test_namespaced_provider_and_profile_ids_reject_unnamespaced_or_malformed_values(identifier):
    from app.learn.recognition.uei.contracts import UEIValidationError, is_namespaced_provider_profile_id, validate_contract
    assert not is_namespaced_provider_profile_id(identifier)
    value = minimal_provider_safe_result()
    value["provider_id"] = identifier
    with pytest.raises(UEIValidationError, match="pattern"):
        validate_contract(value, contract_version="provider_safe_result_v1")
