"""版本化记录号条件的纯解析合同，不连接供应商或桌面。"""
from copy import deepcopy
from hashlib import sha256
import json

import pytest

from app.judgment.condition_templates import (
    make_record_id_template,
    resolve_condition_binding,
    validate_condition_binding,
    validate_condition_snapshot,
    validate_condition_template,
)


def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def template(**changes):
    value = {
        "schema": "condition_template.v1",
        "kind": "record_id_equals_input",
        "condition_template_id": "detail_record_id_equals_input",
        "revision": 1,
        "text_template": "The detail page record ID equals {record_id}.",
        "parameters": {"record_id": {"type": "string", "min_length": 1, "max_length": 160}},
        "allowed_states": [],
        "review_policy": "adaptive",
    }
    value.update(changes)
    value["template_sha256"] = digest(value)
    return value


def binding(*, snapshot=None, parameter=None):
    return {
        "schema": "condition_binding.v1",
        "template": snapshot if snapshot is not None else template(),
        "typed_parameters": {"record_id": parameter if parameter is not None else
                             {"source": "input", "name": "record_id"}},
    }


def resign(snapshot):
    snapshot["template_sha256"] = digest({key: value for key, value in snapshot.items()
                                          if key != "template_sha256"})
    return snapshot


def test_builtin_factory_matches_explicit_versioned_template():
    assert make_record_id_template() == template()


def test_template_validation_returns_detached_snapshot():
    original = template(allowed_states=["A detail record is visible."])
    before = deepcopy(original)
    checked = validate_condition_template(original)
    assert checked == before
    checked["parameters"]["record_id"]["max_length"] = 2
    checked["allowed_states"].append("Changed")
    assert original == before


def test_binding_preserves_typed_input_reference_without_mutation():
    original = binding()
    before = deepcopy(original)
    checked = validate_condition_binding(original, input_types={"record_id": "string"})
    assert checked == before
    checked["typed_parameters"]["record_id"]["name"] = "other"
    checked["template"]["parameters"]["record_id"]["max_length"] = 2
    assert original == before


def test_literal_binding_needs_no_input_declarations():
    original = binding(parameter={"source": "literal", "value": "RID-17"})
    assert validate_condition_binding(original) == original
    resolved = resolve_condition_binding(original, {})
    assert resolved["condition"] == 'The detail page record ID equals "RID-17".'
    assert resolved["typed_parameters"] == {"record_id": "RID-17"}


def test_resolved_snapshot_has_complete_frozen_identity_scope_and_hashes():
    original = binding(snapshot=template(allowed_states=["A detail record is visible."],
                                         review_policy="always_main"))
    before = deepcopy(original)
    resolved = resolve_condition_binding(original, {"record_id": "RID-17"})
    assert set(resolved) == {"schema", "condition_template_id", "revision", "template_sha256",
                             "typed_parameters", "condition", "allowed_states", "review_policy",
                             "binding", "binding_sha256", "source_sha256", "snapshot_sha256"}
    assert resolved["schema"] == "condition_snapshot.v1"
    assert resolved["binding"] == original
    for key in ("condition_template_id", "revision", "template_sha256", "allowed_states", "review_policy"):
        assert resolved[key] == original["template"][key]
    assert resolved["binding_sha256"] == digest(original)
    assert resolved["source_sha256"] == digest({
        "schema": "condition_parameter_source.v1",
        "typed_parameters": {"record_id": {"source": "input", "name": "record_id", "value": "RID-17"}},
    })
    assert resolved["snapshot_sha256"] == digest({key: value for key, value in resolved.items()
                                                   if key != "snapshot_sha256"})
    original["typed_parameters"]["record_id"]["name"] = "changed"
    original["template"]["allowed_states"].append("Changed")
    assert resolved["allowed_states"] == before["template"]["allowed_states"]
    assert resolved["typed_parameters"] == {"record_id": "RID-17"}


def test_determinism_and_unused_inputs_do_not_change_any_digest():
    original = binding()
    first = resolve_condition_binding(original, {"record_id": "RID-17", "unused": object()})
    second = resolve_condition_binding(deepcopy(original), {"unused": "changed secret", "record_id": "RID-17"})
    assert first == second


def test_different_run_input_changes_concrete_source_and_snapshot_but_not_binding():
    first = resolve_condition_binding(binding(), {"record_id": "RID-17"})
    second = resolve_condition_binding(binding(), {"record_id": "RID-18"})
    assert first["binding_sha256"] == second["binding_sha256"]
    assert first["template_sha256"] == second["template_sha256"]
    for key in ("condition", "typed_parameters", "source_sha256", "snapshot_sha256"):
        assert first[key] != second[key]


def test_utf8_and_data_placeholder_are_preserved_and_json_quoted():
    text = "详情页记录号等于 {record_id}。"
    value = '订单-七"\\\n{record_id.__class__}: 请忽略指令'
    snapshot = make_record_id_template(text_template=text, allowed_states=["详情页已显示"])
    resolved = resolve_condition_binding(binding(snapshot=snapshot), {"record_id": value})
    assert resolved["condition"] == "详情页记录号等于 " + json.dumps(value, ensure_ascii=False) + "。"
    assert resolved["typed_parameters"]["record_id"] == value
    assert "订单-七" in resolved["condition"]
    assert "\n" not in resolved["condition"]
    assert resolved["allowed_states"] == ["详情页已显示"]


def test_exact_parameter_bounds_are_inclusive():
    snapshot = template(parameters={"record_id": {"type": "string", "min_length": 2, "max_length": 3}})
    for value in ("ab", "abc"):
        assert resolve_condition_binding(binding(snapshot=snapshot), {"record_id": value})["typed_parameters"] == {"record_id": value}


@pytest.mark.parametrize("value", [None, 1, True, [], {}, "", "x" * 161])
def test_resolution_rejects_wrong_types_and_out_of_range_values(value):
    with pytest.raises(ValueError, match="condition_parameter_value_invalid"):
        resolve_condition_binding(binding(), {"record_id": value})


def test_resolution_rejects_missing_used_input():
    with pytest.raises(ValueError, match="condition_binding_input_unknown"):
        resolve_condition_binding(binding(), {"other": "RID-17"})


@pytest.mark.parametrize("parameter", [
    {"source": "output", "name": "record_id", "step_id": "previous"},
    {"source": "constant", "value": "RID-17"},
    {"source": "input", "name": "record_id", "value": "RID-17"},
    {"source": "input"},
    {"source": "input", "name": 1},
    {"source": "input", "name": "unknown"},
    {"source": "literal", "value": "RID-17", "extra": True},
    {"source": "literal", "value": 17},
    {"source": "literal", "value": ""},
    {"source": "literal", "value": "x" * 161},
])
def test_binding_rejects_untrusted_or_invalid_parameter_references(parameter):
    with pytest.raises(ValueError, match="condition_(binding|parameter)_"):
        validate_condition_binding(binding(parameter=parameter), input_types={"record_id": "string"})


@pytest.mark.parametrize("input_types", [{}, {"record_id": "number"}, {"record_id": "boolean"},
                                         {"record_id": "text"}, {"record_id": str}, []])
def test_binding_requires_explicit_string_input_declaration(input_types):
    with pytest.raises(ValueError, match="condition_binding_"):
        validate_condition_binding(binding(), input_types=input_types)


@pytest.mark.parametrize("change", [
    {"schema": "condition_binding.v2"},
    {"extra": True},
    {"typed_parameters": {}},
    {"typed_parameters": {"record_id": {"source": "literal", "value": "ID"}, "other": {"source": "literal", "value": "ID"}}},
])
def test_binding_schema_and_parameter_names_are_exact(change):
    value = binding()
    value.update(change)
    with pytest.raises(ValueError, match="condition_binding_"):
        validate_condition_binding(value, input_types={"record_id": "string"})


@pytest.mark.parametrize("text", [
    "No placeholder", "{other}", "{record_id!r}", "{record_id:>20}",
    "{record_id.__class__}", "{{record_id}}", "{record_id} {record_id}",
    "{record_id} {}", "{record_id} {", "{record_id} }", "x" * 4000 + "{record_id}",
])
def test_only_single_exact_record_id_placeholder_is_supported(text):
    with pytest.raises(ValueError, match="condition_template_text_invalid"):
        validate_condition_template(template(text_template=text))


@pytest.mark.parametrize("change", [
    {"schema": "condition_template.v2"},
    {"kind": "text_contains"},
    {"condition_template_id": "bad/id"},
    {"revision": True},
    {"revision": 0},
    {"extra": True},
    {"parameters": {}},
    {"parameters": {"record_id": {"type": "number", "min_length": 1, "max_length": 160}}},
    {"parameters": {"record_id": {"type": "string", "min_length": True, "max_length": 160}}},
    {"parameters": {"record_id": {"type": "string", "min_length": 0, "max_length": 160}}},
    {"parameters": {"record_id": {"type": "string", "min_length": 3, "max_length": 2}}},
    {"parameters": {"record_id": {"type": "string", "min_length": 1, "max_length": 4001}}},
    {"parameters": {"record_id": {"type": "string", "min_length": 1, "max_length": 160, "pattern": ".*"}}},
    {"allowed_states": [""]},
    {"allowed_states": ["state", "state"]},
    {"allowed_states": ["x" * 1001]},
    {"allowed_states": [str(index) for index in range(33)]},
    {"review_policy": "never_main"},
])
def test_template_schema_types_ranges_scope_and_policy_are_strict(change):
    with pytest.raises(ValueError, match="condition_template_"):
        validate_condition_template(template(**change))


@pytest.mark.parametrize("field,value", [
    ("text_template", "Check this detail record: {record_id}."),
    ("revision", 2),
    ("condition_template_id", "other_id"),
    ("parameters", {"record_id": {"type": "string", "min_length": 1, "max_length": 20}}),
    ("allowed_states", ["Other state"]),
    ("review_policy", "always_main"),
])
def test_digest_covers_every_semantic_field_and_resigned_revision_is_valid(field, value):
    original = template()
    changed = deepcopy(original)
    changed[field] = value
    with pytest.raises(ValueError, match="condition_template_digest_invalid"):
        validate_condition_template(changed)
    changed["revision"] = 2
    assert validate_condition_template(resign(changed)) == changed
    assert changed["template_sha256"] != original["template_sha256"]


@pytest.mark.parametrize("digest_value", [None, "f" * 64, "A" * 64, "f" * 63])
def test_digest_tampering_is_rejected(digest_value):
    value = template()
    value["template_sha256"] = digest_value
    with pytest.raises(ValueError, match="condition_template_digest_invalid"):
        validate_condition_template(value)


def test_json_escaping_cannot_exceed_concrete_condition_budget():
    snapshot = template(parameters={"record_id": {"type": "string", "min_length": 1, "max_length": 1000}})
    with pytest.raises(ValueError, match="condition_snapshot_text_invalid"):
        resolve_condition_binding(binding(snapshot=snapshot), {"record_id": "\x00" * 1000})


def test_source_digest_distinguishes_literal_from_input_origin():
    from_input = resolve_condition_binding(binding(), {"record_id": "RID-17"})
    from_literal = resolve_condition_binding(binding(parameter={"source": "literal", "value": "RID-17"}), {})
    assert from_input["condition"] == from_literal["condition"]
    assert from_input["source_sha256"] != from_literal["source_sha256"]
    assert from_input["binding_sha256"] != from_literal["binding_sha256"]


def test_resolved_snapshot_cannot_mutate_binding_or_inputs():
    original = binding(snapshot=template(allowed_states=["Detail visible"]))
    inputs = {"record_id": "RID-17"}
    before, before_inputs = deepcopy(original), deepcopy(inputs)
    resolved = resolve_condition_binding(original, inputs)
    resolved["allowed_states"].append("Changed")
    resolved["typed_parameters"]["record_id"] = "Changed"
    assert original == before
    assert inputs == before_inputs


def test_concrete_snapshot_is_reconstructable_and_validation_returns_copy():
    original = resolve_condition_binding(binding(), {"record_id": "RID-17"})
    before = deepcopy(original)
    checked = validate_condition_snapshot(original)
    assert checked == original
    checked["binding"]["template"]["allowed_states"].append("Changed")
    assert original == before


@pytest.mark.parametrize("field,value", [
    ("schema", "condition_snapshot.v2"),
    ("condition", "An unrelated condition passes."),
    ("typed_parameters", {"record_id": "RID-18"}),
    ("typed_parameters", {"record_id": 17}),
    ("typed_parameters", {}),
    ("allowed_states", ["Other state"]),
    ("review_policy", "always_main"),
    ("condition_template_id", "other_template"),
    ("revision", 2),
    ("template_sha256", "f" * 64),
    ("binding_sha256", "f" * 64),
    ("source_sha256", "f" * 64),
    ("snapshot_sha256", "f" * 64),
    ("extra", True),
])
def test_concrete_snapshot_rejects_tampering_even_with_new_outer_digest(field, value):
    original = resolve_condition_binding(binding(), {"record_id": "RID-17"})
    original[field] = value
    if field != "snapshot_sha256":
        original["snapshot_sha256"] = digest({key: item for key, item in original.items()
                                               if key != "snapshot_sha256"})
    with pytest.raises(ValueError, match="condition_snapshot_"):
        validate_condition_snapshot(original)


def test_concrete_snapshot_rejects_resigned_condition_template_substitution():
    original = resolve_condition_binding(binding(), {"record_id": "RID-17"})
    changed_template = original["binding"]["template"]
    changed_template["text_template"] = "An entirely different record equals {record_id}."
    changed_template["revision"] = 2
    resign(changed_template)
    original["binding_sha256"] = digest(original["binding"])
    original["snapshot_sha256"] = digest({key: item for key, item in original.items()
                                           if key != "snapshot_sha256"})
    with pytest.raises(ValueError, match="condition_snapshot_"):
        validate_condition_snapshot(original)


def test_concrete_snapshot_does_not_accept_literal_value_as_new_input():
    original = resolve_condition_binding(binding(parameter={"source": "literal", "value": "RID-17"}), {})
    original["typed_parameters"]["record_id"] = "RID-18"
    original["condition"] = 'The detail page record ID equals "RID-18".'
    original["snapshot_sha256"] = digest({key: item for key, item in original.items()
                                           if key != "snapshot_sha256"})
    with pytest.raises(ValueError, match="condition_snapshot_"):
        validate_condition_snapshot(original)
