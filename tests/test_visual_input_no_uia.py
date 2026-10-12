"""纯视觉字段闭环通过真实凭据和键盘边界，禁止 UIA 与 OCR 读值。"""
from copy import deepcopy
from hashlib import sha256
import json
from types import SimpleNamespace as NS

import pytest

from app.core import local_keyboard_target as keyboard
from app.execution import input_sequence
from tests.test_visual_field_proof import (scene, controller_scene, receipt, assess, FIELD, TEXT, executed_focus)


@pytest.fixture
def visual_sequence(scene, monkeypatch):
    s = scene
    s.context["native_field_evidence"] = False
    executed_focus(s.focus)
    forbidden_calls = []

    def forbidden(*args, **kwargs):
        forbidden_calls.append(1)
        pytest.fail("纯视觉输入不得调用原生字段或 OCR 入口")

    for name in ("read_visual_focus_snapshot", "read_visual_value", "_read_bounded_text", "_read_roi_text"):
        monkeypatch.setattr(s.module, name, forbidden)
    monkeypatch.setattr(input_sequence, "_read_field", forbidden)
    monkeypatch.setattr(input_sequence, "_focus_field_binding", forbidden)
    from app.agent.windows_text_field_reader import WindowsTextFieldReader
    monkeypatch.setattr(WindowsTextFieldReader, "read_focused_at_point", forbidden)
    monkeypatch.setattr(WindowsTextFieldReader, "read_field", forbidden)
    from app.core.ocr_service import ocr_service
    monkeypatch.setattr(ocr_service, "_get_rapidocr_engine", forbidden)
    controller, events, captures = controller_scene(s, monkeypatch, selected_change=True)
    calls, before_dispatch = [], []
    from app.core import local_input_policy, local_text_focus
    from app.core import visual_compound_input as compound
    from app.execution import action_review
    from app.execution.action_review_dispatch import review_original_action
    from app.judgment import DecisionProfile, DecisionService
    from tests.test_action_review_contract import Provider
    from tests.test_visual_field_proof import NATIVE
    monkeypatch.setattr(local_input_policy, "current_local_operator_identity", lambda manager: deepcopy(NATIVE))
    monkeypatch.setattr(local_input_policy, "require_local_operator_input", lambda manager: True)
    monkeypatch.setattr(local_text_focus, "require_local_operator_input", lambda manager: True)
    from app.core.input_controller import window_manager
    monkeypatch.setattr(window_manager, "read_owned_foreground_popup", lambda bound: None)
    candidate_provider = Provider()
    candidate_service = DecisionService(s.root, provider=candidate_provider,
        profile=DecisionProfile(contract_version="decision_profile.v2", mode="auto", request_cap=20,
            auto_conditions=[action_review.CANDIDATE_CONDITION]))

    class Coordinator:
        _owner = NS(call=lambda callback: callback())

        def _windows(self):
            from app.core.input_controller import window_manager
            return window_manager

        def execute_local_step(self, **kwargs):
            calls.append(kwargs)
            operation = kwargs["operation"]
            if kwargs.get("grounding_target") is not None:
                from app.core.agent_grounding_target import agent_grounding_scope
                from app.core.visual_submit_target import prepare_visual_submit, perform_visual_submit
                from tests.test_visual_field_proof import capture
                target = kwargs["grounding_target"]
                step = executed_focus(receipt(s.root, "submit-search"))
                step["request"] = deepcopy(kwargs["request"])
                frame = step["capture"]
                data = step["response"]["data"]
                with agent_grounding_scope(target), action_review.action_review_scope(s.context["service"],
                        context=kwargs["action_review"], cancelled=s.context.get("cancelled"),
                        deadline_ns=s.context["deadline_ns"]):
                    plan = target.plan(image_path=frame["image_path"],goal=FIELD["field_goal"],identity=NATIVE)
                    candidate = plan["recommended_target"]
                    reviewed = review_original_action(capture=frame,identity=NATIVE,candidate=candidate,
                        point=FIELD["click_point"],goal=FIELD["field_goal"],click_kind="single",
                        manager=self._windows(),validate_binding=lambda:(NATIVE,candidate))
                    target.before_dispatch(FIELD["click_point"],NATIVE)
                    prepare_visual_submit(self._windows(),FIELD["click_point"],reviewed)
                    events.append("gate-click")
                    if before_dispatch:
                        before_dispatch[0](operation)
                    try:
                        perform_visual_submit(controller,self._windows(),FIELD["click_point"],
                            data["click_result"],output=data)
                    except Exception as error:
                        step["phase"] = "result_unknown"
                        step["response"] = {"success":False,"error":{"code":str(error)},"data":data}
                return step
            if operation == "execute_recognition_plan":
                step = deepcopy(s.focus)
                step["action_executed"] = True
                step["request"] = deepcopy(kwargs["request"])
                data = step["response"]["data"]
                point = deepcopy(FIELD["click_point"])
                candidate = {"candidate_id": "field", "source": "external_api", "capture_id": step["capture"]["capture_id"],
                    "bbox": deepcopy(FIELD["bbox"]), "click_point": point}
                context = kwargs["action_review"]
                manager = self._windows()
                configured_service = s.context.get("service")
                review_service = candidate_service if getattr(configured_service, "enabled", False) else configured_service
                with action_review.action_review_scope(review_service, context=context,
                        cancelled=s.context.get("cancelled"), deadline_ns=s.context["deadline_ns"]):
                    reviewed = review_original_action(capture=step["capture"], identity=NATIVE,
                        candidate=candidate, point=point, goal=FIELD["field_goal"], click_kind="single",
                        manager=manager, validate_binding=lambda: (NATIVE, candidate))
                    with local_text_focus.visual_text_focus_scope(kwargs["focus_target"]):
                        local_text_focus.check_local_text_focus(point, manager)
                        compound.prepare_visual_compound_input(manager, point, reviewed)
                        # 仅替换真实鼠标边界；候选认证、单次替换和键盘门禁使用生产代码。
                        events.append("gate-click")
                        if before_dispatch:
                            before_dispatch[0](operation)
                        try:
                            compound.perform_visual_compound_input(controller, manager, point,
                                data["click_result"], output=data)
                        except Exception as error:
                            step["phase"] = "result_unknown"
                            step["response"] = {"success": False, "error": {"code": str(error)}, "data": data}
                step["observation"] = deepcopy(s.typed["observation"])
                return step
            if before_dispatch:
                before_dispatch[0](operation)
            target = kwargs["keyboard_target"]
            target.validate_command(operation, kwargs["request"])
            with keyboard.local_keyboard_target_scope(target):
                assert operation == "press_key", "默认替换不得派发独立键入动作"
                data = controller.press_key(**kwargs["request"])
                step = receipt(s.root, "search", "press_key")
                step["request"] = deepcopy(kwargs["request"])
            step["response"] = {"success": True, "data": {**data,
                "execution_path": {"action_executed": True}, "action_executed": True}}
            return step

    def run(**overrides):
        request = {"field_goal": FIELD["field_goal"], "text": TEXT, "clear_existing": True,
            "submit_search": True, **overrides}
        context = {"schema":"action_review_context.v1","run_id":"visual-run",
            "attempt_id":"visual-attempt","step_id":"fill","budget_ms":30000,
            "plan":{"schema_version":"task_plan.v2","title":"Fill the fresh field","inputs":{},
                "steps":[{"step_id":"fill","action":{"kind":"input_sequence",**request},
                    "verification":{"kind":"agent_judgment"}}]}}
        configured = s.context.get("service")
        if getattr(configured,"enabled",False) and action_review.CANDIDATE_CONDITION not in configured.profile.auto_conditions:
            configured.profile = configured.profile.model_copy(update={"auto_conditions":
                (*configured.profile.auto_conditions,action_review.CANDIDATE_CONDITION)})
        return input_sequence.run_input_sequence(Coordinator(), {"handle": 10, "process_id": 20}, request,
            field_evidence_mode="visual", visual_field_context=s.context, action_review=context,
            action_review_deadline_ns=s.context["deadline_ns"])

    yield NS(scene=s, run=run, controller=controller, calls=calls, events=events, captures=captures,
        forbidden_calls=forbidden_calls, before_dispatch=before_dispatch, monkeypatch=monkeypatch,
        candidate_provider=candidate_provider)
    candidate_service.close()


def choice_replies(v, monkeypatch, stage, choice):
    import httpx
    from app.judgment import DecisionProfile, DecisionService, OpenAIDecisionsProvider
    options = ("condition_met", "condition_not_met", "evidence_insufficient")
    def handle(request):
        v.scene.requests.append(request)
        assert [q["name"] for q in json.loads(request.content)["questions"]] == ["current_step"]
        selected = choice if current_stage(v) == stage else "condition_met"
        answers = [{"type": "choice", "name": "current_step", "choice": selected, "confidence": .25,
            "probabilities": [{"value": value, "probability": p} for value, p in zip(options, (.25, .5, .25))]}]
        return httpx.Response(200, json={"model": "gpt-6-luna", "answers": answers,
            "usage": {"input_tokens": 4, "output_tokens": 0, "total_tokens": 4}})
    client = httpx.Client(transport=httpx.MockTransport(handle))
    service = DecisionService(v.scene.root, profile=DecisionProfile.model_validate({
        **v.scene.service.profile.model_dump(mode="json"), "decision_format": "choice"}),
        provider=OpenAIDecisionsProvider(api_key_env="VISUAL_FIELD_TEST_KEY", client=client))
    v.scene.context["service"] = service
    return service, client


@pytest.mark.parametrize("choice", ["condition_not_met", "evidence_insufficient"])
def test_visual_choice_refusal_preserves_authenticated_main_handoff_without_suffix(
        visual_sequence, monkeypatch, choice):
    from app.core.input_controller import VK_CONTROL, VK_A, VK_V, VK_RETURN
    v = visual_sequence
    service, client = choice_replies(v, monkeypatch, "value", choice)
    expected_steps = ["focus_type"]
    try:
        result = v.run()
        assert result["status"] == "interrupted" and result["completed_steps"] == expected_steps
        assert (VK_RETURN,) not in v.events
        assert v.events.count((VK_CONTROL, VK_V)) == v.events.count((VK_CONTROL, VK_A)) == 1
        handoff = result.get("main_handoff")
        assert handoff is not None, "Decision refusal must reach Main with its original evidence"
        assert handoff["schema"] == "visual_field_main_handoff.v1"
        assert handoff["stage"] == "after_type"
        assert handoff["assessment"]["choice_result"]["choice"] == choice
        assert handoff["assessment"]["choice_result"]["confidence"] == .25
        assert service.validate_result(handoff["assessment"], **handoff["request"])
        assert handoff["automatic_retry_allowed"] is handoff["authorizes_action"] is False
        assert handoff["allowed_next_steps"] == ["inspect_original_evidence", "close_or_explicitly_replan"]
        assert handoff["original_input"]["completed_steps"] == expected_steps
        assert result["field_evaluations"][-1]["request_sha256"] == handoff["assessment"]["request_sha256"]
        dispatch = handoff["original_input"]["typing_dispatch"]
        assert dispatch["selection_dispatch"] == dispatch["text_dispatch"] == "completed"
        assert dispatch["submit_dispatch"] == "not_started"
        assert len(v.scene.requests) == 1
        assert v.forbidden_calls == []
    finally:
        service.close()
        client.close()


@pytest.mark.parametrize("choice", ["condition_not_met", "evidence_insufficient"])
@pytest.mark.parametrize("known", [True, False])
def test_value_handoff_reaches_original_main_with_failed_or_unknown_input_without_replay(
        visual_sequence, monkeypatch, choice, known):
    from app.core.json_snapshot import read_json_snapshot
    from tests import test_input_sequence_focus_partial as queue
    from tests.test_visual_field_proof import IDENTITY
    v = visual_sequence
    monkeypatch.setattr(queue, "TARGET", deepcopy(IDENTITY))
    monkeypatch.setattr(queue, "REQUEST", {"field_goal": FIELD["field_goal"], "text": TEXT,
        "clear_existing": True, "submit_search": True})
    s, pending, path, calls = queue.queued(v.scene.root, monkeypatch, {})
    original_state = s.runtime.backend.status(s.run_id)
    v.scene.context["execution_request_id"] = pending["execution_request_id"]
    service, client = choice_replies(v, monkeypatch, "value", choice)
    s.runtime.coordinator._decision_service = service
    try:
        result = v.run()
        if not known:
            # 组合派发记录未知时，保持已认证子回执原件，不能用模型判断补齐终结事实。
            result["steps"][-1]["status"] = "result_unknown"
        original = queue.persist_original(s, pending, path, result, async_terminal=True)
        terminal_path = s.session / "agent-commands" / (pending["execution_request_id"] + ".json")
        terminal = terminal_path.read_bytes()
        final = s.runtime.tick(force=True)
        assert final["status"] == ("failed" if known else "pending")
        assert final["review_required"] is True
        handoff = final["main_handoff"]
        assert handoff["original_input_status"] == ("failed" if known else "unknown")
        assert handoff["field_review"]["assessment"]["choice_result"]["choice"] == choice
        dispatch = handoff["field_review"]["original_input"]["typing_dispatch"]
        assert dispatch["selection_dispatch"] == dispatch["text_dispatch"] == "completed"
        assert dispatch["submit_dispatch"] == "not_started"
        assert handoff["field_review"]["stage"] == "after_type"
        assert handoff["automatic_retry_allowed"] is handoff["authorizes_action"] is False
        assert "review_packet" not in final
        if known:
            assert final["pending"] is None and final["history"][0]["verdict"] == "failure"
            assert final["history"][0]["action_executed"] is True
            with pytest.raises(ValueError):
                s.runtime.control({"action": "continue", "run_id": s.run_id,
                    "wait_id": s.first["wait"]["wait_id"]}, "do-not-resume")
        else:
            assert final["pending"] == pending and final["history"] == []
        for i in range(2):
            status = s.runtime.control({"action": "status", "run_id": s.run_id}, "read-only-" + str(i))
            assert status["main_handoff"] == handoff
        import asyncio
        from pathlib import Path
        from scripts.execution_client import ExecutionClient
        from tests.test_task_plan_client import Session
        opened = ExecutionClient(root=Path(__file__).resolve().parents[1], data_root=v.scene.root / "client", allow_actions=True)
        opened._session = Session([final, final])
        events = []
        for i in range(2):
            delivered = asyncio.run(opened.run_plan("caller-status-" + str(i), {"kind": "task_plan",
                "request": {"action": "status", "run_id": s.run_id}}, event_callback=events.append))
            assert delivered["client_state"] == "review_required"
            assert delivered["result"]["main_handoff"] == handoff
            assert delivered["result"]["review_required"] is True
            assert "verification_results" not in delivered["result"]
        assert len(events) == 1
        assert path.read_bytes() == original and terminal_path.read_bytes() == terminal
        assert len(list(s.session.glob("commands/trial-exec-*.json"))) == 1
        assert len(v.scene.requests) == 1 and calls == []
        assert read_json_snapshot(path)["result"]["status"] == "running"
        from app.execution.task_plan_review import field_main_handoff
        tampered = deepcopy(result)
        tampered["steps"][-1]["receipt"]["local_input_scope_closed"] = False
        with pytest.raises(ValueError, match="task_plan_field_handoff_binding_invalid"):
            field_main_handoff(original_state, {"command": pending["suggested_command"], "result": tampered},
                [], session=s.session, service=service, original_status="unknown")
    finally:
        service.close()
        client.close()


def test_compact_input_receipt_keeps_main_handoff(visual_sequence, monkeypatch):
    from app.instant_receipt import compact_receipt
    v = visual_sequence
    service, client = choice_replies(v, monkeypatch, "value", "condition_not_met")
    try:
        result = v.run()
        compact = compact_receipt({"request_id": "original", "result": result})
        assert compact["sequence"]["main_handoff"] == result["main_handoff"]
    finally:
        service.close()
        client.close()


@pytest.mark.parametrize("explicit_mode", [True, False])
def test_complete_visual_click_replace_value_and_enter_have_zero_native_or_ocr_calls(visual_sequence, explicit_mode):
    from app.core.input_controller import VK_CONTROL, VK_A, VK_V, VK_RETURN
    v = visual_sequence
    if not explicit_mode:
        v.scene.context.pop("native_field_evidence")
    result = v.run()
    assert result["status"] == "completed", result.get("error")
    assert result["completed_steps"] == ["focus_type", "check_input", "search"]
    assert [call["operation"] for call in v.calls] == ["execute_recognition_plan", "execute_recognition_plan"]
    assert v.events.count((VK_CONTROL, VK_A)) == v.events.count((VK_CONTROL, VK_V)) == v.events.count((VK_RETURN,)) == 1
    assert v.events.count("gate-click") == 2
    assert v.events[-2:] == ["gate-click", (VK_RETURN,)]
    assert (v.events.index("gate-click") < v.events.index((VK_CONTROL, VK_A))
        < v.events.index((VK_CONTROL, VK_V)) < v.events.index((VK_RETURN,)))
    assert len(v.candidate_provider.calls) == 1
    assert [row["stage"] for row in result["field_evaluations"]] == ["after_type"]
    assert len(v.scene.requests) == 2 and v.captures == []
    assert "visual_click_evidence" not in result
    assert result["input_check"] == {"status": "verified", "source": "decision_visual", "evidence_kind": "visual"}
    reference = result["field_proofs"][-1]
    assert reference["value_verification"] == "visual" and reference["source"] == "decision_visual"
    assert reference["reading"] is None and reference["value_sha256"] is None
    assert v.forbidden_calls == []


def current_stage(v):
    from app.core.input_controller import VK_CONTROL, VK_V
    # 按实际已派发事件注入故障，不依赖远端提示词携带阶段标签。
    return "value" if (VK_CONTROL, VK_V) in v.events else "click"


@pytest.mark.parametrize("probability", [.5, .01])
def test_visual_decision_uncertainty_or_wrong_value_blocks_enter(visual_sequence, probability):
    from app.core.input_controller import VK_CONTROL, VK_A, VK_V, VK_RETURN
    v = visual_sequence

    def reject_stage():
        assert current_stage(v) == "value"
        v.scene.probabilities[0] = probability

    v.scene.during.append(reject_stage)
    result = v.run()
    assert result["status"] == "interrupted"
    assert result["automatic_retry_allowed"] is False and (VK_RETURN,) not in v.events
    assert v.events.count((VK_CONTROL, VK_V)) == v.events.count((VK_CONTROL, VK_A)) == 1
    assert len(v.scene.requests) == 1
    assert v.forbidden_calls == []


@pytest.mark.parametrize("stop", ["cancel", "expired"])
def test_cancel_or_deadline_after_value_decision_never_dispatches_enter(visual_sequence, monkeypatch, stop):
    from app.core.input_controller import VK_CONTROL, VK_V, VK_RETURN
    v = visual_sequence
    cancelled = [False]
    v.scene.context["cancelled"] = lambda: cancelled[0]

    def interrupt():
        assert current_stage(v) == "value"
        if stop == "cancel":
            cancelled[0] = True
        else:
            monkeypatch.setattr(v.scene.module, "perf_counter_ns", lambda: v.scene.context["deadline_ns"] + 1)

    v.scene.during.append(interrupt)
    result = v.run()
    assert result["status"] == "interrupted" and (VK_RETURN,) not in v.events
    assert v.events.count((VK_CONTROL, VK_V)) == 1
    assert len(v.scene.requests) == 1
    assert v.forbidden_calls == []


@pytest.mark.parametrize("stop", ["cancel", "expired"])
def test_cancel_or_deadline_after_select_all_never_pastes_or_submits(visual_sequence, monkeypatch, stop):
    from app.core import input_controller as native
    v = visual_sequence
    cancelled = [False]
    v.scene.context["cancelled"] = lambda: cancelled[0]

    def press_chord(keys):
        v.events.append(tuple(keys))
        if tuple(keys) == (native.VK_CONTROL, native.VK_A):
            if stop == "cancel":
                cancelled[0] = True
            else:
                monkeypatch.setattr(v.scene.module, "perf_counter_ns", lambda: v.scene.context["deadline_ns"] + 1)
                from app.core import visual_compound_input
                monkeypatch.setattr(visual_compound_input, "perf_counter_ns", lambda: v.scene.context["deadline_ns"] + 1)

    monkeypatch.setattr(v.controller, "_press_chord", press_chord)
    result = v.run()
    assert result["status"] == "interrupted" and result["completed_steps"] == []
    assert v.events.count((native.VK_CONTROL, native.VK_A)) == 1
    assert (native.VK_CONTROL, native.VK_V) not in v.events and (native.VK_RETURN,) not in v.events
    assert len(v.scene.requests) == 0 and v.captures == []
    assert v.events[-1] == "clipboard-restored" and v.forbidden_calls == []
    dispatch = result["steps"][-1]["receipt"]["response"]["data"]["typing_dispatch"]
    assert dispatch["selection_dispatch"] == "completed"
    assert dispatch["text_dispatch"] == dispatch["submit_dispatch"] == "not_started"


def test_real_keyboard_foreground_drift_blocks_select_paste_and_enter(visual_sequence, monkeypatch):
    from app.core import input_controller as native
    v = visual_sequence
    v.before_dispatch.append(lambda operation: monkeypatch.setattr(native.win32gui, "GetForegroundWindow", lambda: 11))
    result = v.run()
    assert result["status"] == "interrupted"
    assert all(not isinstance(event, tuple) for event in v.events)
    assert len(v.scene.requests) == 0 and v.forbidden_calls == []


@pytest.mark.parametrize("service_state", ["disabled", "missing"])
def test_disabled_or_missing_decision_never_blindly_types_or_submits(visual_sequence, service_state):
    v = visual_sequence
    v.scene.context["service"] = (type(v.scene.service)(v.scene.root,
        profile=v.scene.service.profile.model_copy(update={"mode": "off"}))
        if service_state == "disabled" else None)
    result = v.run()
    assert result["status"] == "interrupted" and result["completed_steps"] == []
    assert [row["operation"] for row in v.calls] == ["execute_recognition_plan"]
    assert v.events == v.scene.requests == []
    assert v.forbidden_calls == []


@pytest.mark.parametrize("mode", [None, 0, 1, "false"])
def test_invalid_internal_native_evidence_mode_is_not_a_route_switch(visual_sequence, mode):
    v = visual_sequence
    v.scene.context["native_field_evidence"] = mode
    with pytest.raises(ValueError, match="native_evidence_mode_invalid"):
        v.run()
    assert v.calls == [] and v.forbidden_calls == []


@pytest.mark.parametrize("fault", ["not_typed", "wrong_text", "identity", "old_frame"])
def test_visual_value_still_requires_real_completed_input_and_new_bound_image(scene, fault):
    s = scene
    s.context["native_field_evidence"] = False
    if fault == "not_typed":
        s.typed["response"]["data"]["typed"] = False
    elif fault == "wrong_text":
        s.typed["request"]["text"] = "different"
    elif fault == "identity":
        s.typed["target_identity"]["process_id"] += 1
    else:
        s.typed["observation"]["capture"] = deepcopy(s.focus["observation"]["capture"])
    with pytest.raises(ValueError):
        assess(s, phase="value")
    assert s.requests == []


def test_visual_value_proof_does_not_invent_a_read_of_expected_text(scene):
    s = scene
    s.context["native_field_evidence"] = False
    proof = assess(s, phase="value")
    action = proof.request()["action"]
    assert action["value_verification"] == "visual" and action["expected_text"] == TEXT
    assert action["actual_text"] is None and action["value_reading"] is None
    expected_digest = sha256(s.module._json(s.typed).encode("utf-8")).hexdigest()
    assert action["input_receipt_sha256"] == expected_digest
    assert proof.to_reference()["value_sha256"] is None
