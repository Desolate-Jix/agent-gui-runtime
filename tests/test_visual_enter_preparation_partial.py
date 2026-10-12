"""值判断通过后、Enter 凭据签发前的取消只结算已知输入前缀。"""
from copy import deepcopy
from hashlib import sha256
from time import perf_counter_ns
from types import SimpleNamespace as NS

import pytest

from app.core.input_sequence_partial import original_input_status
from app.core.input_controller import VK_CONTROL, VK_V, VK_RETURN
from tests.test_visual_empty_input import content_service, visual_sequence, scene
from tests.test_visual_empty_partial import sequence_command
from tests.test_visual_field_proof import IDENTITY, FIELD, TEXT, assess, controller_scene, executed_focus


@pytest.fixture(params=["cancelled", "expired"])
def stopped_enter(visual_sequence, monkeypatch, request):
    from app.core import local_keyboard_target
    from app.execution import input_sequence, visual_field_proof
    v = visual_sequence
    cancelled = [False]
    v.scene.context["cancelled"] = lambda: cancelled[0]
    original_issue = local_keyboard_target.issue_visual_keyboard_target
    service, client = content_service(v, "nonempty")

    def issue(proof, operation, **kwargs):
        if operation == "press_key":
            if request.param == "cancelled":
                cancelled[0] = True
            else:
                clock = lambda: proof._deadline_ns + 1
                monkeypatch.setattr(visual_field_proof, "perf_counter_ns", clock)
                monkeypatch.setattr(input_sequence, "perf_counter_ns", clock, raising=False)
        return original_issue(proof, operation, **kwargs)

    monkeypatch.setattr(local_keyboard_target, "issue_visual_keyboard_target", issue)
    try:
        yield v, v.run(), service, request.param
    finally:
        service.close()
        client.close()


def receipt_for(result):
    return {"status": "returned", "command": sequence_command(), "result": result}


@pytest.fixture
def historical_stopped_enter(scene, monkeypatch):
    """构造已冻结的两步原回执；不启用旧默认执行路线。"""
    from app.core import local_keyboard_target
    from app.core.input_sequence_partial import _digest, _request
    from app.execution.local_action_contract import _validated_request
    from app.execution.local_direct_step import _audit_request
    s = scene
    s.context["native_field_evidence"] = False
    executed_focus(s.focus)
    controller, events, _ = controller_scene(s, monkeypatch)
    v = NS(scene=s, events=events, monkeypatch=monkeypatch)
    service, client = content_service(v, "nonempty")
    try:
        focus = assess(s)
        target = local_keyboard_target.issue_visual_keyboard_target(focus, "type_text", text=TEXT,
            clear_existing=True)
        request = {"text": TEXT, **FIELD["click_point"], "click_before_typing": False,
            "clear_existing": True, "submit": False}
        with local_keyboard_target.local_keyboard_target_scope(target):
            typed = controller.type_text(**request)
        s.typed["request"] = _audit_request(_validated_request("type_text", request))
        s.typed["response"] = {"success": True, "data": {"result": {"type_result": typed,
            "execution_path": {"action_executed": True}, "action_executed": True}}}
        value = assess(s, phase="value")
        evidence = lambda proof: {"session_directory": str(service.session_dir),
            "profile": service.profile.model_dump(mode="json", exclude_unset=True),
            "request": proof.request(), "assessment": proof.assessment()}
        result = {"contract_version": "input_sequence_v1", "sequence_id": "historical-split-input",
            "status": "interrupted", "phase": "prepare_search", "interrupted_at": "prepare_search",
            "action_executed": True, "automatic_retry_allowed": False, "task_effect_verified": None,
            "completed_steps": ["focus", "type", "check_input"],
            "target": {"handle": 10, "process_id": 20}, "text_sha256": sha256(TEXT.encode("utf-8")).hexdigest(),
            "text_length": len(TEXT), "submit_search": True,
            "input_check": {"status": "verified", "source": "decision_visual", "evidence_kind": "visual"},
            "error": {"type": "InputSequenceInterrupted", "code": "visual_field_cancelled"},
            "steps": [{"name": name, "operation": receipt["operation"], "status": "returned",
                "action_executed": True, "receipt": deepcopy(receipt)} for name, receipt in
                [("focus", s.focus), ("type", s.typed)]],
            "field_proofs": [focus.to_reference(), value.to_reference()], "visual_click_evidence": evidence(focus)}
        result["enter_preparation_failure"] = {"schema": "visual_enter_preparation_partial.v1",
            "stage": "before_enter_keyboard_target", "sequence_id": result["sequence_id"],
            "request_sha256": _digest(_request(sequence_command()["request"])),
            "focus_receipt_sha256": _digest(s.focus), "input_receipt_sha256": _digest(s.typed),
            "value_request_sha256": value.to_reference()["request_sha256"], "stop_reason": "visual_field_cancelled",
            "cancelled": True, "deadline_ns": s.context["deadline_ns"], "observed_at_ns": perf_counter_ns(),
            "started_actions": ["focus", "type"], "suffix_dispatch_started": False, "evidence": evidence(value)}
        yield v, result, service, "cancelled"
    finally:
        service.close()
        client.close()


def test_historical_split_prefix_retains_authenticated_stop_semantics(historical_stopped_enter):
    _, result, _, _ = historical_stopped_enter
    receipt = receipt_for(result)
    assert original_input_status(receipt, receipt["command"], succeeded=False,
        action_executed=True, target_identity=IDENTITY) == "failed"


def test_cancel_or_expiry_before_enter_is_known_failed_without_repeating_input(stopped_enter):
    v, result, service, cause = stopped_enter
    receipt = receipt_for(result)
    before = deepcopy(receipt)
    assert result["completed_steps"] == ["focus_type", "check_input"]
    assert original_input_status(receipt, receipt["command"], succeeded=False,
        action_executed=True, target_identity=IDENTITY) == "failed"
    assert receipt == before
    assert v.events.count((VK_CONTROL, VK_V)) == 1 and (VK_RETURN,) not in v.events
    assert [call["operation"] for call in v.calls] == ["execute_recognition_plan"]
    assert len(v.scene.requests) == 1 and v.forbidden_calls == []


@pytest.mark.parametrize("async_terminal", [False, True])
def test_known_enter_preparation_cancel_closes_queue_and_admits_next_plan(
        stopped_enter, monkeypatch, async_terminal):
    from tests import test_input_sequence_focus_partial as queue
    v, result, service, cause = stopped_enter
    monkeypatch.setattr(queue, "TARGET", deepcopy(IDENTITY))
    monkeypatch.setattr(queue, "REQUEST", deepcopy(sequence_command()["request"]))
    s, pending, path, calls = queue.queued(v.scene.root, monkeypatch, {})
    s.runtime.coordinator._decision_service = service
    original = queue.persist_original(s, pending, path, result, async_terminal=async_terminal)
    s.runtime.control({"action": "cancel", "run_id": s.run_id}, "cancel-before-enter")
    final = s.runtime.tick(force=True)
    assert final["status"] == "cancelled" and final["pending"] is None
    assert final["history"][0]["original_input_status"] == "failed"
    assert final["history"][0]["action_executed"] is True
    s.runtime.admit("owned-close", {"kind": "close_launched_window", "request": {}})
    source = s.runtime.backend._source(final)["plan"]
    new = s.runtime.control({"action": "start", "plan": source}, "after-enter-preparation")
    assert new["run_id"] != s.run_id
    assert path.read_bytes() == original and calls == []


@pytest.mark.parametrize("damage", ["value_auth", "compound_binding", "text_dispatch", "extra_search"])
def test_incomplete_or_forged_prefix_remains_unknown(stopped_enter, damage):
    v, result, service, cause = stopped_enter
    receipt = receipt_for(deepcopy(result))
    result = receipt["result"]
    if damage == "value_auth":
        result["enter_preparation_failure"]["evidence"]["assessment"]["adopted"] = False
    elif damage == "compound_binding":
        result["steps"][0]["receipt"]["response"]["data"]["visual_compound_input"]["point"]["x"] += 1
    elif damage == "text_dispatch":
        result["steps"][0]["receipt"]["response"]["data"]["visual_compound_input"]["typing_dispatch"]["text_dispatch"] = "started"
    else:
        result["steps"].append({"name": "search", "operation": "press_key", "status": "result_unknown",
            "action_executed": None})
    assert original_input_status(receipt, receipt["command"], succeeded=False,
        action_executed=True, target_identity=IDENTITY) == "unknown"


@pytest.mark.parametrize("damage", ["missing", "request_auth", "execution", "field", "reference",
    "receipt", "frames", "profile"])
def test_historical_click_evidence_is_authenticated_and_bound_to_original_input(historical_stopped_enter, damage):
    from app.core.input_sequence_partial import _digest
    v, result, service, cause = historical_stopped_enter
    receipt = receipt_for(deepcopy(result))
    result = receipt["result"]
    evidence = result["visual_click_evidence"]
    focus_request = evidence["request"]
    if damage == "missing":
        result.pop("visual_click_evidence")
    elif damage == "request_auth":
        focus_request["request_id"] += "-forged"
    elif damage == "execution":
        focus_request["execution_request_id"] += "-different-task"
    elif damage == "field":
        focus_request["action"]["field"]["field_goal"] += " different"
        result["field_proofs"][0]["field"] = deepcopy(focus_request["action"]["field"])
    elif damage == "reference":
        result["field_proofs"][0]["request_sha256"] = "0" * 64
    elif damage == "receipt":
        result["steps"][0]["receipt"]["finished_at"] = "2026-10-12T00:00:00Z"
        digest = _digest(result["steps"][0]["receipt"])
        focus_request["action"]["focus_receipt_sha256"] = digest
        result["field_proofs"][0]["focus_receipt_sha256"] = digest
        result["field_proofs"][-1]["focus_receipt_sha256"] = digest
        result["enter_preparation_failure"]["focus_receipt_sha256"] = digest
        result["enter_preparation_failure"]["evidence"]["request"]["action"]["focus_receipt_sha256"] = digest
    elif damage == "frames":
        focus_request["frames"][0]["capture_id"] += "-different"
        result["field_proofs"][0]["frames"] = deepcopy(focus_request["frames"])
        result["field_proofs"][0]["frame"] = deepcopy(focus_request["frames"][0])
    else:
        evidence["profile"]["mode"] = "shadow"
    before = deepcopy(receipt)
    assert original_input_status(receipt, receipt["command"], succeeded=False,
        action_executed=True, target_identity=IDENTITY) == "unknown"
    assert receipt == before


def test_historical_authenticated_same_session_click_cannot_replace_original(historical_stopped_enter):
    v, result, service, cause = historical_stopped_enter
    receipt = receipt_for(deepcopy(result))
    evidence = receipt["result"]["visual_click_evidence"]
    request = evidence["request"]
    request["request_id"] += "-other-task"
    request["execution_request_id"] += "-other-task"
    evidence["assessment"] = service.evaluate(**request)
    assert service.validate_result(evidence["assessment"], **request)
    assert evidence["assessment"]["adopted"] is True
    assert original_input_status(receipt, receipt["command"], succeeded=False,
        action_executed=True, target_identity=IDENTITY) == "unknown"


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_authenticated_legacy_content_strategy_still_closes_enter_preparation(historical_stopped_enter, version):
    from app.core.visual_typing_strategy import validated_effective_typing_request
    v, result, service, cause = historical_stopped_enter
    receipt = receipt_for(deepcopy(result))
    result = receipt["result"]
    evidence = result.pop("visual_click_evidence")
    focus_request = evidence["request"]
    focus_request["request_id"] += "-legacy"
    focus_request["condition"] = "The marked click is inside the intended visible text input and the field is usable for typing now."
    if version == "v1":
        focus_request["action"]["field_content_check"] = {"schema": "visual_field_content.v1", "clear_existing": True}
    else:
        from app.execution.field_content_ocr import read_field_content
        focus_request["action"]["field_content_ocr"] = {"schema": "visual_field_content_ocr.v1",
            "clear_existing": True, "reading": read_field_content(frame=focus_request["frames"][0],
                field=focus_request["action"]["field"], session_dir=service.session_dir)}
    evidence["assessment"] = service.evaluate(**focus_request)
    assert evidence["assessment"]["adopted"] is True
    digest = evidence["assessment"]["request_sha256"]
    result["typing_strategy_evidence"] = evidence
    result["typing_strategy"] = {"schema": "visual_typing_strategy." + version, "requested_clear_existing": True,
        "effective_clear_existing": True, "reason": "replace_existing", "focus_request_sha256": digest}
    result["field_proofs"][0]["request_sha256"] = digest
    if version == "v1":
        result["field_proofs"][0]["field_content_result"] = deepcopy(evidence["assessment"]["field_content_result"])
    else:
        result["field_proofs"][0]["field_content_ocr"] = deepcopy(focus_request["action"]["field_content_ocr"])
    assert validated_effective_typing_request(result, receipt["command"]["request"])["clear_existing"] is True
    assert original_input_status(receipt, receipt["command"], succeeded=False,
        action_executed=True, target_identity=IDENTITY) == "failed"


def test_arbitrary_enter_issuance_error_remains_unknown(visual_sequence, monkeypatch):
    from app.core import local_keyboard_target
    v = visual_sequence
    service, client = content_service(v, "empty")
    original_issue = local_keyboard_target.issue_visual_keyboard_target
    def issue(proof, operation, **kwargs):
        if operation == "press_key":
            raise ValueError("visual_field_cancelled")
        return original_issue(proof, operation, **kwargs)
    monkeypatch.setattr(local_keyboard_target, "issue_visual_keyboard_target", issue)
    try:
        result = v.run()
        receipt = receipt_for(result)
        assert "enter_preparation_failure" not in result
        assert original_input_status(receipt, receipt["command"], succeeded=False,
            action_executed=True, target_identity=IDENTITY) == "unknown"
        assert (VK_RETURN,) not in v.events
    finally:
        service.close()
        client.close()


@pytest.mark.parametrize("async_terminal", [False, True])
def test_error_after_real_enter_dispatch_stays_unknown_and_holds_original_ticket(
        visual_sequence, monkeypatch, async_terminal):
    from app.core.input_controller import InputController
    from tests import test_input_sequence_focus_partial as queue
    v = visual_sequence
    service, client = content_service(v, "empty")
    original_press = InputController.press_key
    def press_then_fail(controller, *args, **kwargs):
        original_press(controller, *args, **kwargs)
        raise RuntimeError("return path failed after real offline key dispatch")
    monkeypatch.setattr(InputController, "press_key", press_then_fail)
    try:
        result = v.run()
        receipt = receipt_for(result)
        assert v.events.count((VK_CONTROL, VK_V)) == v.events.count((VK_RETURN,)) == 1
        assert "enter_preparation_failure" not in result
        assert original_input_status(receipt, receipt["command"], succeeded=False,
            action_executed=True, target_identity=IDENTITY) == "unknown"
        monkeypatch.setattr(queue, "TARGET", deepcopy(IDENTITY))
        monkeypatch.setattr(queue, "REQUEST", deepcopy(sequence_command()["request"]))
        s, pending, path, calls = queue.queued(v.scene.root, monkeypatch, {})
        original = queue.persist_original(s, pending, path, result, async_terminal=async_terminal)
        s.runtime.control({"action": "cancel", "run_id": s.run_id}, "cancel-unknown-enter")
        final = s.runtime.tick(force=True)
        assert final["status"] == "cancel_requested" and final["pending"] == pending
        assert path.read_bytes() == original and calls == []
    finally:
        service.close()
        client.close()
