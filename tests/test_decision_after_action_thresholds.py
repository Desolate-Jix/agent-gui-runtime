"""动作后结果与接管阈值独立于动作前、错误及加载门槛。"""
import math

import pytest

from app.judgment import DecisionProfile
from app.judgment.adaptive_policy import assessment


def profile(**patch):
    return DecisionProfile.model_validate({"contract_version": "decision_profile.v2", **patch})


def judge(config, *, phase="after_action", met=0.8, danger=0.01, review=0.01, progress=None):
    probabilities = {"condition_met": met, "needs_agent_review": review,
                     "unsafe_effect" if phase == "before_action" else "visible_error": danger}
    context = None
    if progress is not None:
        probabilities["still_progressing"] = progress
        context = {"wait_policy": {"completion_excludes_loading": True}}
    return assessment(config, phase, probabilities, context)


@pytest.mark.parametrize("version,expected", [
    ("decision_profile.v1", '{"contract_version":"decision_profile.v1","mode":"shadow","api_key_env":"OPENAI_API_KEY","timeout_seconds":8.0,"pass_threshold":0.9,"fail_threshold":0.1,"request_cap":20,"auto_conditions":[]}'),
    ("decision_profile.v2", '{"contract_version":"decision_profile.v2","mode":"auto","api_key_env":"OPENAI_API_KEY","timeout_seconds":8.0,"pass_threshold":0.9,"fail_threshold":0.1,"request_cap":20,"auto_conditions":[],"proactive_review":true,"review_policy":"adaptive"}'),
])
def test_omitted_thresholds_preserve_exact_historical_serialization(version, expected):
    config = DecisionProfile.model_validate({"contract_version": version})
    assert config.after_action_pass_threshold is None
    assert config.after_action_review_threshold is None
    assert config.model_dump_json() == expected
    assert "after_action_pass_threshold" not in config.model_dump()
    assert "after_action_review_threshold" not in config.model_dump()


def test_explicit_null_v2_thresholds_preserve_historical_snapshot():
    config = profile(after_action_pass_threshold=None, after_action_review_threshold=None)
    assert config.model_dump_json() == profile().model_dump_json()
    assert judge(config, met=0.8) == judge(profile(), met=0.8)


@pytest.mark.parametrize("field", ["after_action_pass_threshold", "after_action_review_threshold"])
@pytest.mark.parametrize("value", [None, 0.8])
def test_v1_rejects_after_action_fields_even_when_null(field, value):
    with pytest.raises(ValueError, match="decision_v2_policy_requires_v2_profile"):
        DecisionProfile.model_validate({"contract_version": "decision_profile.v1", field: value})


@pytest.mark.parametrize("field", ["after_action_pass_threshold", "after_action_review_threshold"])
@pytest.mark.parametrize("value", [True, False, "0.8", math.nan, math.inf, -math.inf, -0.01, 1.01, 10 ** 400])
def test_after_action_thresholds_reject_invalid_types_or_nonfinite_out_of_range(field, value):
    with pytest.raises(ValueError):
        profile(**{field: value})


@pytest.mark.parametrize("patch", [
    {"after_action_pass_threshold": 0.1},
    {"after_action_pass_threshold": 0.0},
    {"fail_threshold": 0.4, "after_action_pass_threshold": 0.4},
    {"fail_threshold": 0.4, "after_action_pass_threshold": 0.3},
    {"after_action_review_threshold": 0.0},
])
def test_threshold_relationships_do_not_admit_overlap_or_unconditional_review(patch):
    with pytest.raises(ValueError):
        profile(**patch)


def test_v2_serializes_explicit_fields_and_allows_independent_configuration():
    config = profile(after_action_pass_threshold=0.8, after_action_review_threshold=0.7)
    serialized = config.model_dump()
    assert serialized["after_action_pass_threshold"] == 0.8
    assert serialized["after_action_review_threshold"] == 0.7
    assert DecisionProfile.model_validate(serialized) == config
    assert judge(profile(after_action_pass_threshold=0.8), review=0.2)["disposition"] == "review_required"
    assert judge(profile(after_action_review_threshold=0.7), met=0.8)["verdict"] == "uncertain"
    assert profile(after_action_pass_threshold=1.0, after_action_review_threshold=1.0)


@pytest.mark.parametrize("met,verdict", [(0.799999, "uncertain"), (0.8, "success"), (0.800001, "success")])
def test_after_action_pass_boundary_is_inclusive(met, verdict):
    result = judge(profile(after_action_pass_threshold=0.8, after_action_review_threshold=0.7), met=met)
    assert result["verdict"] == verdict
    assert result["adopted"] is (verdict == "success")
    assert ("condition_gray" in result["reason_codes"]) is (verdict == "uncertain")


@pytest.mark.parametrize("review,expected", [(0.699999, "continue"), (0.7, "review_required"), (0.700001, "review_required")])
def test_explicit_after_action_review_boundary_is_inclusive_and_high(review, expected):
    result = judge(profile(after_action_pass_threshold=0.8, after_action_review_threshold=0.7), review=review)
    assert result["verdict"] == "success" and result["disposition"] == expected
    assert result["review_scope"] == ("remaining_plan" if expected == "review_required" else "effect")
    assert ("off_plan_intervention_high" in result["reason_codes"]) is (expected == "review_required")
    assert "off_plan_intervention_gray" not in result["reason_codes"]
    assert result["adopted"] is (expected == "continue")


@pytest.mark.parametrize("review,code", [(0.1, None), (0.100001, "off_plan_intervention_gray"), (0.9, "off_plan_intervention_high")])
def test_omitted_review_threshold_retains_strict_low_boundary_and_old_classification(review, code):
    result = judge(profile(), met=0.9, review=review)
    assert result["disposition"] == ("review_required" if code else "continue")
    assert not code or code in result["reason_codes"]


@pytest.mark.parametrize("met,danger,review", [
    (0.8, 0.01, 0.01), (0.9, 0.01, 0.7), (0.9, 0.1, 0.1),
    (0.9, 0.100001, 0.01), (0.01, 0.8, 0.01), (0.01, 0.9, 0.01), (0.9, 0.9, 0.9),
])
def test_before_action_ignores_both_after_action_fields(met, danger, review):
    changed = profile(after_action_pass_threshold=0.8, after_action_review_threshold=0.7)
    args = {"phase": "before_action", "met": met, "danger": danger, "review": review}
    assert judge(changed, **args) == judge(profile(), **args)


@pytest.mark.parametrize("met,danger,verdict,reason", [
    (0.8, 0.1, "success", None),
    (0.8, 0.100001, "uncertain", "visible_error_gray"),
    (0.1, 0.8, "failure", "visible_error_gray"),
    (0.1, 0.9, "failure", "visible_error_high"),
    (0.8, 0.9, "uncertain", "decision_predicate_conflict"),
    (0.1, 0.01, "failure", "condition_not_met"),
])
def test_visible_error_and_failure_boundaries_remain_original(met, danger, verdict, reason):
    result = judge(profile(after_action_pass_threshold=0.8, after_action_review_threshold=0.7),
                   met=met, danger=danger)
    assert result["verdict"] == verdict
    assert not reason or reason in result["reason_codes"]
    assert result["adopted"] is (verdict == "success")


@pytest.mark.parametrize("met,progress,verdict,disposition,reason", [
    (0.8, 0.899999, "success", "continue", None),
    (0.8, 0.9, "uncertain", "review_required", "decision_completion_loading_conflict"),
    (0.799999, 0.9, "uncertain", "review_required", "condition_gray"),
    (0.1, 0.8, "failure", "review_required", "condition_not_met"),
    (0.1, 0.9, "uncertain", "observe", "declared_loading_high"),
])
def test_loading_conflict_uses_new_result_threshold_but_original_progress_threshold(met, progress, verdict, disposition, reason):
    result = judge(profile(after_action_pass_threshold=0.8, after_action_review_threshold=0.7),
                   met=met, progress=progress)
    assert (result["verdict"], result["disposition"]) == (verdict, disposition)
    assert not reason or reason in result["reason_codes"]


def test_disabled_review_and_shadow_semantics_are_preserved():
    config = profile(after_action_pass_threshold=0.8, after_action_review_threshold=0.7, proactive_review=False)
    assert judge(config, review=1.0)["adopted"]
    result = judge(config.model_copy(update={"mode": "shadow"}))
    assert result["verdict"] == "success" and result["suggested_disposition"] == "continue"
    assert result["disposition"] == "review_required" and not result["adopted"]
