"""判断接口复用真实动作路由；外部服务和桌面输入均用边界替身。"""
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

from PIL import Image, ImageDraw
import pytest

from tests.test_agent_grounding_target import scene
from tests.test_local_step_timings import timed_scene
from app.execution.local_direct_step import _post_action as REAL_POST_ACTION


class Decisions:
    enabled = True

    def __init__(self, *, mode="auto", verdict="success", condition="Search is safe", during=None):
        self.profile = SimpleNamespace(mode=mode, auto_conditions=[condition])
        self.adoption_mode = mode
        self.verdict = verdict
        self.during = during
        self.calls = []

    def auto_condition_allowed(self, condition):
        return self.adoption_mode == "auto" and condition in self.profile.auto_conditions

    def readiness(self):
        return {"ready": True, "status": "ready"}

    def validate_result(self, result, **request):
        return result.get("request_id") == request["request_id"]

    def evaluate(self, **request):
        self.calls.append(deepcopy(request))
        if self.during:
            self.during()
        return {"status": "completed", "verdict": self.verdict, "phase": request["phase"],
            "request_id": request["request_id"], "execution_request_id": request["execution_request_id"],
            "condition": request["condition"], "adopted": self.profile.mode == "auto" and self.verdict != "uncertain",
            "authorizes_action": False, "automatic_retry_allowed": False,
            "evidence_hashes": [row["sha256"] for row in request["frames"]]}


def run_route(scene, monkeypatch, service, *, condition="Search is safe", repeat=1, hosted=True, coordinator=None):
    from app.api import action
    from app.api.models.request import ExecuteRecognitionPlanRequest
    from app.core.agent_grounding_target import AgentGroundingTarget, agent_grounding_scope
    from app.core.local_input_policy import _local_operator_input_scope
    from app.execution.decision_check import execution_decision_scope
    from app.execution.local_action_contract import _validated_request

    state, _, im, root = scene
    current = root / "current.png"
    im.save(current)
    identity = {"contract_version": "windows_native_identity_observation_v1",
        "provider": "windows_native_identity", "status": "observed", "target_window_handle": 10,
        "process_id": 20, "process_create_time": 30.0, "executable_path": "c:\\fixture\\editor.exe"}
    bound = SimpleNamespace(handle=10, process_id=20, title="Fixture", process_name="editor.exe",
        rect=SimpleNamespace(left=100, top=200, right=300, bottom=350))
    manager = SimpleNamespace(get_bound_window=lambda: bound)
    service.runtime_scene = (current, identity, bound)
    monkeypatch.setattr(action, "window_manager", manager)
    captures = []

    def capture(**kwargs):
        captures.append(kwargs)
        return {"image_path": str(current), "window_size": {"width": 200, "height": 150}, "roi": None}

    monkeypatch.setattr(action.screenshot_service, "capture_window", capture)
    monkeypatch.setattr(action, "prepare_browser_content", lambda *args: None)
    monkeypatch.setattr(action, "_render_recognition_plan_overlay_for_execution", lambda p: None)
    monkeypatch.setattr(action, "write_trace", lambda **kwargs: str(root / "trace.json"))
    monkeypatch.setattr(action, "_rewrite_execute_trace_result", lambda **kwargs: None)
    clicks = []
    monkeypatch.setattr(action.input_controller, "click_point", lambda x, y, **kwargs:
        clicks.append((x, y)) or {"clicked": True, "point": {"x": x, "y": y}})
    target = AgentGroundingTarget(state)
    check = {"condition": condition, "phase": "before_action"}
    request = ExecuteRecognitionPlanRequest.model_validate(_validated_request("execute_recognition_plan", {
        "goal": "Search", "enable_post_click_verification": False, "metadata": {"decision_check": check}}))
    reader = SimpleNamespace(read_identity=lambda handle: deepcopy(identity))
    if coordinator is not None:
        from app.execution import local_direct_step as direct
        manager.bind_window_by_handle = lambda handle: bound
        coordinator._windows = lambda: manager
        coordinator._decision_service = service
        monkeypatch.setattr(direct, "WindowsNativeIdentityReader", lambda **kwargs: reader)
        monkeypatch.setattr(direct, "_local_operator_input_scope", _local_operator_input_scope)
        monkeypatch.setattr(direct, "_post_action", REAL_POST_ACTION)
        receipt = coordinator.execute_local_step(target_window_handle=10, target_process_id=20,
            operation="execute_recognition_plan", request=request.model_dump(), grounding_target=target,
            decision_check=check, execution_request_id="exec-1")
        return receipt, clicks, captures, target, current, identity, bound
    with execution_decision_scope(service, decision_check=check if hosted else None, request_id="judgment-1",
            execution_request_id="exec-1", step_id="step-1"), agent_grounding_scope(target), \
            _local_operator_input_scope(manager=manager, identity_reader=reader, identity=identity,
                window_rect=(100, 200, 300, 350), enabled=lambda: True):
        for _ in range(repeat):
            receipt = action.execute_recognition_plan(request)
    return receipt, clicks, captures, target, current, identity, bound


def test_explicit_before_declaration_without_host_scope_fails_closed(scene, monkeypatch):
    service = Decisions()
    receipt, clicks, captures, target, _, _, _ = run_route(scene, monkeypatch, service, hosted=False)
    assert not receipt.success and clicks == [] and target.input_claimed is False
    assert receipt.error.code == "decision_check_host_scope_required"
    assert receipt.data["decision_judgment"]["status"] == "not_applied"
    assert captures == [] and service.calls == []


def test_before_success_uses_current_candidate_and_preserves_coordinates(scene, monkeypatch):
    service = Decisions()
    receipt, clicks, captures, target, _, _, _ = run_route(scene, monkeypatch, service)
    assert receipt.success, receipt
    assert clicks == [(65, 55)] and target.input_claimed is True
    assert len(service.calls) == 1
    sent = service.calls[0]
    assert sent["execution_request_id"] == "exec-1"
    assert sent["phase"] == "before_action" and sent["condition"] == "Search is safe"
    assert sent["frames"][0]["window_identity"] == {"handle": 10, "process_id": 20, "process_create_time": 30.0}
    assert sent["action"]["goal"] == "Search"
    assert sent["action"]["candidate"]["click_point"] == {"x": 65, "y": 55}
    assert sent["action"]["candidate"]["bbox"] == {"x": 30, "y": 40, "w": 71, "h": 31}
    assert receipt.data["result"]["decision_judgment"]["authorizes_action"] is False
    assert any(row["purpose"] == "decision-after-wait-revalidation" for row in captures)


@pytest.mark.parametrize("verdict", ["failure", "uncertain"])
def test_explicit_auto_before_gate_never_dispatches_rejected_or_uncertain(scene, monkeypatch, verdict):
    receipt, clicks, _, target, _, _, _ = run_route(scene, monkeypatch, Decisions(verdict=verdict))
    assert not receipt.success and clicks == [] and target.input_claimed is False
    assert receipt.error.code == "decision_check_rejected"
    assert receipt.data["dispatch_status"] == "not_dispatched"
    assert receipt.data["execution_path"]["action_executed"] is False
    assert receipt.data["decision_judgment"]["verdict"] == verdict


@pytest.mark.parametrize("mode,condition", [("shadow", "Search is safe"), ("auto", "Other condition")])
def test_shadow_or_unapproved_condition_keeps_existing_admission(scene, monkeypatch, mode, condition):
    service = Decisions(mode=mode, verdict="failure")
    receipt, clicks, _, _, _, _, _ = run_route(scene, monkeypatch, service, condition=condition)
    assert receipt.success and clicks == [(65, 55)]
    assert receipt.data["result"]["decision_judgment"]["gate_applied"] is False


@pytest.mark.parametrize("mode", ["auto", "shadow"])
def test_frame_changed_while_waiting_is_rejected_before_input(scene, monkeypatch, mode):
    def change():
        ImageDraw.Draw(scene[2]).rectangle((150, 100, 199, 149), fill="red")
        scene[2].save(scene[3] / "current.png")

    receipt, clicks, _, target, _, _, _ = run_route(scene, monkeypatch,
        Decisions(mode=mode, during=change))
    assert not receipt.success and clicks == [] and target.input_claimed is False
    assert receipt.error.code == "decision_check_stale_after_wait"
    assert receipt.data["decision_judgment"]["adopted"] is False


def test_disabled_service_does_not_add_capture_or_evaluate(scene, monkeypatch):
    service = Decisions()
    service.enabled = False
    receipt, clicks, captures, _, _, _, _ = run_route(scene, monkeypatch, service)
    assert receipt.success and clicks == [(65, 55)] and service.calls == []
    assert not any(row["purpose"].startswith("decision-") for row in captures)


@pytest.mark.parametrize("mode,want_clicks", [("auto", []), ("shadow", [(65, 55)])])
def test_not_connected_has_no_added_capture_or_network_and_reports_gate(scene, monkeypatch, mode, want_clicks):
    service = Decisions(mode=mode)
    service.readiness = lambda: {"ready": False, "status": "not_connected"}
    receipt, clicks, captures, _, _, _, _ = run_route(scene, monkeypatch, service)
    actual = receipt.data.get("result", receipt.data)
    assert clicks == want_clicks and receipt.success is bool(want_clicks)
    assert actual["decision_judgment"]["status"] == "not_connected"
    assert service.calls == []
    assert not any(row["purpose"].startswith("decision-") for row in captures)


def test_untrusted_adopted_service_result_cannot_allow_input(scene, monkeypatch):
    service = Decisions()
    service.validate_result = lambda result, **request: False
    receipt, clicks, _, target, _, _, _ = run_route(scene, monkeypatch, service)
    assert not receipt.success and clicks == [] and target.input_claimed is False
    assert receipt.data["decision_judgment"]["adopted"] is False
    assert receipt.data["decision_judgment"]["reason"] == "decision_result_authentication_invalid"


@pytest.mark.parametrize("changed", ["pid", "birth", "geometry", "target"])
def test_window_or_candidate_change_during_wait_never_dispatches(scene, monkeypatch, changed):
    service = Decisions()

    def change():
        current, identity, bound = service.runtime_scene
        if changed == "pid":
            identity["process_id"] += 1
        elif changed == "birth":
            identity["process_create_time"] += 1
        elif changed == "geometry":
            bound.rect.right += 1
        else:
            ImageDraw.Draw(scene[2]).rectangle((30, 40, 100, 70), fill="red")
            scene[2].save(current)

    service.during = change
    receipt, clicks, _, target, _, _, _ = run_route(scene, monkeypatch, service)
    assert not receipt.success and clicks == [] and target.input_claimed is False
    assert receipt.error.code == "decision_check_stale_after_wait"


@pytest.mark.parametrize("mode,want_clicks", [("auto", []), ("shadow", [(65, 55)])])
def test_provider_timeout_preserves_explicit_gate_and_shadow_semantics(scene, monkeypatch, mode, want_clicks):
    def timeout():
        raise TimeoutError("private token must not leak")

    receipt, clicks, _, _, _, _, _ = run_route(scene, monkeypatch, Decisions(mode=mode, during=timeout))
    assert clicks == want_clicks and receipt.success is bool(want_clicks)
    actual = receipt.data.get("result", receipt.data)
    assert actual["decision_judgment"]["error_type"] == "TimeoutError"
    assert "private token" not in str(actual)


def test_completed_candidate_cannot_be_claimed_twice_even_if_judgment_passes(scene, monkeypatch):
    receipt, clicks, _, target, _, _, _ = run_route(scene, monkeypatch, Decisions(), repeat=2)
    assert not receipt.success and clicks == [(65, 55)] and target.input_claimed is True
    assert "already_claimed" in str(receipt.error)


@pytest.mark.parametrize("label,blocked", [("Submit application", True), ("Submit search", False)])
def test_explicit_decision_keeps_existing_final_submit_taxonomy_and_search_scope(scene, monkeypatch, label, blocked):
    scene[0]["result"]["candidates"][0]["label"] = label
    service = Decisions()
    receipt, clicks, _, target, _, _, _ = run_route(scene, monkeypatch, service)
    actual = receipt.data.get("result", receipt.data)
    if blocked:
        assert not receipt.success and clicks == [] and target.input_claimed is False
        assert receipt.error.code == "decision_check_unsafe_target"
        assert actual["final_submit_guard"]["action_taxonomy"] == "final_submit"
        assert service.calls == []
    else:
        assert receipt.success and clicks == [(65, 55)]
        assert actual["final_submit_guard"]["action_taxonomy"] != "final_submit"
        assert actual["final_submit_guard"]["scoped_decision"]["blocked"] is False


def test_post_check_reuses_original_after_capture_and_preserves_input_status(tmp_path):
    from app.execution.decision_check import evaluate_post_action
    image = tmp_path / "after.png"
    Image.new("RGB", (100, 80), "white").save(image)
    frame = {"capture_id": "after-1", "image_path": str(image), "sha256": sha256(image.read_bytes()).hexdigest()}
    receipt = {"phase": "returned", "effect_verified": False,
        "target_identity": {"target_window_handle": 10, "process_id": 20, "process_create_time": 30.0},
        "observation": {"status": "captured", "capture": frame},
        "response": {"success": True, "data": {"result": {"execution_path": {"action_executed": True}}}}}
    before = deepcopy(receipt)
    service = Decisions(condition="Results are visible")
    result = evaluate_post_action(service, request_id="post-1", execution_request_id="exec-1",
        decision_check={"condition": "Results are visible", "phase": "after_action"}, receipt=receipt)
    assert receipt == before
    assert result["effect_verified"] is True and result["input_status"] == "returned"
    assert result["automatic_retry_allowed"] is False and result["authorizes_action"] is False
    assert service.calls[0]["frames"] == [{**frame,
        "window_identity": {"handle": 10, "process_id": 20, "process_create_time": 30.0}, "role": "after"}]


def test_coordinator_after_check_runs_on_its_existing_observation(timed_scene):
    co, state, _, _ = timed_scene
    service = Decisions(condition="Results are visible")
    co._decision_service = service
    report = co.execute_local_step(target_window_handle=321, target_process_id=12,
        operation="execute_recognition_plan", request={"goal": "Search",
            "metadata": {"decision_check": {"condition": "Results are visible", "phase": "after_action"}}},
        include_observation=True, execution_request_id="exec-1")
    assert state.events.count("route") == 1 and state.events.count("capture") == 2
    assert report["phase"] == "returned" and report["response"]["success"] is True
    assert report["decision_judgment"]["effect_verified"] is True
    assert service.calls[0]["frames"][0]["image_path"] == report["observation"]["capture"]["image_path"]


def test_after_provider_failure_keeps_original_returned_input_status(timed_scene):
    co, state, _, _ = timed_scene

    def timeout():
        raise TimeoutError("private token must not leak")

    co._decision_service = Decisions(condition="Results are visible", during=timeout)
    report = co.execute_local_step(target_window_handle=321, target_process_id=12,
        operation="press_key", request={"key": "Enter", "x": 30, "y": 20}, include_observation=True,
        decision_check={"condition": "Results are visible", "phase": "after_action"}, execution_request_id="exec-2")
    assert report["phase"] == "returned" and report["response"]["success"] is True
    assert report["decision_judgment"]["status"] == "error"
    assert report["decision_judgment"]["input_status"] == "returned"
    assert report["effect_verified"] is False and state.events.count("route") == 1


@pytest.mark.parametrize("change", ["pending", "wrong_id", "failed_input", "bad_response", "missing_after", "cross_window", "tamper"])
def test_post_check_refuses_invalid_original_receipt_before_provider(tmp_path, change):
    from app.execution.decision_check import evaluate_post_action
    image = tmp_path / "after.png"
    Image.new("RGB", (100, 80), "white").save(image)
    frame = {"capture_id": "after-1", "image_path": str(image), "sha256": sha256(image.read_bytes()).hexdigest()}
    inner = {"phase": "returned", "target_identity": {"target_window_handle": 10,
        "process_id": 20, "process_create_time": 30.0}, "response": {"success": True},
        "observation": {"status": "captured", "capture": frame}}
    receipt = {"status": "returned", "request_id": "exec-1", "result": inner}
    if change == "pending":
        receipt["status"] = "pending"
    elif change == "wrong_id":
        receipt["request_id"] = "exec-2"
    elif change == "failed_input":
        inner["response"]["success"] = False
    elif change == "bad_response":
        inner["response"] = "invalid"
    elif change == "missing_after":
        inner.pop("observation")
    elif change == "cross_window":
        frame["window_identity"] = {"handle": 99, "process_id": 20, "process_create_time": 30.0}
    else:
        Image.new("RGB", (100, 80), "black").save(image)
    service = Decisions(condition="Results are visible")
    result = evaluate_post_action(service, request_id="post-1", execution_request_id="exec-1",
        decision_check={"condition": "Results are visible", "phase": "after_action"}, receipt=receipt)
    assert result["adopted"] is False and result["effect_verified"] is None
    assert service.calls == [] and result["authorizes_action"] is False


@pytest.mark.parametrize("change", ["hash", "candidate"])
def test_invalid_before_evidence_is_explicit_not_dispatched_without_provider(tmp_path, change):
    from app.execution.decision_check import (DecisionCheckRejected, evaluate_before_action,
        execution_decision_scope)
    image = tmp_path / "before.png"
    Image.new("RGB", (100, 80), "white").save(image)
    capture = {"image_path": str(image), "sha256": sha256(image.read_bytes()).hexdigest()}
    candidate = {"candidate_id": "button", "bbox": {"x": 10, "y": 10, "w": 20, "h": 20},
        "click_point": {"x": 20, "y": 20}, "source": "agent_visual"}
    if change == "hash":
        capture["sha256"] = "0" * 64
    else:
        candidate = None
    service = Decisions()
    with execution_decision_scope(service, decision_check={"condition": "Search is safe", "phase": "before_action"},
            request_id="decision-before-exec-1", execution_request_id="exec-1") as scope:
        with pytest.raises(DecisionCheckRejected) as raised:
            evaluate_before_action(scope, capture=capture, identity={"handle": 10, "process_id": 20,
                "process_create_time": 30.0}, candidate=candidate, point={"x": 20, "y": 20},
                goal="Search", click_kind="single", revalidate=lambda: None)
        assert raised.value.reason_code == "decision_check_invalid_evidence"
        assert scope["result"]["adopted"] is False and service.calls == []


@pytest.mark.parametrize("route", ["missing_id", "conflict", "unsupported_before"])
def test_declaration_binding_rejected_before_model_or_capture(timed_scene, route):
    co, state, _, _ = timed_scene
    check = {"condition": "Search is safe", "phase": "before_action"}
    kwargs = {"target_window_handle": 321, "target_process_id": 12,
        "operation": "execute_recognition_plan", "request": {"goal": "Search"}, "decision_check": check}
    if route != "missing_id":
        kwargs["execution_request_id"] = "exec-1"
    if route == "conflict":
        kwargs["request"]["metadata"] = {"decision_check": {"condition": "Different", "phase": "after_action"}}
    if route == "unsupported_before":
        kwargs.update(operation="press_key", request={"key": "Enter", "x": 30, "y": 20})
    with pytest.raises(ValueError, match="decision_check"):
        co.execute_local_step(**kwargs)
    assert "configuration_load" not in state.events and "capture" not in state.events and "route" not in state.events


def test_real_service_post_wrapper_preserves_authenticated_payload_and_offline_duplicate(tmp_path, monkeypatch):
    from app.execution.decision_check import evaluate_post_action
    from app.judgment import DecisionService
    from test_decision_service import setup_service, frame
    condition = "Results are visible"
    service, calls, client = setup_service(tmp_path, monkeypatch, mode="auto", conditions=[condition])
    after = frame(tmp_path)
    original = {"phase": "returned", "step_id": "step-1", "target_identity": {
        "target_window_handle": 123, "process_id": 456, "process_create_time": 1000.25},
        "response": {"success": True}, "observation": {"status": "captured", "capture": after}}
    kwargs = dict(request_id="decision-after-exec-1", execution_request_id="exec-1",
        decision_check={"condition": condition, "phase": "after_action"}, receipt=original)
    advice = evaluate_post_action(service, **kwargs)
    assert advice["effect_verified"] is True and advice["input_status"] == "returned"
    assert service.validate_result(advice["judgment_result"])
    assert not service.validate_result(advice)
    assert advice["judgment_result"]["mode"] == "execution"
    assert len(calls) == 1
    service.close()
    monkeypatch.delenv("DECISION_TEST_KEY")
    reopened = DecisionService(tmp_path, profile=service.profile)
    duplicate = evaluate_post_action(reopened, **kwargs)
    assert duplicate == advice and len(calls) == 1
    reopened.close()
    client.close()


@pytest.mark.parametrize("probability,want_clicks", [(0.97, [(65, 55)]), (0.01, []), (0.5, [])])
def test_real_service_before_gate_reuses_provider_contract_and_dpapi(scene, monkeypatch, probability, want_clicks):
    from test_decision_service import setup_service
    from test_openai_decisions import reply
    response = reply(probability)
    response["answers"][1]["name"] = "unsafe_effect"
    service, calls, client = setup_service(scene[3], monkeypatch, mode="auto",
        conditions=["Search is safe"], response=response)
    receipt, clicks, _, _, _, _, _ = run_route(scene, monkeypatch, service)
    actual = receipt.data.get("result", receipt.data)
    assert clicks == want_clicks and receipt.success is bool(want_clicks)
    assert service.validate_result(actual["decision_judgment"]["judgment_result"])
    assert actual["decision_judgment"]["judgment_result"]["mode"] == "execution"
    assert len(calls) == 1
    service.close()
    client.close()


def test_coordinator_real_route_and_service_keep_candidate_boundary_scope(scene, timed_scene, monkeypatch):
    from test_decision_service import setup_service
    from test_openai_decisions import reply
    co, _, _, _ = timed_scene
    response = reply()
    response["answers"][1]["name"] = "unsafe_effect"
    service, calls, client = setup_service(scene[3], monkeypatch, mode="auto",
        conditions=["Search is safe"], response=response)
    report, clicks, _, target, _, _, _ = run_route(scene, monkeypatch, service, coordinator=co)
    assert report["phase"] == "returned" and report["response"]["success"] is True
    assert clicks == [(65, 55)] and target.input_claimed is True and len(calls) == 1
    raw = report["decision_judgment"]["judgment_result"]
    assert raw["request_id"] == "decision-before-exec-1" and service.validate_result(raw)
    assert "decision-evidence" in raw["frames"][0]["image_path"]
    assert report["effect_verified"] is False
    service.close()
    client.close()


@pytest.mark.parametrize("check", [True, {}, {"condition": "", "phase": "before_action"},
    {"condition": "safe", "phase": "before"}, {"condition": "safe", "phase": "before_action", "authorize": True}])
def test_invalid_check_rejected_before_capture_or_input(timed_scene, check):
    co, state, _, _ = timed_scene
    with pytest.raises(ValueError, match="decision_check"):
        co.execute_local_step(target_window_handle=321, target_process_id=12,
            operation="execute_recognition_plan", request={"goal": "Search", "metadata": {"decision_check": check}})
    assert "capture" not in state.events and "route" not in state.events
