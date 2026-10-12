"""默认视觉输入一次点击替换，值审核后才允许 Enter。"""
from contextlib import contextmanager
from contextvars import copy_context
from copy import deepcopy
from time import perf_counter_ns, time
from types import SimpleNamespace as NS

import pytest

from app.core import visual_compound_input as compound, local_text_focus as focus
from app.execution import action_review
from app.execution.action_review_dispatch import review_original_action
from app.execution.decision_check import DecisionCheckRejected
from app.core.local_input_policy import _local_operator_input_scope
from app.judgment import DecisionProfile, DecisionService
from tests.test_action_review_contract import Provider
from tests.test_visual_field_proof import (scene, controller_scene, FIELD, TEXT, NATIVE, executed_focus)
from tests.test_visual_input_no_uia import visual_sequence


def test_default_visual_input_has_text_check_then_current_submit_target_review(visual_sequence):
    v = visual_sequence
    result = v.run()
    assert result["status"] == "completed", result.get("error")
    assert [row["name"] for row in result["steps"]] == ["focus_type", "search"]
    assert [row["stage"] for row in result["field_evaluations"]] == ["after_type"]
    assert len(v.scene.requests) == 2
    assert v.events.count("gate-click") == 2


@pytest.fixture
def core(scene, monkeypatch):
    import app.core.input_controller as native
    s = scene
    controller, events, captures = controller_scene(s, monkeypatch)
    manager = native.window_manager
    bound = manager.get_bound_window()
    from app.core.window_manager import WindowRect
    bound.rect = WindowRect(0, 0, 180, 90)
    monkeypatch.setattr(controller, "_focus_window", lambda _: events.append("click-focus"))
    monkeypatch.setattr(controller, "_send_move", lambda *args: events.append("move"))
    monkeypatch.setattr(controller, "_send_mouse_flags", lambda flag: events.append(("mouse", flag)))
    monkeypatch.setattr(native.win32api, "GetCursorPos", lambda: (40, 30))
    monkeypatch.setattr(manager, "get_owned_foreground_popup_handle", lambda _: None)
    monkeypatch.setattr(manager, "validate_bound_point_visibility", lambda **kw: {"allowed": True})
    monkeypatch.setattr(manager, "validate_bound_capture_visibility", lambda **kw: {"allowed": True})
    monkeypatch.setattr(manager, "validate_bound_region_visibility", lambda **kw: {"allowed": True})
    monkeypatch.setattr("app.judgment.service._protect", lambda data, entropy, decrypt=False: data)
    provider = Provider()
    service = DecisionService(s.root, provider=provider,
        profile=DecisionProfile(contract_version="decision_profile.v2", mode="auto",
            auto_conditions=[action_review.CANDIDATE_CONDITION], request_cap=20))
    action = {"kind": "input_sequence", "field_goal": FIELD["field_goal"], "text": TEXT,
        "clear_existing": True, "submit_search": True}
    context = {"schema": "action_review_context.v1", "run_id": "compound-run", "attempt_id": "one",
        "step_id": "input", "budget_ms": 30000, "plan": {"schema_version": "task_plan.v2",
        "title": "Fill search field", "inputs": {}, "steps": [{"step_id": "input", "action": action,
        "verification": {"kind": "agent_judgment"}}]}}
    candidate = {"candidate_id": "field", "source": "external_api", "bbox": deepcopy(FIELD["bbox"]),
        "click_point": deepcopy(FIELD["click_point"])}
    cancelled = [False]
    s.context["cancelled"] = lambda: cancelled[0]

    @contextmanager
    def scope(*, reviewed=True, text=TEXT, field_goal=FIELD["field_goal"]):
        target = focus.VisualTextFocusTarget(10, 20)
        compound.bind_visual_compound_input(target, text=text, context=s.context, field_goal=field_goal)
        with _local_operator_input_scope(manager=manager, identity_reader=NS(read_identity=lambda _: deepcopy(NATIVE)),
                identity=NATIVE, window_rect=[0, 0, 180, 90], enabled=lambda: True), \
                focus.visual_text_focus_scope(target), action_review.action_review_scope(service,
                    context=context if reviewed not in {False, "missing"} else None, deadline_ns=s.context["deadline_ns"]):
            if reviewed not in {"pending", "missing"}:
                focus.check_local_text_focus(FIELD["click_point"], manager)
            review = (review_original_action(capture=s.focus["capture"], identity=NATIVE,
                candidate=candidate, point=FIELD["click_point"], goal=FIELD["field_goal"], click_kind="single",
                manager=manager, validate_binding=lambda: (NATIVE, candidate)) if reviewed is True else None)
            yield target, review

    def dispatch(review, *, prepared=False):
        if not prepared:
            compound.prepare_visual_compound_input(manager, FIELD["click_point"], review)
        click = controller.click_point(**FIELD["click_point"], settle_ms=0, hold_ms=0)
        output = {"click_result": click, "execution_path": {"action_executed": True}}
        compound.perform_visual_compound_input(controller, manager, FIELD["click_point"], click, output=output)
        return output

    yield NS(s=s, controller=controller, manager=manager, events=events, captures=captures, provider=provider,
        scope=scope, dispatch=dispatch, cancelled=cancelled)
    service.close()


def test_real_controller_one_click_then_replace_has_no_middle_focus_capture_or_decision(core):
    from app.core.input_controller import VK_CONTROL, VK_A, VK_V, MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP
    c = core
    with c.scope() as (_, review):
        output = c.dispatch(review)
    assert c.events == ["click-focus", "move", ("mouse", MOUSEEVENTF_LEFTDOWN), ("mouse", MOUSEEVENTF_LEFTUP),
        "clipboard-prepared", "clipboard-verified", (VK_CONTROL, VK_A), "clipboard-verified",
        (VK_CONTROL, VK_V), "clipboard-restored"]
    assert c.captures == [] and len(c.provider.calls) == 1 and c.s.requests == []
    fact = output["visual_compound_input"]
    assert fact["type_result"]["typed"] is True and fact["type_result"]["clipboard_restore_status"] == "restored"
    assert fact["type_result"] == output["type_result"] and fact["typing_dispatch"] == output["typing_dispatch"]
    assert fact["typing_dispatch"]["selection_dispatch"] == fact["typing_dispatch"]["text_dispatch"] == "completed"


@pytest.mark.parametrize("fault", ["missing_review", "text", "field_goal", "point", "assessment"])
def test_compound_requires_current_authenticated_same_candidate_review_before_click(core, fault):
    c = core
    with c.scope(reviewed=fault != "missing_review", text=TEXT + "!" if fault == "text" else TEXT,
            field_goal="Other field" if fault == "field_goal" else FIELD["field_goal"]) as (_, review):
        if fault == "point":
            review["candidate"]["click_point"] = {"x": 41, "y": 30}
        if fault == "assessment":
            review["scope"]["assessment"]["disposition"] = "review"
        with pytest.raises(DecisionCheckRejected):
            c.dispatch(review)
    assert c.events == [] and c.captures == []


@pytest.mark.parametrize("phase", ["selection", "text"])
def test_real_controller_partial_dispatch_is_preserved_and_never_replayed(core, monkeypatch, phase):
    from app.core.input_controller import VK_CONTROL, VK_A, VK_V
    c = core
    def chord(keys):
        c.events.append(tuple(keys))
        if keys[-1] == (VK_A if phase == "selection" else VK_V):
            raise RuntimeError("injected keyboard failure")
    monkeypatch.setattr(c.controller, "_press_chord", chord)
    with c.scope() as (_, review):
        compound.prepare_visual_compound_input(c.manager, FIELD["click_point"], review)
        click = c.controller.click_point(**FIELD["click_point"], settle_ms=0, hold_ms=0)
        output = {"click_result": click}
        with pytest.raises(RuntimeError, match="injected keyboard"):
            compound.perform_visual_compound_input(c.controller, c.manager, FIELD["click_point"], click, output=output)
        fact = output["visual_compound_input"]
        assert fact["typing_dispatch"][phase + "_dispatch"] == "started"
        assert fact["typing_dispatch"]["submit_dispatch"] == "not_started" and "type_result" not in fact
        assert fact["typing_dispatch"]["selection_dispatch"] == ("started" if phase == "selection" else "completed")
        with pytest.raises(ValueError, match="already_consumed"):
            compound.perform_visual_compound_input(c.controller, c.manager, FIELD["click_point"], click)
    assert c.events[-1] == "clipboard-restored"
    assert c.events.count((VK_CONTROL, VK_A)) == 1
    assert c.events.count((VK_CONTROL, VK_V)) == (phase == "text") and c.captures == []


def completed_receipt(c):
    with c.scope() as (_, review):
        output = c.dispatch(review)
    receipt = executed_focus(deepcopy(c.s.focus))
    receipt["action_executed"] = True
    receipt["response"]["data"].update(output)
    return receipt


def test_ordinary_local_receipt_without_optional_action_summary_accepts_real_dispatch(core):
    c = core
    receipt = completed_receipt(c)
    # 首次实机原件没有 selection_intent；普通回执的派发事实在原 API execution_path 内。
    receipt.pop("action_executed")
    receipt["response"]["data"].pop("action_executed")
    validated = compound.validate_visual_compound_receipt(receipt, FIELD,
        execution_request_id=c.s.context["execution_request_id"])
    assert validated["type_result"]["typed"] is True
    context = {**c.s.context, "native_field_evidence": False}
    proof = c.s.module.assess_visual_field(phase="value", focus_receipt=receipt, input_receipt=receipt,
        frame=receipt["observation"]["capture"], expected_field=deepcopy(FIELD), context=context)
    assert proof.request()["action"]["focus_receipt_sha256"] == proof.request()["action"]["input_receipt_sha256"]


@pytest.mark.parametrize("place", ["receipt", "execution_path"])
@pytest.mark.parametrize("value", [False, None])
def test_unknown_or_conflicting_action_fact_is_not_completed_compound(core, place, value):
    c = core
    receipt = completed_receipt(c)
    container = receipt if place == "receipt" else receipt["response"]["data"]["execution_path"]
    container["action_executed"] = value
    with pytest.raises(ValueError):
        compound.validate_visual_compound_receipt(receipt, FIELD,
            execution_request_id=c.s.context["execution_request_id"])


@pytest.mark.parametrize("missing", ["execution_path", "action_executed"])
def test_missing_original_api_dispatch_fact_is_not_completed_compound(core, missing):
    c = core
    receipt = completed_receipt(c)
    data = receipt["response"]["data"]
    if missing == "execution_path": data.pop("execution_path")
    else: data["execution_path"].pop("action_executed")
    with pytest.raises(ValueError):
        compound.validate_visual_compound_receipt(receipt, FIELD,
            execution_request_id=c.s.context["execution_request_id"])


@pytest.mark.parametrize("fault", ["open_scope", "contract", "action_unknown", "typed", "text", "identity", "point",
    "click", "dispatch_started", "execution", "submit", "events"])
def test_value_proof_rejects_incomplete_or_rebound_compound_before_decision(core, fault):
    c = core
    receipt = completed_receipt(c)
    fact = receipt["response"]["data"]["visual_compound_input"]
    if fault == "open_scope": receipt["local_input_scope_closed"] = False
    if fault == "contract": receipt["contract_version"] = "forged"
    if fault == "action_unknown": receipt["action_executed"] = None
    if fault == "typed": fact["type_result"]["typed"] = False
    if fault == "text": fact["text_sha256"] = "0" * 64
    if fault == "identity": fact["window_identity"]["process_create_time"] += 1
    if fault == "point": fact["point"]["x"] += 1
    if fault == "click": receipt["response"]["data"]["click_result"]["clicked"] = False
    if fault == "dispatch_started": fact["typing_dispatch"]["text_dispatch"] = "started"
    if fault == "execution": fact["execution_request_id"] = "different-command"
    if fault == "submit": fact["type_result"]["submit"] = True
    if fault == "events": fact["typing_dispatch"]["events"] = []
    with pytest.raises(ValueError):
        compound.validate_visual_compound_receipt(receipt, FIELD, execution_request_id=c.s.context["execution_request_id"])
    assert c.s.requests == []


def test_compound_value_proof_uses_original_step_new_after_frame_and_only_text_question(core):
    c = core
    receipt = completed_receipt(c)
    context = {**c.s.context, "native_field_evidence": False}
    proof = c.s.module.assess_visual_field(phase="value", focus_receipt=receipt, input_receipt=receipt,
        frame=receipt["observation"]["capture"], expected_field=deepcopy(FIELD), context=context)
    request = proof.request()
    assert request["condition"] == c.s.module.VISUAL_TEXT_VALUE_CONDITION
    assert request["action"]["focus_receipt_sha256"] == request["action"]["input_receipt_sha256"]
    assert len(c.s.requests) == 1
    with pytest.raises(ValueError, match="new_after_frame"):
        c.s.module.assess_visual_field(phase="value", focus_receipt=receipt, input_receipt=receipt,
            frame=receipt["capture"], expected_field=deepcopy(FIELD), context=context)


def test_compound_scope_is_one_use_and_copied_closed_context_cannot_type(core):
    c = core
    with c.scope() as (_, review):
        output = c.dispatch(review)
        copied = copy_context()
        with pytest.raises(ValueError, match="already_consumed"):
            compound.perform_visual_compound_input(c.controller, c.manager, FIELD["click_point"], output["click_result"])
    before = list(c.events)
    with pytest.raises(ValueError, match="scope_unavailable"):
        copied.run(compound.perform_visual_compound_input, c.controller, c.manager, FIELD["click_point"], output["click_result"])
    assert c.events == before


@pytest.mark.parametrize("stop", ["cancel", "expire"])
def test_stop_after_click_preserves_click_without_selection_or_paste(core, stop):
    c = core
    with c.scope() as (target, review):
        compound.prepare_visual_compound_input(c.manager, FIELD["click_point"], review)
        click = c.controller.click_point(**FIELD["click_point"], settle_ms=0, hold_ms=0)
        if stop == "cancel": c.cancelled[0] = True
        else: target._compound_spec["deadline_ns"] = perf_counter_ns() - 1
        output = {"click_result": click}
        with pytest.raises(ValueError, match="visual_field_"):
            compound.perform_visual_compound_input(c.controller, c.manager, FIELD["click_point"], click, output=output)
    assert output["click_result"]["clicked"] is True
    assert output["visual_compound_input"]["typing_dispatch"]["input_started"] is False
    assert "clipboard-prepared" not in c.events and c.captures == []


def test_keyboard_entry_failure_without_dispatch_receipt_remains_unknown(core, monkeypatch):
    c = core
    def unknown(*args, **kwargs):
        raise RuntimeError("unknown backend outcome")
    monkeypatch.setattr(c.controller, "type_text", unknown)
    with c.scope() as (_, review):
        compound.prepare_visual_compound_input(c.manager, FIELD["click_point"], review)
        click = c.controller.click_point(**FIELD["click_point"], settle_ms=0, hold_ms=0)
        output = {"click_result": click}
        with pytest.raises(RuntimeError, match="unknown backend"):
            compound.perform_visual_compound_input(c.controller, c.manager, FIELD["click_point"], click, output=output)
    assert output["click_result"]["clicked"] is True
    assert output["visual_compound_input"]["typing_dispatch"] is None
    assert output["typing_dispatch"] is None and "type_result" not in output


@pytest.mark.parametrize("fault", [None, "selection", "text", "missing_review"])
def test_gated_recognition_api_runs_compound_inside_original_click_dispatch(core, monkeypatch, fault):
    from app.api import action
    from app.api.models.request import ExecuteRecognitionPlanRequest
    from app.core.agent_grounding_target import AgentGroundingTarget, agent_grounding_scope
    from app.core.input_controller import VK_A, VK_V, VK_CONTROL
    from app.core.recognition_dispatch import recognition_plan_rejected_before_dispatch
    c = core
    capture = c.s.focus["capture"]
    state = {"request_id": "current-field", "phase": "executing", "goal": FIELD["field_goal"],
        "expires_at": time() + 180, "configuration": {"source": "agent_current"}, "capture": deepcopy(capture),
        "result": {"schema_version": "grounding.v1", "request_id": "current-field", "capture_id": capture["capture_id"],
            "coordinate_space": "capture_image_pixels", "image_size": {"width": 180, "height": 90},
            "status": "found", "selected_candidate_id": "field", "candidates": [{"id": "field", "label": "Search field",
                "bbox": {"x": 10, "y": 10, "width": 140, "height": 40}, "click_point": FIELD["click_point"],
                "evidence_source": "agent_visual"}]}}
    monkeypatch.setattr(action, "window_manager", c.manager)
    monkeypatch.setattr(action, "input_controller", c.controller)
    monkeypatch.setattr(action.screenshot_service, "capture_window", lambda **kw: {
        "image_path": capture["image_path"], "window_size": {"width": 180, "height": 90}, "roi": None})
    monkeypatch.setattr(action, "prepare_browser_content", lambda *a: None)
    monkeypatch.setattr(action, "_render_recognition_plan_overlay_for_execution", lambda *a: None)
    monkeypatch.setattr(action, "write_trace", lambda **kw: str(c.s.root / "offline-trace.json"))
    monkeypatch.setattr(action, "_rewrite_execute_trace_result", lambda **kw: None)
    def chord(keys):
        c.events.append(tuple(keys))
        if fault in {"selection", "text"} and keys[-1] == (VK_A if fault == "selection" else VK_V):
            raise RuntimeError("injected keyboard failure")
    monkeypatch.setattr(c.controller, "_press_chord", chord)
    with c.scope(reviewed="missing" if fault == "missing_review" else "pending"), \
            agent_grounding_scope(AgentGroundingTarget(state)):
        response = action.execute_recognition_plan(ExecuteRecognitionPlanRequest(goal=FIELD["field_goal"],
            enable_post_click_verification=False, max_attempts=1))
    data = response.data.get("result", response.data)
    assert response.success is (fault is None), response
    if fault == "missing_review":
        assert c.events == [] and recognition_plan_rejected_before_dispatch(response.model_dump(mode="json"))
        return
    assert data["click_result"]["clicked"] is True and data["execution_path"]["action_executed"] is True
    fact = data["visual_compound_input"]
    assert fact["typing_dispatch"]["selection_dispatch"] == ("started" if fault == "selection" else "completed")
    assert fact["typing_dispatch"]["text_dispatch"] == ("not_started" if fault == "selection" else "started" if fault == "text" else "completed")
    assert c.events.count((VK_CONTROL, VK_A)) == 1 and c.events.count((VK_CONTROL, VK_V)) == (fault != "selection")
    assert c.captures == [] and len(c.provider.calls) == 1
