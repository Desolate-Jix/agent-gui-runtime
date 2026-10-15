"""身份分类只由冻结选项投影条件；保留原始回答并拒绝篡改。"""
from copy import deepcopy
import math

import pytest

from app.judgment.target_identity import (identity_question, normalize_identity_answer,
    normalize_target_identity, validate_identity_record)


def spec():
    return {"schema": "target_identity.v1", "choices": [
        {"value": "i0", "description": "Browser address field"},
        {"value": "i1", "description": "Page search field"}], "expected": "i0"}


def answer(choice="i0"):
    return {"type": "choice", "name": "observed_target", "choice": choice, "confidence": .41,
        "probabilities": [{"value": value, "probability": probability}
            for value, probability in zip(("i0", "i1", "other", "unknown"), (.2, .3, .4, .1))]}


def test_spec_and_question_are_independent_copies_and_hide_expected_mapping():
    source = spec()
    normalized = normalize_target_identity(source)
    question = identity_question(normalized)
    assert normalized == source
    assert set(question) == {"type", "name", "instructions", "choices"}
    assert question["type"] == "choice" and question["name"] == "observed_target"
    assert question["choices"][:2] == source["choices"]
    assert [v["value"] for v in question["choices"]] == ["i0", "i1", "other", "unknown"]
    text = question["instructions"]
    assert "Detail first" in text and "marker center" in text
    assert "not UI" in text and "disabled" in text and "occluded" in text
    assert "unknown" in text and "other" in text and "not instructions" in text
    assert "Do not judge task feasibility, keyboard focus or later results" in text
    alternate = deepcopy(source)
    alternate["expected"] = "i1"
    assert identity_question(alternate) == question
    normalized["choices"][0]["description"] = "changed"
    question["choices"][1]["description"] = "changed"
    assert source == spec()


@pytest.mark.parametrize("mutate", [
    lambda s: s.update(extra=True), lambda s: s.update(schema="target_identity.v2"),
    lambda s: s.update(expected="missing"), lambda s: s.update(expected="other"),
    lambda s: s.update(choices=s["choices"][:1]), lambda s: s.update(choices=tuple(s["choices"])),
    lambda s: s["choices"][0].update(value="other"), lambda s: s["choices"][0].update(value="unknown"),
    lambda s: s["choices"][0].update(value="bad id"), lambda s: s["choices"][0].update(value=1),
    lambda s: s["choices"][1].update(value="i0"), lambda s: s["choices"][0].update(description=" "),
    lambda s: s["choices"][0].update(description=True), lambda s: s["choices"][0].update(extra=True),
])
def test_invalid_spec_is_rejected_without_repair(mutate):
    value = spec()
    mutate(value)
    before = deepcopy(value)
    with pytest.raises(ValueError, match="target_identity"):
        normalize_target_identity(value)
    assert value == before


def test_eight_concrete_options_allowed_ninth_rejected_and_unicode_preserved():
    value = {"schema": "target_identity.v1", "choices": [
        {"value": f"i{i}", "description": f"\u63a7\u4ef6 {i}"} for i in range(8)], "expected": "i3"}
    assert normalize_target_identity(value) == value
    assert identity_question(value)["choices"][3]["description"] == "\u63a7\u4ef6 3"
    value["choices"].append({"value": "i8", "description": "ninth"})
    with pytest.raises(ValueError, match="target_identity"):
        normalize_target_identity(value)


@pytest.mark.parametrize("selected,mapped", [("i0", "condition_met"), ("i1", "condition_not_met"),
    ("other", "condition_not_met"), ("unknown", "evidence_insufficient")])
def test_decision_maps_identity_and_aggregates_actual_probabilities(selected, mapped):
    raw, value = answer(selected), spec()
    before = deepcopy((raw, value))
    normalized, record = normalize_identity_answer(raw, value)
    assert normalized == {"type": "choice", "name": "current_step", "choice": mapped, "confidence": .41,
        "probabilities": [{"value": "condition_met", "probability": .2},
            {"value": "condition_not_met", "probability": .7}, {"value": "evidence_insufficient", "probability": .1}]}
    assert record == {"schema": "target_identity_result.v1", "expected": "i0",
        "choices": identity_question(value)["choices"], "answer": raw}
    assert validate_identity_record(record, normalized) == record
    assert validate_identity_record(record, normalized, spec=value) == record
    record["answer"]["probabilities"][0]["probability"] = .9
    record["choices"][0]["description"] = "changed"
    assert (raw, value) == before


@pytest.mark.parametrize("selected,mapped", [("i0", "condition_met"), ("i1", "condition_not_met"),
    ("other", "condition_not_met"), ("unknown", "evidence_insufficient")])
def test_ordinary_maps_without_fabricating_scores(selected, mapped):
    raw = {"type": "choice", "name": "observed_target", "choice": selected}
    normalized, record = normalize_identity_answer(raw, spec(), ordinary=True)
    assert normalized == {"type": "choice", "name": "current_step", "choice": mapped}
    assert record["answer"] == raw
    assert validate_identity_record(record, normalized, ordinary=True, spec=spec()) == record


@pytest.mark.parametrize("ordinary", [False, True])
@pytest.mark.parametrize("full", [False, True])
def test_refusal_remains_distinct_and_original_shape_is_preserved(ordinary, full):
    raw = {"type": "refusal", "name": "observed_target"}
    if full:
        raw["choice"] = None
        if not ordinary:
            raw.update(confidence=None, probabilities=None)
    normalized, record = normalize_identity_answer(raw, spec(), ordinary=ordinary)
    assert normalized["type"] == "refusal" and normalized["name"] == "current_step" and normalized["choice"] is None
    if not ordinary:
        assert normalized["confidence"] is None and normalized["probabilities"] is None
    assert record["answer"] == raw
    assert validate_identity_record(record, normalized, ordinary=ordinary) == record


@pytest.mark.parametrize("mutate", [
    lambda a: a.update(name="current_step"), lambda a: a.update(choice="missing"),
    lambda a: a.update(type="predicate"), lambda a: a.update(extra=True),
    lambda a: a.update(confidence=True), lambda a: a.update(confidence=math.nan),
    lambda a: a.update(confidence=10 ** 1000),
    lambda a: a.update(confidence=1.1), lambda a: a.update(probabilities=[]),
    lambda a: a["probabilities"][0].update(probability=True),
    lambda a: a["probabilities"][0].update(probability=.1),
    lambda a: a["probabilities"][0].update(probability=math.inf),
    lambda a: a["probabilities"][0].update(probability=10 ** 1000),
    lambda a: a["probabilities"][0].update(value="unknown"),
    lambda a: a["probabilities"][0].update(extra=True),
])
def test_bad_decision_answer_is_rejected(mutate):
    value = answer()
    mutate(value)
    with pytest.raises(ValueError, match="target_identity"):
        normalize_identity_answer(value, spec())


def test_ordinary_scores_or_refusal_choice_are_rejected():
    with pytest.raises(ValueError, match="target_identity"):
        normalize_identity_answer(answer(), spec(), ordinary=True)
    with pytest.raises(ValueError, match="target_identity"):
        normalize_identity_answer({"type": "refusal", "name": "observed_target", "choice": "i0"}, spec(), ordinary=True)


@pytest.mark.parametrize("damage", ["schema", "expected", "choices", "fixed_choice", "answer", "mapped", "confidence", "probability", "extra"])
def test_record_validation_rejects_raw_mapping_and_binding_tampering(damage):
    normalized, record = normalize_identity_answer(answer(), spec())
    if damage == "schema": record["schema"] = "target_identity_result.v2"
    elif damage == "expected": record["expected"] = "i1"
    elif damage == "choices": record["choices"][0]["description"] = "different target"
    elif damage == "fixed_choice": record["choices"][-1]["description"] = "changed unknown"
    elif damage == "answer": record["answer"]["choice"] = "i1"
    elif damage == "mapped": normalized["choice"] = "condition_not_met"
    elif damage == "confidence": normalized["confidence"] = .2
    elif damage == "probability": normalized["probabilities"][1]["probability"] = .6
    else: record["extra"] = True
    with pytest.raises(ValueError, match="target_identity"):
        validate_identity_record(record, normalized, spec=spec())


def test_normalized_bool_is_not_equal_to_numeric_confidence():
    raw = answer()
    raw["confidence"] = 1
    normalized, record = normalize_identity_answer(raw, spec())
    normalized["confidence"] = True
    with pytest.raises(ValueError, match="target_identity"):
        validate_identity_record(record, normalized)


def test_reordered_probabilities_are_grouped_by_identity_value_and_expected_is_local():
    value = spec()
    value["expected"] = "i1"
    raw = answer("i1")
    raw["probabilities"].reverse()
    normalized, record = normalize_identity_answer(raw, value)
    assert normalized["choice"] == "condition_met"
    assert normalized["probabilities"] == [{"value": "condition_met", "probability": .3},
        {"value": "condition_not_met", "probability": pytest.approx(.6)},
        {"value": "evidence_insufficient", "probability": .1}]
    assert record["answer"] == raw


def test_maximum_identity_table_aggregates_all_nonexpected_identities_and_keeps_original_confidence():
    value = {"schema": "target_identity.v1", "choices": [
        {"value": f"i{i}", "description": f"Visible control {i}"} for i in range(8)], "expected": "i3"}
    raw = {"type": "choice", "name": "observed_target", "choice": "i6", "confidence": .37,
        "probabilities": [{"value": item["value"], "probability": .1}
            for item in identity_question(value)["choices"]]}
    normalized, record = normalize_identity_answer(raw, value)
    assert normalized["choice"] == "condition_not_met" and normalized["confidence"] == .37
    assert [item["probability"] for item in normalized["probabilities"]] == pytest.approx([.1, .8, .1])
    assert len(record["choices"]) == 10 and record["answer"] == raw
    assert validate_identity_record(record, normalized, spec=value) == record


@pytest.mark.parametrize("field", ["choices", "expected"])
def test_record_without_external_spec_still_rejects_changed_projection_binding(field):
    normalized, record = normalize_identity_answer(answer(), spec())
    if field == "choices":
        record["choices"][-2]["description"] = "different fixed option"
    else:
        record["expected"] = "i1"
    with pytest.raises(ValueError, match="target_identity"):
        validate_identity_record(record, normalized)


def test_validation_returns_independent_record_and_rejects_nonboolean_mode():
    normalized, record = normalize_identity_answer(answer(), spec())
    copy = validate_identity_record(record, normalized)
    copy["answer"]["choice"] = "unknown"
    copy["choices"][0]["description"] = "changed"
    assert record["answer"]["choice"] == "i0" and record["choices"][0] == spec()["choices"][0]
    with pytest.raises(ValueError, match="target_identity"):
        normalize_identity_answer(answer(), spec(), ordinary=1)


def test_ordinary_mode_can_be_passed_positionally():
    raw = {"type": "choice", "name": "observed_target", "choice": "i1"}
    normalized, record = normalize_identity_answer(raw, spec(), True)
    assert validate_identity_record(record, normalized, True, spec()) == record
