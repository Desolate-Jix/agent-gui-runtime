"""当前原生只读失败与历史视觉焦点回执均保留原认证和取消边界。"""
from copy import deepcopy
from hashlib import sha256
from time import perf_counter_ns
from types import SimpleNamespace

import pytest

from app.agent.windows_text_field_reader import TextFieldReadError
from app.core.input_sequence_partial import original_input_status
from app.execution import input_sequence, visual_field_proof
from tests.test_input_sequence_focus_partial import REQUEST, TARGET, queued, persist_original
from tests.test_local_step_timings import timed_scene
from tests.test_recognition_dispatch_boundary import route


@pytest.fixture
def visual_sequence(route, timed_scene, monkeypatch):
    from app.execution import local_direct_step
    response = route.run("success")
    data = response["data"].get("result", response["data"])
    plan = data["recognition_plan"]
    plan["recommended_target"] = deepcopy(plan["candidate_result"]["candidates"][0])
    monkeypatch.setattr(local_direct_step, "_post_action", lambda *args: deepcopy(response))
    calls = []

    def run(stage="read", error=None):
        failure = error or TextFieldReadError("text_field_target_not_writable", diagnostic={
            "phase": "describe_target", "check": "value_readonly", "control_type": "Edit",
            "read_index": 1, "private_text": "must not escape"})

        def read(*args, **kwargs):
            calls.append("readonly_provider")
            if stage == "read":
                raise failure
            return None

        def assess(**kwargs):
            calls.append("assessment")
            raise failure

        monkeypatch.setattr(visual_field_proof, "_read_bounded_text", read)
        monkeypatch.setattr(visual_field_proof, "assess_visual_field", assess)
        result = input_sequence.run_input_sequence(timed_scene[0], {"handle": 321, "process_id": 12},
            REQUEST, field_evidence_mode="visual", visual_field_context={
                "field_kind": "search", "native_field_evidence": True,
                "deadline_ns": perf_counter_ns() + 30_000_000_000})
        assert result["action_executed"] is True and result["completed_steps"] == ["focus"]
        assert len(result["steps"]) == 1 and route.events.count("click_point") == 1
        return result

    return SimpleNamespace(run=run, calls=calls)


@pytest.fixture
def historical_visual_focus_partial(route, timed_scene, monkeypatch):
    from app.core.input_sequence_partial import make_focus_partial_proof
    from app.execution import local_direct_step

    # 历史纯视觉两步合同只用于原回执消费，不通过新默认入口重建旧路线。
    response = route.run("success")
    monkeypatch.setattr(local_direct_step, "_post_action", lambda *args: deepcopy(response))
    focus = timed_scene[0].execute_local_step(target_window_handle=321, target_process_id=12,
        operation="execute_recognition_plan", request={"goal": REQUEST["field_goal"], "click_kind": "single"},
        include_observation=True, observation_wait_ms=0)
    assert focus["phase"] == "returned" and focus["local_input_scope_closed"] is True
    assert route.events.count("click_point") == 1
    result = {"contract_version": "input_sequence_v1", "sequence_id": "historical-visual-focus-partial",
        "status": "interrupted", "phase": "check_focus", "interrupted_at": "check_focus",
        "action_executed": True, "completed_steps": ["focus"], "automatic_retry_allowed": False,
        "task_effect_verified": None, "target": {"handle": 321, "process_id": 12},
        "text_sha256": sha256(REQUEST["text"].encode("utf-8")).hexdigest(),
        "text_length": len(REQUEST["text"]), "submit_search": REQUEST["submit_search"],
        "input_check": {"status": "unavailable", "phase": "check_focus", "reason": "visual_field_requires_review",
            "evidence_kind": "visual", "focus_stage": "after_click", "read_only_stage": "after_click_assessment"},
        "error": {"type": "InputSequenceInterrupted", "code": "visual_field_requires_review"},
        "steps": [{"name": "focus", "operation": "execute_recognition_plan", "status": "returned",
            "action_executed": True, "receipt": focus}]}
    proof = make_focus_partial_proof(result, REQUEST, started_actions=["focus"],
        read_only_stage="after_click_assessment")
    assert proof is not None and proof["target_identity"] == TARGET
    result["partial_input_terminal"] = proof
    return result


def test_visual_read_failure_preserves_original_error_diagnostic_and_partial_proof(visual_sequence):
    result = visual_sequence.run()
    assert result["error"] == {"code": "text_field_target_not_writable", "type": "TextFieldReadError",
        "diagnostic": {"phase": "describe_target", "check": "value_readonly", "control_type": "Edit", "read_index": 1}}
    assert result["input_check"] == {"status": "unavailable", "phase": "check_focus",
        "reason": "text_field_target_not_writable"}
    assert result["partial_input_terminal"]["contract_version"] == "input_sequence_focus_partial.v1"
    assert result["partial_input_terminal"]["started_actions"] == ["focus"]
    command = {"kind": "input_sequence", "request": deepcopy(REQUEST)}
    assert original_input_status({"status": "returned", "command": command, "result": result}, command,
        succeeded=False, action_executed=True, target_identity=TARGET) == "failed"
    assert visual_sequence.calls == ["readonly_provider"]


def test_visual_readonly_partial_cancel_settles_original_without_replay(visual_sequence, tmp_path, monkeypatch):
    result = visual_sequence.run()
    s, pending, path, decision_calls = queued(tmp_path, monkeypatch, result)
    original = persist_original(s, pending, path, result)
    s.runtime.control({"action": "cancel", "run_id": s.run_id}, "cancel-visual-focus")
    final = s.runtime.tick(force=True)
    assert final["status"] == "cancelled" and final["pending"] is None
    assert final["history"][0]["original_input_status"] == "failed"
    assert final["history"][0]["action_executed"] is True
    assert path.read_bytes() == original and decision_calls == []
    assert len(list(s.session.glob("commands/trial-exec-*.json"))) == 1


@pytest.mark.parametrize("stage,typed", [("assessment", False), ("assessment", True), ("read", False)])
def test_visual_assessment_or_untyped_read_failure_does_not_mint_native_partial(visual_sequence, stage, typed):
    failure = (TextFieldReadError("text_field_target_not_writable", diagnostic={"phase": "read_text"})
        if typed else ValueError("visual_field_focus_requires_review"))
    result = visual_sequence.run(stage, failure)
    assert result["error"]["type"] == "InputSequenceInterrupted"
    assert "partial_input_terminal" not in result and "diagnostic" not in result["error"]
    command = {"kind": "input_sequence", "request": deepcopy(REQUEST)}
    assert original_input_status({"status": "returned", "command": command, "result": result}, command,
        succeeded=False, action_executed=True, target_identity=TARGET) == "unknown"


@pytest.mark.parametrize("async_terminal", [False, True])
def test_historical_visual_focus_readonly_failure_cancels_original_queue_without_replay(
        historical_visual_focus_partial, tmp_path, monkeypatch, async_terminal):
    result = historical_visual_focus_partial
    proof = result.get("partial_input_terminal")
    assert proof is not None and proof["contract_version"] == "input_sequence_focus_partial.v2"
    assert proof["started_actions"] == ["focus"] and proof["suffix_dispatch_started"] is False
    assert proof["read_only_stage"] == "after_click_assessment"
    s, pending, path, calls = queued(tmp_path, monkeypatch, result)
    original = persist_original(s, pending, path, result, async_terminal=async_terminal)
    waiting = s.runtime.control({"action": "cancel", "run_id": s.run_id}, "cancel-pure-visual")
    assert waiting["status"] == "cancel_requested"
    final = s.runtime.tick(force=True)
    assert final["status"] == "cancelled" and final["pending"] is None
    assert final["history"][0]["original_input_status"] == "failed"
    assert final["history"][0]["action_executed"] is True
    assert path.read_bytes() == original and calls == []
    assert len(list(s.session.glob("commands/trial-exec-*.json"))) == 1
    s.runtime.admit("owned-close", {"kind": "close_launched_window", "request": {}})


@pytest.mark.parametrize("damage", ["missing", "wrong_stage", "extra_input", "unknown_dispatch", "proof_stage", "readonly_flag", "success_claim"])
def test_historical_visual_partial_forgery_cannot_settle_unknown_or_started_keyboard(
        historical_visual_focus_partial, damage):
    from app.core.input_sequence_partial import focus_only_partial_verified
    result = historical_visual_focus_partial
    assert "partial_input_terminal" in result
    if damage == "missing":
        result.pop("partial_input_terminal")
    elif damage == "wrong_stage":
        result["input_check"]["read_only_stage"] = "after_selection"
    elif damage == "extra_input":
        result["steps"].append({"name": "type", "operation": "type_text", "status": "dispatching", "action_executed": None})
    elif damage == "unknown_dispatch":
        result["steps"][0]["status"] = "result_unknown"
    elif damage == "proof_stage":
        result["partial_input_terminal"]["read_only_stage"] = "after_selection"
    elif damage == "readonly_flag":
        result["partial_input_terminal"]["read_only_failure"] = 1
    else:
        result["status"] = "completed"
    command = {"kind": "input_sequence", "request": deepcopy(REQUEST)}
    receipt = {"status": "returned", "command": command, "result": result}
    assert not focus_only_partial_verified(receipt, command, target_identity=TARGET)
    assert original_input_status(receipt, command, succeeded=damage == "success_claim",
        action_executed=True, target_identity=TARGET) == "unknown"


def test_historical_visual_partial_requires_internal_readonly_stage_and_exact_dispatch_frontier(historical_visual_focus_partial):
    from app.core.input_sequence_partial import make_focus_partial_proof
    result = historical_visual_focus_partial
    assert result["partial_input_terminal"]["read_only_stage"] == "after_click_assessment"
    assert make_focus_partial_proof(result, REQUEST, started_actions=["focus"]) is None
    for started in (["focus", "type"], ["focus", "selection"], [], ["unknown"]):
        assert make_focus_partial_proof(result, REQUEST, started_actions=started,
            read_only_stage="after_click_assessment") is None


def test_historical_keyboard_target_failure_does_not_impersonate_visual_readonly_failure(historical_visual_focus_partial):
    from app.core.input_sequence_partial import make_focus_partial_proof
    result = historical_visual_focus_partial
    result.pop("partial_input_terminal")
    result["error"]["code"] = "visual_keyboard_target_failed"
    result["input_check"] = {"status": "unavailable", "phase": "check_focus", "reason": "visual_keyboard_target_failed"}
    assert result["error"]["type"] == "InputSequenceInterrupted"
    assert "partial_input_terminal" not in result
    assert make_focus_partial_proof(result, REQUEST, started_actions=["focus"],
        read_only_stage="after_click_assessment") is None
    command = {"kind": "input_sequence", "request": deepcopy(REQUEST)}
    assert original_input_status({"status": "returned", "command": command, "result": result}, command,
        succeeded=False, action_executed=True, target_identity=TARGET) == "unknown"
