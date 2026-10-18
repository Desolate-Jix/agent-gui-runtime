"""同字段实际值严格比较；不把包含文本、旧采集或改变选区当作成功。"""
from dataclasses import replace
import json

import pytest

from app.agent.text_parameters import ReviewedTextParameters, ReviewedTextSource, resolve_text_parameters
from app.agent.text_field_evidence import (
    TextFieldIdentity, TextFieldSnapshot, prepare_text_field_expectation,
    validate_text_field_precondition, verify_text_field_result,
)


def snapshot(value="A", selection=(1, 1), *, capture="capture-1", read="read-1", clock=100):
    identity = TextFieldIdentity("field", 4242, 9001, 1000.5, (42, 1), (10, 20, 320, 200), (20, 30, 180, 40))
    return TextFieldSnapshot(identity, capture, read, clock, "uia_value", value, selection)


def resolved(text="B", *, clear=True, kind="literal"):
    params = ReviewedTextParameters("field", ReviewedTextSource(kind, text if kind == "literal" else "query"), clear, True)
    return resolve_text_parameters(params, {"query": text})


@pytest.mark.parametrize("kind", ["literal", "variable"])
def test_replacement_requires_exact_value_from_fresh_same_field(kind):
    before = snapshot()
    expected = prepare_text_field_expectation(before, resolved(kind=kind))
    assert expected.expected_value == "B"
    wrong = replace(before, capture_id="capture-2", read_id="read-2", observed_at_ns=101, value="AB")
    assert verify_text_field_result(expected, wrong)["reason_code"] == "text_value_mismatch"
    after = replace(wrong, value="B")
    result = verify_text_field_result(expected, after)
    assert result["status"] == "verified"
    assert verify_text_field_result(expected, replace(after, identity=replace(after.identity, runtime_id=(42, 2))))["status"] == "not_verified"
    assert verify_text_field_result(expected, replace(after, capture_id="capture-1"))["reason_code"] == "text_field_read_not_new"
    assert verify_text_field_result(expected, None)["reason_code"] == "text_field_unavailable"


def test_insert_replaces_selected_span_and_rechecks_full_selection():
    before = snapshot("甲🙂乙丙", (1, 3))
    expected = prepare_text_field_expectation(before, resolved("新\r\n值", clear=False))
    assert expected.expected_value == "甲新\r\n值丙"
    fresh = replace(before, read_id="fresh", observed_at_ns=101)
    validate_text_field_precondition(expected, fresh)
    with pytest.raises(ValueError, match="precondition"):
        validate_text_field_precondition(expected, replace(fresh, selection=(2, 2)))
    with pytest.raises(ValueError, match="selection"):
        prepare_text_field_expectation(replace(before, selection=None), resolved("B", clear=False))


def test_snapshot_reference_does_not_serialize_original_value_and_binds_empty():
    before = snapshot("秘密原值\r\n下一行")
    ref = before.to_reference()
    assert "秘密原值" not in json.dumps(ref, ensure_ascii=False)
    assert "秘密原值" not in repr(before)
    expected = prepare_text_field_expectation(before, resolved(""))
    assert expected.expected_value == ""
    assert expected.to_reference()["expected_value_length"] == 0
    with pytest.raises(ValueError):
        replace(before, selection=(0, len(before.value) + 1))
    with pytest.raises(ValueError):
        replace(before, identity=replace(before.identity, process_create_time=float("nan")))
