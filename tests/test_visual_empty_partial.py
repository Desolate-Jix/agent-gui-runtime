"""替换前缀只结算真实失败，损坏历史策略不得退回无策略规则。"""
from copy import deepcopy
import pytest

from app.core.input_sequence_partial import original_input_status
from tests.test_visual_prefix_failure import closed
from tests.test_input_sequence_search_partial import closed as native_closed, TARGET
from tests.test_key_no_dispatch import key_route
from tests.test_type_text_no_dispatch import route
from tests.test_recognition_dispatch_boundary import route as recognition_route
from tests.test_local_step_timings import timed_scene
from tests.test_visual_empty_input import content_service, visual_sequence, scene
from tests.test_visual_field_proof import FIELD, IDENTITY, TEXT


@pytest.mark.parametrize("declaration", ["strategy", "evidence", "both"])
def test_invalid_legacy_strategy_cannot_fall_back_to_unmodified_prefix(closed, declaration):
    assert original_input_status(closed, closed["command"], succeeded=False,
        action_executed=True, target_identity=TARGET) == "failed"
    if declaration in {"strategy", "both"}:
        closed["result"]["typing_strategy"] = {}
    if declaration in {"evidence", "both"}:
        closed["result"]["typing_strategy_evidence"] = {}
    before = deepcopy(closed)
    assert original_input_status(closed, closed["command"], succeeded=False,
        action_executed=True, target_identity=TARGET) == "unknown"
    assert closed == before


def sequence_command(clear_existing=True):
    return {"kind": "input_sequence", "request": {"field_goal": FIELD["field_goal"], "text": TEXT,
        "clear_existing": clear_existing, "submit_search": True}}


@pytest.fixture
def replacement_value_failure(visual_sequence):
    v = visual_sequence
    service, client = content_service(v, "empty", value_choice="condition_not_met")
    try:
        result = v.run()
        assert result["status"] == "interrupted" and result["completed_steps"] == ["focus_type"]
        assert result["steps"][0]["receipt"]["response"]["data"]["visual_compound_input"]["clear_existing"] is True
        yield {"status": "returned", "command": sequence_command(), "result": result}, v
    finally:
        service.close()
        client.close()


def test_replacement_value_failure_is_known_failed_without_reinterpreting_request(replacement_value_failure):
    from app.core.visual_typing_strategy import validated_effective_typing_request
    receipt, v = replacement_value_failure
    before = deepcopy(receipt)
    assert validated_effective_typing_request(receipt["result"], receipt["command"]["request"])["clear_existing"] is True
    assert "typing_strategy" not in receipt["result"] and "typing_strategy_evidence" not in receipt["result"]
    assert original_input_status(receipt, receipt["command"], succeeded=False,
        action_executed=True, target_identity=IDENTITY) == "failed"
    assert receipt == before
    assert receipt["command"]["request"]["clear_existing"] is True
    dispatch = receipt["result"]["steps"][0]["receipt"]["response"]["data"]["visual_compound_input"]["typing_dispatch"]
    assert dispatch["selection_dispatch"] == "completed" and dispatch["submit_dispatch"] == "not_started"
    assert dispatch["text_dispatch"] == "completed"
    assert [event["phase"] for event in dispatch["events"]] == ["selection", "selection", "text", "text"]


@pytest.mark.parametrize("damage", ["clear_existing", "text_digest", "scope"])
def test_modified_replacement_receipt_cannot_settle_known_failure(replacement_value_failure, damage):
    receipt, _ = replacement_value_failure
    forged = deepcopy(receipt)
    typed = forged["result"]["steps"][0]["receipt"]
    compound = typed["response"]["data"]["visual_compound_input"]
    if damage == "clear_existing":
        compound["clear_existing"] = False
    elif damage == "text_digest":
        compound["text_sha256"] = "f" * 64
    else:
        typed["local_input_scope_closed"] = False
    assert original_input_status(forged, forged["command"], succeeded=False,
        action_executed=True, target_identity=IDENTITY) == "unknown"
    assert receipt["command"] == sequence_command()


@pytest.mark.parametrize("async_terminal", [False, True])
def test_replacement_prefix_cancel_preserves_original_and_admits_next_plan(visual_sequence, monkeypatch, async_terminal):
    from tests import test_input_sequence_focus_partial as queue
    v = visual_sequence
    monkeypatch.setattr(queue, "TARGET", deepcopy(IDENTITY))
    monkeypatch.setattr(queue, "REQUEST", deepcopy(sequence_command()["request"]))
    s, pending, path, calls = queue.queued(v.scene.root, monkeypatch, {})
    v.scene.context["execution_request_id"] = pending["execution_request_id"]
    service, client = content_service(v, "empty", value_choice="condition_not_met")
    s.runtime.coordinator._decision_service = service
    try:
        result = v.run()
        assert result["completed_steps"] == ["focus_type"]
        original = queue.persist_original(s, pending, path, result, async_terminal=async_terminal)
        s.runtime.control({"action": "cancel", "run_id": s.run_id}, "cancel-replacement-prefix")
        final = s.runtime.tick(force=True)
        assert final["status"] == "cancelled" and final["pending"] is None
        assert final["history"][0]["original_input_status"] == "failed"
        assert final["history"][0]["action_executed"] is True
        s.runtime.admit("owned-close", {"kind": "close_launched_window", "request": {}})
        source = s.runtime.backend._source(final)["plan"]
        new = s.runtime.control({"action": "start", "plan": source}, "after-replacement-prefix")
        assert new["run_id"] != s.run_id
        assert path.read_bytes() == original and calls == []
    finally:
        service.close()
        client.close()
