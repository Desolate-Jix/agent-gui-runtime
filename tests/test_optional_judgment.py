"""可选判断位置：关闭零调用，启用后严格绑定证据且不授权输入。"""
from copy import deepcopy

import pytest


def request(mode="execution"):
    value = {"request_id": "judge-1", "mode": mode, "execution_request_id": "execute-1",
        "condition": "当前详情是否已打开", "evidence": [{"capture_id": "capture-1",
        "sha256": "a" * 64, "image_ref": "captures/current.png", "text": "当前详情",
        "window_id": "window-1", "role": "after"}]}
    if mode == "learning":
        value.update(run_id="run-1", step_id="step-1")
    return value


class Provider:
    provider_id = "test-provider"
    model_id = "test-model"
    supports_images = True

    def __init__(self, answer=True, error=None):
        self.calls = []
        self.answer, self.error = answer, error

    def judge(self, payload):
        self.calls.append(deepcopy(payload))
        if self.error:
            raise self.error
        return {"request_sha256": payload["request_sha256"], "answer": self.answer,
                "probability": None, "usage": None}


def test_disabled_and_unconnected_do_not_capture_or_call_provider():
    from app.core.outcome_judgment import OptionalJudgment
    provider = Provider()
    def capture():
        raise AssertionError("关闭的接口不得读取证据或新增截图")
    assert OptionalJudgment(provider=provider).evaluate(capture)["status"] == "disabled"
    assert OptionalJudgment(enabled=True).evaluate(capture)["status"] == "not_connected"
    assert provider.calls == []


@pytest.mark.parametrize("mode", ["execution", "learning"])
@pytest.mark.parametrize("answer,verdict", [(True, "success"), (False, "failure"), (None, "uncertain")])
def test_both_modes_use_the_same_bound_boolean_contract(mode, answer, verdict):
    from app.core.outcome_judgment import OptionalJudgment
    provider = Provider(answer)
    original = request(mode)
    result = OptionalJudgment(enabled=True, provider=provider).evaluate(lambda: original)
    assert result["status"] == "completed" and result["verdict"] == verdict
    assert result["probability"] is None and result["usage"] is None
    assert result["request_sha256"] == provider.calls[0]["request_sha256"]
    assert result["authorizes_action"] is False and result["automatic_retry_allowed"] is False
    assert result["provider"] == "test-provider" and result["model"] == "test-model"
    assert result["elapsed_ms"] >= 0 and "request_sha256" not in original


@pytest.mark.parametrize("error,status", [(TimeoutError("late"), "timeout"), (OSError("offline"), "error")])
def test_provider_failure_is_uncertain_and_never_retried(error, status):
    from app.core.outcome_judgment import OptionalJudgment
    provider = Provider(error=error)
    result = OptionalJudgment(enabled=True, provider=provider).evaluate(request)
    assert result["status"] == status and result["verdict"] == "uncertain"
    assert len(provider.calls) == 1


@pytest.mark.parametrize("patch", [{"answer": "yes"}, {"answer": 1}, {"request_sha256": "b" * 64},
    {"probability": 1.1}, {"click_point": [1, 2]}])
def test_malformed_or_stale_reply_cannot_become_success(patch):
    from app.core.outcome_judgment import OptionalJudgment
    class InvalidProvider(Provider):
        def judge(self, payload):
            return {**super().judge(payload), **patch}
    result = OptionalJudgment(enabled=True, provider=InvalidProvider()).evaluate(request)
    assert result["status"] == "error" and result["verdict"] == "uncertain"


def test_text_only_provider_cannot_silently_drop_images():
    from app.core.outcome_judgment import OptionalJudgment
    provider = Provider()
    provider.supports_images = False
    result = OptionalJudgment(enabled=True, provider=provider).evaluate(request)
    assert result["status"] == "unsupported" and provider.calls == []


def test_bound_before_after_and_supplied_usage_are_preserved():
    from app.core.outcome_judgment import OptionalJudgment
    class UsageProvider(Provider):
        def judge(self, payload):
            return {**super().judge(payload), "usage": {"input_tokens": 5, "output_tokens": 2}, "probability": 0.8}
    value = request("learning")
    value["evidence"].insert(0, {**value["evidence"][0], "role": "before", "capture_id": "before-1",
                              "sha256": "b" * 64, "image_ref": "captures/before.png"})
    provider = UsageProvider()
    result = OptionalJudgment(enabled=True, provider=provider).evaluate(lambda: value)
    assert result["usage"] == {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7}
    assert result["probability"] == 0.8 and len(provider.calls[0]["evidence"]) == 2
    value["evidence"][0]["window_id"] = "other-window"
    with pytest.raises(ValueError, match="window_binding_mismatch"):
        OptionalJudgment(enabled=True, provider=provider).evaluate(lambda: value)
    assert len(provider.calls) == 1


@pytest.mark.parametrize("change", [{"run_id": None}, {"step_id": ""}, {"condition": "  "}, {"evidence": []}])
def test_invalid_learning_request_is_rejected_before_provider(change):
    from app.core.outcome_judgment import OptionalJudgment
    provider = Provider()
    with pytest.raises(ValueError):
        OptionalJudgment(enabled=True, provider=provider).evaluate(lambda: {**request("learning"), **change})
    assert provider.calls == []
