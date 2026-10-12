"""同一真实点击/键入回执只结算原输入事实，不创建虚构的键入步骤。"""
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

import pytest

from app.core.input_sequence_partial import _digest, original_input_status
from app.core.typing_dispatch import create_typing_dispatch
from tests.test_input_sequence_search_partial import closed as native_closed, TARGET
from tests.test_key_no_dispatch import key_route
from tests.test_type_text_no_dispatch import route
from tests.test_recognition_dispatch_boundary import route as recognition_route
from tests.test_local_step_timings import timed_scene
from tests.test_visual_input_no_uia import visual_sequence
from tests.test_visual_field_proof import scene


@pytest.fixture
def compound(native_closed):
    value = deepcopy(native_closed)
    result = value["result"]
    request = value["command"]["request"]
    request["submit_search"] = result["submit_search"] = False
    focus, typed, _ = result["steps"]
    local = focus["receipt"]
    data = local["response"]["data"]
    data = data.get("result", data)
    # 旧夹具裁掉了输入层实际返回的 HWND，新合同需保留这一事实。
    data["click_result"]["window_handle"] = TARGET["handle"]
    typed_data = typed["receipt"]["response"]["data"]
    typed_data = typed_data.get("result", typed_data)
    type_result = deepcopy(typed_data["type_result"])
    data["visual_compound_input"] = {"schema": "visual_compound_input.v1",
        "text_sha256": sha256(request["text"].encode("utf-8")).hexdigest(),
        "text_length": len(request["text"]), "clear_existing": True, "submit": False,
        "window_identity": deepcopy(TARGET), "execution_request_id": "original-execution",
        "click_result_sha256": _digest(data["click_result"]),
        "window_rect": deepcopy(local["target_window_geometry"]["rect"]), "point": deepcopy(data["click_result"]["window_point"]),
        "typing_dispatch": deepcopy(type_result["typing_dispatch"]), "type_result": type_result}
    focus["name"] = "focus_type"
    result.update(steps=[focus], completed_steps=["focus_type"], phase="check_input", interrupted_at="check_input",
        error={"type": "InputSequenceInterrupted", "code": "visual_field_requires_review"},
        input_check={"status": "unavailable", "phase": "check_input", "reason": "visual_field_requires_review"})
    return value


def payload(value):
    local = value["result"]["steps"][0]["receipt"]
    data = local["response"]["data"]
    return local, data.get("result", data)["visual_compound_input"]


def classify(value, *, succeeded=False):
    return original_input_status(value, value["command"], succeeded=succeeded,
        action_executed=True, target_identity=TARGET)


def test_completed_compound_with_value_failure_is_known_failed_input(compound):
    before = deepcopy(compound)
    assert classify(compound) == "failed"
    assert len(compound["result"]["steps"]) == 1
    assert compound == before


@pytest.mark.parametrize("async_terminal", [False, True])
def test_completed_input_with_missing_after_capture_settles_failure_without_enter(
        visual_sequence, monkeypatch, async_terminal):
    from app.core.input_controller import VK_CONTROL, VK_V, VK_RETURN
    from tests import test_input_sequence_focus_partial as queue
    from tests.test_visual_field_proof import IDENTITY, FIELD, TEXT
    v = visual_sequence
    v.scene.typed["observation"]["capture"].pop("sha256")
    result = v.run()
    request = {"field_goal": FIELD["field_goal"], "text": TEXT, "clear_existing": True, "submit_search": True}
    receipt = {"status": "returned", "command": {"kind": "input_sequence", "request": request}, "result": result}
    assert result["phase"] == "focus_type" and result["completed_steps"] == ["focus_type"]
    assert result["error"]["code"] == "focus_type_observation_unavailable"
    assert original_input_status(receipt, receipt["command"], succeeded=False,
        action_executed=True, target_identity=IDENTITY) == "failed"
    assert v.events.count((VK_CONTROL, VK_V)) == 1 and (VK_RETURN,) not in v.events
    assert v.scene.requests == [] and result["automatic_retry_allowed"] is False
    assert [call["operation"] for call in v.calls] == ["execute_recognition_plan"]
    damaged = deepcopy(receipt)
    damaged["result"]["error"]["code"] = "other_observation_error"
    assert original_input_status(damaged, damaged["command"], succeeded=False,
        action_executed=True, target_identity=IDENTITY) == "unknown"
    monkeypatch.setattr(queue, "TARGET", deepcopy(IDENTITY))
    monkeypatch.setattr(queue, "REQUEST", request)
    s, pending, path, calls = queue.queued(v.scene.root, monkeypatch, {})
    original = queue.persist_original(s, pending, path, result, async_terminal=async_terminal)
    s.runtime.control({"action": "cancel", "run_id": s.run_id}, "cancel-missing-after-capture")
    final = s.runtime.tick(force=True)
    assert final["status"] == "cancelled" and final["pending"] is None
    assert final["history"][0]["original_input_status"] == "failed"
    assert final["history"][0]["action_executed"] is True
    assert path.read_bytes() == original and calls == []


@pytest.mark.parametrize("selection", [False, True])
def test_closed_click_with_no_text_dispatch_is_known_partial(compound, selection):
    local, fact = payload(compound)
    dispatch = create_typing_dispatch()
    if selection:
        dispatch.record("selection", "started")
        dispatch.record("selection", "completed")
    fact["typing_dispatch"] = dispatch.reference()
    fact.pop("type_result")
    local["phase"] = compound["result"]["steps"][0]["status"] = "result_unknown"
    local["response"]["success"] = False
    compound["result"].update(phase="focus_type", interrupted_at="focus_type", completed_steps=[],
        input_check={"status": "not_checked"},
        error={"type": "InputSequenceInterrupted", "code": "focus_type_input_not_confirmed"})
    assert classify(compound) == "failed"


@pytest.mark.parametrize("damage", ["text_started", "typed_missing", "typed_false", "text_hash", "scope", "identity",
    "extra_row", "click_false", "dispatch_events", "geometry", "outer_completed"])
def test_incomplete_compound_cannot_be_settled_or_promoted_to_success(compound, damage):
    local, fact = payload(compound)
    if damage == "text_started": fact["typing_dispatch"]["text_dispatch"] = "started"
    elif damage == "typed_missing": fact.pop("type_result")
    elif damage == "typed_false": fact["type_result"]["typed"] = False
    elif damage == "text_hash": fact["text_sha256"] = "f" * 64
    elif damage == "scope": local["local_input_scope_closed"] = False
    elif damage == "identity": local["target_identity"]["process_create_time"] += 1
    elif damage == "extra_row": compound["result"]["steps"].append(deepcopy(compound["result"]["steps"][0]))
    elif damage == "click_false":
        data = local["response"]["data"]
        data.get("result", data)["click_result"]["clicked"] = False
    elif damage == "dispatch_events": fact["typing_dispatch"]["events"] = []
    elif damage == "geometry": fact["window_rect"][0] += 1
    else:
        fact["typing_dispatch"] = create_typing_dispatch().reference()
        compound["result"].update(status="completed", phase="completed", completed_steps=["focus_type", "check_input"])
    assert classify(compound, succeeded=damage == "outer_completed") == "unknown"


def test_real_completed_compound_is_completed_without_a_type_row(compound):
    compound["result"].update(status="completed", phase="completed", completed_steps=["focus_type", "check_input"],
        input_check={"status": "verified", "source": "decision_visual", "evidence_kind": "visual"})
    compound["result"].pop("interrupted_at")
    compound["result"].pop("error")
    assert classify(compound, succeeded=True) == "completed"


@pytest.mark.parametrize("known", [True, False])
@pytest.mark.parametrize("async_terminal", [False, True])
def test_compound_failure_settles_only_known_closed_input(compound, tmp_path, monkeypatch, known, async_terminal):
    from tests import test_input_sequence_focus_partial as queue
    monkeypatch.setattr(queue, "REQUEST", deepcopy(compound["command"]["request"]))
    if not known:
        payload(compound)[1]["typing_dispatch"]["text_dispatch"] = "started"
    s, pending, path, calls = queue.queued(tmp_path, monkeypatch, compound["result"])
    original = queue.persist_original(s, pending, path, compound["result"], async_terminal=async_terminal)
    s.runtime.control({"action": "cancel", "run_id": s.run_id}, "cancel-compound")
    final = s.runtime.tick(force=True)
    if known:
        assert final["status"] == "cancelled" and final["pending"] is None
        assert final["history"][0]["original_input_status"] == "failed"
        assert final["history"][0]["action_executed"] is True
        s.runtime.admit("owned-close", {"kind": "close_launched_window", "request": {}})
    else:
        assert final["status"] == "cancel_requested" and final["pending"] == pending and final["history"] == []
    assert path.read_bytes() == original and calls == []


def test_learning_observation_reads_original_compound_row(compound):
    from app.learning_memory.receipt_adapter import _target_observation
    local, _ = payload(compound)
    data = local["response"]["data"]
    data = data.get("result", data)
    observation = {"status": "unavailable", "reason": "offline_synthetic"}
    data["learning_observation"] = observation
    assert _target_observation("input_sequence", compound["result"]) == observation


def handoff_for(value, session):
    from app.execution.task_plan_review import digest
    local, fact = payload(value)
    request = {"execution_request_id": "original-execution", "phase": "after_action", "frames": [],
        "action": {"field_phase": "value", "focus_stage": None,
            "field": {"window_identity": TARGET, "field_goal": value["command"]["request"]["field_goal"],
                "expected_text": value["command"]["request"]["text"]},
            "focus_receipt_sha256": digest(local), "input_receipt_sha256": digest(local)}}
    assessment = {"adopted": False, "disposition": "review_required"}
    result = value["result"]
    result["main_handoff"] = {"schema": "visual_field_main_handoff.v1", "reason": "visual_field_requires_review",
        "request": request, "assessment": assessment, "stage": "after_type", "automatic_retry_allowed": False,
        "authorizes_action": False, "allowed_next_steps": ["inspect_original_evidence", "close_or_explicitly_replan"],
        "original_input": {"completed_steps": result["completed_steps"], "interrupted_at": result["interrupted_at"],
            "action_executed": True, "input_check": result["input_check"], "typing_dispatch": fact["typing_dispatch"]}}
    state = {"pending": {"execution_request_id": "original-execution", "step_id": "field"},
        "target_identity": TARGET, "run_id": "run", "plan_id": "plan", "plan_sha256": "a" * 64,
        "owner_id": "owner", "session_directory": str(session)}
    original_request, original_assessment = deepcopy(request), deepcopy(assessment)
    service = SimpleNamespace(validate_result=lambda result, **binding:
        result == original_assessment and binding == original_request)
    return state, service


def test_value_handoff_projects_same_original_compound_receipt(compound, tmp_path):
    from app.execution.task_plan_review import field_main_handoff
    state, service = handoff_for(compound, tmp_path)
    handoff = field_main_handoff(state, compound, [], session=tmp_path, service=service, original_status="failed")
    assert handoff["original_input_status"] == "failed" and handoff["action_executed"] is True
    assert handoff["field_review"]["original_input"]["typing_dispatch"]["text_dispatch"] == "completed"
    assert handoff["authorizes_action"] is handoff["automatic_retry_allowed"] is False


def test_unknown_outer_row_only_allows_readonly_handoff_and_keeps_input_unknown(compound, tmp_path):
    from app.execution.task_plan_review import field_main_handoff
    state, service = handoff_for(compound, tmp_path)
    compound["result"]["steps"][0]["status"] = "result_unknown"
    assert classify(compound) == "unknown"
    handoff = field_main_handoff(state, compound, [], session=tmp_path, service=service, original_status="unknown")
    assert handoff["original_input_status"] == "unknown"
    assert handoff["authorizes_action"] is handoff["automatic_retry_allowed"] is False


@pytest.mark.parametrize("damage", ["scope", "text", "execution"])
def test_value_handoff_refuses_another_or_unclosed_compound(compound, tmp_path, damage):
    from app.execution.task_plan_review import field_main_handoff
    state, service = handoff_for(compound, tmp_path)
    if damage == "scope": payload(compound)[0]["local_input_scope_closed"] = False
    elif damage == "text": compound["command"]["request"]["text"] += " changed"
    else: state["pending"]["execution_request_id"] = "other-execution"
    with pytest.raises(ValueError, match="task_plan_field_handoff_binding_invalid"):
        field_main_handoff(state, compound, [], session=tmp_path, service=service, original_status="unknown")


@pytest.mark.parametrize("damaged", [False, True])
def test_compound_zero_input_requires_original_local_rejection_proof(recognition_route, timed_scene, monkeypatch, damaged):
    from tests.test_recognition_dispatch_boundary import owner
    local = owner(timed_scene, monkeypatch, recognition_route.run())
    request = {"field_goal": "Focus the fresh field", "text": "fresh text", "clear_existing": True, "submit_search": False}
    result = {"contract_version": "input_sequence_v1", "sequence_id": "zero-compound", "status": "interrupted",
        "automatic_retry_allowed": False, "task_effect_verified": None, "submit_search": False,
        "text_length": len(request["text"]), "text_sha256": sha256(request["text"].encode()).hexdigest()}
    compound = {"status": "returned", "command": {"kind": "input_sequence", "request": request}, "result": result}
    result.update(steps=[{"name": "focus_type", "operation": "execute_recognition_plan", "status": "not_dispatched",
        "action_executed": False, "receipt": local}], phase="focus_type", interrupted_at="focus_type",
        action_executed=False, completed_steps=[], input_check={"status": "not_checked"},
        error={"type": "InputSequenceInterrupted", "code": "focus_type_input_not_confirmed"})
    if damaged:
        local["response"]["data"].pop("pre_click_input_rejection")
    assert original_input_status(compound, compound["command"], succeeded=False,
        action_executed=False, target_identity=TARGET) == ("unknown" if damaged else "failed")


@pytest.mark.parametrize("damaged", [False, True])
def test_compound_completed_text_and_zero_enter_settles_only_verified_suffix(compound, native_closed, damaged):
    result = compound["result"]
    compound["command"]["request"]["submit_search"] = result["submit_search"] = True
    result["steps"].append(deepcopy(native_closed["result"]["steps"][-1]))
    result.update(phase="search", interrupted_at="search", completed_steps=["focus_type", "check_input"],
        input_check={"status": "verified", "source": "decision_visual", "evidence_kind": "visual"},
        error={"type": "InputSequenceInterrupted", "code": "search_input_not_confirmed"})
    if damaged:
        result["steps"][-1]["receipt"].pop("key_no_dispatch")
    assert classify(compound) == ("unknown" if damaged else "failed")
