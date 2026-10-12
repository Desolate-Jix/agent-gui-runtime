"""动作后阈值进入真实服务认证，旧票据不能按新策略重新采用。"""
from copy import deepcopy
import json

import pytest

from app.core.decision_configuration import freeze_decision_profile
from app.judgment import DecisionProfile
from test_adaptive_decision_policy import context, service
from test_decision_service import arguments


TUNED = {"after_action_pass_threshold": 0.8, "after_action_review_threshold": 0.7}


@pytest.mark.parametrize("met,review,adopted", [(0.8, 0.699, True), (0.8, 0.7, False),
    (0.799, 0.01, False), (0.99, 0.45, True), (0.75, 0.01, False)])
def test_new_thresholds_are_authenticated_and_repeated_reads_do_not_redispatch(
        tmp_path, monkeypatch, met, review, adopted):
    runtime, requests, client = service(tmp_path, monkeypatch, met=met, review=review, profile=TUNED)
    try:
        args = arguments(tmp_path, review_context=context())
        result = runtime.evaluate(**args)
        assert result["adopted"] is adopted
        assert result["authorizes_action"] is False
        assert runtime.validate_result(result, **args)
        assert runtime.evaluate(**args) == result and len(requests) == 1
        changed = deepcopy(result)
        changed["adopted"] = not adopted
        assert not runtime.validate_result(changed, **args)
    finally:
        runtime.close()
        client.close()


def test_policy_change_cannot_reinterpret_saved_result_or_refreeze_session(tmp_path, monkeypatch):
    old, old_requests, old_client = service(tmp_path, monkeypatch, met=0.82, review=0.45)
    new, new_requests, new_client = service(tmp_path, monkeypatch, met=0.82, review=0.45, profile=TUNED)
    try:
        args = arguments(tmp_path, review_context=context())
        freeze_decision_profile(old)
        original = old.evaluate(**args)
        assert not original["adopted"] and old.validate_result(original, **args)
        assert not new.validate_result(original, **args)
        conflict = new.evaluate(**args)
        assert conflict["status"] == "conflict" and not conflict["adopted"]
        assert len(old_requests) == 1 and new_requests == []
        with pytest.raises(ValueError, match="decision_session_profile_mismatch"):
            freeze_decision_profile(new)
        snapshot = json.loads((tmp_path / "decision-profile.snapshot.json").read_text(encoding="utf-8"))
        assert DecisionProfile.model_validate(snapshot) == old.profile
        assert old.evaluate(**args) == original
    finally:
        old.close()
        new.close()
        old_client.close()
        new_client.close()
