"""动作前通过阈值独立于危险、接管、动作后及旧票据。"""
from copy import deepcopy
import math

import pytest

from app.core.decision_configuration import freeze_decision_profile
from app.judgment import DecisionProfile
from test_adaptive_decision_policy import context, service
from test_decision_after_action_thresholds import judge, profile
from test_decision_service import arguments, frame


@pytest.mark.parametrize("met,adopted", [(0.799999, False), (0.8, True), (0.86, True)])
def test_before_pass_boundary_and_after_action_isolation(met, adopted):
    original = profile()
    changed = profile(before_action_pass_threshold=0.8)
    assert judge(changed, phase="before_action", met=met)["adopted"] is adopted
    assert judge(changed, met=met) == judge(original, met=met)


@pytest.mark.parametrize("met,danger,review,code", [
    (0.86, 0.100001, 0.0, "unsafe_effect_gray"),
    (0.86, 0.9, 0.0, "decision_predicate_conflict"),
    (0.86, 0.0, 0.100001, "off_plan_intervention_gray"),
    (0.0, 0.0, 0.99, "condition_not_met"),
])
def test_relaxed_feasibility_keeps_other_rejections(met, danger, review, code):
    result = judge(profile(before_action_pass_threshold=0.8), phase="before_action",
                   met=met, danger=danger, review=review)
    assert not result["adopted"] and code in result["reason_codes"]


@pytest.mark.parametrize("value", [True, "0.8", math.nan, math.inf, -0.01, 1.01, 0.1])
def test_before_threshold_rejects_invalid_or_overlapping_values(value):
    with pytest.raises(ValueError):
        profile(before_action_pass_threshold=value)


def test_omitted_or_null_preserves_legacy_hash_and_v1_rejects_field():
    original = profile()
    assert "before_action_pass_threshold" not in original.model_dump()
    assert profile(before_action_pass_threshold=None).model_dump_json() == original.model_dump_json()
    with pytest.raises(ValueError, match="decision_v2_policy_requires_v2_profile"):
        DecisionProfile.model_validate({"contract_version": "decision_profile.v1",
                                        "before_action_pass_threshold": 0.8})


def test_live_score_offline_replay_authenticates_without_reinterpreting_old_receipt(tmp_path, monkeypatch):
    old, old_requests, old_client = service(tmp_path, monkeypatch, met=0.86, danger=0, review=0)
    changed = {"before_action_pass_threshold": 0.8}
    new, new_requests, new_client = service(tmp_path, monkeypatch, met=0.86, danger=0, review=0, profile=changed)
    try:
        args = arguments(tmp_path, phase="before_action", frames=[frame(tmp_path, role="before")],
                         action={"operation": "click", "goal": "Address bar"}, review_context=context())
        freeze_decision_profile(old)
        original = old.evaluate(**args)
        assert original["verdict"] == "uncertain" and not original["adopted"]
        assert old.validate_result(original, **args)
        assert not new.validate_result(original, **args)
        assert new.evaluate(**args)["status"] == "conflict" and new_requests == []
        with pytest.raises(ValueError, match="decision_session_profile_mismatch"):
            freeze_decision_profile(new)
        fresh = {**args, "request_id": "new-policy-request"}
        result = new.evaluate(**fresh)
        assert result["adopted"] and result["authorizes_action"] is False
        assert new.validate_result(result, **fresh)
        assert new.evaluate(**fresh) == result and len(new_requests) == 1
        tampered = deepcopy(result)
        tampered["adopted"] = False
        assert not new.validate_result(tampered, **fresh)
        assert len(old_requests) == 1
    finally:
        old.close()
        new.close()
        old_client.close()
        new_client.close()
