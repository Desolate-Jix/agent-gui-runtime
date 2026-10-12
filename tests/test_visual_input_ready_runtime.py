"""默认替换连续派发，仅核对文字；旧点击证明保持冻结语义。"""
from copy import deepcopy

import pytest

from tests.test_visual_field_proof import scene, assess, FIELD, executed_focus
from tests.test_visual_input_no_uia import visual_sequence


CLICKED = "The recorded click is inside the intended visible text input."


def test_historical_visual_click_proof_binds_postclick_frame_and_executed_point(scene):
    s = scene
    s.context["native_field_evidence"] = False
    executed_focus(s.focus)
    original = deepcopy(s.focus)
    proof = assess(s)
    request = proof.request()
    assert request["condition"] == CLICKED
    assert len(request["frames"]) == 1 and request["frames"][0]["role"] == "after"
    assert request["frames"][0]["capture_id"] == s.focus["observation"]["capture"]["capture_id"]
    assert request["action"]["executed_click"]["click_point"] == FIELD["click_point"]
    assert request["action"]["executed_click"]["receipt_sha256"] == s.module._digest(original)
    assert s.focus == original and len(s.requests) == 1


@pytest.mark.parametrize("problem", ["missing", "point", "up"])
def test_historical_visual_click_proof_requires_completed_actual_click(scene, problem):
    s = scene
    s.context["native_field_evidence"] = False
    if problem != "missing":
        executed_focus(s.focus)
        click = s.focus["response"]["data"]["click_result"]
        if problem == "point": click["window_point"]["x"] += 1
        else: click["up"]["cursor"]["x"] += 1
    with pytest.raises(ValueError):
        assess(s)
    assert s.requests == []


def test_residual_focus_wait_is_not_used_and_replacement_has_no_selection_decision(visual_sequence, monkeypatch):
    v = visual_sequence
    v.scene.context["focus_observation_delay_ms"] = 500
    requests = []
    original_evaluate = v.scene.service.evaluate
    def evaluate(**kwargs):
        requests.append(deepcopy(kwargs))
        return original_evaluate(**kwargs)
    monkeypatch.setattr(v.scene.service, "evaluate", evaluate)
    monkeypatch.setattr(v.scene.module, "capture_visual_focus_observation",
        lambda *args, **kwargs: pytest.fail("旧补图参数不得重新启用焦点观察"))
    result = v.run()
    assert result["status"] == "completed", result.get("error")
    assert len(v.scene.requests) == 2
    from app.execution.action_review import CANDIDATE_CONDITION
    assert [p["condition"] for p in requests] == [v.scene.module.VISUAL_TEXT_VALUE_CONDITION, CANDIDATE_CONDITION]
    assert len(result["field_proofs"][0]["frames"]) == 1
    assert len(result["field_proofs"]) == 1
    assert result["field_proofs"][0]["frames"][0]["capture_id"] == v.scene.typed["observation"]["capture"]["capture_id"]
    assert [row["stage"] for row in result["field_evaluations"]] == ["after_type"]
    assert v.captures == []
    assert v.forbidden_calls == []


def test_explicit_native_condition_and_old_receipt_are_not_reinterpreted(scene):
    s = scene
    proof = assess(s)
    assert proof.request()["condition"] == s.module.VISUAL_FOCUS_CONDITION
    assert "executed_click" not in proof.request()["action"]
    assert len(proof.request()["frames"]) == 1
