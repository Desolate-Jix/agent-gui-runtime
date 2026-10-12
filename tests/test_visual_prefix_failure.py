"""可信视觉输入前缀只结算原失败，不授权重放或业务成功。"""
from copy import deepcopy
import pytest

from app.core.input_sequence_partial import original_input_status
from tests.test_input_sequence_search_partial import closed as native_closed, REQUEST, TARGET
from tests.test_key_no_dispatch import key_route
from tests.test_type_text_no_dispatch import route
from tests.test_recognition_dispatch_boundary import route as recognition_route
from tests.test_local_step_timings import timed_scene


@pytest.fixture(params=["selection", "value", "search"])
def closed(native_closed, request, tmp_path):
    value = deepcopy(native_closed)
    result = value["result"]
    stage = request.param
    if stage == "search":
        result["input_check"] = {"status": "verified", "source": "decision_visual", "evidence_kind": "visual"}
    else:
        result["steps"] = result["steps"][:2]
        result["completed_steps"] = ["focus"] if stage == "selection" else ["focus", "type"]
        result["phase"] = result["interrupted_at"] = "type" if stage == "selection" else "check_input"
        code = "type_input_not_confirmed" if stage == "selection" else "visual_field_requires_review"
        result["error"] = {"type": "InputSequenceInterrupted", "code": code}
        result["input_check"] = ({"status": "not_checked"} if stage == "selection" else {
            "status": "unavailable", "phase": "check_input", "reason": code})
        if stage == "selection":
            from app.core.typing_dispatch import create_typing_dispatch
            dispatch = create_typing_dispatch()
            dispatch.record("selection", "started")
            dispatch.record("selection", "completed")
            dispatch.persist_selection(tmp_path / "selection-evidence")
            row = result["steps"][1]
            row["status"] = row["receipt"]["phase"] = "result_unknown"
            row["receipt"]["response"] = {"success": False, "error": {"code": "type_text_failed"}, "data": {
                "execution_path": {"action_executed": True}, "input_started": True,
                "typing_dispatch": dispatch.reference()}}
    value["test_stage"] = stage
    return value


def test_complete_prefix_is_failed_and_preserves_real_input_fact(closed):
    assert original_input_status(closed, closed["command"], succeeded=False,
        action_executed=True, target_identity=TARGET) == "failed"


@pytest.mark.parametrize("damage", ["text_started", "submit_started", "focus_started", "events", "identity", "scope", "extra_row", "request"])
def test_unknown_or_incomplete_dispatch_cannot_be_called_known_prefix(closed, damage):
    typed = closed["result"]["steps"][1]["receipt"]
    data = typed["response"]["data"]
    data = data.get("result", data)
    dispatch = data.get("typing_dispatch") or data.get("type_result", {}).get("typing_dispatch")
    if damage == "text_started": dispatch["text_dispatch"] = "started"
    elif damage == "submit_started": dispatch["submit_dispatch"] = "started"
    elif damage == "focus_started": dispatch["focus_dispatch"] = "started"
    elif damage == "events": dispatch["events"] = []
    elif damage == "identity": typed["target_identity"]["process_create_time"] += 1
    elif damage == "scope": typed["local_input_scope_closed"] = False
    elif damage == "extra_row": closed["result"]["steps"].append(deepcopy(closed["result"]["steps"][-1]))
    else: typed["request"]["text_sha256"] = "f" * 64
    assert original_input_status(closed, closed["command"], succeeded=False,
        action_executed=True, target_identity=TARGET) == "unknown"


@pytest.mark.parametrize("async_terminal", [False, True])
def test_cancel_settles_real_queue_preserves_original_and_admits_next_plan(closed, tmp_path, monkeypatch, async_terminal):
    from tests import test_input_sequence_focus_partial as queue
    monkeypatch.setattr(queue, "REQUEST", deepcopy(REQUEST))
    s, pending, path, calls = queue.queued(tmp_path, monkeypatch, closed["result"])
    original = queue.persist_original(s, pending, path, closed["result"], async_terminal=async_terminal)
    s.runtime.control({"action": "cancel", "run_id": s.run_id}, "cancel-prefix")
    final = s.runtime.tick(force=True)
    assert final["status"] == "cancelled" and final["pending"] is None
    assert final["history"][0]["original_input_status"] == "failed"
    assert final["history"][0]["action_executed"] is True
    s.runtime.admit("owned-close", {"kind": "close_launched_window", "request": {}})
    source = s.runtime.backend._source(final)["plan"]
    new = s.runtime.control({"action": "start", "plan": source}, "new-plan-after-prefix")
    assert new["run_id"] != s.run_id
    assert path.read_bytes() == original and calls == []
