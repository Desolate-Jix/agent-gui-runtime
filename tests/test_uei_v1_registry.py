from __future__ import annotations

from pathlib import Path

import pytest

from app.learn.recognition.uei.canonical import seal_immutable
from app.learn.recognition.uei.contracts import UEIOuterBoundaryError, UEIValidationError
from app.learn.recognition.uei.registry import resolve_projection_context, resolve_requested_profile
from app.learn.recognition.uei.store import UEIObjectStore


PROVIDER_ID = "local.test/ocr"
PROFILE_ID = "local.test/ocr/default"


def _put(store: UEIObjectStore, value: dict[str, object]) -> dict[str, str]:
    return store.put(seal_immutable(value))


def _store_valid(tmp_path: Path) -> tuple[UEIObjectStore, dict[str, str], dict[str, str], dict[str, str]]:
    store = UEIObjectStore(root=tmp_path / "uei")
    artifact_ref = _put(store, {
        "contract_version": "artifact_ref_v1", "artifact_id": "artifact/test",
        "artifact_sha256": "a" * 64, "media_type": "image/png", "byte_length": 1,
        "restricted": True,
    })
    lineage_ref = _put(store, {
        "contract_version": "capture_lineage_v1", "capture_id": "capture/test",
        "artifact_ref": artifact_ref, "artifact_sha256": "a" * 64,
        "image_size": {"width": 16, "height": 9},
        "capture_coordinate_space": "capture_pixel_xyxy",
        "captured_at": "2026-08-21T00:00:00Z",
    })
    request_ref = _put(store, {
        "contract_version": "screen_parse_request_v1", "request_id": "request/test",
        "capture_lineage_ref": lineage_ref,
        "requested_profiles": [{"provider_id": PROVIDER_ID, "profile_id": PROFILE_ID, "mode": "Shadow"}],
        "privacy_policy": "restricted", "requester_id": "test",
    })
    registration_ref = _put(store, {
        "contract_version": "trusted_provider_registration_v1", "registration_id": "registration/test",
        "provider_id": PROVIDER_ID, "profile_ids": [PROFILE_ID], "enabled": True,
        "allowed_modes": ["Shadow"], "allowed_privacy_policies": ["restricted"],
        "egress_policy": "local_only", "wire_payload_policy": "restricted_store_only",
        "safe_payload_limits": {
            "max_json_bytes": 256, "max_depth": 4, "max_array_items": 4,
            "max_object_properties": 4, "max_string_chars": 16,
            "allowed_json_types": ["object", "array", "string", "number", "boolean", "null"],
        },
        "required_conformance_suite": "uei-v1-static-projection",
    })
    manifest_ref = _put(store, {
        "contract_version": "provider_manifest_v1", "manifest_id": "manifest/test",
        "provider_id": PROVIDER_ID, "provider_version": "1",
        "profiles": [{
            "profile_id": PROFILE_ID, "operation": "screen_parse",
            "input_contract": "screen_parse_request_v1", "output_contract": "provider_safe_result_v1",
            "declared_output_kinds": ["text"], "supported_coordinate_spaces": ["capture_pixel_xyxy"],
            "supports_capture_artifact": True, "privacy_capabilities": ["restricted"],
            "mode_allowlist": ["Shadow"],
        }],
    })
    return store, request_ref, registration_ref, manifest_ref


def _assert_no_projection_writes(store: UEIObjectStore) -> None:
    assert store.object_count(contract_version="provider_error_v1") == 0
    assert store.object_count(contract_version="provider_safe_result_v1") == 0


def test_invalid_request_ref_is_outer_error_and_writes_no_projection_objects(tmp_path: Path):
    store, _, _, _ = _store_valid(tmp_path)
    with pytest.raises(UEIOuterBoundaryError, match="request_ref"):
        resolve_projection_context(store=store, request_ref={"id": "request/x", "content_sha256": "0" * 64})
    _assert_no_projection_writes(store)


@pytest.mark.parametrize("request_ref", [None, [], {"id": "request/x"}, {"id": 1, "content_sha256": "a" * 64}])
def test_unhashable_request_refs_are_outer_errors(tmp_path: Path, request_ref: object):
    store, _, _, _ = _store_valid(tmp_path)
    with pytest.raises(UEIOuterBoundaryError, match="request_ref"):
        resolve_projection_context(store=store, request_ref=request_ref)  # type: ignore[arg-type]
    _assert_no_projection_writes(store)


def test_missing_lineage_is_outer_error(tmp_path: Path):
    store = UEIObjectStore(root=tmp_path / "uei")
    request_ref = _put(store, {
        "contract_version": "screen_parse_request_v1", "request_id": "request/missing-lineage",
        "capture_lineage_ref": {"id": "capture/missing", "content_sha256": "a" * 64},
        "requested_profiles": [{"provider_id": PROVIDER_ID, "profile_id": PROFILE_ID, "mode": "Shadow"}],
        "privacy_policy": "restricted", "requester_id": "test",
    })
    with pytest.raises(UEIOuterBoundaryError, match="capture_lineage_ref"):
        resolve_projection_context(store=store, request_ref=request_ref)
    _assert_no_projection_writes(store)


@pytest.mark.parametrize("mutation, expected", [
    (lambda lineage: lineage.update({"artifact_ref": {"id": "artifact/missing", "content_sha256": "a" * 64}}), "artifact_ref"),
    (lambda lineage: lineage.update({"artifact_sha256": "b" * 64}), "artifact_sha256"),
])
def test_unresolved_or_mismatched_artifact_is_outer_error(tmp_path: Path, mutation, expected: str):
    store, _, _, _ = _store_valid(tmp_path)
    artifact_ref = _put(store, {
        "contract_version": "artifact_ref_v1", "artifact_id": "artifact/test",
        "artifact_sha256": "a" * 64, "media_type": "image/png", "byte_length": 1, "restricted": True,
    })
    lineage = {
        "contract_version": "capture_lineage_v1", "capture_id": "capture/mutated", "artifact_ref": artifact_ref,
        "artifact_sha256": "a" * 64, "image_size": {"width": 16, "height": 9},
        "capture_coordinate_space": "capture_pixel_xyxy", "captured_at": "2026-08-21T00:00:00Z",
    }
    mutation(lineage)
    lineage_ref = _put(store, lineage)
    request_ref = _put(store, {
        "contract_version": "screen_parse_request_v1", "request_id": "request/mutated",
        "capture_lineage_ref": lineage_ref,
        "requested_profiles": [{"provider_id": PROVIDER_ID, "profile_id": PROFILE_ID, "mode": "Shadow"}],
        "privacy_policy": "restricted", "requester_id": "test",
    })
    with pytest.raises(UEIOuterBoundaryError, match=expected):
        resolve_projection_context(store=store, request_ref=request_ref)
    _assert_no_projection_writes(store)


def test_context_then_intersection_returns_all_resolved_facts(tmp_path: Path):
    store, request_ref, registration_ref, manifest_ref = _store_valid(tmp_path)
    context = resolve_projection_context(store=store, request_ref=request_ref)
    record = resolve_requested_profile(context=context, registration_ref=registration_ref, manifest_ref=manifest_ref,
                                       provider_id=PROVIDER_ID, profile_id=PROFILE_ID)
    assert context["request_ref"] == request_ref
    assert context["artifact_sha256"] == "a" * 64
    assert context["image_size"] == {"width": 16, "height": 9}
    assert record["resolved"] is True
    assert record["requested_provider_id"] == PROVIDER_ID
    assert record["requested_profile_id"] == PROFILE_ID
    assert record["registration_resolution"] == "resolved"
    assert record["manifest_resolution"] == "resolved"
    assert record["registration_ref"] == registration_ref
    assert record["manifest_ref"] == manifest_ref
    assert record["safe_payload_limits"]["max_json_bytes"] == 256
    _assert_no_projection_writes(store)


def test_profile_resolution_reloads_stored_context_after_caller_mutates_every_nested_value(tmp_path: Path):
    store, request_ref, registration_ref, manifest_ref = _store_valid(tmp_path)
    context = resolve_projection_context(store=store, request_ref=request_ref)
    context["request"]["privacy_policy"] = "minimal"
    context["request"]["requested_profiles"][0]["mode"] = "Primary"
    context["capture_lineage"]["artifact_sha256"] = "b" * 64
    context["capture_lineage"]["image_size"]["width"] = 1
    context["artifact"]["artifact_sha256"] = "b" * 64
    context["artifact_sha256"] = "b" * 64
    context["image_size"]["height"] = 1

    record = resolve_requested_profile(context=context, registration_ref=registration_ref, manifest_ref=manifest_ref,
                                       provider_id=PROVIDER_ID, profile_id=PROFILE_ID)

    assert record["resolved"] is True
    assert store.get(request_ref, contract_version="screen_parse_request_v1")["privacy_policy"] == "restricted"
    _assert_no_projection_writes(store)


@pytest.mark.parametrize("context", [
    {"store": object(), "request": {}},
    {"store": object(), "request_ref": {"id": "request/test", "content_sha256": "a" * 64}},
])
def test_profile_resolution_rejects_fabricated_contexts(tmp_path: Path, context: dict[str, object]):
    _store_valid(tmp_path)
    with pytest.raises(UEIOuterBoundaryError, match="context"):
        resolve_requested_profile(context=context, registration_ref=None, manifest_ref=None,
                                 provider_id=PROVIDER_ID, profile_id=PROFILE_ID)


def test_profile_resolution_rejects_wrong_store_or_request_ref(tmp_path: Path):
    store, request_ref, registration_ref, manifest_ref = _store_valid(tmp_path)
    context = resolve_projection_context(store=store, request_ref=request_ref)
    other_store = UEIObjectStore(root=tmp_path / "other")
    context["store"] = other_store
    with pytest.raises(UEIOuterBoundaryError, match="request_ref"):
        resolve_requested_profile(context=context, registration_ref=registration_ref, manifest_ref=manifest_ref,
                                 provider_id=PROVIDER_ID, profile_id=PROFILE_ID)

    context = resolve_projection_context(store=store, request_ref=request_ref)
    context["request_ref"] = {"id": "request/wrong", "content_sha256": "a" * 64}
    with pytest.raises(UEIOuterBoundaryError, match="request_ref"):
        resolve_requested_profile(context=context, registration_ref=registration_ref, manifest_ref=manifest_ref,
                                 provider_id=PROVIDER_ID, profile_id=PROFILE_ID)


def test_outer_boundary_error_hides_store_exception_cause(tmp_path: Path):
    store, _, _, _ = _store_valid(tmp_path)
    with pytest.raises(UEIOuterBoundaryError) as raised:
        resolve_projection_context(store=store, request_ref={"id": "request/missing", "content_sha256": "0" * 64})
    assert raised.value.__cause__ is None


def test_invalid_registration_or_manifest_refs_have_conditional_resolution_facts(tmp_path: Path):
    store, request_ref, registration_ref, manifest_ref = _store_valid(tmp_path)
    context = resolve_projection_context(store=store, request_ref=request_ref)
    invalid_registration = {"id": "registration/missing", "content_sha256": "0" * 64}
    invalid_manifest = {"id": "manifest/missing", "content_sha256": "0" * 64}

    registration_failure = resolve_requested_profile(
        context=context, registration_ref=invalid_registration, manifest_ref=manifest_ref,
        provider_id=PROVIDER_ID, profile_id=PROFILE_ID,
    )
    manifest_failure = resolve_requested_profile(
        context=context, registration_ref=registration_ref, manifest_ref=invalid_manifest,
        provider_id=PROVIDER_ID, profile_id=PROFILE_ID,
    )

    assert (registration_failure["registration_resolution"], registration_failure["manifest_resolution"]) == ("invalid", "not_reached")
    assert "registration_ref" not in registration_failure and "manifest_ref" not in registration_failure
    assert (manifest_failure["registration_resolution"], manifest_failure["manifest_resolution"]) == ("resolved", "invalid")
    assert manifest_failure["registration_ref"] == registration_ref and "manifest_ref" not in manifest_failure
    _assert_no_projection_writes(store)


@pytest.mark.parametrize("target, expected_code, expected_resolutions", [
    ("registration_provider", "provider_unregistered", ("resolved", "not_reached")),
    ("manifest_provider", "capability_intersection_empty", ("resolved", "resolved")),
    ("disabled_egress", "egress_disallowed", ("resolved", "not_reached")),
])
def test_valid_policy_objects_fail_closed_for_provider_mismatch_and_disabled_egress(
    tmp_path: Path, target: str, expected_code: str, expected_resolutions: tuple[str, str],
):
    store, request_ref, registration_ref, manifest_ref = _store_valid(tmp_path)
    context = resolve_projection_context(store=store, request_ref=request_ref)
    registration = store.get(registration_ref, contract_version="trusted_provider_registration_v1")
    manifest = store.get(manifest_ref, contract_version="provider_manifest_v1")
    if target == "registration_provider":
        registration["provider_id"] = "local.test/other"
    elif target == "manifest_provider":
        manifest["provider_id"] = "local.test/other"
    else:
        registration["egress_policy"] = "disabled"
    registration.pop("content_sha256")
    manifest.pop("content_sha256")
    registration_ref = _put(store, registration)
    manifest_ref = _put(store, manifest)

    record = resolve_requested_profile(context=context, registration_ref=registration_ref, manifest_ref=manifest_ref,
                                       provider_id=PROVIDER_ID, profile_id=PROFILE_ID)

    assert record["resolved"] is False
    assert record["failure"]["code"] == expected_code
    assert (record["registration_resolution"], record["manifest_resolution"]) == expected_resolutions
    assert ("registration_ref" in record) is (expected_resolutions[0] == "resolved")
    assert ("manifest_ref" in record) is (expected_resolutions[1] == "resolved")


def test_schema_blocks_nonrestricted_wire_policy_before_registry_resolution(tmp_path: Path):
    store, _, registration_ref, _ = _store_valid(tmp_path)
    registration = store.get(registration_ref, contract_version="trusted_provider_registration_v1")
    registration["wire_payload_policy"] = "embedded"
    registration.pop("content_sha256")
    with pytest.raises(UEIValidationError, match="const mismatch"):
        _put(store, registration)
    _assert_no_projection_writes(store)


def test_valid_restrictive_payload_limits_are_preserved_deterministically_without_input_mutation(tmp_path: Path):
    store, request_ref, registration_ref, manifest_ref = _store_valid(tmp_path)
    context = resolve_projection_context(store=store, request_ref=request_ref)
    registration = store.get(registration_ref, contract_version="trusted_provider_registration_v1")
    restrictive = {
        "max_json_bytes": 1, "max_depth": 1, "max_array_items": 1,
        "max_object_properties": 1, "max_string_chars": 1, "allowed_json_types": ["null"],
    }
    registration["safe_payload_limits"] = restrictive
    registration.pop("content_sha256")
    registration_ref = _put(store, registration)
    before_context_request_ref = dict(context["request_ref"])
    before_registration_ref = dict(registration_ref)
    before_manifest_ref = dict(manifest_ref)

    first = resolve_requested_profile(context=context, registration_ref=registration_ref, manifest_ref=manifest_ref,
                                      provider_id=PROVIDER_ID, profile_id=PROFILE_ID)
    second = resolve_requested_profile(context=context, registration_ref=registration_ref, manifest_ref=manifest_ref,
                                       provider_id=PROVIDER_ID, profile_id=PROFILE_ID)

    assert first == second and first["resolved"] is True
    assert first["safe_payload_limits"] == restrictive
    assert context["request_ref"] == before_context_request_ref
    assert registration_ref == before_registration_ref and manifest_ref == before_manifest_ref


@pytest.mark.parametrize("registration_ref, manifest_ref, expected_resolutions, expected_code", [
    (None, None, ("not_found", "not_reached"), "provider_unregistered"),
    ("disabled", "valid", ("resolved", "not_reached"), "capability_intersection_empty"),
    ("remote", "valid", ("resolved", "not_reached"), "egress_disallowed"),
    ("conformance", "valid", ("resolved", "not_reached"), "capability_intersection_empty"),
    ("valid", None, ("resolved", "not_found"), "capability_intersection_empty"),
    ("valid", "absent-profile", ("resolved", "resolved"), "capability_intersection_empty"),
])
def test_post_precondition_failures_return_stage_conditional_resolution_facts(
    tmp_path: Path, registration_ref: str | None, manifest_ref: str | None,
    expected_resolutions: tuple[str, str], expected_code: str,
):
    store, request_ref, valid_registration_ref, valid_manifest_ref = _store_valid(tmp_path)
    context = resolve_projection_context(store=store, request_ref=request_ref)

    def altered_registration(**changes: object) -> dict[str, str]:
        base = store.get(valid_registration_ref, contract_version="trusted_provider_registration_v1")
        base["registration_id"] = "registration/" + next(iter(changes))
        base.update(changes)
        base.pop("content_sha256")
        return _put(store, base)

    def altered_manifest(**changes: object) -> dict[str, str]:
        base = store.get(valid_manifest_ref, contract_version="provider_manifest_v1")
        base["manifest_id"] = "manifest/" + next(iter(changes))
        base.update(changes)
        base.pop("content_sha256")
        return _put(store, base)

    refs = {
        "valid": valid_registration_ref,
        "disabled": altered_registration(enabled=False),
        "remote": altered_registration(egress_policy="remote_allowed"),
        "conformance": altered_registration(required_conformance_suite="other-suite"),
    }
    manifests = {
        "valid": valid_manifest_ref,
        "absent-profile": altered_manifest(profiles=[{
            "profile_id": "local.test/ocr/other", "operation": "screen_parse",
            "input_contract": "screen_parse_request_v1", "output_contract": "provider_safe_result_v1",
            "declared_output_kinds": ["text"], "supported_coordinate_spaces": ["capture_pixel_xyxy"],
            "supports_capture_artifact": True, "privacy_capabilities": ["restricted"], "mode_allowlist": ["Shadow"],
        }]),
    }
    record = resolve_requested_profile(
        context=context, registration_ref=refs.get(registration_ref), manifest_ref=manifests.get(manifest_ref),
        provider_id=PROVIDER_ID, profile_id=PROFILE_ID,
    )
    assert record["resolved"] is False
    assert (record["registration_resolution"], record["manifest_resolution"]) == expected_resolutions
    assert record["failure"]["code"] == expected_code
    assert record["requested_provider_id"] == PROVIDER_ID
    assert record["requested_profile_id"] == PROFILE_ID
    assert ("registration_ref" in record) is (expected_resolutions[0] == "resolved")
    assert ("manifest_ref" in record) is (expected_resolutions[1] == "resolved")
    _assert_no_projection_writes(store)


@pytest.mark.parametrize("target, expected_code", [
    ("request_pair", "capability_intersection_empty"),
    ("registration_profile", "profile_unregistered"),
    ("registration_mode", "capability_intersection_empty"),
    ("registration_privacy", "privacy_disallowed"),
    ("manifest_mode", "capability_intersection_empty"),
    ("manifest_privacy", "capability_intersection_empty"),
    ("manifest_capture", "capability_intersection_empty"),
])
def test_profile_mode_privacy_and_capture_capability_intersection_fails_closed(
    tmp_path: Path, target: str, expected_code: str,
):
    store, request_ref, registration_ref, manifest_ref = _store_valid(tmp_path)
    context = resolve_projection_context(store=store, request_ref=request_ref)
    registration = store.get(registration_ref, contract_version="trusted_provider_registration_v1")
    manifest = store.get(manifest_ref, contract_version="provider_manifest_v1")
    if target == "request_pair":
        provider_id, profile_id = PROVIDER_ID, "local.test/ocr/not-requested"
    else:
        provider_id, profile_id = PROVIDER_ID, PROFILE_ID
        if target == "registration_profile":
            registration["profile_ids"] = ["local.test/ocr/other"]
        elif target == "registration_mode":
            registration["allowed_modes"] = ["Primary"]
        elif target == "registration_privacy":
            registration["allowed_privacy_policies"] = ["minimal"]
        elif target == "manifest_mode":
            manifest["profiles"][0]["mode_allowlist"] = ["Primary"]
        elif target == "manifest_privacy":
            manifest["profiles"][0]["privacy_capabilities"] = ["minimal"]
        else:
            manifest["profiles"][0]["supports_capture_artifact"] = False
        registration.pop("content_sha256")
        manifest.pop("content_sha256")
        registration_ref = _put(store, registration)
        manifest_ref = _put(store, manifest)
    record = resolve_requested_profile(context=context, registration_ref=registration_ref, manifest_ref=manifest_ref,
                                       provider_id=provider_id, profile_id=profile_id)
    assert record["resolved"] is False
    assert record["failure"]["code"] == expected_code
    _assert_no_projection_writes(store)
