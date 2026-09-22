"""内部控件约束的输入前负控；真实识别路由仅替换模型和输入设备边界。"""
from contextvars import copy_context
from copy import deepcopy
from threading import Thread
from types import SimpleNamespace

import pytest

from tests.test_form_fill import control, option, ReadError


def api():
    from app.core import local_control_target
    return local_control_target


def test_control_binding_copies_evidence_and_verifies_fresh_state():
    before = control()
    current = deepcopy(before)
    guard = api().LocalControlTarget(lambda: deepcopy(current), before)
    before["runtime_id"][0] = 999
    checked = guard({"x": 10, "y": 20})
    assert checked["status"] == "matched" and checked["runtime_id"] == [1, 3]
    assert checked["action_executed"] is False
    assert checked["point"] == {"x": 10, "y": 20}


@pytest.mark.parametrize("changes,reason", [
    ({"runtime_id": [9]}, "runtime_id_changed"),
    ({"window_identity": {"process_id": 8}}, "window_identity_changed"),
    ({"window_rect": [1, 2, 800, 600]}, "window_rect_changed"),
    ({"bbox": {"x": 10, "y": 10, "w": 20, "h": 20}}, "bbox_changed"),
    ({"checked": True}, "state_changed"),
    ({"checked": None}, "state_unavailable"),
    ({"state_available": False}, "state_unavailable"),
])
def test_unknown_changed_control_rejects_before_dispatch(changes, reason):
    before = control()
    guard = api().LocalControlTarget(lambda: {**before, **changes}, before)
    with pytest.raises(api().LocalControlTargetError, match=reason):
        guard({"x": 10, "y": 20})


@pytest.mark.parametrize("point", [{"x": 0, "y": 0}, {"x": 10.0, "y": 20}, {"x": 10},
    {"x": 21, "y": 20}, {"x": 10, "y": 22}])
def test_control_point_must_be_integer_inside_current_box(point):
    before = control()
    guard = api().LocalControlTarget(lambda: before, before)
    with pytest.raises(api().LocalControlTargetError, match="point"):
        guard(point)


@pytest.mark.parametrize("options,reason", [
    ([], "option_not_visible"), ([option(), option()], "option_ambiguous"),
    ([{**option(), "runtime_id": [9]}], "option_runtime_id_changed"),
    ([{**option(), "bbox": {"x": 1, "y": 40, "w": 80, "h": 20}}], "option_bbox_changed"),
])
def test_option_remains_uniquely_owned_same_runtime_and_geometry(options, reason):
    before = control(kind="dropdown", label="Country", value="AU", options=[option()])
    guard = api().LocalControlTarget(lambda: {**before, "options": options}, before, expected_option=option())
    with pytest.raises(api().LocalControlTargetError, match=reason):
        guard({"x": 10, "y": 35})


def test_option_point_and_returned_receipt_use_same_scope():
    before = control(kind="dropdown", label="Country", value="AU", options=[option()])
    guard = api().LocalControlTarget(lambda: before, before, expected_option=option())
    assert guard({"x": 10, "y": 35})["option_runtime_id"] == [1, 3, 4]
    guard.verify_receipt({"x": 10, "y": 35}, "capture_image_pixels")
    with pytest.raises(api().LocalControlTargetError, match="point"):
        guard.verify_receipt({"x": 700, "y": 500}, "capture_image_pixels")
    with pytest.raises(api().LocalControlTargetError, match="coordinate_space"):
        guard.verify_receipt({"x": 10, "y": 35}, "desktop_pixels")


@pytest.mark.parametrize("expanded,reason", [(True, "expansion_changed"), (None, "expansion_unavailable")])
def test_dropdown_expansion_is_rechecked_before_model_click(expanded, reason):
    before = control(kind="dropdown", label="Country", value="AU", expanded=False)
    guard = api().LocalControlTarget(lambda: {**before, "expanded": expanded}, before)
    with pytest.raises(api().LocalControlTargetError, match=reason):
        guard({"x": 10, "y": 20})


def test_dropdown_binding_evidence_records_fresh_expansion_state():
    before = control(kind="dropdown", label="Country", value="AU", expanded=False)
    guard = api().LocalControlTarget(lambda: before, before)
    assert guard({"x": 10, "y": 20})["expanded"] is False


def test_reader_error_keeps_stable_reason_only():
    def read():
        raise ReadError("form_control_window_mismatch")
    guard = api().LocalControlTarget(read, control())
    with pytest.raises(api().LocalControlTargetError) as failure:
        guard({"x": 10, "y": 20})
    assert failure.value.reason_code == "form_control_window_mismatch"


def test_scope_is_revoked_after_failure_and_copied_context_cannot_reuse():
    guard = api().LocalControlTarget(lambda: control(), control())
    with pytest.raises(RuntimeError, match="test interruption"):
        with api().local_control_target_scope(guard):
            saved = copy_context()
            assert api().check_local_control_target({"x": 10, "y": 20})["status"] == "matched"
            raise RuntimeError("test interruption")
    assert api().check_local_control_target({"x": 999, "y": 999}) is None
    with pytest.raises(api().LocalControlTargetError, match="scope_expired"):
        saved.run(api().check_local_control_target, {"x": 10, "y": 20})


def test_scope_rejects_wrong_thread_and_nested_scope():
    guard = api().LocalControlTarget(lambda: control(), control())
    errors = []
    with api().local_control_target_scope(guard):
        with pytest.raises(api().LocalControlTargetError, match="scope_overlap"):
            with api().local_control_target_scope(None):
                pass
        saved = copy_context()
        def invoke():
            try:
                saved.run(api().check_local_control_target, {"x": 10, "y": 20})
            except Exception as error:
                errors.append(error)
        worker = Thread(target=invoke)
        worker.start()
        worker.join()
    assert len(errors) == 1 and errors[0].reason_code == "local_control_target_wrong_owner"


@pytest.mark.parametrize("defect", [None, "outside", "identity", "option_identity", "unknown", "reader_failure",
    "expanded", "expansion_unknown"])
def test_real_recognition_route_checks_control_before_input_controller(monkeypatch, tmp_path, defect):
    from app.api import action
    from app.api.models.request import ExecuteRecognitionPlanRequest
    from app.api.models.response import APIResponse
    from app.core.local_input_policy import _local_operator_input_scope
    from tests.test_local_recognition_policy import plan_fixture
    identity = {"contract_version": "windows_native_identity_observation_v1", "provider": "windows_native_identity",
        "status": "observed", "target_window_handle": 321, "process_id": 12,
        "process_create_time": 123.5, "executable_path": "c:\\fixture\\editor.exe"}
    bound = SimpleNamespace(handle=321, process_id=12, title="Fixture", process_name="editor.exe",
        rect=SimpleNamespace(left=100, top=200, right=1100, bottom=890))
    manager = SimpleNamespace(get_bound_window=lambda: bound)
    monkeypatch.setattr(action, "window_manager", manager)
    monkeypatch.setattr(action.screenshot_service, "capture_window", lambda **kw: {
        "image_path": "capture.png", "window_size": {"width": 1000, "height": 690}, "roi": None})
    monkeypatch.setattr(action, "_run_recognition_plan_for_execution", lambda req:
        APIResponse(success=True, message="fixture", data={"result": plan_fixture()}))
    monkeypatch.setattr(action, "_render_recognition_plan_overlay_for_execution", lambda p: None)
    monkeypatch.setattr(action, "write_trace", lambda **kw: str(tmp_path / "trace.json"))
    monkeypatch.setattr(action, "_rewrite_execute_trace_result", lambda **kw: None)
    clicks = []
    monkeypatch.setattr(action.input_controller, "click_point", lambda x, y, **kw:
        clicks.append((x, y)) or {"clicked": True, "window_point": {"x": x, "y": y}})
    box = {"x": 160, "y": 492, "w": 48, "h": 48}
    before = control(window_identity=identity, window_rect=[100, 200, 1000, 690], bbox=box)
    expected_option = None
    if defect == "option_identity":
        before = {**before, "kind": "dropdown", "value": "AU", "options": [{**option(), "bbox": box}], "expanded": True}
        expected_option = before["options"][0]
    elif defect in {"expanded", "expansion_unknown"}:
        before = {**before, "kind": "dropdown", "value": "AU", "expanded": False}
    current = deepcopy(before)
    if defect == "outside":
        before["bbox"] = current["bbox"] = {"x": 1, "y": 1, "w": 20, "h": 20}
    elif defect == "identity":
        current["runtime_id"] = [999]
    elif defect == "option_identity":
        current["options"][0]["runtime_id"] = [999]
    elif defect == "unknown":
        current["checked"] = None
    elif defect in {"expanded", "expansion_unknown"}:
        current["expanded"] = True if defect == "expanded" else None
    def read():
        if defect == "reader_failure":
            raise ReadError("form_control_window_mismatch")
        return current
    guard = api().LocalControlTarget(read, before, expected_option=expected_option)
    request = ExecuteRecognitionPlanRequest(goal="Fixture control", enable_post_click_verification=False,
        max_execution_attempts=1, auto_observe_learning_artifacts=False,
        write_policy={"path_graph": False, "element_memory": False, "trace": True})
    native_reader = SimpleNamespace(read_identity=lambda handle: deepcopy(identity))
    with _local_operator_input_scope(manager=manager, identity_reader=native_reader, identity=identity,
            window_rect=(100, 200, 1100, 890), enabled=lambda: True):
        with api().local_control_target_scope(guard):
            response = action.execute_recognition_plan(request)
    data = response.data.get("result", response.data)
    if defect is None:
        assert response.success and clicks == [(184, 516)]
        assert data["control_target_check"]["status"] == "matched"
    else:
        assert not response.success and clicks == []
        assert data["execution_path"]["action_executed"] is False
        assert data["control_target_check"]["status"] == "rejected"
    assert api().check_local_control_target({"x": 184, "y": 516}) is None


def test_coordinator_enters_scope_only_on_owner_and_clears_between_steps(monkeypatch, tmp_path):
    from app.desktop_review.local_direct_step import LocalDirectStepMixin
    from threading import Event, RLock
    from app.desktop_review.single_step_runtime_owner import SerialRuntimeOwner
    from app.desktop_review import local_direct_step as direct
    owner = SerialRuntimeOwner()
    calls = []

    class Coordinator(LocalDirectStepMixin):
        _uses_production_factory = False
        _automatic_safety_interception = False
        _runtime = _learning_binding = _model_service = None
        _attached = _shutdown = False
        _guard = RLock()
        _cancel_wait = Event()
        _runtime_output_root = tmp_path
        _owner = owner
        def _begin(self, phase):
            pass
        def _end(self):
            pass
        def _require_host_ready(self, **kwargs):
            pass
        def _perform_local_step_on_owner(self, *args):
            calls.append(api().check_local_control_target({"x": 10, "y": 20}))
            return {"phase": "returned"}

    monkeypatch.setattr(direct, "_persist_invocation", lambda *args: None)
    try:
        co = Coordinator()
        guard = api().LocalControlTarget(lambda: owner.call(lambda: control()), control())
        co.execute_local_step(target_window_handle=1, target_process_id=2,
            operation="execute_recognition_plan", request={"goal": "Remember"}, control_target=guard)
        co.execute_local_step(target_window_handle=1, target_process_id=2,
            operation="execute_recognition_plan", request={"goal": "Unrelated"})
        assert calls[0]["status"] == "matched" and calls[1] is None
    finally:
        owner.close()
