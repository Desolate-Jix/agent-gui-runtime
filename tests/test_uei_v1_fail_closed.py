from __future__ import annotations

from copy import deepcopy
import json

import pytest

from app.learn.recognition.uei.canonical import deterministic_error_id, deterministic_result_id
from app.learn.recognition.uei.projections import (
    project_ocr_result,
    project_screen_parser_result,
    project_uia_snapshot,
)
from tests.uei_v1_helpers import build_context_from_sidecar, load_fixture


@pytest.fixture
def context(tmp_path):
    return build_context_from_sidecar(tmp_path, "uia")


def oversized_opaque_fixture() -> dict[str, object]:
    fixture = deepcopy(load_fixture("uia-snapshot-static.json"))
    fixture["controls"][0]["automation_id"] = "x" * 4097
    return fixture


def test_post_precondition_payload_failure_stores_error_before_failed_result(context):
    result = project_uia_snapshot(**context.for_case("uia"), fixture=oversized_opaque_fixture())

    assert result["status"] == "failed"
    assert result["items"] == []
    assert result["review_only"] is True
    error = context.store.get(result["error_ref"], contract_version="provider_error_v1")
    assert error["code"] == "payload_limit_exceeded"
    assert context.store.write_order[-2:] == ("provider_error_v1", "provider_safe_result_v1")
    assert result["result_id"] == deterministic_result_id(
        request_ref=context.request_ref,
        provider_id=context.provider_id,
        profile_id=context.profile_id,
        fixture_kind="uia",
    )
    assert error["error_id"] == deterministic_error_id(
        request_ref=context.request_ref,
        provider_id=context.provider_id,
        profile_id=context.profile_id,
        stage="redaction",
        code="payload_limit_exceeded",
    )
    assert error["safe_details"] == {"reason_class": "payload"}


@pytest.mark.parametrize(
    ("value", "category"),
    [
        ("Bearer top-secret", "credential"),
        ("Basic dXNlcjpwYXNz", "credential"),
        ("api_key=top-secret", "credential"),
        ("password=top-secret", "credential"),
        ("token=top-secret", "credential"),
        ("session=top-secret", "credential"),
        ("cookie=top-secret", "credential"),
        ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.signature", "credential"),
        ("-----BEGIN PRIVATE KEY-----", "private_key"),
        (r"C:\Users\secret\Desktop\private.txt", "personal_path"),
        ("secret@example.com", "personal_data"),
        ("+64 21 555 1234", "personal_data"),
    ],
    ids=[
        "bearer", "basic", "api-key", "password", "token", "session", "cookie", "jwt",
        "private-key", "windows-user-path", "email", "phone",
    ],
)
def test_sensitive_fixture_value_is_redacted_then_fails_closed(context, value, category):
    fixture = deepcopy(load_fixture("uia-snapshot-static.json"))
    fixture["controls"][0]["name"] = value

    result = project_uia_snapshot(**context.for_case("uia"), fixture=fixture)
    error = context.store.get(result["error_ref"], contract_version="provider_error_v1")
    persisted_result = context.store.get(
        {"id": result["result_id"], "content_sha256": result["content_sha256"]},
        contract_version="provider_safe_result_v1",
    )
    serialized = json.dumps([error, persisted_result], sort_keys=True)

    assert result["status"] == "failed" and result["items"] == []
    assert value not in serialized
    assert error["safe_details"] == {"reason_class": "privacy"}
    summary = result["redaction_summary"]
    assert summary["redacted_item_count"] == 1
    assert summary["redacted_field_count"] == 1
    assert summary["secret_detected"] is True
    assert summary["sensitive_categories"] == [category]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda fixture: fixture.__setitem__("wire_payload", "never-store"),
        lambda fixture: fixture.__setitem__("raw_payload", "never-store"),
        lambda fixture: fixture["controls"][0].__setitem__("unknown", "value"),
        lambda fixture: fixture["controls"].append(deepcopy(fixture["controls"][0])),
        lambda fixture: fixture["controls"][0].__setitem__("control_id", ""),
        lambda fixture: fixture["controls"][0].__setitem__("bbox", {"x": 0, "y": 0, "w": 0, "h": 1}),
        lambda fixture: fixture["controls"][0].__setitem__("bbox", {"x": -1, "y": 0, "w": 1, "h": 1}),
        lambda fixture: fixture["controls"][0].__setitem__("bbox", {"x": 0, "y": 0, "w": 100001, "h": 1}),
    ],
)
def test_post_precondition_fixture_failures_are_failed_results(context, mutate):
    fixture = deepcopy(load_fixture("uia-snapshot-static.json"))
    mutate(fixture)

    result = project_uia_snapshot(**context.for_case("uia"), fixture=fixture)
    error = context.store.get(result["error_ref"], contract_version="provider_error_v1")

    assert result["status"] == "failed" and result["items"] == [] and result["review_only"] is True
    assert error["code"] in {"wire_payload_forbidden", "provider_fixture_schema_invalid", "fixture_invalid", "coordinate_invalid"}
    assert context.store.write_order[-2:] == ("provider_error_v1", "provider_safe_result_v1")


@pytest.mark.parametrize(
    "fixture",
    [
        {"provider": "windows_uia", "status": "ok", "controls": [b"bytes"]},
        {"provider": "windows_uia", "status": "ok", "controls": ["x" * 4097]},
        {"provider": "windows_uia", "status": "ok", "controls": [[] for _ in range(257)]},
        {"provider": "windows_uia", "status": "ok", "controls": [{str(i): None for i in range(65)}]},
        {"provider": "windows_uia", "status": "ok", "controls": [[[[[[[[[None]]]]]]]]]},
    ],
)
def test_payload_shape_limits_fail_closed(context, fixture):
    result = project_uia_snapshot(**context.for_case("uia"), fixture=fixture)
    error = context.store.get(result["error_ref"], contract_version="provider_error_v1")

    assert result["status"] == "failed"
    assert error["stage"] == "redaction" and error["code"] == "payload_limit_exceeded"


def _failure_pair(context, result):
    error = context.store.get(result["error_ref"], contract_version="provider_error_v1")
    assert result["status"] == "failed" and result["items"] == [] and result["review_only"] is True
    assert context.store.write_order[-2:] == ("provider_error_v1", "provider_safe_result_v1")
    return error


def test_deep_payload_is_iteratively_rejected_and_preserves_prior_redaction(context):
    fixture = deepcopy(load_fixture("uia-snapshot-static.json"))
    fixture["controls"][0]["name"] = "Bearer sensitive-value"
    nested: object = None
    for _ in range(1500):
        nested = [nested]
    fixture["window"]["deep"] = nested
    fixture = {"controls": fixture["controls"], **fixture}

    result = project_uia_snapshot(**context.for_case("uia"), fixture=fixture)
    error = _failure_pair(context, result)

    assert (error["stage"], error["code"]) == ("redaction", "payload_limit_exceeded")
    assert result["redaction_summary"] == {
        "redacted_item_count": 1,
        "redacted_field_count": 1,
        "secret_detected": True,
        "sensitive_categories": ["credential"],
    }


def test_payload_aggregate_bytes_use_resolved_registration_limit(context):
    fixture = deepcopy(load_fixture("uia-snapshot-static.json"))
    fixture["provider_version"] = "x" * 4096
    fixture["window"]["title"] = "y" * 4096
    fixture["controls"] = [deepcopy(fixture["controls"][0]) for _ in range(20)]
    for index, control in enumerate(fixture["controls"]):
        control["control_id"] = f"safe-item-{index}"
        control["name"] = "n" * 4096
        control["automation_id"] = "a" * 4096
        control["class_name"] = "c" * 4096
        control["patterns"] = ["p" * 4096]

    result = project_uia_snapshot(**context.for_case("uia"), fixture=fixture)
    error = _failure_pair(context, result)

    assert (error["stage"], error["code"]) == ("redaction", "payload_limit_exceeded")


@pytest.mark.parametrize("case", ["ocr", "screen-parser"], ids=["ocr", "screen-parser"])
def test_ocr_and_screen_parser_privacy_failures_are_terminal(tmp_path, case):
    context = build_context_from_sidecar(tmp_path, case)
    fixture_name = "ocr-result-static.json" if case == "ocr" else "screen-parser-result-static.json"
    fixture = deepcopy(load_fixture(fixture_name))
    if case == "ocr":
        fixture["matches"][0]["text"] = "Bearer sensitive-value"
        result = project_ocr_result(**context.for_case(case), fixture=fixture)
    else:
        fixture["elements"][0]["content"] = "Bearer sensitive-value"
        result = project_screen_parser_result(**context.for_case(case), fixture=fixture)

    error = _failure_pair(context, result)
    assert error["safe_details"] == {"reason_class": "privacy"}
    assert result["redaction_summary"]["sensitive_categories"] == ["credential"]


@pytest.mark.parametrize(
    ("missing_ref", "stage", "code", "registration_resolution", "manifest_resolution"),
    [
        ("registration_ref", "registration", "provider_unregistered", "not_found", "not_reached"),
        ("manifest_ref", "manifest", "capability_intersection_empty", "resolved", "not_found"),
    ],
    ids=["missing-registration", "missing-manifest"],
)
def test_policy_failures_keep_only_conditionally_resolved_references(
    context, missing_ref, stage, code, registration_resolution, manifest_resolution,
):
    arguments = context.for_case("uia")
    arguments[missing_ref] = None

    result = project_uia_snapshot(**arguments, fixture=load_fixture("uia-snapshot-static.json"))
    error = _failure_pair(context, result)

    assert (error["stage"], error["code"]) == (stage, code)
    assert error["safe_details"] == {"reason_class": "policy"}
    assert result["registration_resolution"] == registration_resolution
    assert result["manifest_resolution"] == manifest_resolution
    assert ("registration_ref" in result) is (registration_resolution == "resolved")
    assert ("manifest_ref" in result) is (manifest_resolution == "resolved")


def test_adapter_bad_transform_is_coordinate_failure(context):
    arguments = context.for_case("uia")
    arguments["transform_ref"] = context.request_ref

    result = project_uia_snapshot(**arguments, fixture=load_fixture("uia-snapshot-static.json"))
    error = _failure_pair(context, result)

    assert (error["stage"], error["code"]) == ("coordinate", "coordinate_invalid")


@pytest.mark.parametrize("case", ["ocr", "screen-parser"], ids=["ocr", "screen-parser"])
def test_ocr_and_screen_parser_payload_and_schema_failures_are_terminal(tmp_path, case):
    context = build_context_from_sidecar(tmp_path, case)
    fixture_name = "ocr-result-static.json" if case == "ocr" else "screen-parser-result-static.json"
    fixture = deepcopy(load_fixture(fixture_name))
    if case == "ocr":
        fixture["matches"] = [deepcopy(fixture["matches"][0]) for _ in range(257)]
        result = project_ocr_result(**context.for_case(case), fixture=fixture)
        expected = ("redaction", "payload_limit_exceeded")
    else:
        fixture["unexpected"] = "safe-extra"
        result = project_screen_parser_result(**context.for_case(case), fixture=fixture)
        expected = ("projection", "provider_fixture_schema_invalid")

    error = _failure_pair(context, result)
    assert (error["stage"], error["code"]) == expected


def test_invalid_projected_safe_result_contract_is_failed_result(context, monkeypatch):
    from app.learn.recognition.uei import projections

    monkeypatch.setattr(projections, "make_source_item", lambda **_: {"invalid": True})
    result = project_uia_snapshot(**context.for_case("uia"), fixture=load_fixture("uia-snapshot-static.json"))
    error = _failure_pair(context, result)

    assert (error["stage"], error["code"]) == ("projection", "provider_fixture_schema_invalid")


def test_same_failure_pair_is_idempotent(context):
    fixture = oversized_opaque_fixture()
    first = project_uia_snapshot(**context.for_case("uia"), fixture=fixture)
    first_order = context.store.write_order
    second = project_uia_snapshot(**context.for_case("uia"), fixture=fixture)

    assert first == second
    assert context.store.write_order == first_order


def test_large_redaction_summary_writes_one_valid_idempotent_failure_pair(context):
    from app.learn.recognition.uei.projections import _failure_context, _projection_context, store_post_precondition_failure

    resolved, selection = _projection_context(**{key: value for key, value in context.for_case("uia").items() if key != "fixture_binding" and key != "transform_ref"})
    failure_context = _failure_context(resolved, selection)
    failure_context.update({
        "_uei_provider_id": context.provider_id,
        "_uei_profile_id": context.profile_id,
        "_uei_fixture_kind": "uia",
        "_uei_redaction_summary": {
            "redacted_item_count": 110000,
            "redacted_field_count": 110000,
            "secret_detected": True,
            "sensitive_categories": ["credential"],
        },
    })

    first = store_post_precondition_failure(context=failure_context, stage="redaction", code="payload_limit_exceeded", reason_class="payload")
    order = context.store.write_order
    second = store_post_precondition_failure(context=failure_context, stage="redaction", code="payload_limit_exceeded", reason_class="payload")

    assert first == second and context.store.write_order == order
    assert order[-2:] == ("provider_error_v1", "provider_safe_result_v1")
    assert first["redaction_summary"]["redacted_field_count"] == 110000
