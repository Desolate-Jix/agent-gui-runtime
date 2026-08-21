from __future__ import annotations

import math
import struct
import pytest

from app.learn.recognition.uei.contracts import UEIValidationError
from app.learn.recognition.uei.canonical import (
    canonical_json_bytes,
    content_sha256,
    deterministic_error_id,
    deterministic_result_id,
    immutable_ref,
    seal_immutable,
)


RFC8785_APPENDIX_B_VECTORS = (
    ("0000000000000000", "0"),
    ("8000000000000000", "0"),
    ("0000000000000001", "5e-324"),
    ("8000000000000001", "-5e-324"),
    ("7fefffffffffffff", "1.7976931348623157e+308"),
    ("ffefffffffffffff", "-1.7976931348623157e+308"),
    ("4340000000000000", "9007199254740992"),
    ("c340000000000000", "-9007199254740992"),
    ("4430000000000000", "295147905179352830000"),
    ("c430000000000000", "-295147905179352830000"),
    ("44b52d02c7e14af5", "9.999999999999997e+22"),
    ("44b52d02c7e14af6", "1e+23"),
    ("44b52d02c7e14af7", "1.0000000000000001e+23"),
    ("444b1ae4d6e2ef4e", "999999999999999700000"),
    ("444b1ae4d6e2ef4f", "999999999999999900000"),
    ("444b1ae4d6e2ef50", "1e+21"),
    ("3eb0c6f7a0b5ed8c", "9.999999999999997e-7"),
    ("3eb0c6f7a0b5ed8d", "0.000001"),
    ("41b3de4355555553", "333333333.3333332"),
    ("41b3de4355555554", "333333333.33333325"),
    ("41b3de4355555555", "333333333.3333333"),
    ("41b3de4355555556", "333333333.3333334"),
    ("41b3de4355555557", "333333333.33333343"),
    ("becbf647612f3696", "-0.0000033333333333333333"),
    ("43143ff3c1cb0959", "1424953923781206.2"),
)


def test_jcs_hash_uses_utf8_and_excludes_only_self_hash():
    value = {
        "contract_version": "artifact_ref_v1",
        "artifact_id": "artifact/x",
        "artifact_sha256": "a" * 64,
        "media_type": "image/png",
        "byte_length": 1,
    }
    sealed = seal_immutable(value)
    assert sealed["content_sha256"] == content_sha256(sealed)
    assert canonical_json_bytes({"\u00e9": 1, "a": 2}) == b'{"a":2,"\xc3\xa9":1}'
    assert content_sha256({**sealed, "content_sha256": "f" * 64}) == sealed["content_sha256"]
    assert content_sha256({**sealed, "byte_length": 2}) != sealed["content_sha256"]
    assert 'content_sha256' not in value


@pytest.mark.parametrize(("bits", "expected"), RFC8785_APPENDIX_B_VECTORS)
def test_jcs_uses_rfc8785_binary64_lexical_vectors(bits: str, expected: str):
    value = struct.unpack(">d", bytes.fromhex(bits))[0]
    assert canonical_json_bytes(value).decode("ascii") == expected


def test_jcs_sorts_property_names_by_utf16_code_units():
    assert canonical_json_bytes({"\ue000": 2, "\U0001f600": 1}) == '{"\U0001f600":1,"\ue000":2}'.encode("utf-8")


def test_jcs_escapes_only_required_characters_and_preserves_supplementary_unicode():
    value = "\b\t\n\f\r\x00\x1f\"\\/\U0001f600"
    assert canonical_json_bytes(value) == b'"\\b\\t\\n\\f\\r\\u0000\\u001f\\"\\\\/\xf0\x9f\x98\x80"'


@pytest.mark.parametrize(
    "value",
    [math.nan, math.inf, -math.inf, "\ud800", {"\udfff": 1}, {1: "not-a-string-key"}, b"bytes", ("tuple",)],
)
def test_jcs_rejects_non_json_nonfinite_and_lone_surrogate_values(value: object):
    with pytest.raises(UEIValidationError):
        canonical_json_bytes(value)


def test_jcs_rejects_integer_not_exactly_representable_as_binary64():
    with pytest.raises(UEIValidationError):
        canonical_json_bytes((1 << 53) + 1)


def test_seal_is_a_deep_copy_and_immutable_ref_has_exact_shape():
    source = {"artifact_id": "artifact/x", "nested": {"items": ["before"]}}
    sealed = seal_immutable(source)
    source["nested"]["items"].append("after")
    assert sealed["nested"] == {"items": ["before"]}
    assert immutable_ref(sealed, id_field="artifact_id") == {
        "id": "artifact/x",
        "content_sha256": sealed["content_sha256"],
    }


@pytest.mark.parametrize(
    "value,id_field",
    [({}, "artifact_id"), ({"artifact_id": ""}, "artifact_id"), ({"artifact_id": 1}, "artifact_id")],
)
def test_immutable_ref_rejects_missing_or_non_string_stable_id(value: dict[str, object], id_field: str):
    with pytest.raises(UEIValidationError):
        immutable_ref(seal_immutable(value), id_field=id_field)


def test_jcs_rejects_cyclic_list_and_dict_but_allows_shared_acyclic_values():
    cyclic_list: list[object] = []
    cyclic_list.append(cyclic_list)
    cyclic_dict: dict[str, object] = {}
    cyclic_dict["self"] = cyclic_dict
    for value in (cyclic_list, cyclic_dict):
        with pytest.raises(UEIValidationError, match="jcs_cyclic_value"):
            canonical_json_bytes(value)

    shared = {"value": 1}
    assert canonical_json_bytes([shared, shared]) == b'[{"value":1},{"value":1}]'


def test_deterministic_result_id_uses_each_identity_field_and_canonical_request_ref():
    request_ref = {"id": "request/x", "content_sha256": "a" * 64}
    result_id = deterministic_result_id(
        request_ref=request_ref,
        provider_id="provider/x",
        profile_id="profile/x",
        fixture_kind="ocr",
    )
    assert result_id == deterministic_result_id(
        request_ref={"content_sha256": "a" * 64, "id": "request/x"},
        provider_id="provider/x",
        profile_id="profile/x",
        fixture_kind="ocr",
    )
    assert result_id.startswith("result/")
    assert len(result_id.removeprefix("result/")) == 64
    assert all(character in "0123456789abcdef" for character in result_id.removeprefix("result/"))
    for changes in (
        {"request_ref": {"id": "request/y", "content_sha256": "a" * 64}},
        {"request_ref": {"id": "request/x", "content_sha256": "b" * 64}},
        {"provider_id": "provider/y"},
        {"profile_id": "profile/y"},
        {"fixture_kind": "uia"},
    ):
        assert deterministic_result_id(
            request_ref=changes.get("request_ref", request_ref),
            provider_id=changes.get("provider_id", "provider/x"),
            profile_id=changes.get("profile_id", "profile/x"),
            fixture_kind=changes.get("fixture_kind", "ocr"),
        ) != result_id


def test_deterministic_error_id_uses_each_identity_field_and_canonical_request_ref():
    request_ref = {"id": "request/x", "content_sha256": "a" * 64}
    error_id = deterministic_error_id(
        request_ref=request_ref,
        provider_id="provider/x",
        profile_id="profile/x",
        stage="projection",
        code="projection_failed",
    )
    assert error_id == deterministic_error_id(
        request_ref={"content_sha256": "a" * 64, "id": "request/x"},
        provider_id="provider/x",
        profile_id="profile/x",
        stage="projection",
        code="projection_failed",
    )
    assert error_id.startswith("error/")
    assert len(error_id.removeprefix("error/")) == 64
    assert all(character in "0123456789abcdef" for character in error_id.removeprefix("error/"))
    for changes in (
        {"request_ref": {"id": "request/y", "content_sha256": "a" * 64}},
        {"request_ref": {"id": "request/x", "content_sha256": "b" * 64}},
        {"provider_id": "provider/y"},
        {"profile_id": "profile/y"},
        {"stage": "redaction"},
        {"code": "payload_limit_exceeded"},
    ):
        assert deterministic_error_id(
            request_ref=changes.get("request_ref", request_ref),
            provider_id=changes.get("provider_id", "provider/x"),
            profile_id=changes.get("profile_id", "profile/x"),
            stage=changes.get("stage", "projection"),
            code=changes.get("code", "projection_failed"),
        ) != error_id
